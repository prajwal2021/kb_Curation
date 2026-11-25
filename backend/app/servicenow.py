"""ServiceNow curation: one-time import, links per category, AI proposals from page changes, review and publishing.

Article lifecycle mirrors website entries: an article waits as new (imported or proposed), approved text is the
live knowledge, and a later change or removal waits as a proposal on top of it until a person decides.
"""
from __future__ import annotations

import queue
import threading
import time
import traceback
from collections.abc import Callable
from datetime import timedelta

import httpx
from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from . import publish, sn_ai
from .config import SN_INSTANCE, USER_AGENT
from .crawler import canon
from .db import SessionLocal
from .diffing import line_diff
from .extract import extract, norm
from .models import Activity, Chatbot, SnArticle, SnArticleEvent, SnCategory, SnLink, SnLinkEvent, SnVersion, now
from .sn_html import article_content

STATES = ("draft", "review", "published", "pending_retirement", "retired")
RELEASED = ("published", "pending_retirement", "retired")         # what goes into a release
STATE_LABEL = {"published": "Published", "pending_retirement": "Pending retirement", "retired": "Retired"}
INTERNAL = "Internal only"

# Previous architecture (upstream's new/changed/approved lifecycle). Replaced on this branch by
# STATES / RELEASED / STATE_LABEL. Kept for reference; not called.
# QUEUE = ("new", "changed", "removal")
# LIVE = ("approved", "changed", "removal")
# STATE_LABEL = {"draft": "Draft in ServiceNow", "review": "In review in ServiceNow",
#                "pending_retirement": "Pending retirement in ServiceNow"}
# EXPIRED = "Expired in ServiceNow"
# NEWER = "Newer version in ServiceNow"
# STATE_WORD = {"draft": "draft", "review": "in-review", "pending_retirement": "pending-retirement", "published": "published"}
# # Review flags: they say where the record stood in ServiceNow or what the AI did, which helps a reviewer decide but is
# # not knowledge. They are shown in Review and never kept on approved text or sent to the chatbot.
# SYSTEM_LABELS = {EXPIRED, NEWER, "AI update", "New from link", "AI suggests removing", *STATE_LABEL.values()}


class SnError(Exception):
    pass


def log(db: Session, a: SnArticle, action: str, actor: str = "system", **detail) -> None:
    db.add(SnArticleEvent(article_id=a.id, action=action, actor=actor, detail=detail))


def record(db: Session, bot_id: int, action: str, actor: str, summary: str, **detail) -> None:
    db.add(Activity(chatbot_id=bot_id, area="servicenow", action=action, actor=actor, summary=summary, detail=detail))


def has_proposal(a: SnArticle) -> bool:
    """True when p_* holds text: a draft or review article's text, or a pending change on a published one."""
    return a.p_content is not None


def clear_proposal(a: SnArticle) -> None:
    a.p_title = a.p_content = a.p_category_id = a.p_kind = a.p_reason = a.p_link_id = a.p_event_id = a.p_stage = None
    a.p_labels, a.p_edited = [], False


def current_text(a: SnArticle) -> tuple[str, str]:
    """What the article says right now for the AI: a pending text wins over the published text."""
    if has_proposal(a):
        return a.p_title or "", a.p_content
    return a.title or "", a.content or ""


def kb_url(number: str | None) -> str | None:
    return f"{SN_INSTANCE}/kb_view.do?sysparm_article={number}" if number else None


# ── import ────────────────────────────────────────────────────────────────────

def sn_state(raw: str | None) -> str:
    """ServiceNow's state as ours. Anything else (scheduled_publish, outdated…) is a draft, so it never ships by accident."""
    return raw if raw in STATES else "draft"


def _newness(r: dict) -> tuple:
    try:
        version = tuple(int(x) for x in str(r.get("version") or "").split("."))   # "22.01" → (22, 1)
    except ValueError:
        version = ()
    return version, r.get("updated") or ""


def pick_versions(records: list[dict]) -> tuple[dict, dict | None]:
    """(main, pending) for all ServiceNow records of one KB number. main = the newest published or pending-retirement
    record, else the newest record. pending = the newest draft or review record newer than main, only when main is published."""
    recs = sorted(records, key=_newness)
    main = ([r for r in recs if sn_state(r.get("state")) in ("published", "pending_retirement")] or recs)[-1]
    if sn_state(main.get("state")) != "published":
        return main, None
    newer = [r for r in recs if sn_state(r.get("state")) in ("draft", "review") and _newness(r) > _newness(main)]
    return main, newer[-1] if newer else None


def import_flags(art: dict) -> list[str]:
    """Flags from a ServiceNow record: "Internal only" when its can_read list has no "Public view".
    Older files have no can_read: then guess from the wording, as before."""
    if "can_read" in art:
        internal = "Public view" not in (art["can_read"] or [])
    else:
        raw = " ".join(p[1] for p in art.get("parts") or [] if p[1]) + (art.get("text") or "")
        internal = "INTERNAL" in (art.get("title") or "") or "INTERNAL USE ONLY" in raw.upper()
    return [INTERNAL] if internal else []


def normalize_flags(flags: list[str], known: list[str]) -> list[str]:
    """Trimmed, at most 40 characters, at most 8, matched ignoring case (a known name's casing wins)."""
    casing = {k.lower(): k for k in known}
    out: dict[str, str] = {}
    for f in flags:
        f = norm(f or "")[:40].strip()
        if f:
            out.setdefault(f.lower(), casing.get(f.lower(), f))
    return list(out.values())[:8]


