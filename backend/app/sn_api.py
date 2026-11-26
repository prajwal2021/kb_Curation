"""HTTP routes for the ServiceNow curation section."""
from __future__ import annotations

import json
import re
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from . import docgen, servicenow as sn, sn_ai
from .config import DATA_DIR, PUBLIC_API_BASE, SN_IMPORT_TOKEN, SN_MODEL
from .db import get_db
from .diffing import line_diff, word_diff
from .models import Activity, Chatbot, SnArticle, SnArticleEvent, SnAsset, SnCategory, SnLink, SnLinkEvent, SnVersion, User, now
from .users import actor, can_open, current_user, owned

router = APIRouter(dependencies=[Depends(current_user)])   # every ServiceNow screen needs a signed-in reviewer
public = APIRouter()   # image files linked from published exports, and the import guarded by its own token
ASSETS = DATA_DIR / "servicenow" / "assets"
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp", "image/svg+xml", "image/tiff", "image/x-icon"}


def get_bot(key: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Chatbot:
    bot = db.scalar(select(Chatbot).where(Chatbot.key == key))
    if not bot or not can_open(user, bot.id):
        raise HTTPException(404, "Chatbot not found")
    return bot


def guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except sn.SnError as e:
        raise HTTPException(400, str(e))


def shown(a: SnArticle) -> dict:
    if sn.has_proposal(a):
        return {"title": a.p_title, "content": a.p_content, "category_id": a.p_category_id if a.p_category_id is not None else a.category_id}
    return {"title": a.title, "content": a.content, "category_id": a.category_id}


def article_dict(a: SnArticle, cats: dict[int, SnCategory], full: bool = False) -> dict:
    s = shown(a)
    c = cats.get(s["category_id"])
    d = {"id": a.id, "status": a.status, "p_stage": a.p_stage, "flags": a.labels or [], **s, "category": c.path if c else None, "number": a.number, "sn_state": a.sn_state,
         "kb_url": sn.kb_url(a.number), "kind": a.p_kind, "reason": a.p_reason, "has_approved": a.content is not None,
         "edited": a.p_edited, "reviewer": a.reviewer, "reviewed_at": a.reviewed_at, "detected_at": a.detected_at,
         "updated_at": a.updated_at, "revision": a.revision, "link_id": a.p_link_id, "event_id": a.p_event_id}
    if not full:
        d["excerpt"] = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s["content"] or ""))[:240]
        d.pop("content")
    return d


def cat_map(db: Session, bot_id: int) -> dict[int, SnCategory]:
    return {c.id: c for c in db.scalars(select(SnCategory).where(SnCategory.chatbot_id == bot_id))}


# ── overview ──────────────────────────────────────────────────────────────────

