"""ServiceNow converter and AI-edit tests: no database needed. The flow tests are in test_sn_flow.py."""
from __future__ import annotations

import pytest

from app.sn_html import article_content, image_ids, to_lines

BASE = "https://support.k12.ttu.edu/"


def test_legacy_k12_table_keeps_only_the_content():
    html = """<p><table><tbody>
      <tr><td><p>Title:</p></td><td><p>What browsers work?</p></td></tr>
      <tr><td><p>Location:</p></td><td><p>K-12 KB / SHP</p></td></tr>
      <tr><td><p>Last Updated:</p></td><td><p>07/09/2018</p></td></tr>
      <tr><td><p>Content:</p></td><td><p>First paragraph.</p><p>Second <a href="/kb_view.do?sysparm_article=KB1">link</a>.</p></td></tr>
      <tr><td><p>Article Keywords:</p></td><td><p>browser</p></td></tr></tbody></table></p>"""
    out = to_lines(html, BASE)
    assert out.splitlines() == ["First paragraph.", "Second [link](https://support.k12.ttu.edu/kb_view.do?sysparm_article=KB1)."]


def test_images_become_asset_lines_and_headings_lists_survive():
    html = """<h2>Inline Grading</h2><h3>Tools</h3>
      <p>Pick a tool: <img alt="Pen" src="/sys_attachment.do?sys_id&#61;D72F29DB8778AA10629A0ED8CEBB3529" /></p>
      <ul><li><strong>Drawing</strong> marks</li><li>Comments<ul><li>Saved</li></ul></li></ul>
      <ol><li>Open</li><li>Grade</li></ol>
      <p><img src="https://media.screensteps.com/x.png"></p>"""
    lines = to_lines(html, BASE).splitlines()
    assert lines[:2] == ["## Inline Grading", "### Tools"]
    assert "Pick a tool:" in lines
    assert "![Pen](sn-asset:d72f29db8778aa10629a0ed8cebb3529)" in lines
    assert "- Drawing marks" in lines and "  - Saved" in lines
    assert "1. Open" in lines and "2. Grade" in lines
    assert "![Image](https://media.screensteps.com/x.png)" in lines
    assert image_ids(html) == {"d72f29db8778aa10629a0ed8cebb3529"}


def test_template_parts_are_merged_and_faq_question_not_repeated():
    art = {"title": "Can I transfer?", "template": "kb_template_faq",
           "parts": [["kb_question", "<p>Can I transfer?</p>"], ["kb_answer", "<p>Yes, within 30 days.</p>"]], "text": ""}
    assert article_content(art, BASE) == "Yes, within 30 days."
    kcs = {"title": "x", "template": "kb_template_incident_kcs_article_html",
           "parts": [["kb_issue", "<p>Login fails</p>"], ["kb_resolution", "<p>Reset it</p>"]], "text": ""}
    assert article_content(kcs, BASE) == "## Issue\nLogin fails\n## Resolution\nReset it"
    empty = {"title": "y", "template": "kb_template_how_to", "parts": [["kb_introduction", ""]], "text": "<p>From text</p>"}
    assert article_content(empty, BASE) == "From text"


def test_ai_edits_apply_exactly_or_fail():
    from app.sn_ai import AIError, apply_edits

    body = "Refunds take 10 days.\n![Form](sn-asset:abc)\nThe fee is $40.\nContact us."
    out = apply_edits(body, [{"find": "The fee is $40.", "replace": "The fee is $50."},
                             {"find": "Contact us.", "replace": "Contact us.\n- Phone: 806-555-0100"}])
    assert out == "Refunds take 10 days.\n![Form](sn-asset:abc)\nThe fee is $50.\nContact us.\n- Phone: 806-555-0100"
    assert apply_edits(body, [{"find": "The  fee is\n$40.", "replace": "x"}]).endswith("x\nContact us.")
    with pytest.raises(AIError):
        apply_edits(body, [{"find": "not in the article", "replace": "x"}])
    with pytest.raises(AIError):
        apply_edits("a\na", [{"find": "a", "replace": "b"}])