# Previous architecture (upstream's new/changed/approved lifecycle). Replaced on this branch by
# pick_versions + _merge inside import_kb (one article per KB number). Kept for reference; not called.
# def _version_rank(state: str | None, updated: str | None) -> tuple:
#     """Which ServiceNow record of an article to keep: the published one, then the most recently updated."""
#     return (state == "published", updated or "")
#
#
# def _one_per_number(articles: list[dict]) -> tuple[list[dict], dict[str, dict]]:
#     """ServiceNow keeps one record per article version (published v1, v2 in review...). Keep one record per KB
#     number and return, per number, the newer unpublished version whose text differs (if any)."""
#     groups: dict[str, list[dict]] = {}
#     out: list[dict] = []
#     for art in articles:
#         if art.get("number"):
#             groups.setdefault(art["number"], []).append(art)
#         else:
#             out.append(art)
#     newer: dict[str, dict] = {}
#     for number, rows in groups.items():
#         rows.sort(key=lambda r: _version_rank(r.get("state"), r.get("updated")), reverse=True)
#         base = rows[0]
#         out.append(base)
#         text = article_content(base, SN_INSTANCE + "/")
#         later = [r for r in rows[1:] if (r.get("updated") or "") > (base.get("updated") or "")
#                  and norm(article_content(r, SN_INSTANCE + "/")) != norm(text)]
#         if later:
#             newer[number] = max(later, key=lambda r: r.get("updated") or "")
#     return out, newer
#
#
# def merge_versions(db: Session, bot: Chatbot, actor: str = "system") -> dict:
#     """Collapse articles that came in more than once (one row per ServiceNow version) into one per KB number.
#     The published version stays. If a newer version says something different, its text becomes a proposal on the
#     kept article, so a reviewer decides whether it goes live. The extra rows are deleted."""
#     stats = {"numbers": 0, "removed": 0, "proposals": 0}
#     rows = db.scalars(select(SnArticle).where(SnArticle.chatbot_id == bot.id, SnArticle.number.is_not(None))).all()
#     groups: dict[str, list[SnArticle]] = {}
#     for a in rows:
#         groups.setdefault(a.number, []).append(a)
#     text = lambda a: (a.content if a.content is not None else a.p_content) or ""   # noqa: E731
#     for number, items in groups.items():
#         if len(items) < 2:
#             continue
#         items.sort(key=lambda a: (_version_rank(a.sn_state, a.sn_updated), a.status == "approved"), reverse=True)
#         base, others = items[0], items[1:]
#         diff = [o for o in others if norm(text(o)) != norm(text(base)) and (o.sn_updated or "") >= (base.sn_updated or "")]
#         newer = max(diff, key=lambda o: o.sn_updated or "", default=None)
#         if newer is not None:
#             reason = (f"ServiceNow also has a newer {STATE_WORD.get(newer.sn_state, newer.sn_state)} version of {number} with "
#                       "different text. Approve to use the newer text, or reject to keep the published text.")
#             if base.status == "approved":
#                 base.status, base.detected_at = "changed", now()
#                 base.p_title, base.p_content = (newer.title or newer.p_title or base.title), text(newer)
#                 base.p_category_id, base.p_kind, base.p_reason = base.category_id, "update", reason
#                 base.p_labels = sorted(set(base.labels or []) | {NEWER})
#                 stats["proposals"] += 1
#             elif has_proposal(base):
#                 base.p_labels = sorted(set(base.p_labels or []) | {NEWER})
#                 base.p_reason = base.p_reason or reason
#         for o in others:
#             db.execute(update(SnLink).where(SnLink.article_id == o.id).values(article_id=base.id))
#             db.delete(o)
#         log(db, base, "merged_versions", actor, number=number, removed=[o.id for o in others],
#             newer_text=newer is not None)
#         stats["numbers"] += 1
#         stats["removed"] += len(others)
#     if stats["numbers"]:
#         record(db, bot.id, "merge_versions", actor, f"Merged {stats['numbers']} articles that were imported once per ServiceNow "
#                f"version: {stats['removed']} extra copies removed, {stats['proposals']} newer texts waiting in Review", **stats)
#     db.commit()
#     return stats