@router.get("/api/chatbots/{key}/servicenow/overview")
def overview(bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    st = dict(db.execute(select(SnArticle.status, func.count()).where(SnArticle.chatbot_id == bot.id).group_by(SnArticle.status)).all())
    kinds = dict(db.execute(select(SnArticle.p_kind, func.count()).where(SnArticle.chatbot_id == bot.id, sn.todo_clause())
                            .group_by(SnArticle.p_kind)).all())
    links = dict(db.execute(select(SnLink.status, func.count()).where(SnLink.chatbot_id == bot.id).group_by(SnLink.status)).all())
    imp = db.scalar(select(Activity).where(Activity.chatbot_id == bot.id, Activity.area == "servicenow", Activity.action == "import")
                    .order_by(Activity.id.desc()).limit(1))
    v = sn.latest(db, bot)
    d = sn.draft(db, bot)
    recent = db.execute(select(SnLinkEvent, SnLink).join(SnLink, SnLink.id == SnLinkEvent.link_id)
                        .where(SnLinkEvent.chatbot_id == bot.id, SnLinkEvent.kind != "baseline").order_by(SnLinkEvent.id.desc()).limit(8)).all()
    cats = cat_map(db, bot.id)
    return {
        "imported": bool(imp), "import": {"at": imp.created_at, "by": imp.actor, **(imp.detail or {}),
                                          "articles": db.scalar(select(func.count()).select_from(SnArticle).where(
                                              SnArticle.chatbot_id == bot.id, SnArticle.sys_id.is_not(None)))} if imp else None,
        "articles": {s: st.get(s, 0) for s in sn.STATES},
        "waiting": sum(kinds.values()), "waiting_by_kind": {k or "import": n for k, n in kinds.items()},
        "live": st.get("published", 0), "categories": len(cats),
        "links": {"total": sum(links.values()), "error": links.get("error", 0), "checking": links.get("checking", 0) + links.get("pending", 0)},
        "published": version_dict(v) if v else None, "unpublished": d["counts"], "unpublished_total": len(d["changes"]),
        "recent": [event_dict(e, l, cats) for e, l in recent], "ai": sn_ai.enabled(), "model": SN_MODEL,
    }


# ── categories and links ──────────────────────────────────────────────────────

def link_dict(l: SnLink, cats: dict[int, SnCategory], busy: set[int] | None = None) -> dict:
    c = cats.get(l.category_id)
    return {"id": l.id, "url": l.url, "label": l.label, "title": l.title, "category_id": l.category_id, "category": c.path if c else None,
            "article_id": l.article_id, "schedule_hours": l.schedule_hours, "next_run_at": l.next_run_at, "last_checked_at": l.last_checked_at,
            "last_changed_at": l.last_changed_at, "status": "checking" if busy and l.id in busy else l.status, "error": l.error,
            "created_by": l.created_by, "created_at": l.created_at}


@router.get("/api/chatbots/{key}/servicenow/categories")
def categories(bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    cats = cat_map(db, bot.id)
    counts: dict[int | None, dict] = {}
    for a in db.scalars(select(SnArticle).where(SnArticle.chatbot_id == bot.id, SnArticle.status != "retired")):
        cid = shown(a)["category_id"]
        c = counts.setdefault(cid, {"total": 0, "waiting": 0, "published": 0})
        c["total"] += 1
        c["waiting"] += sn.in_todo(a)
        c["published"] += a.status == "published"
    links: dict[int, list] = {}
    busy = sn.busy_links()
    for l in db.scalars(select(SnLink).where(SnLink.chatbot_id == bot.id).order_by(SnLink.id)):
        links.setdefault(l.category_id, []).append(link_dict(l, cats, busy))
    rows = sorted(cats.values(), key=lambda c: c.position)
    return {"categories": [{"id": c.id, "name": c.name, "path": c.path, "parent_id": c.parent_id, "active": c.active,
                            "depth": c.path.count(" > "), **counts.get(c.id, {"total": 0, "waiting": 0, "published": 0}),
                            "links": links.get(c.id, [])} for c in rows],
            "uncategorized": counts.get(None, {"total": 0, "waiting": 0, "published": 0})}


class LinkIn(BaseModel):
    category_id: int | None = None
    url: str | None = None
    article_id: int | None = None
    label: str | None = None
    schedule_hours: int | None = None
    set_schedule: bool = False


@router.get("/api/chatbots/{key}/servicenow/links")
def links(bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    cats = cat_map(db, bot.id)
    busy = sn.busy_links()
    return [link_dict(l, cats, busy) for l in db.scalars(select(SnLink).where(SnLink.chatbot_id == bot.id).order_by(SnLink.id.desc()))]


@router.post("/api/chatbots/{key}/servicenow/links")
def add_link(b: LinkIn, bot: Chatbot = Depends(get_bot), who: str = Depends(actor), db: Session = Depends(get_db)):
    if not b.category_id:
        raise HTTPException(400, "Choose a category for the link.")
    hours = b.schedule_hours if b.set_schedule else 24
    if hours is not None and not 1 <= hours <= 24 * 90:
        raise HTTPException(400, "Choose a check interval between 1 hour and 90 days.")
    l = guard(sn.add_link, db, bot, b.category_id, b.url or "", who, b.article_id, b.label or "", hours)
    return link_dict(l, cat_map(db, bot.id), sn.busy_links())


def _link(db: Session, lid: int, user: User) -> SnLink:
    l = owned(db, SnLink, lid, user)
    if not l:
        raise HTTPException(404, "Link not found")
    return l


@router.patch("/api/servicenow/links/{lid}")
def update_link(lid: int, b: LinkIn, user: User = Depends(current_user), who: str = Depends(actor), db: Session = Depends(get_db)):
    l = _link(db, lid, user)
    if b.label is not None:
        l.label = b.label.strip()[:120]
    if b.set_schedule:
        if b.schedule_hours is not None and not 1 <= b.schedule_hours <= 24 * 90:
            raise HTTPException(400, "Choose a check interval between 1 hour and 90 days.")
        l.schedule_hours = b.schedule_hours or None
        sn._reschedule(l)
        sn.record(db, l.chatbot_id, "link_schedule", who, f"Checks of {l.url}: " + (f"every {l.schedule_hours} hours" if l.schedule_hours else "manual only"))
    db.commit()
    return link_dict(l, cat_map(db, l.chatbot_id), sn.busy_links())


@router.delete("/api/servicenow/links/{lid}")
def delete_link(lid: int, user: User = Depends(current_user), who: str = Depends(actor), db: Session = Depends(get_db)):
    l = owned(db, SnLink, lid, user)
    if l:
        sn.record(db, l.chatbot_id, "link_removed", who, f"Removed the link {l.url}")
        heir = next((x for x in sn.siblings(db, l) if x.id != l.id), None)
        if heir:                                              # the page is still watched: its history moves, not dies
            db.execute(update(SnLinkEvent).where(SnLinkEvent.link_id == l.id).values(link_id=heir.id))
            db.execute(update(SnArticle).where(SnArticle.p_link_id == l.id).values(p_link_id=heir.id))
        db.delete(l)
        db.commit()
    return {"ok": True}


class CheckIn(BaseModel):
    audit: bool = False


@router.post("/api/servicenow/links/{lid}/check")
def check(lid: int, b: CheckIn, user: User = Depends(current_user), who: str = Depends(actor), db: Session = Depends(get_db)):
    l = _link(db, lid, user)
    if b.audit and not sn_ai.enabled():
        raise HTTPException(400, "AI is off: add OPENAI_API_KEY to backend/.env.")
    if not sn.enqueue(l.id, "manual", who, b.audit):
        raise HTTPException(400, "This link is already being checked.")
    return {"queued": True}


# ── link events (the Changes page) ────────────────────────────────────────────

def event_dict(e: SnLinkEvent, l: SnLink, cats: dict[int, SnCategory], full: bool = False) -> dict:
    c = cats.get(l.category_id)
    d = {"id": e.id, "kind": e.kind, "trigger": e.trigger, "actor": e.actor, "added": e.added, "removed": e.removed,
         "summary": e.summary, "error": (e.error or "").split("\n")[0] or None, "created_at": e.created_at,
         "proposals": sum(1 for x in e.decisions or [] if x.get("result") == "proposed"),
         "link": {"id": l.id, "url": l.url, "title": l.title, "category": c.path if c else None}}
    if full:
        d["diff"], d["decisions"] = e.diff, e.decisions
    return d


@router.get("/api/chatbots/{key}/servicenow/events")
def events(limit: int = 100, include_baseline: bool = False, bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    q = select(SnLinkEvent, SnLink).join(SnLink, SnLink.id == SnLinkEvent.link_id).where(SnLinkEvent.chatbot_id == bot.id)
    if not include_baseline:
        q = q.where(SnLinkEvent.kind != "baseline")
    cats = cat_map(db, bot.id)
    return [event_dict(e, l, cats) for e, l in db.execute(q.order_by(SnLinkEvent.id.desc()).limit(min(limit, 500)))]


@router.get("/api/servicenow/events/{eid}")
def event_detail(eid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = owned(db, SnLinkEvent, eid, user)
    if not e:
        raise HTTPException(404, "Not found")
    return event_dict(e, db.get(SnLink, e.link_id), cat_map(db, e.chatbot_id), full=True)


# ── articles and review ───────────────────────────────────────────────────────

@router.get("/api/chatbots/{key}/servicenow/articles")
def articles(status: str = "queue", category: int | None = None, sub: bool = True, q: str | None = None, flag: str | None = None,
             kind: str | None = None, offset: int = 0, limit: int = 200, bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    cats = cat_map(db, bot.id)
    want = set(sn.descendants(db, category) if sub else [category]) if category else None
    ql = (q or "").lower().strip()
    out, total = [], 0
    which = sn.todo_clause() if status == "queue" else SnArticle.status.in_(status.split(","))
    rows = db.scalars(select(SnArticle).where(SnArticle.chatbot_id == bot.id, which).order_by(SnArticle.id)).all()
    rows = sorted(rows, key=lambda a: ((cats[shown(a)["category_id"]].position if shown(a)["category_id"] in cats else 99999), a.number or "~", a.id))
    for a in rows:
        s = shown(a)
        if category == 0 and s["category_id"] is not None:
            continue
        if want is not None and s["category_id"] not in want:
            continue
        if flag and flag not in (a.labels or []):
            continue
        if kind and (a.p_kind or "") != kind:
            continue
        if ql and ql not in f"{s['title']} {s['content']} {a.number or ''}".lower():
            continue
        total += 1
        if offset < total <= offset + min(limit, 500):
            out.append(article_dict(a, cats))
    return {"total": total, "articles": out}


@router.get("/api/chatbots/{key}/servicenow/review-summary")
def review_summary(bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    st = dict(db.execute(select(SnArticle.status, func.count()).where(SnArticle.chatbot_id == bot.id).group_by(SnArticle.status)).all())
    flags: dict[str, int] = {}
    kinds: dict[str, int] = {}
    for a in db.scalars(select(SnArticle).where(SnArticle.chatbot_id == bot.id)):
        for f in a.labels or []:
            flags[f] = flags.get(f, 0) + 1
        if sn.in_todo(a):
            kinds[a.p_kind or "import"] = kinds.get(a.p_kind or "import", 0) + 1
    return {"status": {s: st.get(s, 0) for s in sn.STATES}, "todo": sum(kinds.values()),
            "flags": sorted(flags.items(), key=lambda x: -x[1]), "kinds": kinds}


@router.get("/api/chatbots/{key}/servicenow/flags")
def flags(bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    return sn.flag_list(db, bot)


def _article(db: Session, aid: int, user: User) -> SnArticle:
    a = owned(db, SnArticle, aid, user)
    if not a:
        raise HTTPException(404, "Article not found")
    return a


def _detail(db: Session, a: SnArticle) -> dict:
    cats = cat_map(db, a.chatbot_id)
    d = article_dict(a, cats, full=True)
    d["approved"] = {"title": a.title, "content": a.content, "category_id": a.category_id} if a.content is not None else None
    d["sn_content"] = a.sn_content
    d["valid_to"], d["template"], d["sn_updated"] = a.valid_to, a.sn_template, a.sn_updated
    d["diff_base"] = None
    if a.status == "pending_retirement":
        d["diff"], d["added"], d["removed"] = line_diff(f"{a.title}\n{a.content}", "")
        d["diff_base"] = "approved"
    elif sn.has_proposal(a) and a.content is not None:      # a pending change on the published text
        d["diff"], d["added"], d["removed"] = line_diff(f"{a.title}\n{a.content}", f"{a.p_title}\n{a.p_content}", context=3)
        d["diff_base"] = "approved"
    elif a.status in ("draft", "review") and a.sn_content is not None and (a.p_content or "") != a.sn_content:
        d["diff"], d["added"], d["removed"] = line_diff(a.sn_content, a.p_content or "", context=3)
        d["diff_base"] = "servicenow"
    shown_text = a.p_content if sn.has_proposal(a) else a.content
    d["word_diff"] = None
    if a.status != "pending_retirement" and d["diff_base"] == "approved":
        d["word_diff"] = word_diff(a.content or "", a.p_content or "")
    elif d["diff_base"] == "servicenow":
        d["word_diff"] = word_diff(a.sn_content or "", a.p_content or "")
    d["same_as_servicenow"] = shown_text == a.sn_content
    up, c = set(), cats.get(a.category_id)
    while c and c.id not in up:            # the article's category and its ancestors
        up.add(c.id)
        c = cats.get(c.parent_id)
    pages = db.scalars(select(SnLink).where(SnLink.chatbot_id == a.chatbot_id, (SnLink.article_id == a.id)
                                            | (SnLink.article_id.is_(None) & SnLink.category_id.in_(up))).order_by(SnLink.id))
    d["pages"] = [{"id": l.id, "url": l.url, "title": l.title, "status": l.status} for l in pages]
    v = db.scalars(select(SnVersion).where(SnVersion.chatbot_id == a.chatbot_id).order_by(SnVersion.number.desc()).limit(1)).first()
    d["in_release"] = v.number if v and any(i.get("entry_id") == a.id for i in v.items or []) else None
    l = db.get(SnLink, a.p_link_id) if a.p_link_id else None
    d["link"] = {"id": l.id, "url": l.url, "title": l.title} if l else None
    d["history"] = [{"id": h.id, "action": h.action, "actor": h.actor, "detail": h.detail, "created_at": h.created_at}
                    for h in db.scalars(select(SnArticleEvent).where(SnArticleEvent.article_id == a.id).order_by(SnArticleEvent.id.desc()).limit(40))]
    return d


@router.get("/api/servicenow/articles/{aid}")
def article_detail(aid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _detail(db, _article(db, aid, user))


class ArticleIn(BaseModel):
    title: str | None = None
    content: str | None = None
    category_id: int | None = None
    flags: list[str] | None = None


@router.patch("/api/servicenow/articles/{aid}")
def edit_article(aid: int, b: ArticleIn, user: User = Depends(current_user), who: str = Depends(actor), db: Session = Depends(get_db)):
    a = _article(db, aid, user)
    if (b.title, b.content, b.category_id) != (None, None, None):
        guard(sn.edit, db, a, who, title=b.title, content=b.content, category_id=b.category_id)
    if b.flags is not None:
        sn.set_flags(db, a, who, b.flags)
        sn.record(db, a.chatbot_id, "flags", who, f"Set the flags of “{shown(a)['title']}” to: {', '.join(a.labels) or 'none'}", article_id=a.id)
    db.commit()
    return _detail(db, a)


class NewArticleIn(BaseModel):
    title: str
    content: str
    category_id: int | None = None
    flags: list[str] = []
    review: bool = False


@router.post("/api/chatbots/{key}/servicenow/articles")
def create_article(b: NewArticleIn, bot: Chatbot = Depends(get_bot), who: str = Depends(actor), db: Session = Depends(get_db)):
    a = guard(sn.create_article, db, bot, who, title=b.title, content=b.content, category_id=b.category_id, flags=b.flags, review=b.review)
    sn.record(db, bot.id, "created", who, f"Created “{a.p_title}”" + (" and sent it for review" if b.review else " as a draft"), article_id=a.id)
    db.commit()
    return _detail(db, a)


class NoteIn(BaseModel):
    note: str = ""


VERBS = {"send_for_review": "Sent for review", "publish": "Published", "send_back": "Sent back to draft", "discard": "Discarded",
         "suggest_retire": "Suggested retiring", "keep": "Kept published", "retire": "Retired", "restore": "Restored"}


@router.post("/api/servicenow/articles/{aid}/{action}")
def act(aid: int, action: str, b: NoteIn, user: User = Depends(current_user), who: str = Depends(actor), db: Session = Depends(get_db)):
    a = _article(db, aid, user)
    fn = sn.ACTIONS.get(action)
    if not fn:
        raise HTTPException(404)
    sn.record(db, a.chatbot_id, action, who, f"{VERBS[action]} “{shown(a)['title']}”", article_id=a.id, **({"note": b.note} if b.note else {}))
    guard(fn, db, a, who, b.note)                             # an SnError stops before the commit, so the line above is dropped
    gone = a in db.deleted                                    # discard deletes a new article that was never published
    db.commit()
    return {"deleted": True} if gone else _detail(db, a)


class BulkIn(BaseModel):
    ids: list[int]
    action: str


@router.post("/api/chatbots/{key}/servicenow/articles/bulk")
def bulk(b: BulkIn, bot: Chatbot = Depends(get_bot), who: str = Depends(actor), db: Session = Depends(get_db)):
    if b.action not in ("publish", "send_back"):
        raise HTTPException(400, "The action must be publish or send_back.")
    fn = sn.ACTIONS[b.action]
    done, skipped = 0, []
    for a in db.scalars(select(SnArticle).where(SnArticle.chatbot_id == bot.id, SnArticle.id.in_(b.ids[:1000]))):
        try:
            fn(db, a, who)
            done += 1
        except sn.SnError as e:
            skipped.append({"id": a.id, "reason": str(e)})
    if done:
        sn.record(db, bot.id, "bulk_" + b.action, who, f"{'Published' if b.action == 'publish' else 'Sent back to draft'} {done} articles in one go",
                  skipped=len(skipped))
    db.commit()
    return {"done": done, "skipped": skipped}


# ── publishing and export ─────────────────────────────────────────────────────

def version_dict(v: SnVersion, full: bool = False) -> dict:
    d = {"id": v.id, "number": v.number, "note": v.note, "created_by": v.created_by, "created_at": v.created_at, "stats": v.stats or {}}
    if full:
        d["items"], d["changes"] = v.items, v.changes
    return d


@router.get("/api/chatbots/{key}/servicenow/draft")
def draft(bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    return sn.draft(db, bot)


class PublishIn(BaseModel):
    note: str = ""


@router.post("/api/chatbots/{key}/servicenow/publish")
def do_publish(b: PublishIn, bot: Chatbot = Depends(get_bot), who: str = Depends(actor), db: Session = Depends(get_db)):
    return version_dict(guard(sn.publish_version, db, bot, b.note, who))


@router.get("/api/chatbots/{key}/servicenow/versions")
def versions(bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    return [version_dict(v) for v in db.scalars(select(SnVersion).where(SnVersion.chatbot_id == bot.id).order_by(SnVersion.number.desc()))]


def _version(db: Session, bot: Chatbot, number: int | None) -> SnVersion:
    v = sn.latest(db, bot) if not number else db.scalar(select(SnVersion).where(SnVersion.chatbot_id == bot.id, SnVersion.number == number))
    if not v:
        raise HTTPException(404, "Nothing has been published yet.")
    return v


@router.get("/api/chatbots/{key}/servicenow/versions/{number}")
def version_detail(number: int, bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    return version_dict(_version(db, bot, number), full=True)


def _for_export(items: list[dict], base: str) -> list[dict]:
    def fix(c: str) -> str:
        c = re.sub(r"\(sn-asset:([0-9a-f]{32})\)", lambda m: f"({base}/api/servicenow/assets/{m.group(1)})", c or "")
        return re.sub(r"(?m)^#{2,3} (.+)$", r"**\1**", c)
    return [{**it, "content": fix(it["content"])} for it in items]


@router.get("/api/chatbots/{key}/servicenow/export")
def export(request: Request, format: str = "json", version: int | None = None, scope: str = "published",
           bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    """scope=published: a published version. scope=everything: right now, approved articles plus those not reviewed
    yet, each labelled with its ServiceNow state and whether it was reviewed here, for a chatbot that filters."""
    base = PUBLIC_API_BASE.rstrip("/") or str(request.base_url).rstrip("/")
    if scope == "everything":
        when = now()
        raw, number, label = sn.everything_items(db, bot), 0, "everything"
        name = f"{bot.key}-servicenow-kb-everything-{when:%Y%m%d}"
    elif scope == "published":
        v = _version(db, bot, version)
        raw, number, when, label = v.items, v.number, v.created_at, f"v{v.number}"
        name = f"{bot.key}-servicenow-kb-v{v.number}"
    else:
        raise HTTPException(400, "scope must be published or everything")
    items = _for_export(raw, base)
    if format == "md":
        return Response(docgen.build_markdown(f"{bot.name} ServiceNow ({label})", number, when.strftime("%B %d, %Y"), items),
                        media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}.md"'})
    if format == "json":
        doc = docgen.build_json(f"{bot.key}-servicenow", f"{bot.name} ServiceNow", number, when.isoformat(), items)
        doc["scope"] = scope
        for e, it in zip(doc["entries"], items):
            e["servicenow_number"] = it.get("number")
            e.update(it.get("meta") or {})                 # older versions were published without these fields
        return Response(json.dumps(doc, ensure_ascii=False, indent=2), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{name}.json"'})
    raise HTTPException(400, "format must be json or md")


# ── images copied from ServiceNow ─────────────────────────────────────────────

@public.get("/api/servicenow/assets/{sid}")
def asset(sid: str, db: Session = Depends(get_db)):
    if not re.fullmatch(r"[0-9a-f]{32}", sid):
        raise HTTPException(404)
    a = db.get(SnAsset, sid)
    path = ASSETS / sid
    if not a or not path.exists():
        raise HTTPException(404, "Image not found")
    return FileResponse(path, media_type=a.content_type, headers={"Cache-Control": "public, max-age=31536000, immutable",
                                                                    "X-Content-Type-Options": "nosniff",
                                                                    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})


# ── one-time import, pushed from a signed-in browser session ──────────────────

def import_auth(x_import_token: str | None = Header(default=None)) -> None:
    if not SN_IMPORT_TOKEN:
        raise HTTPException(403, "Import is turned off on this server.")
    if not x_import_token or not secrets.compare_digest(x_import_token, SN_IMPORT_TOKEN):
        raise HTTPException(403, "Wrong import token.")


@public.post("/api/servicenow/import/{key}", dependencies=[Depends(import_auth)])
async def import_kb(request: Request, key: str, db: Session = Depends(get_db)):
    bot = db.scalar(select(Chatbot).where(Chatbot.key == key))  # the token, not a user, grants access: no get_bot
    if not bot:
        raise HTTPException(404, "Chatbot not found")
    kb = json.loads(await request.body())
    if not isinstance(kb, dict) or not isinstance(kb.get("articles"), list):
        raise HTTPException(400, "Expected {categories: [...], articles: [...]}")
    return sn.import_kb(db, bot, kb, "ServiceNow import")  # sent with a token, not a signed-in session


class IdsIn(BaseModel):
    ids: list[str]


@public.post("/api/servicenow/import-assets/missing", dependencies=[Depends(import_auth)])
def missing_assets(b: IdsIn, db: Session = Depends(get_db)):
    have = set(db.scalars(select(SnAsset.sys_id).where(SnAsset.sys_id.in_([i.lower() for i in b.ids]))))
    return {"missing": [i for i in dict.fromkeys(x.lower() for x in b.ids[:5000]) if i not in have]}


@public.post("/api/servicenow/import-assets/{sid}", dependencies=[Depends(import_auth)])
async def upload_asset(sid: str, request: Request, db: Session = Depends(get_db)):
    sid = sid.lower()
    if not re.fullmatch(r"[0-9a-f]{32}", sid):
        raise HTTPException(400, "Bad id")
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype not in IMAGE_TYPES:
        raise HTTPException(415, f"Only images are kept ({ctype or 'no type'})")
    body = await request.body()
    if not body or len(body) > 20_000_000:
        raise HTTPException(413, "Empty or too large")
    ASSETS.mkdir(parents=True, exist_ok=True)
    tmp = ASSETS / f".{sid}.part"
    tmp.write_bytes(body)
    tmp.replace(ASSETS / sid)
    a = db.get(SnAsset, sid) or SnAsset(sys_id=sid, content_type=ctype)
    a.content_type, a.size = ctype, len(body)
    db.merge(a)
    db.commit()
    return {"ok": True, "size": len(body)}