# Previous architecture (upstream's new/changed/approved lifecycle). Replaced on this branch by test_sn_flow.py:
# test_import_groups_versions_by_number, test_import_merges_duplicate_rows_keeping_links_and_events,
# test_merge_keeps_newest_person_edit_and_logs_the_other, test_release_labels_and_contents and
# test_everything_export_labels_each_stage. Kept for reference; not run.
#
# @pytestmark_db
# def test_versions_collapse_to_one_article_per_number(env):
#     s, bot, sn = env
#     from app.models import SnArticle
#
#     cat = {"sys_id": "c" * 32, "label": "Fees", "parent": None, "active": True}
#     def art(sys, state, updated, text):
#         return {"sys_id": sys, "number": "KB9", "title": "Fees", "state": state, "category": "c" * 32, "template": "kb_template_what_is",
#                 "valid_to": "2100-01-01", "updated": updated, "parts": [["kb_explanation", f"<p>{text}</p>"]], "text": ""}
#
#     # one import batch holding the published version and a newer one in review: one article, published text, flagged
#     st = sn.import_kb(s, bot, {"categories": [cat], "articles": [art("1" * 32, "review", "2025-02-01", "Fee is $50."),
#                                                                 art("2" * 32, "published", "2025-01-01", "Fee is $40.")]}, "t")
#     rows = s.query(SnArticle).filter_by(number="KB9").all()
#     assert len(rows) == 1 and st["versions_skipped"] == 1
#     assert rows[0].sys_id == "2" * 32 and rows[0].p_content == "Fee is $40." and sn.NEWER in rows[0].p_labels
#
#     # re-import never brings the other version back
#     sn.import_kb(s, bot, {"categories": [cat], "articles": [art("1" * 32, "review", "2025-02-01", "Fee is $50.")]}, "t")
#     assert s.query(SnArticle).filter_by(number="KB9").count() == 1
#
#     # data imported before this fix: two approved rows; merging keeps the published one and proposes the newer text
#     a1 = rows[0]
#     sn.approve(s, a1, "t")
#     dup = SnArticle(chatbot_id=bot.id, sys_id="3" * 32, number="KB9", sn_state="review", sn_updated="2025-03-01",
#                     status="approved", title="Fees", content="Fee is $55.", category_id=a1.category_id)
#     same = SnArticle(chatbot_id=bot.id, sys_id="4" * 32, number="KB8", sn_state="published", sn_updated="2025-01-01",
#                      status="approved", title="X", content="Same.")
#     same2 = SnArticle(chatbot_id=bot.id, sys_id="5" * 32, number="KB8", sn_state="draft", sn_updated="2025-02-01",
#                       status="approved", title="X", content="Same.")
#     s.add_all([dup, same, same2])
#     s.commit()
#     r = sn.merge_versions(s, bot, "t")
#     assert r == {"numbers": 2, "removed": 2, "proposals": 1}
#     kept = s.query(SnArticle).filter_by(number="KB9").one()
#     assert kept.id == a1.id and kept.status == "changed" and kept.content == "Fee is $40." and kept.p_content == "Fee is $55."
#     assert s.query(SnArticle).filter_by(number="KB8").one().sys_id == "4" * 32
#     sn.approve(s, kept, "t")
#     assert kept.content == "Fee is $55." and sn.NEWER not in kept.labels
#     assert sn.merge_versions(s, bot, "t") == {"numbers": 0, "removed": 0, "proposals": 0}
#
#
# @pytestmark_db
# def test_every_published_item_gets_consistent_status_labels(env):
#     s, bot, sn = env
#     from app.models import SnArticle
#
#     sn.import_kb(s, bot, KB, "t")
#     a = s.query(SnArticle).filter_by(number="KB2").one()        # a draft in ServiceNow, flagged "Internal only"
#     assert "Draft in ServiceNow" in a.p_labels                   # the reviewer sees where it stood in ServiceNow
#     sn.approve(s, a, "Jane")
#     assert "Draft in ServiceNow" not in a.labels                 # not stored: worked out again at publish time
#
#     old = s.query(SnArticle).filter_by(number="KB1").one()        # published in ServiceNow, expired, approved long ago
#     sn.approve(s, old, "Jane")
#     old.labels = ["In review in ServiceNow", "Fees"]             # a stale flag left over from before
#     s.commit()
#     items = {i["number"]: i for i in sn.live_items(s, bot)}
#     assert items["KB1"]["labels"] == ["Fees", "Published in ServiceNow", "Expired in ServiceNow", "Reviewed in KB Curation"]
#     assert items["KB2"]["labels"] == ["Draft in ServiceNow", "Internal only", "Reviewed in KB Curation"]
#     assert items["KB2"]["meta"]["servicenow_state"] == "draft" and items["KB2"]["meta"]["reviewed_by"] == "Jane"
#     assert sn.clear_review_flags(s, bot, "t") == 1 and old.labels == ["Fees"]
#
#
# @pytestmark_db
# def test_everything_export_includes_unreviewed_articles_labelled(env):
#     s, bot, sn = env
#     from app.models import SnArticle
#
#     sn.import_kb(s, bot, KB, "t")
#     sn.approve(s, s.query(SnArticle).filter_by(number="KB1").one(), "Jane")
#     rej = s.query(SnArticle).filter_by(number="KB2").one()
#     s.commit()
#     every = {i["number"]: i for i in sn.everything_items(s, bot)}
#     assert every["KB1"]["meta"]["reviewed_in_kb_curation"] and "Reviewed in KB Curation" in every["KB1"]["labels"]
#     assert not every["KB2"]["meta"]["reviewed_in_kb_curation"] and "Not reviewed in KB Curation" in every["KB2"]["labels"]
#     assert every["KB2"]["content"] == "Escalate."
#     sn.reject(s, rej, "Jane")
#     s.commit()
#     assert "KB2" not in {i["number"] for i in sn.everything_items(s, bot)}
#     assert [i["number"] for i in sn.live_items(s, bot)] == ["KB1"]