def import_kb(db: Session, bot: Chatbot, kb: dict, actor: str) -> dict:
    """kb = {categories: [{sys_id, label, parent, active}], articles: [{sys_id, number, title, state, category, template,
    valid_to, updated, version, latest, can_read, parts, text}]}. ServiceNow keeps each version as its own record: they are
    grouped by KB number (by sys_id when there is none) into one article. Safe to run again (every 2 weeks):
    changed only in ServiceNow → ServiceNow wins; changed only in the app → the app wins; changed in both → ServiceNow's
    version waits in review. Articles missing from the file are left alone."""
    stats = {"categories": 0, "articles_new": 0, "articles_refreshed": 0, "articles_kept": 0, "articles_conflict": 0,
             "articles_merged": 0}
    cats = {c.sys_id: c for c in db.scalars(select(SnCategory).where(SnCategory.chatbot_id == bot.id))}
    for c in kb.get("categories") or []:
        row = cats.get(c["sys_id"])
        if row is None:
            row = SnCategory(chatbot_id=bot.id, sys_id=c["sys_id"], name="", path="")
            db.add(row)
            cats[c["sys_id"]] = row
        row.name, row.active = norm(c.get("label") or "") or "Untitled", bool(c.get("active", True))
        stats["categories"] += 1
    db.flush()
    parents = {c["sys_id"]: c.get("parent") for c in kb.get("categories") or []}
    for sid, row in cats.items():
        p = parents.get(sid)
        row.parent_id = cats[p].id if p in cats else None
    by_id = {r.id: r for r in cats.values()}

    def path(r: SnCategory) -> str:
        bits, seen = [], set()
        while r and r.id not in seen:
            seen.add(r.id)
            bits.insert(0, r.name)
            r = by_id.get(r.parent_id)
        return " > ".join(bits)

    for r in cats.values():
        r.path = path(r)
    for i, r in enumerate(sorted(cats.values(), key=lambda r: r.path.lower())):
        r.position = i

    def said(r: dict) -> tuple[str, str, int | None]:
        cat = cats.get(r.get("category") or "")
        return (norm(r.get("title") or "") or r.get("number") or "Untitled article",
                article_content(r, SN_INSTANCE + "/") or "(This article has no text in ServiceNow.)", cat.id if cat else None)

    groups: dict[str, list[dict]] = {}
    for art in kb.get("articles") or []:
        groups.setdefault(art.get("number") or f"sys_id:{art['sys_id']}", []).append(art)
    rows = list(db.scalars(select(SnArticle).where(SnArticle.chatbot_id == bot.id, SnArticle.sys_id.is_not(None) | SnArticle.number.is_not(None))
                           .order_by(SnArticle.id)))
    done: set[int] = set()                                    # rows already matched to a group (or merged away)
    for recs in groups.values():
        main, pending = pick_versions(recs)
        sys_ids = {r["sys_id"] for r in recs}
        found = [r for r in rows if r.id not in done and ((main.get("number") and r.number == main["number"]) or r.sys_id in sys_ids)]
        done.update(r.id for r in found)
        a = next((r for r in found if r.sys_id == main["sys_id"]), found[0] if found else None)
        if len(found) > 1:
            stats["articles_merged"] += _merge(db, a, [r for r in found if r is not a], actor)
        status = sn_state(main.get("state"))
        title, text, cat_id = said(main)
        updated = max(r.get("updated") or "" for r in (main, pending) if r) or None
        if a is not None and a.sn_updated == updated:         # ServiceNow has not changed it since the last import
            stats["articles_kept"] += int(a.app_changed)
            continue
        if a is not None and a.app_changed:                   # changed in both places: a person decides
            stats["articles_conflict"] += 1
            if status == "retired" and a.status == "published":
                a.status, a.p_kind, a.p_reason = "pending_retirement", "remove", "Retired in ServiceNow"
            elif a.status == "published" and not has_proposal(a) and (title, text) != (a.title, a.content):
                a.p_title, a.p_content, a.p_category_id = title, text, cat_id
                a.p_stage, a.p_kind, a.p_reason = "review", "servicenow", "Changed in ServiceNow"
            log(db, a, "servicenow_changed", actor, state=status, title=title, content=text)
            a.sn_updated = updated
            continue
        if a is None:
            a = SnArticle(chatbot_id=bot.id)
            db.add(a)
            stats["articles_new"] += 1
        else:
            stats["articles_refreshed"] += 1
        clear_proposal(a)
        a.status, a.sys_id, a.number, a.labels = status, main["sys_id"], main.get("number"), import_flags(main)
        a.sn_state, a.sn_template, a.valid_to, a.sn_updated = main.get("state"), main.get("template"), main.get("valid_to"), updated
        a.source_html = "\n".join(p[1] for p in main.get("parts") or [] if p[1]) or main.get("text") or ""
        a.sn_content, a.category_id = text, cat_id
        if status in RELEASED:
            a.title, a.content = title, text
        else:                                                 # a draft or review article has no published text yet
            a.title = a.content = None
            a.p_title, a.p_content, a.p_category_id, a.p_kind = title, text, cat_id, "import"
        if pending:
            a.p_title, a.p_content, a.p_category_id = said(pending)
            a.p_stage, a.p_kind = sn_state(pending.get("state")), "import"
        db.flush()
        log(db, a, "imported", actor, number=a.number, state=a.sn_state)
    record(db, bot.id, "import", actor, f"Imported from ServiceNow: {stats['articles_new']} new articles, "
           f"{stats['articles_refreshed']} updated from ServiceNow, {stats['articles_conflict']} changed in both places, "
           f"{stats['articles_merged']} duplicates merged, {stats['categories']} categories", **stats)
    db.commit()
    return stats


def _merge(db: Session, keep: SnArticle, others: list[SnArticle], actor: str) -> int:
    """Fold duplicate rows of one KB number into keep. Their web page links and history move over; the newest
    person-edited text wins, and every other person-edited text stays in keep's history. Returns how many were merged."""
    ids = [o.id for o in others]
    for l in db.scalars(select(SnLink).where(SnLink.article_id.in_(ids))):
        l.article_id = keep.id
    for e in db.scalars(select(SnArticleEvent).where(SnArticleEvent.article_id.in_(ids))):
        e.article_id = keep.id
    if any(o.app_changed for o in others):
        edited = sorted((r for r in [keep, *others] if r.app_changed), key=lambda r: r.updated_at)
        for r in edited[:-1]:
            log(db, keep, "merged_copy", actor, title=r.title, content=r.content)
        keep.title, keep.content, keep.category_id = edited[-1].title, edited[-1].content, edited[-1].category_id
        keep.app_changed = True
    db.flush()                                                # move links and events before the rows (and their cascades) go
    for o in others:
        db.delete(o)
    return len(others)


# ── review ────────────────────────────────────────────────────────────────────

def in_todo(a: SnArticle) -> bool:
    """Waiting for a person: in review (a new article or a pending change), or pending retirement."""
    return a.status in ("review", "pending_retirement") or a.p_stage == "review"


def todo_clause():
    """in_todo as a query condition."""
    return SnArticle.status.in_(("review", "pending_retirement")) | (SnArticle.p_stage == "review")


def flag_list(db: Session, bot: Chatbot) -> list[str]:
    """The flags checklist: "Internal only", then every flag this knowledge base's articles use, merged ignoring case."""
    names = {INTERNAL.lower(): INTERNAL}
    for labels in db.scalars(select(SnArticle.labels).where(SnArticle.chatbot_id == bot.id).order_by(SnArticle.id)):
        for f in labels or []:
            names.setdefault(f.lower(), f)
    return [INTERNAL] + sorted((v for k, v in names.items() if k != INTERNAL.lower()), key=str.lower)


def _check(db: Session, bot_id: int, title: str | None, content: str | None, category_id: int | None) -> None:
    if category_id and not db.scalar(select(SnCategory.id).where(SnCategory.id == category_id, SnCategory.chatbot_id == bot_id)):
        raise SnError("That category does not exist.")
    if title is not None and not norm(title):
        raise SnError("The title cannot be empty.")
    if content is not None and not norm(content):
        raise SnError("The content cannot be empty.")


