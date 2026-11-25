"""The knowledge base flow: ServiceNow states, flags, import grouping, review actions and releases."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app import docgen, servicenow as sn
from app.diffing import word_diff
from app.models import SnArticle, SnArticleEvent, SnCategory, SnLink, SnLinkEvent, now
from conftest import needs_db
from sn_helpers import CATS, T1, T2, published, rec


def test_pick_versions_published_with_newer_draft():
    main, pending = sn.pick_versions([rec("KB1", "published", "22.0"), rec("KB1", "draft", "22.01"), rec("KB1", "retired", "21.02")])
    assert main["version"] == "22.0" and pending["version"] == "22.01"


def test_pick_versions_ignores_a_draft_older_than_published():
    main, pending = sn.pick_versions([rec("KB1", "published", "22.0"), rec("KB1", "review", "21.5")])
    assert main["version"] == "22.0" and pending is None


def test_pick_versions_without_published_uses_newest():
    main, pending = sn.pick_versions([rec("KB2", "draft", "2.0"), rec("KB2", "retired", "3.0")])
    assert main["state"] == "retired" and pending is None


def test_pick_versions_pending_retirement_gets_no_pending_change():
    main, pending = sn.pick_versions([rec("KB3", "pending_retirement", "5.0"), rec("KB3", "draft", "6.0")])
    assert main["version"] == "5.0" and pending is None


def test_pick_versions_without_version_orders_by_updated():
    a = rec("KB4", "published", None, updated="2025-05-01 10:00:00")
    b = rec("KB4", "draft", None, updated="2026-01-01 10:00:00")
    assert sn.pick_versions([b, a]) == (a, b)


def test_sn_state_maps_known_and_unknown():
    assert [sn.sn_state(x) for x in ("published", "review", "pending_retirement", "retired", "draft")] == \
           ["published", "review", "pending_retirement", "retired", "draft"]
    assert sn.sn_state("scheduled_publish") == "draft" and sn.sn_state(None) == "draft"


def test_import_flags():
    assert sn.import_flags(rec("KB5", "published", can_read=["K12 Agents"])) == ["Internal only"]
    assert sn.import_flags(rec("KB5", "published", can_read=["K12 Agents", "Public view"])) == []
    old = rec("KB5", "published", title="Drop policy INTERNAL"); del old["can_read"]
    assert sn.import_flags(old) == ["Internal only"]


def test_normalize_flags():
    assert sn.normalize_flags([" internal ONLY ", "Needs check", "needs check", ""], ["Internal only"]) == ["Internal only", "Needs check"]
    assert sn.normalize_flags(["x" * 50], []) == ["x" * 40]
    assert len(sn.normalize_flags([f"f{i}" for i in range(12)], [])) == 8


# ── article actions, create, edit and flags ─────────────────────────────────

@needs_db
def test_new_article_draft_review_publish(env):
    s, bot, sn = env
    a = sn.create_article(s, bot, "Pat", title="Q?", content="A.", category_id=None, flags=["internal only"], review=False)
    assert (a.status, a.p_content, a.content, a.labels) == ("draft", "A.", None, ["Internal only"]) and not sn.in_todo(a)
    sn.send_for_review(s, a, "Pat"); assert a.status == "review" and sn.in_todo(a)
    sn.publish_article(s, a, "Pat")
    assert (a.status, a.content, a.p_content) == ("published", "A.", None) and not sn.in_todo(a)


@needs_db
def test_edit_published_goes_through_draft_and_review(env):
    s, bot, sn = env
    a = published(s, bot, "Old.")
    sn.edit(s, a, "Pat", content="New.")
    assert (a.status, a.content, a.p_content, a.p_stage) == ("published", "Old.", "New.", "draft") and not sn.in_todo(a)
    sn.send_for_review(s, a, "Pat"); assert a.p_stage == "review" and sn.in_todo(a)
    sn.send_back(s, a, "Rev", "not yet"); assert a.p_stage == "draft"
    sn.send_for_review(s, a, "Pat"); sn.publish_article(s, a, "Pat")
    assert (a.content, a.p_content, a.p_stage, a.revision, a.app_changed) == ("New.", None, None, 1, True)
    ev = s.query(SnArticleEvent).filter_by(article_id=a.id, action="published").one()
    assert ev.detail["old_content"] == "Old."


@needs_db
def test_discard(env):
    s, bot, sn = env
    a = published(s, bot, "Old."); sn.edit(s, a, "Pat", content="New."); sn.discard(s, a, "Pat")
    assert (a.content, a.p_content, a.p_stage) == ("Old.", None, None)
    b = sn.create_article(s, bot, "Pat", title="Q", content="A", category_id=None, flags=[], review=True)
    sn.discard(s, b, "Rev"); s.commit(); assert s.get(SnArticle, b.id) is None
    c = published(s, bot, None, status="draft", p_title="t", p_content="x")
    with pytest.raises(sn.SnError, match="next import"): sn.discard(s, c, "Rev")


@needs_db
def test_retirement_and_restore(env):
    s, bot, sn = env
    a = published(s, bot, "Old.")
    sn.suggest_retire(s, a, "Pat", "outdated"); assert (a.status, a.p_reason) == ("pending_retirement", "outdated") and sn.in_todo(a)
    sn.keep_published(s, a, "Rev"); assert a.status == "published" and a.p_reason is None
    sn.suggest_retire(s, a, "Pat"); sn.retire(s, a, "Rev"); assert a.status == "retired" and not sn.in_todo(a)
    sn.restore(s, a, "Rev"); assert (a.status, a.p_content) == ("draft", "Old.")


@needs_db
def test_moves_that_are_not_allowed(env):
    s, bot, sn = env
    a = published(s, bot, "Old.")
    for fn in (sn.publish_article, sn.retire, sn.restore, sn.keep_published):
        with pytest.raises(sn.SnError): fn(s, a, "Pat")
    sn.edit(s, a, "Pat", content="New.")
    with pytest.raises(sn.SnError): sn.suggest_retire(s, a, "Pat")
    sn.discard(s, a, "Pat"); sn.suggest_retire(s, a, "Pat")
    with pytest.raises(sn.SnError, match="before editing"): sn.edit(s, a, "Pat", content="x")


@needs_db
def test_flags_apply_now_and_list_is_shared(env):
    s, bot, sn = env
    a, b = published(s, bot, "A"), published(s, bot, "B")
    sn.set_flags(s, a, "Pat", ["Needs check"]); sn.set_flags(s, b, "Pat", ["needs CHECK", "X", "INTERNAL ONLY"])
    assert a.labels == ["Needs check"] and b.labels == ["Needs check", "X", "Internal only"] and a.app_changed
    assert sn.flag_list(s, bot) == ["Internal only", "Needs check", "X"]


# ── import grouped by KB number ─────────────────────────────────────────────

@needs_db
def test_import_groups_versions_by_number(env):
    s, bot, sn = env
    st = sn.import_kb(s, bot, {"categories": CATS, "articles": [
        rec("KB1", "published", "22.0", body="Live."), rec("KB1", "draft", "22.01", body="Next."), rec("KB1", "retired", "21.0", body="Old."),
        rec("KB2", "retired", "3.0", body="Gone."), rec("KB3", "review", "1.0", body="New?", can_read=["K12 Agents"])]}, "import")
    rows = {a.number: a for a in s.query(SnArticle)}
    assert len(rows) == 3 and st["articles_new"] == 3
    assert (rows["KB1"].status, rows["KB1"].content, rows["KB1"].p_content, rows["KB1"].p_stage) == ("published", "Live.", "Next.", "draft")
    assert (rows["KB2"].status, rows["KB2"].content) == ("retired", "Gone.")
    assert (rows["KB3"].status, rows["KB3"].content, rows["KB3"].p_content, rows["KB3"].labels) == ("review", None, "New?", ["Internal only"])


@needs_db
def test_reimport_rules(env):
    s, bot, sn = env
    sn.import_kb(s, bot, {"categories": CATS, "articles": [rec(f"KB{i}", "published", updated=T1, body=f"v1-{i}") for i in (1, 2, 3, 4)]}, "import")
    get = lambda n: s.query(SnArticle).filter_by(number=n).one()
    for n in ("KB2", "KB3"):
        a = get(n); sn.edit(s, a, "Pat", content=f"app-{n}"); sn.send_for_review(s, a, "Pat"); sn.publish_article(s, a, "Pat")
    st = sn.import_kb(s, bot, {"categories": CATS, "articles": [
        rec("KB1", "published", updated=T2, body="v2-1"), rec("KB2", "published", updated=T1, body="v1-2"),
        rec("KB3", "published", updated=T2, body="v2-3"), rec("KB4", "retired", updated=T2, body="v1-4"), rec("KB5", "published", body="new")]}, "import")
    assert get("KB1").content == "v2-1"
    assert (get("KB2").content, get("KB2").p_content) == ("app-KB2", None)
    k3 = get("KB3"); assert (k3.content, k3.p_content, k3.p_stage, k3.p_kind) == ("app-KB3", "v2-3", "review", "servicenow") and sn.in_todo(k3)
    assert get("KB4").status == "retired" and get("KB5").status == "published"
    assert (st["articles_refreshed"], st["articles_kept"], st["articles_conflict"], st["articles_new"]) == (2, 1, 1, 1)


@needs_db
def test_reimport_conflict_retired_in_servicenow(env):
    s, bot, sn = env
    sn.import_kb(s, bot, {"categories": CATS, "articles": [rec("KB1", "published", updated=T1)]}, "import")
    a = s.query(SnArticle).one(); sn.set_flags(s, a, "Pat", ["X"])
    sn.import_kb(s, bot, {"categories": CATS, "articles": [rec("KB1", "retired", updated=T2)]}, "import")
    assert (a.status, a.p_reason) == ("pending_retirement", "Retired in ServiceNow") and a.labels == ["X"]


@needs_db
def test_import_merges_duplicate_rows_keeping_links_and_events(env):
    s, bot, sn = env
    sn.import_kb(s, bot, {"categories": CATS, "articles": []}, "import")
    keep = published(s, bot, "Live.", number="KB1", sys_id=rec("KB1", "published", "22.0")["sys_id"])
    dup = published(s, bot, "Next.", number="KB1", sys_id=rec("KB1", "draft", "22.01")["sys_id"])
    cat = s.query(SnCategory).filter_by(name="Refunds").one()
    s.add(SnLink(chatbot_id=bot.id, category_id=cat.id, article_id=dup.id, url="https://x.edu/a"))
    s.add(SnArticleEvent(article_id=dup.id, action="note", actor="Pat")); s.commit()
    st = sn.import_kb(s, bot, {"categories": CATS, "articles": [rec("KB1", "published", "22.0", body="Live."), rec("KB1", "draft", "22.01", body="Next.")]}, "import")
    assert st["articles_merged"] == 1 and s.query(SnArticle).count() == 1
    assert s.query(SnLink).one().article_id == keep.id
    assert s.query(SnArticleEvent).filter_by(action="note").one().article_id == keep.id


@needs_db
def test_merge_keeps_newest_person_edit_and_logs_the_other(env):
    s, bot, sn = env
    a = published(s, bot, "Edit A", number="KB1", app_changed=True, updated_at=datetime(2026, 1, 1))
    b = published(s, bot, "Edit B", number="KB1", app_changed=True, updated_at=datetime(2026, 2, 1))
    assert sn._merge(s, a, [b], "import") == 1
    assert a.content == "Edit B" and a.app_changed
    assert s.query(SnArticleEvent).filter_by(article_id=a.id, action="merged_copy").one().detail["content"] == "Edit A"


@needs_db
def test_import_accepts_old_file_format(env):
    s, bot, sn = env
    old = rec("KB1", "published", None, title="Notes INTERNAL")
    for k in ("version", "latest", "can_read", "updated"): old.pop(k)
    sn.import_kb(s, bot, {"categories": CATS, "articles": [old]}, "import")
    a = s.query(SnArticle).one(); assert a.status == "published" and a.labels == ["Internal only"]


@needs_db
def test_import_record_without_number_is_its_own_article(env):
    s, bot, sn = env
    sn.import_kb(s, bot, {"categories": CATS, "articles": [rec(None, "published", sys_id="1" * 32), rec(None, "published", sys_id="2" * 32)]}, "import")
    assert s.query(SnArticle).count() == 2


# ── AI proposals follow the states ──────────────────────────────────────────

@needs_db
def test_ai_proposals_follow_states(env, monkeypatch):
    s, bot, sn = env
    sn.import_kb(s, bot, {"categories": CATS, "articles": []}, "import")
    cat = s.query(SnCategory).filter_by(name="Refunds").one()
    up, rm, editing = (published(s, bot, t, category_id=cat.id) for t in ("The fee is $40.", "Retention Center.", "Draft me."))
    sn.edit(s, editing, "Pat", content="Person draft.")
    gone = published(s, bot, "Old.", category_id=cat.id, status="retired")
    pages = iter([{"title": "R", "text": "fee $40", "hash": "h1", "final": "u"}, {"title": "R", "text": "fee $50", "hash": "h2", "final": "u"}])
    monkeypatch.setattr(sn, "_fetch", lambda url: next(pages)); monkeypatch.setattr(sn, "enqueue", lambda *a, **k: True)
    seen = {}
    def fake(category, url, diff, page_text, articles, audit=False):
        seen["ids"] = {a["id"] for a in articles}
        return [{"action": "update", "article_id": up.id, "title": "T", "content": "The fee is $50.", "reason": "fee"},
                {"action": "remove", "article_id": rm.id, "title": "T", "content": "", "reason": "gone from page"},
                {"action": "update", "article_id": editing.id, "title": "T", "content": "AI text", "reason": "x"},
                {"action": "new", "title": "Refund timeline", "content": "Ten days.", "reason": "new topic"}]
    monkeypatch.setattr(sn.sn_ai, "reconcile", fake)
    link = sn.add_link(s, bot, cat.id, "https://www.depts.ttu.edu/k12/refunds/", "Pat")
    sn.check_link(link.id); sn.check_link(link.id); s.expire_all()
    assert gone.id not in seen["ids"] and {up.id, rm.id, editing.id} <= seen["ids"]
    up, rm, editing = (s.get(SnArticle, x.id) for x in (up, rm, editing))
    assert (up.content, up.p_content, up.p_stage, up.p_kind) == ("The fee is $40.", "The fee is $50.", "review", "update")
    assert (rm.status, rm.p_reason) == ("pending_retirement", "gone from page")
    assert editing.p_content == "Person draft."
    new = s.query(SnArticle).filter_by(p_kind="new").one(); assert (new.status, new.labels) == ("review", [])


# ── release contents and labels ─────────────────────────────────────────────

@needs_db
def test_release_labels_and_contents(env):
    s, bot, sn = env
    pub = published(s, bot, "P", title="pub"); sn.set_flags(s, pub, "Pat", ["Internal only"])
    chg = published(s, bot, "Live text", title="chg"); sn.edit(s, chg, "Pat", content="Draft text")
    pend = published(s, bot, "R", title="pend"); sn.suggest_retire(s, pend, "Pat")
    ret = published(s, bot, "Old", title="ret", status="retired")
    sn.create_article(s, bot, "Pat", title="new", content="N", category_id=None, flags=[], review=True)
    items = {i["title"]: i for i in sn.release_items(s, bot)}
    assert set(items) == {"pub", "chg", "pend", "ret"}
    assert items["pub"]["labels"] == ["Published", "Internal only"] and items["chg"]["content"] == "Live text"
    assert items["pend"]["labels"] == ["Pending retirement"] and items["ret"]["labels"] == ["Retired"]
    doc = docgen.build_json("k12-servicenow", "K12", 1, "now", list(items.values()))
    assert ["Published", "Internal only"] in [e["labels"] for e in doc["entries"]]
    sn.publish_version(s, bot, "", "Rev"); sn.retire(s, pend, "Rev")
    assert sn.draft(s, bot)["counts"]["modified"] == 1


@needs_db
def test_everything_export_labels_each_stage(env, api_client):
    s, bot, sn = env
    rel = published(s, bot, "R", title="rel"); sn.set_flags(s, rel, "Pat", ["Internal only"])
    chg = published(s, bot, "Live text", title="chg")
    upd = published(s, bot, "Old text", title="upd")
    sn.publish_version(s, bot, "", "Rev")                                  # v1 holds rel, chg, upd
    sn.edit(s, chg, "Pat", content="Draft text")                          # waiting change: the release still has the live text
    sn.edit(s, upd, "Pat", content="New text"); sn.send_for_review(s, upd, "Pat"); sn.publish_article(s, upd, "Pat")
    published(s, bot, "L", title="later")
    published(s, bot, "Gone", title="ret", status="retired")
    sn.create_article(s, bot, "Pat", title="d", content="D", category_id=None, flags=[], review=False)
    sn.create_article(s, bot, "Pat", title="r", content="Rv", category_id=None, flags=[], review=True)
    s.commit()
    items = {i["title"]: i for i in sn.everything_items(s, bot)}
    assert set(items) == {"rel", "chg", "upd", "later", "ret", "d", "r"}
    assert items["rel"]["labels"] == ["Released in v1", "Internal only"]
    assert items["rel"]["meta"] == {"stage": "Released in v1", "released_version": 1}
    assert (items["chg"]["labels"], items["chg"]["content"]) == (["Released in v1"], "Live text")
    assert (items["upd"]["labels"], items["upd"]["content"]) == (["Published, not released yet"], "New text")
    assert items["upd"]["meta"] == {"stage": "Published, not released yet", "released_version": None}
    assert items["later"]["labels"] == ["Published, not released yet"]
    assert items["ret"]["labels"] == ["Retired"]
    assert (items["d"]["labels"], items["d"]["content"]) == (["Draft"], "D")
    assert (items["r"]["labels"], items["r"]["content"]) == (["In review"], "Rv")
    assert "meta" not in sn.release_items(s, bot)[0]                     # stored releases keep their old shape
    doc = api_client.get("/api/chatbots/k12/servicenow/export?format=json&scope=everything").json()
    assert doc["scope"] == "everything"
    assert {e["title"]: e["stage"] for e in doc["entries"]}["d"] == "Draft"


# ── API ─────────────────────────────────────────────────────────────────────

@needs_db
def test_api_create_act_and_flags(env, api_client):
    c = api_client
    a = c.post("/api/chatbots/k12/servicenow/articles", json={"title": "Q?", "content": "A.", "category_id": None, "flags": ["internal only"], "review": True}).json()
    assert (a["status"], a["flags"]) == ("review", ["Internal only"])
    assert c.get("/api/chatbots/k12/servicenow/articles?status=queue").json()["total"] == 1
    assert c.post(f"/api/servicenow/articles/{a['id']}/publish", json={}).json()["status"] == "published"
    assert c.get("/api/chatbots/k12/servicenow/articles?status=queue").json()["total"] == 0
    assert c.patch(f"/api/servicenow/articles/{a['id']}", json={"flags": ["Needs check"]}).json()["flags"] == ["Needs check"]
    assert c.get("/api/chatbots/k12/servicenow/flags").json() == ["Internal only", "Needs check"]
    assert c.post(f"/api/servicenow/articles/{a['id']}/approve", json={}).status_code == 404


@needs_db
def test_activity_filters_by_action(env, api_client):
    s, bot, sn = env
    sn.record(s, bot.id, "publish", "Pat", "Published “A”")
    sn.record(s, bot.id, "link_added", "Pat", "Added the link x")
    sn.record(s, bot.id, "published", "Pat", "Released version 1")
    s.commit()
    r = api_client.get("/api/chatbots/k12/activity?actions=publish,bulk_publish").json()
    assert [i["summary"] for i in r["items"]] == ["Published “A”"]
    assert r["actions"] == {"publish": 1, "link_added": 1, "published": 1}


def test_word_diff_marks_changed_words():
    assert word_diff("Approvals take 3 business days.", "Approvals take 5 business days.") == [
        {"t": "=", "s": "Approvals take "}, {"t": "-", "s": "3"}, {"t": "+", "s": "5"}, {"t": "=", "s": " business days."}]


def test_word_diff_identical_and_empty():
    assert word_diff("a b", "a b") == [{"t": "=", "s": "a b"}]
    assert word_diff("", "New.") == [{"t": "+", "s": "New."}]


def test_word_diff_is_fast_on_texts_with_little_in_common():
    import time
    cases = [("word " * 2000, "other " * 2000), ("a b " * 1000, "b a " * 1000),
             ("\n".join("line %d word" % i for i in range(400)), "\n".join("row %d other" % i for i in range(400)))]
    for old, new in cases:
        t0 = time.perf_counter()
        out = word_diff(old, new)
        assert time.perf_counter() - t0 < 2
        assert "".join(x["s"] for x in out if x["t"] != "+") == old and "".join(x["s"] for x in out if x["t"] != "-") == new


def test_word_diff_is_bounded():
    old, new = "word " * 20000, "other " * 20000
    out = word_diff(old, new, limit=100)
    assert "".join(x["s"] for x in out if x["t"] != "+") == old and "".join(x["s"] for x in out if x["t"] != "-") == new


@needs_db
def test_detail_has_pages_release_and_word_diff(env, api_client):
    s, bot, sn = env
    sn.import_kb(s, bot, {"categories": CATS, "articles": []}, "import")
    parent = s.query(SnCategory).filter_by(name="Financial Questions").one()
    child = s.query(SnCategory).filter_by(name="Refunds").one()
    s.add(SnLink(chatbot_id=bot.id, category_id=parent.id, url="https://x.edu/refunds")); s.commit()
    a = published(s, bot, "Fee is $40.", category_id=child.id)
    sn.publish_version(s, bot, "", "Pat")
    sn.edit(s, a, "Pat", content="Fee is $50."); s.commit()
    d = api_client.get(f"/api/servicenow/articles/{a.id}").json()
    assert [p["url"] for p in d["pages"]] == ["https://x.edu/refunds"] and d["in_release"] == 1
    assert {"t": "+", "s": "50"} in d["word_diff"]


@needs_db
def test_one_fetch_and_one_ai_call_per_url(env, monkeypatch):
    s, bot, sn = env
    sn.import_kb(s, bot, {"categories": CATS, "articles": []}, "import")
    parent = s.query(SnCategory).filter_by(name="Financial Questions").one()
    child = s.query(SnCategory).filter_by(name="Refunds").one()
    a1, a2 = published(s, bot, "A", category_id=parent.id), published(s, bot, "B", category_id=child.id)
    monkeypatch.setattr(sn, "enqueue", lambda *a, **k: True)
    l1 = sn.add_link(s, bot, parent.id, "https://x.edu/p", "Pat"); l2 = sn.add_link(s, bot, child.id, "https://x.edu/p", "Pat")
    pages = iter([{"title": "P", "text": "v1", "hash": "h1", "final": "u"}, {"title": "P", "text": "v2", "hash": "h2", "final": "u"}])
    fetched, calls = [], []
    monkeypatch.setattr(sn, "_fetch", lambda url: fetched.append(url) or next(pages))
    monkeypatch.setattr(sn.sn_ai, "reconcile", lambda c, u, d, t, articles, audit=False: calls.append([a["id"] for a in articles]) or [])
    sn.check_link(l1.id); s.expire_all()
    assert len(fetched) == 1 and {s.get(SnLink, l.id).content_hash for l in (l1, l2)} == {"h1"}
    sn.check_link(l2.id); s.expire_all()
    assert len(fetched) == 2 and len(calls) == 1 and sorted(calls[0]) == sorted([a1.id, a2.id])
    assert {s.get(SnLink, l.id).content_hash for l in (l1, l2)} == {"h2"}


@needs_db
def test_due_links_one_per_url(env, monkeypatch):
    s, bot, sn = env
    sn.import_kb(s, bot, {"categories": CATS, "articles": []}, "import")
    monkeypatch.setattr(sn, "enqueue", lambda *a, **k: True)
    cats = s.query(SnCategory).order_by(SnCategory.id).all()
    l1 = sn.add_link(s, bot, cats[0].id, "https://x.edu/p", "Pat"); sn.add_link(s, bot, cats[1].id, "https://x.edu/p", "Pat")
    l3 = sn.add_link(s, bot, cats[0].id, "https://x.edu/q", "Pat")
    for l in s.query(SnLink): l.next_run_at = now() - timedelta(minutes=1)
    s.commit()
    assert sorted(sn.due_links(s)) == sorted([l1.id, l3.id])


@needs_db
def test_removing_one_category_keeps_the_page_history(env, api_client, monkeypatch):
    s, bot, sn = env
    sn.import_kb(s, bot, {"categories": CATS, "articles": []}, "import")
    monkeypatch.setattr(sn, "enqueue", lambda *a, **k: True)
    cats = s.query(SnCategory).order_by(SnCategory.id).all()
    l1 = sn.add_link(s, bot, cats[0].id, "https://x.edu/p", "Pat"); l2 = sn.add_link(s, bot, cats[1].id, "https://x.edu/p", "Pat")
    ev = SnLinkEvent(chatbot_id=bot.id, link_id=l1.id, kind="changed", trigger="manual", actor="Pat")
    s.add(ev); s.flush()
    a = published(s, bot, "A", p_link_id=l1.id, p_event_id=ev.id)
    l1_id, l2_id, ev_id = l1.id, l2.id, ev.id
    assert api_client.delete(f"/api/servicenow/links/{l1_id}").status_code == 200
    s.expire_all()
    assert s.get(SnLinkEvent, ev_id).link_id == l2_id and s.get(SnArticle, a.id).p_link_id == l2_id