def _tidy(content: str) -> str:
    return "\n".join(x.rstrip() for x in content.strip().splitlines())


def create_article(db: Session, bot: Chatbot, actor: str, *, title: str, content: str, category_id: int | None,
                   flags: list[str], review: bool) -> SnArticle:
    """A new article written in the app, saved as a draft or sent straight to review."""
    _check(db, bot.id, title, content, category_id)
    a = SnArticle(chatbot_id=bot.id, status="review" if review else "draft", category_id=category_id or None,
                  p_title=title.strip(), p_content=_tidy(content), p_category_id=category_id or None, p_kind="written",
                  labels=normalize_flags(flags, flag_list(db, bot)), app_changed=True)
    db.add(a)
    db.flush()
    log(db, a, "created", actor, review=review)
    return a


def edit(db: Session, a: SnArticle, actor: str, *, title=None, content=None, category_id=None) -> None:
    """Change the text. A draft or review article is edited in place; a published one gets (or keeps) a pending change."""
    if a.status in ("pending_retirement", "retired"):
        raise SnError("Keep it published or restore it before editing.")
    _check(db, a.chatbot_id, title, content, category_id)
    if a.status == "published" and not has_proposal(a):
        a.p_title, a.p_content, a.p_category_id = a.title, a.content, a.category_id
        a.p_stage, a.p_kind = "draft", "edit"
    before = {"title": a.p_title, "content": a.p_content}
    changed = (title is not None and title.strip() != before["title"]) or (content is not None and _tidy(content) != before["content"])
    if title is not None:
        a.p_title = title.strip()
    if content is not None:
        a.p_content = _tidy(content)
    if category_id is not None:
        a.p_category_id = category_id or None
    a.p_edited = a.p_edited or changed
    a.app_changed = True
    log(db, a, "edited", actor, text_changed=changed, **(before if changed else {}))


def set_flags(db: Session, a: SnArticle, actor: str, flags: list[str]) -> None:
    """Flags apply at once, whatever the state, and go out with the next release."""
    before = list(a.labels or [])
    a.labels = normalize_flags(flags, flag_list(db, db.get(Chatbot, a.chatbot_id)))
    a.app_changed = True
    log(db, a, "flags_changed", actor, before=before, after=a.labels)


def _acted(db: Session, a: SnArticle, actor: str, action: str, **detail) -> None:
    a.app_changed, a.reviewer, a.reviewed_at = True, actor, now()
    log(db, a, action, actor, **detail)


def send_for_review(db: Session, a: SnArticle, actor: str, note: str = "") -> None:
    if a.status == "draft":
        a.status = "review"
    elif a.status == "published" and a.p_stage == "draft":
        a.p_stage = "review"
    else:
        raise SnError("Only a draft can be sent for review.")
    _acted(db, a, actor, "sent_for_review", note=note)


def publish_article(db: Session, a: SnArticle, actor: str, note: str = "") -> None:
    """The text in review becomes the published text; the text it replaces stays in the event."""
    if not (a.status == "review" or (a.status == "published" and a.p_stage == "review")) or not has_proposal(a):
        raise SnError("Only an article in review can be published.")
    old = {"old_title": a.title, "old_content": a.content} if a.content is not None else {}
    a.title, a.content = a.p_title, a.p_content
    a.category_id = a.p_category_id if a.p_category_id is not None else a.category_id
    a.status, a.revision = "published", a.revision + 1
    clear_proposal(a)
    _acted(db, a, actor, "published", note=note, revision=a.revision, **old)


def send_back(db: Session, a: SnArticle, actor: str, note: str = "") -> None:
    if a.status == "review":
        a.status = "draft"
    elif a.status == "published" and a.p_stage == "review":
        a.p_stage = "draft"
    else:
        raise SnError("Only an article in review can be sent back to draft.")
    _acted(db, a, actor, "sent_back", note=note)


def discard(db: Session, a: SnArticle, actor: str, note: str = "") -> None:
    """Drop a pending change, or delete a new article made in the app that was never published."""
    if a.status == "published" and has_proposal(a):
        clear_proposal(a)
        _acted(db, a, actor, "discarded", note=note)
    elif a.status in ("draft", "review") and a.sys_id:
        raise SnError("This draft comes from ServiceNow and would come back with the next import.")
    elif a.status in ("draft", "review") and a.content is None:
        db.delete(a)                                          # its events go with it; History keeps the Activity line
    elif a.status in ("draft", "review"):
        raise SnError("This article was published before, so it stays as a draft.")
    else:
        raise SnError("There is no draft to discard on this article.")


def suggest_retire(db: Session, a: SnArticle, actor: str, note: str = "") -> None:
    if a.status != "published" or has_proposal(a):
        raise SnError("Only a published article with no pending change can be suggested for retiring.")
    a.status, a.p_kind, a.p_reason = "pending_retirement", "remove", note.strip() or None
    _acted(db, a, actor, "suggested_retire", note=note)


def keep_published(db: Session, a: SnArticle, actor: str, note: str = "") -> None:
    if a.status != "pending_retirement":
        raise SnError("This article is not waiting to be retired.")
    a.status, a.p_reason, a.p_kind = "published", None, None
    _acted(db, a, actor, "kept_published", note=note)


def retire(db: Session, a: SnArticle, actor: str, note: str = "") -> None:
    if a.status != "pending_retirement":
        raise SnError("Only an article pending retirement can be retired.")
    a.status = "retired"
    _acted(db, a, actor, "retired", note=note)


def restore(db: Session, a: SnArticle, actor: str, note: str = "") -> None:
    """Retired → draft. Its published text is copied into the draft so there is something to edit."""
    if a.status != "retired":
        raise SnError("Only a retired article can be restored.")
    if a.content is not None:
        a.p_title, a.p_content, a.p_category_id = a.title, a.content, a.category_id
    a.status, a.p_stage, a.p_kind, a.p_reason = "draft", None, None, None
    _acted(db, a, actor, "restored", note=note)


ACTIONS: dict[str, Callable] = {"send_for_review": send_for_review, "publish": publish_article, "send_back": send_back,
                                "discard": discard, "suggest_retire": suggest_retire, "keep": keep_published,
                                "retire": retire, "restore": restore}


# ── links: fetch, compare, ask the AI, turn its answer into proposals ─────────

def descendants(db: Session, cat_id: int) -> list[int]:
    rows = db.execute(select(SnCategory.id, SnCategory.parent_id).where(
        SnCategory.chatbot_id == db.scalar(select(SnCategory.chatbot_id).where(SnCategory.id == cat_id)))).all()
    kids: dict[int | None, list[int]] = {}
    for i, p in rows:
        kids.setdefault(p, []).append(i)
    out, todo = [], [cat_id]
    while todo:
        c = todo.pop()
        if c in out:
            continue
        out.append(c)
        todo += kids.get(c, [])
    return out


def _articles_for(db: Session, link: SnLink) -> list[SnArticle]:
    """What the AI reads: published articles (with or without a pending change) and new articles in review."""
    q = select(SnArticle).where(SnArticle.chatbot_id == link.chatbot_id,
                                (SnArticle.status == "published") | ((SnArticle.status == "review") & SnArticle.content.is_(None)))
    if link.article_id:
        q = q.where(SnArticle.id == link.article_id)
    else:
        ids = descendants(db, link.category_id)
        q = q.where((SnArticle.category_id.in_(ids)) | (SnArticle.p_category_id.in_(ids)))
    return list(db.scalars(q.order_by(SnArticle.id)))


def _fetch(url: str) -> dict:
    with httpx.Client(follow_redirects=True, timeout=30, headers={"User-Agent": USER_AGENT}) as c:
        r = c.get(url)
    if r.status_code >= 400:
        raise SnError(f"The page answered HTTP {r.status_code}")
    if "html" not in r.headers.get("content-type", ""):
        raise SnError(f"Not a web page ({r.headers.get('content-type', 'unknown type').split(';')[0]})")
    d = extract(r.text, str(r.url))
    if not d["sections"]:
        raise SnError("No readable content on the page")
    return {"title": d["title"], "text": d["text"], "hash": d["hash"], "final": str(r.url)}


def apply_decisions(db: Session, link: SnLink, ev: SnLinkEvent, decisions: list[dict], sent: dict[int, str] | None = None) -> list[dict]:
    """Turn AI decisions into proposals. Returns the decisions annotated with what happened.
    `sent` = the article text the AI read; an article a person changed meanwhile is not overwritten."""
    db.flush()
    db.expire_all()                                           # the AI took a while: read what people did meanwhile
    out = []
    for d in decisions:
        res = dict(d)
        res.pop("content", None)
        if d["action"] == "new":
            a = SnArticle(chatbot_id=link.chatbot_id, category_id=link.category_id, status="review", p_title=d["title"], p_content=d["content"],
                          p_category_id=link.category_id, p_kind="new", p_reason=d.get("reason"), p_link_id=link.id, p_event_id=ev.id,
                          labels=[])
            db.add(a)
            db.flush()
            log(db, a, "proposed_new", "AI", link=link.url, reason=d.get("reason"))
            res.update(article_id=a.id, result="proposed")
        elif d["action"] in ("update", "remove"):
            a = db.get(SnArticle, d["article_id"])
            if a is None or a.chatbot_id != link.chatbot_id or not (a.status == "published" or (a.status == "review" and a.content is None)):
                res["result"] = "skipped"                     # the AI only works on what it was given
            elif sent is not None and current_text(a)[1] != sent.get(a.id):
                res["result"] = "skipped: a reviewer changed the article while the AI was reading it"
            elif d["action"] == "update" and a.p_stage == "draft":
                res["result"] = "skipped: a person is editing it"
            elif d["action"] == "update":
                if a.status == "published" and not has_proposal(a):
                    a.p_category_id, a.p_stage, a.p_kind, a.detected_at = a.category_id, "review", "update", now()
                a.p_title, a.p_content = d["title"] or a.p_title or a.title, d["content"]   # else revise the change in review
                a.p_reason, a.p_link_id, a.p_event_id = d.get("reason"), link.id, ev.id
                log(db, a, "ai_update", "AI", link=link.url, reason=d.get("reason"))
                res["result"] = "proposed"
            elif a.status == "published" and not has_proposal(a):
                a.status, a.detected_at, a.p_kind = "pending_retirement", now(), "remove"
                a.p_reason, a.p_link_id, a.p_event_id = d.get("reason"), link.id, ev.id
                log(db, a, "ai_remove", "AI", link=link.url, reason=d.get("reason"))
                res["result"] = "proposed"
            else:
                res["result"] = "skipped: a change is waiting on it"
        else:
            res.setdefault("result", "no change")
        out.append(res)
    return out


def siblings(db: Session, link: SnLink) -> list[SnLink]:
    """Every link of the same chatbot with the same address: one web page, checked once for all its categories."""
    return list(db.scalars(select(SnLink).where(SnLink.chatbot_id == link.chatbot_id, SnLink.url == link.url).order_by(SnLink.id)))


def check_link(link_id: int, trigger: str = "manual", actor: str = "system", audit: bool = False) -> None:
    """Check one web page for every category it is linked to: one fetch, one AI call, the outcome written to every sibling link."""
    db = SessionLocal()
    try:
        link = db.get(SnLink, link_id)
        if link is None:
            return
        sibs = siblings(db, link)
        for l in sibs:
            l.status = "checking"
        db.commit()
        ev = SnLinkEvent(chatbot_id=link.chatbot_id, link_id=link.id, kind="audit" if audit else "changed", trigger=trigger, actor=actor)
        try:
            page = _fetch(link.url)
        except (httpx.HTTPError, SnError) as e:
            err = str(e) or type(e).__name__
            for l in sibs:
                l.status, l.error, l.last_checked_at = "error", err, now()
                _reschedule(l)
            ev.kind, ev.error, ev.summary = "error", err, f"Could not read the page: {err}"
            db.add(ev)
            db.commit()
            return
        for l in sibs:
            l.title, l.error, l.last_checked_at = page["title"], None, now()
        base = next((l for l in sibs if l.content_hash), None)   # a link added later has no baseline yet: use a sibling's
        if base is None and not audit:
            for l in sibs:
                l.text, l.content_hash, l.status = page["text"], page["hash"], "ok"
                _reschedule(l)
            ev.kind, ev.summary = "baseline", "First read of the page. Future changes on it will be compared with this."
            db.add(ev)
            db.commit()
            return
        if not audit and page["hash"] == base.content_hash:
            for l in sibs:
                l.text, l.content_hash, l.status = base.text, base.content_hash, "ok"
                _reschedule(l)
            db.commit()
            return
        diff, added, removed = line_diff(base.text or "", page["text"]) if not audit else ([], 0, 0)
        ev.diff, ev.added, ev.removed = diff, added, removed
        db.add(ev)
        arts = {a.id: a for l in sibs for a in _articles_for(db, l)}
        payload = [{"id": a.id, "title": current_text(a)[0], "content": current_text(a)[1]} for a in sorted(arts.values(), key=lambda a: a.id)]
        cats = ", ".join(dict.fromkeys(c.path for c in (db.get(SnCategory, l.category_id) for l in sibs) if c))
        sib_ids, url = [l.id for l in sibs], link.url
        db.commit()                                           # no transaction stays open while the AI reads
        try:
            decisions = sn_ai.reconcile(cats, url, diff, page["text"], payload, audit=audit)
        except sn_ai.AIError as e:
            ev.error = str(e)
            ev.summary = ("The page changed, but the AI could not review it: " if not audit else "The AI check failed: ") + str(e)
            for l in sibs:                                    # the old text is kept, so the next check sees the change again
                l.status, l.error = "error", str(e)
                _reschedule(l)
            db.commit()
            return
        ev_id = ev.id
        # shortcut: a new article goes to the first linked category; the reviewer can change it
        ev.decisions = apply_decisions(db, sibs[0], ev, decisions, {p["id"]: p["content"] for p in payload})
        ev = db.get(SnLinkEvent, ev_id)
        sibs = [db.get(SnLink, i) for i in sib_ids]
        sibs = [l for l in sibs if l is not None]             # a person may have removed a link meanwhile
        n = {k: sum(1 for d in ev.decisions if d["action"] == k and d.get("result") == "proposed") for k in ("update", "new", "remove")}
        bits = [f"{n['update']} article update{'s' if n['update'] != 1 else ''}"] if n["update"] else []
        bits += [f"{n['new']} new article{'s' if n['new'] != 1 else ''}"] if n["new"] else []
        bits += [f"{n['remove']} removal{'s' if n['remove'] != 1 else ''}"] if n["remove"] else []
        ev.summary = (("Checked the articles against the page: " if audit else f"The page changed (+{added} −{removed} lines): ")
                      + (", ".join(bits) + " proposed for review" if bits else "no article needs to change"))
        for l in sibs:
            if not audit:
                l.text, l.content_hash, l.last_changed_at = page["text"], page["hash"], now()
            l.status = "ok"
            _reschedule(l)
        record(db, ev.chatbot_id, "link_check" if not audit else "link_audit", actor if trigger == "manual" else "Schedule",
               f"{url}: {ev.summary}", link_id=ev.link_id, event_id=ev.id, **n)
        db.commit()
    except Exception as e:                                    # noqa: BLE001
        db.rollback()
        try:
            link = db.get(SnLink, link_id)
            if link:
                for l in siblings(db, link):
                    l.status, l.error = "error", f"{type(e).__name__}: {e}"[:500]
                db.add(SnLinkEvent(chatbot_id=link.chatbot_id, link_id=link.id, kind="error", trigger=trigger, actor=actor,
                                   error=traceback.format_exc()[-1500:], summary=f"Check failed: {type(e).__name__}"))
                db.commit()
        except Exception:                                     # noqa: BLE001
            db.rollback()
    finally:
        db.close()


def _reschedule(link: SnLink) -> None:
    link.next_run_at = now() + timedelta(hours=link.schedule_hours) if link.schedule_hours else None


# ── background worker (separate from the website crawl queue) ─────────────────

_queue: "queue.Queue[tuple]" = queue.Queue()
_pending: set[int] = set()
_lock = threading.Lock()


def enqueue(link_id: int, trigger: str = "manual", actor: str = "system", audit: bool = False) -> bool:
    with _lock:
        if link_id in _pending:
            return False
        _pending.add(link_id)
    _queue.put((link_id, trigger, actor, audit))
    return True


def busy_links() -> set[int]:
    with _lock:
        return set(_pending)


def _worker() -> None:
    while True:
        link_id, trigger, actor, audit = _queue.get()
        try:
            check_link(link_id, trigger, actor, audit)
        except Exception:                                     # noqa: BLE001
            pass                                              # check_link records its own failures; never let the worker die
        finally:
            with _lock:
                _pending.discard(link_id)


def due_links(db: Session) -> list[int]:
    """For each web page with a link due, the lowest link id of its group: the scheduler checks each page once."""
    due = select(SnLink.chatbot_id, SnLink.url).where(SnLink.schedule_hours.is_not(None), SnLink.next_run_at <= now())
    return list(db.scalars(select(func.min(SnLink.id)).where(tuple_(SnLink.chatbot_id, SnLink.url).in_(due))
                           .group_by(SnLink.chatbot_id, SnLink.url)))


def _scheduler() -> None:
    while True:
        time.sleep(60)
        db = SessionLocal()
        try:
            for i in due_links(db):
                enqueue(i, "schedule", "schedule")
        except Exception:                                     # noqa: BLE001
            pass
        finally:
            db.close()


def start_background() -> None:
    db = SessionLocal()
    try:
        for l in db.scalars(select(SnLink).where(SnLink.status == "checking")):
            l.status = "error"
            l.error = "Interrupted by a server restart"
        db.commit()
        for l in db.scalars(select(SnLink).where(SnLink.status == "pending")):
            enqueue(l.id, "manual", "system")
    finally:
        db.close()
    threading.Thread(target=_worker, daemon=True).start()
    threading.Thread(target=_scheduler, daemon=True).start()


def add_link(db: Session, bot: Chatbot, category_id: int, url: str, actor: str, article_id: int | None = None,
             label: str = "", schedule_hours: int | None = 24) -> SnLink:
    c = canon(url or "")
    if not c or c.startswith(("http://localhost", "http://127.")):
        raise SnError("Enter the full web address, starting with https://")
    cat = db.get(SnCategory, category_id)
    if cat is None or cat.chatbot_id != bot.id:
        raise SnError("That category does not exist.")
    if article_id:
        a = db.get(SnArticle, article_id)
        if a is None or a.chatbot_id != bot.id:
            raise SnError("That article does not exist.")
    if db.scalar(select(SnLink.id).where(SnLink.category_id == category_id, SnLink.url == c)):
        raise SnError("That link is already on this category.")
    link = SnLink(chatbot_id=bot.id, category_id=category_id, article_id=article_id or None, url=c, label=label.strip()[:120],
                  schedule_hours=schedule_hours if schedule_hours and schedule_hours > 0 else None, created_by=actor)
    db.add(link)
    record(db, bot.id, "link_added", actor, f"Added the link {c} to “{cat.path}”", category=cat.path)
    db.commit()
    enqueue(link.id, "manual", actor)
    return link


# ── publishing ────────────────────────────────────────────────────────────────

def release_items(db: Session, bot: Chatbot) -> list[dict]:
    """What a release holds: every published, pending-retirement and retired article, with its published text
    (never a pending change), labelled [state, flags…]."""
    cats = {c.id: c for c in db.scalars(select(SnCategory).where(SnCategory.chatbot_id == bot.id))}
    return _sorted([_item(a, cats, a.title, a.content, a.category_id, STATE_LABEL[a.status]) for a in db.scalars(
        select(SnArticle).where(SnArticle.chatbot_id == bot.id, SnArticle.status.in_(RELEASED), SnArticle.content.is_not(None)))])


def everything_items(db: Session, bot: Chatbot) -> list[dict]:
    """Every article right now, for a chatbot that filters: drafts and articles in review with their pending text, the
    rest with their published text. Each gets one stage label: Draft, In review, Published, not released yet,
    Released in vN (the latest release holds this revision), Pending retirement or Retired."""
    last = latest(db, bot)
    released = {(it["entry_id"], it["revision"]) for it in last.items} if last else set()
    cats = {c.id: c for c in db.scalars(select(SnCategory).where(SnCategory.chatbot_id == bot.id))}
    items = []
    for a in db.scalars(select(SnArticle).where(SnArticle.chatbot_id == bot.id)):
        if a.status in RELEASED and a.content is not None:
            version = last.number if (a.id, a.revision) in released else None
            stage = STATE_LABEL[a.status] if a.status != "published" else (
                f"Released in v{version}" if version else "Published, not released yet")
            it = _item(a, cats, a.title, a.content, a.category_id, stage)
        elif a.status in ("draft", "review") and a.p_content is not None:
            version, stage = None, "Draft" if a.status == "draft" else "In review"
            it = _item(a, cats, a.p_title, a.p_content, a.p_category_id or a.category_id, stage)
        else:
            continue
        it["meta"] = {"stage": stage, "released_version": version}   # the JSON export adds these fields to each entry
        items.append(it)
    return _sorted(items)


def _item(a: SnArticle, cats: dict, title: str | None, content: str, category_id: int | None, stage: str) -> dict:
    c = cats.get(category_id)
    return {
        "entry_id": a.id, "title": title, "content": content, "category_id": category_id,
        "category": c.path if c else "Uncategorized", "category_position": c.position if c else 99999, "color": "slate",
        "secondary": [], "labels": [stage, *(a.labels or [])],
        "number": a.number, "source_url": kb_url(a.number), "source_title": a.number,
        "manual_edit": False, "revision": a.revision, "_order": (a.number or "~", a.id),
    }


def _sorted(items: list[dict]) -> list[dict]:
    items.sort(key=lambda x: (x["category_position"], x["_order"]))
    for it in items:
        it.pop("_order")
    return items


# Previous architecture (upstream's new/changed/approved lifecycle). Replaced on this branch by
# release_items (publishing). Kept for reference; not called.
# PUBLISHED_LABEL = "Published in ServiceNow"
# REVIEWED, NOT_REVIEWED = "Reviewed in KB Curation", "Not reviewed in KB Curation"
# INTERNAL = "Internal only"
# SN_STATE_LABEL = {"published": PUBLISHED_LABEL, **STATE_LABEL}
#
#
# def status_of(a: SnArticle, reviewed: bool) -> tuple[list[str], dict]:
#     """Labels and fields that say where an article stands, worked out from its current state at publish time, so
#     every item gets them the same way: exactly one ServiceNow state, expired/internal when true, and whether a
#     person approved it here. The chatbot can filter on either (e.g. only "Published in ServiceNow" + "Reviewed")."""
#     state = a.sn_state if a.sys_id else None
#     title, text = (a.title or a.p_title or ""), (a.content or a.p_content or "")
#     internal = INTERNAL in (a.labels or []) or INTERNAL in (a.p_labels or []) or "INTERNAL" in title or "INTERNAL USE ONLY" in text.upper()
#     expired = bool(a.sys_id) and _expired(a.valid_to)
#     labels = [SN_STATE_LABEL.get(state or "", f"{state} in ServiceNow") if a.sys_id else "Not in ServiceNow (added from a TTU page)"]
#     labels += [EXPIRED] if expired else []
#     labels += [INTERNAL] if internal else []
#     labels += [REVIEWED if reviewed else NOT_REVIEWED]
#     meta = {"servicenow_state": state, "servicenow_expired": expired, "internal_only": internal,
#             "reviewed_in_kb_curation": reviewed, "reviewed_by": a.reviewer if reviewed else None,
#             "reviewed_at": a.reviewed_at.isoformat() if reviewed and a.reviewed_at else None}
#     return labels, meta
#
#
# def _item(a: SnArticle, cats: dict, reviewed: bool) -> dict:
#     c = cats.get(a.category_id if reviewed else (a.p_category_id or a.category_id))
#     status_labels, meta = status_of(a, reviewed)
#     own = [x for x in (a.labels if reviewed else a.p_labels) or [] if x not in SYSTEM_LABELS and x != INTERNAL]
#     return {
#         "entry_id": a.id, "title": a.title if reviewed else a.p_title, "content": a.content if reviewed else a.p_content,
#         "category_id": c.id if c else None, "category": c.path if c else "Uncategorized", "category_position": c.position if c else 99999,
#         "color": "slate", "secondary": [], "labels": own + status_labels, "meta": meta,
#         "number": a.number, "source_url": kb_url(a.number), "source_title": a.number,
#         "manual_edit": False, "revision": a.revision, "_order": (a.number or "~", a.id),
#     }
#
#
# def _sorted(items: list[dict]) -> list[dict]:
#     items.sort(key=lambda x: (x["category_position"], x["_order"]))
#     for it in items:
#         it.pop("_order")
#     return items
#
#
# def live_items(db: Session, bot: Chatbot) -> list[dict]:
#     """What a published version holds: every article a person approved here (its approved text)."""
#     cats = {c.id: c for c in db.scalars(select(SnCategory).where(SnCategory.chatbot_id == bot.id))}
#     return _sorted([_item(a, cats, True) for a in db.scalars(select(SnArticle).where(
#         SnArticle.chatbot_id == bot.id, SnArticle.status.in_(LIVE), SnArticle.content.is_not(None)))])
#
#
# def everything_items(db: Session, bot: Chatbot) -> list[dict]:
#     """Approved articles plus the ones still waiting for their first review (as imported), each labelled with
#     whether it was reviewed here. Rejected and removed articles are left out."""
#     cats = {c.id: c for c in db.scalars(select(SnCategory).where(SnCategory.chatbot_id == bot.id))}
#     rows = db.scalars(select(SnArticle).where(SnArticle.chatbot_id == bot.id, SnArticle.status.not_in(("rejected", "removed")))).all()
#     out = [_item(a, cats, True) if a.content is not None else _item(a, cats, False) for a in rows
#            if a.content is not None or a.p_content is not None]
#     return _sorted(out)


def latest(db: Session, bot: Chatbot) -> SnVersion | None:
    return db.scalar(select(SnVersion).where(SnVersion.chatbot_id == bot.id).order_by(SnVersion.number.desc()).limit(1))


def draft(db: Session, bot: Chatbot) -> dict:
    last = latest(db, bot)
    items = release_items(db, bot)
    changes = publish.compare(last.items if last else [], items)
    waiting = db.scalar(select(func.count()).select_from(SnArticle).where(SnArticle.chatbot_id == bot.id, todo_clause())) or 0
    return {"base_version": last.number if last else None, "next_version": (last.number if last else 0) + 1,
            "changes": changes, "counts": publish.counts(changes), "total": len(items), "waiting_review": waiting}


def publish_version(db: Session, bot: Chatbot, note: str, actor: str) -> SnVersion:
    d = draft(db, bot)
    if not d["changes"]:
        raise SnError("Nothing has changed since the last release.")
    items = release_items(db, bot)
    v = SnVersion(chatbot_id=bot.id, number=d["next_version"], note=note.strip(), created_by=actor, items=items,
                  changes=d["changes"], stats={**d["counts"], "total": len(items)})
    db.add(v)
    st = v.stats
    record(db, bot.id, "published", actor, f"Released ServiceNow version {v.number}: {st.get('added', 0)} added, {st.get('modified', 0)} modified, "
           f"{st.get('removed', 0)} removed ({st.get('total', 0)} articles)", version=v.number)
    db.commit()
    return v


# Previous architecture (upstream's new/changed/approved lifecycle). Replaced on this branch by
# status-based labels (state is never stored as a label, so there is nothing to clear). Kept for reference; not called.
# def clear_review_flags(db: Session, bot: Chatbot, actor: str = "system") -> int:
#     """Remove review flags from approved text (articles approved before flags were left out on approval)."""
#     n = 0
#     for a in db.scalars(select(SnArticle).where(SnArticle.chatbot_id == bot.id, SnArticle.status.in_(LIVE))):
#         kept = [x for x in a.labels or [] if x not in SYSTEM_LABELS]
#         if kept != list(a.labels or []):
#             log(db, a, "flags_cleared", actor, removed=[x for x in a.labels or [] if x in SYSTEM_LABELS])
#             a.labels = kept
#             n += 1
#     if n:
#         record(db, bot.id, "clear_flags", actor, f"Removed ServiceNow workflow labels (draft, in review, pending retirement, "
#                f"expired) from the approved text of {n} articles; they stay visible in Review only")
#     db.commit()
#     return n
#
#
# if __name__ == "__main__":                       # python -m app.servicenow merge-versions | clear-flags
#     import sys as _sys
#     cmd = _sys.argv[1:]
#     if cmd not in (["merge-versions"], ["clear-flags"]):
#         _sys.exit("usage: python -m app.servicenow merge-versions | clear-flags")
#     with SessionLocal() as _db:
#         for _bot in _db.scalars(select(Chatbot).order_by(Chatbot.id)).all():
#             if cmd == ["merge-versions"]:
#                 print(_bot.key, merge_versions(_db, _bot, "Duplicate clean-up"))
#             else:
#                 print(_bot.key, "articles cleaned:", clear_review_flags(_db, _bot, "Label clean-up"))
