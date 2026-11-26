"""KB Curation API."""
from __future__ import annotations

import json
import re
import secrets
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import APIRouter, Cookie, Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import categorize, docgen, gdocs, pipeline, publish, review, scope, servicenow, sn_api
from .config import DATA_DIR, EXTRA_ORIGINS, OPENAI_API_KEY, WEB_ORIGIN
from .crawler import canon
from .db import Base, SessionLocal, engine, get_db
from .diffing import line_diff
from .pipeline import record
from .models import (Activity, Category, Chatbot, Comment, CrawlRun, Entry, EntryEvent, KbVersion, LoginSession, Page, PageEvent,
                     ScopeTopic, SnArticle, Source, User, now)
from .users import (MIN_PASSWORD, actor, add_user_columns, can_open, current_user, find_user, hash_password, owned,
                    require_admin, token_hash, verify_password)

QUEUE = ("new", "changed", "removal")


def seed() -> None:
    db = SessionLocal()
    try:
        if not db.scalar(select(func.count()).select_from(Chatbot)):
            for key, name, desc, url in (
                ("k12", "TTU K-12", "Texas Tech K-12 chatbot for families, students and schools", "https://www.depts.ttu.edu/k12/"),
                ("ttu-online", "TTU Online", "Texas Tech Online chatbot for prospective and current online students", "https://www.depts.ttu.edu/online/"),
            ):
                create_chatbot(db, key, name, desc, [url])
        add_default_excludes(db)
    finally:
        db.close()


# Staff directories are not chatbot knowledge. Added once (the activity line remembers it), so removing it on the
# Sources page keeps it removed.
DEFAULT_EXCLUDE = {"https://www.depts.ttu.edu/k12/": "/k12/about/staff/", "https://www.depts.ttu.edu/online/": "/online/about/staff/"}


def add_default_excludes(db: Session) -> None:
    for s in db.scalars(select(Source).where(Source.url.in_(DEFAULT_EXCLUDE))):
        rule = DEFAULT_EXCLUDE[s.url]
        if not db.scalar(select(Activity.id).where(Activity.chatbot_id == s.chatbot_id, Activity.detail["default"].astext == rule)):
            s.exclude = [*(x for x in s.exclude or [] if x != rule), rule]
            record(db, s.chatbot_id, "pages", "exclude_rules", "system",
                   f"Now leaving out {rule} (staff directory). Remove it on the Sources page to crawl it.", source=s.url, default=rule)
    db.commit()


def create_chatbot(db: Session, key: str, name: str, desc: str, urls: list[str]) -> Chatbot:
    bot = Chatbot(key=key, name=name, description=desc)
    db.add(bot)
    db.flush()
    for i, (cname, cdesc, kws) in enumerate(categorize.seed_for(key)):
        db.add(Category(chatbot_id=bot.id, key=re.sub(r"[^a-z0-9]+", "-", cname.lower()).strip("-"), name=cname,
                        description=cdesc, keywords=kws, color=categorize.COLORS[i % len(categorize.COLORS)], position=i))
    for u in urls:
        c = canon(u)
        if c:
            db.add(Source(chatbot_id=bot.id, url=c, label=""))
    db.commit()
    return bot


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    with engine.begin() as con:            # additive changes for databases created by an earlier version
        con.exec_driver_sql("ALTER TABLE sources ADD COLUMN IF NOT EXISTS exclude JSONB DEFAULT '[]'::jsonb")
        con.exec_driver_sql("ALTER TABLE pages ADD COLUMN IF NOT EXISTS found_via VARCHAR(10) DEFAULT 'link'")
        con.exec_driver_sql("ALTER TABLE pages ADD COLUMN IF NOT EXISTS verdict VARCHAR(8)")
        con.exec_driver_sql("ALTER TABLE pages ADD COLUMN IF NOT EXISTS checks JSONB DEFAULT '[]'::jsonb")
        con.exec_driver_sql("ALTER TABLE pages ADD COLUMN IF NOT EXISTS verified_hash VARCHAR(64)")
        con.exec_driver_sql("ALTER TABLE pages ADD COLUMN IF NOT EXISTS keep BOOLEAN DEFAULT false")
        con.exec_driver_sql("ALTER TABLE chatbots ADD COLUMN IF NOT EXISTS scope_threshold DOUBLE PRECISION")
        con.exec_driver_sql("ALTER TABLE entries ADD COLUMN IF NOT EXISTS scope_topic_id INTEGER")
        con.exec_driver_sql("ALTER TABLE entries ADD COLUMN IF NOT EXISTS scope_score DOUBLE PRECISION")
        con.exec_driver_sql("ALTER TABLE entries ADD COLUMN IF NOT EXISTS in_scope BOOLEAN")
        con.exec_driver_sql("ALTER TABLE entries ADD COLUMN IF NOT EXISTS scope_verdict BOOLEAN")
        con.exec_driver_sql("ALTER TABLE sn_articles ALTER COLUMN status TYPE VARCHAR(20)")
        con.exec_driver_sql("ALTER TABLE sn_articles ADD COLUMN IF NOT EXISTS p_stage VARCHAR(10)")
        con.exec_driver_sql("ALTER TABLE sn_articles ADD COLUMN IF NOT EXISTS app_changed BOOLEAN DEFAULT false")
        add_user_columns(con)
    seed()
    # Previous architecture, hidden for now: the website crawler and its schedule (it can call OpenAI on every run).
    # pipeline.start_background()
    servicenow.start_background()
    yield


app = FastAPI(title="KB Curation", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[WEB_ORIGIN, "http://localhost:3010", "http://127.0.0.1:3010", *EXTRA_ORIGINS],
                   allow_methods=["*"], allow_headers=["*"], expose_headers=["Content-Disposition"], allow_credentials=True)


# ── sign-in ───────────────────────────────────────────────────────────────────
COOKIE = "kb_session"
SESSION_LIFE = timedelta(days=30)
# checked when the name is unknown, so a wrong name takes as long as a wrong password and doesn't reveal who has an account
DUMMY_HASH = hash_password(secrets.token_hex(8))


# Every route except login is on this router, so none can be left open by mistake.
api = APIRouter(dependencies=[Depends(current_user)])
app.include_router(sn_api.router)   # ServiceNow: locked the same way inside sn_api
app.include_router(sn_api.public)   # ServiceNow: image files and the token-guarded import


class LoginIn(BaseModel):
    name: str
    password: str


class PasswordIn(BaseModel):
    current: str
    new: str


@app.post("/api/login")
def login(b: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = find_user(db, b.name)
    ok = verify_password(b.password, user.password_hash if user else DUMMY_HASH)
    if not (user and ok):
        raise HTTPException(401, "Wrong name or password")
    token = secrets.token_urlsafe(32)
    db.add(LoginSession(token_hash=token_hash(token), user_id=user.id, expires_at=now() + SESSION_LIFE))
    db.commit()
    response.set_cookie(COOKIE, token, max_age=int(SESSION_LIFE.total_seconds()), httponly=True, samesite="lax",
                        secure=WEB_ORIGIN.startswith("https"))
    return {"name": user.name}


@api.post("/api/logout")
def logout(response: Response, kb_session: str | None = Cookie(default=None), db: Session = Depends(get_db)):
    if s := db.get(LoginSession, token_hash(kb_session or "")):
        db.delete(s)
        db.commit()
    response.delete_cookie(COOKIE)
    return {"ok": True}


@api.get("/api/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "name": user.name, "is_admin": bool(user.is_admin)}


@api.post("/api/me/password")
def change_password(b: PasswordIn, user: User = Depends(current_user), kb_session: str | None = Cookie(default=None),
                    db: Session = Depends(get_db)):
    if not verify_password(b.current, user.password_hash):
        raise HTTPException(400, "Current password is wrong")
    if len(b.new) < MIN_PASSWORD:
        raise HTTPException(400, f"New password must be at least {MIN_PASSWORD} characters")
    user.password_hash = hash_password(b.new)
    # sign out the user's other browsers; this one stays signed in
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id,
                                          LoginSession.token_hash != token_hash(kb_session or "")))
    db.commit()
    return {"ok": True}


def get_bot(key: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Chatbot:
    bot = db.scalar(select(Chatbot).where(Chatbot.key == key))
    if not bot or not can_open(user, bot.id):
        raise HTTPException(404, "Chatbot not found")
    return bot


def guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except (review.ReviewError, scope.ScopeError, ValueError) as e:
        raise HTTPException(400, str(e))


# ── serializers ───────────────────────────────────────────────────────────────

def run_dict(r: CrawlRun | None) -> dict | None:
    if not r:
        return None
    return {"id": r.id, "status": r.status, "stage": r.stage, "trigger": r.trigger, "progress": r.progress or {},
            "stats": r.stats or {}, "error": (r.error or "").split("\n")[0] or None, "created_by": r.created_by,
            "created_at": r.created_at, "started_at": r.started_at, "finished_at": r.finished_at}


def shown(e: Entry) -> dict:
    """The values a reviewer should see for this entry right now."""
    if review.has_proposal(e):
        return {"title": e.p_title, "content": e.p_content, "category_id": e.p_category_id,
                "secondary_ids": e.p_secondary_ids or [], "labels": e.p_labels or []}
    return {"title": e.title, "content": e.content, "category_id": e.category_id,
            "secondary_ids": e.secondary_ids or [], "labels": e.labels or []}


def topic_names(db: Session, bot_id: int) -> dict[int, str]:
    return dict(db.execute(select(ScopeTopic.id, ScopeTopic.name).where(ScopeTopic.chatbot_id == bot_id)).all())


def entry_dict(e: Entry, page: Page | None, full: bool = False, topics: dict[int, str] | None = None) -> dict:
    s = shown(e)
    d = {"id": e.id, "status": e.status, **s,
         "scope": None if e.in_scope is None else {"in": e.in_scope, "topic_id": e.scope_topic_id, "score": e.scope_score,
                                                   "topic": (topics or {}).get(e.scope_topic_id)}, "page": {"id": page.id, "url": page.url, "title": page.title, "status": page.status} if page else None,
         "has_approved": e.content is not None, "duplicate_of": e.duplicate_of, "manual_edit": e.manual_edit, "edited": e.p_edited, "reviewer": e.reviewer,
         "reviewed_at": e.reviewed_at, "detected_at": e.detected_at, "updated_at": e.updated_at, "revision": e.revision}
    if not full:
        d["excerpt"] = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", (s["content"] or ""))[:240]
        d.pop("content")
    return d


def version_dict(v: KbVersion, full: bool = False) -> dict:
    d = {"id": v.id, "number": v.number, "note": v.note, "created_by": v.created_by, "created_at": v.created_at, "stats": v.stats or {}}
    if full:
        d["items"], d["changes"] = v.items, v.changes
    return d


# ── chatbots ──────────────────────────────────────────────────────────────────

class ChatbotIn(BaseModel):
    name: str
    description: str = ""
    urls: list[str] = []


@api.get("/api/chatbots")
def chatbots(user: User = Depends(current_user), db: Session = Depends(get_db)):
    out = []
    for b in db.scalars(select(Chatbot).order_by(Chatbot.id)):
        if not can_open(user, b.id):
            continue
        waiting = db.scalar(select(func.count()).select_from(Entry).where(Entry.chatbot_id == b.id, Entry.status.in_(QUEUE)))
        sn_waiting = db.scalar(select(func.count()).select_from(SnArticle).where(SnArticle.chatbot_id == b.id, servicenow.todo_clause()))
        out.append({"id": b.id, "key": b.key, "name": b.name, "description": b.description, "waiting": waiting, "sn_waiting": sn_waiting})
    return out


@api.post("/api/chatbots")
def add_chatbot(b: ChatbotIn, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    key = re.sub(r"[^a-z0-9]+", "-", b.name.lower()).strip("-")[:40]
    if not key:
        raise HTTPException(400, "Give the chatbot a name.")
    if db.scalar(select(Chatbot).where(Chatbot.key == key)):
        raise HTTPException(400, "A chatbot with that name already exists.")
    bad = [u for u in b.urls if u.strip() and not canon(u)]
    if bad:
        raise HTTPException(400, f"Not a valid URL: {bad[0]}")
    bot = create_chatbot(db, key, b.name.strip(), b.description.strip(), [u for u in b.urls if u.strip()])
    return {"key": bot.key, "name": bot.name}


@api.get("/api/chatbots/{key}/overview")
def overview(bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    pages = dict(db.execute(select(Page.status, func.count()).where(Page.chatbot_id == bot.id).group_by(Page.status)).all())
    entries = dict(db.execute(select(Entry.status, func.count()).where(Entry.chatbot_id == bot.id).group_by(Entry.status)).all())
    runs = db.scalars(select(CrawlRun).where(CrawlRun.chatbot_id == bot.id).order_by(CrawlRun.id.desc()).limit(14)).all()
    active = next((r for r in runs if r.status in ("queued", "running")), None)
    last_done = next((r for r in runs if r.status == "done"), None)
    v = publish.latest(db, bot)
    d = publish.draft(db, bot)
    recent = db.execute(select(PageEvent, Page).join(Page, Page.id == PageEvent.page_id).where(PageEvent.chatbot_id == bot.id)
                        .order_by(PageEvent.id.desc()).limit(8)).all()
    return {
        "chatbot": {"key": bot.key, "name": bot.name, "description": bot.description},
        "pages": {"active": pages.get("active", 0), "removed": pages.get("removed", 0), "skipped": pages.get("skipped", 0), "excluded": pages.get("excluded", 0),
                  "error": pages.get("error", 0)},
        "entries": {s: entries.get(s, 0) for s in ("new", "changed", "removal", "approved", "rejected", "removed")},
        "waiting": sum(entries.get(s, 0) for s in QUEUE),
        "live": sum(entries.get(s, 0) for s in publish.LIVE),
        "sources": db.scalar(select(func.count()).select_from(Source).where(Source.chatbot_id == bot.id)),
        "active_run": run_dict(active), "last_run": run_dict(last_done),
        "runs": [run_dict(r) for r in reversed(runs) if r.status == "done"],
        "published": version_dict(v) if v else None,
        "unpublished": d["counts"], "unpublished_total": len(d["changes"]),
        "recent": [{"id": ev.id, "kind": ev.kind, "added": ev.added, "removed": ev.removed, "created_at": ev.created_at,
                    "page": {"id": p.id, "title": p.title, "url": p.url}} for ev, p in recent],
        "document": {"gdoc_url": bot.gdoc_url, "synced_version": bot.gdoc_synced_version},
    }


# ── sources and crawl runs ────────────────────────────────────────────────────

class SourceIn(BaseModel):
    url: str | None = None
    label: str | None = None
    max_pages: int | None = None
    schedule_hours: int | None = None
    set_schedule: bool = False
    exclude: list[str] | None = None


def source_dict(s: Source, db: Session) -> dict:
    n = dict(db.execute(select(Page.status, func.count()).where(Page.source_id == s.id).group_by(Page.status)).all())
    return {"id": s.id, "url": s.url, "label": s.label, "max_pages": s.max_pages, "exclude": s.exclude or [], "schedule_hours": s.schedule_hours,
            "next_run_at": s.next_run_at, "last_run_at": s.last_run_at, "pages": n.get("active", 0),
            "skipped": n.get("skipped", 0), "removed": n.get("removed", 0), "excluded": n.get("excluded", 0)}


@api.get("/api/chatbots/{key}/sources")
def sources(bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    return [source_dict(s, db) for s in db.scalars(select(Source).where(Source.chatbot_id == bot.id).order_by(Source.id))]


@api.post("/api/chatbots/{key}/sources")
def add_source(b: SourceIn, bot: Chatbot = Depends(get_bot), who: str = Depends(actor), db: Session = Depends(get_db)):
    url = canon(b.url or "")
    if not url:
        raise HTTPException(400, "Enter a full web address, e.g. https://www.depts.ttu.edu/k12/")
    if db.scalar(select(Source).where(Source.chatbot_id == bot.id, Source.url == url)):
        raise HTTPException(400, "That source is already listed.")
    s = Source(chatbot_id=bot.id, url=url, label=(b.label or "").strip(), max_pages=b.max_pages or 2500)
    db.add(s)
    record(db, bot.id, "pages", "source_added", who, f"Added the source {url}")
    db.commit()
    return source_dict(s, db)


@api.patch("/api/sources/{sid}")
def update_source(sid: int, b: SourceIn, user: User = Depends(current_user), who: str = Depends(actor), db: Session = Depends(get_db)):
    s = owned(db, Source, sid, user)
    if not s:
        raise HTTPException(404)
    if b.label is not None:
        s.label = b.label.strip()
    if b.max_pages:
        s.max_pages = max(1, min(b.max_pages, 5000))
    if b.exclude is not None:
        new = [x for x in dict.fromkeys(e.strip() for e in b.exclude) if x][:50]
        added, gone = [x for x in new if x not in (s.exclude or [])], [x for x in (s.exclude or []) if x not in new]
        s.exclude = new
        if added or gone:
            record(db, s.chatbot_id, "pages", "exclude_rules", who,
                   "; ".join(([f"Now leaving out addresses containing {', '.join(added)}"] if added else [])
                             + ([f"No longer leaving out {', '.join(gone)}"] if gone else [])), source=s.url)
    if b.set_schedule:
        record(db, s.chatbot_id, "pages", "schedule", who,
               f"Automatic checks for {s.url}: " + (f"every {b.schedule_hours} hours" if b.schedule_hours else "turned off"))
        s.schedule_hours = b.schedule_hours or None
        s.next_run_at = now() + timedelta(hours=b.schedule_hours) if b.schedule_hours else None
    db.commit()
    return source_dict(s, db)


@api.delete("/api/sources/{sid}")
def delete_source(sid: int, user: User = Depends(current_user), who: str = Depends(actor), db: Session = Depends(get_db)):
    s = owned(db, Source, sid, user)
    if s:
        record(db, s.chatbot_id, "pages", "source_removed", who, f"Removed the source {s.url}")
        db.delete(s)
        db.commit()
    return {"ok": True}


class CrawlIn(BaseModel):
    source_id: int | None = None


@api.post("/api/chatbots/{key}/crawl")
def crawl_now(b: CrawlIn, bot: Chatbot = Depends(get_bot), who: str = Depends(actor), db: Session = Depends(get_db)):
    if not db.scalar(select(func.count()).select_from(Source).where(Source.chatbot_id == bot.id)):
        raise HTTPException(400, "Add a source URL first.")
    return run_dict(pipeline.start_run(db, bot, b.source_id, "manual", who))


@api.get("/api/chatbots/{key}/runs")
def runs(bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    return [run_dict(r) for r in db.scalars(select(CrawlRun).where(CrawlRun.chatbot_id == bot.id).order_by(CrawlRun.id.desc()).limit(40))]


# ── pages and changes ─────────────────────────────────────────────────────────

@api.get("/api/chatbots/{key}/pages")
def pages(bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    counts: dict[int, dict] = {}
    for pid, st, n in db.execute(select(Entry.page_id, Entry.status, func.count()).where(Entry.chatbot_id == bot.id).group_by(Entry.page_id, Entry.status)):
        c = counts.setdefault(pid, {"entries": 0, "waiting": 0})
        if st in QUEUE:
            c["waiting"] += n
        if st not in ("rejected", "removed"):
            c["entries"] += n
    last_run = db.scalar(select(func.max(CrawlRun.id)).where(CrawlRun.chatbot_id == bot.id, CrawlRun.status == "done"))
    first_run = db.scalar(select(func.min(CrawlRun.id)).where(CrawlRun.chatbot_id == bot.id, CrawlRun.status == "done"))
    rows = db.scalars(select(Page).where(Page.chatbot_id == bot.id).order_by(Page.last_changed_at.desc().nulls_last(), Page.url)).all()
    return {"last_run_id": last_run, "pages": [{
        "id": p.id, "url": p.url, "title": p.title, "status": p.status, "reason": p.skip_reason, "http_status": p.http_status,
        "depth": p.depth, "found_via": p.found_via, "verdict": p.verdict, "kept_by_person": bool(p.keep), "first_seen_at": p.first_seen_at, "last_crawled_at": p.last_crawled_at, "last_changed_at": p.last_changed_at,
        "last_change_kind": p.last_change_kind, "change_count": p.change_count, "changed_in_last_run": p.changed_run_id == last_run and last_run is not None,
        "new_in_last_run": p.changed_run_id == last_run and last_run is not None and p.last_change_kind == "new" and (first_run is not None and first_run != last_run),
        **counts.get(p.id, {"entries": 0, "waiting": 0})} for p in rows]}


class PageIn(BaseModel):
    url: str


@api.post("/api/chatbots/{key}/pages")
def add_page(b: PageIn, bot: Chatbot = Depends(get_bot), who: str = Depends(actor), db: Session = Depends(get_db)):
    url = canon(b.url)
    if not url:
        raise HTTPException(400, "Enter the full address of the page, starting with https://")
    p = db.scalar(select(Page).where(Page.chatbot_id == bot.id, Page.url == url))
    if p and p.status == "active":
        raise HTTPException(400, "That page is already being tracked.")
    src = next((s for s in db.scalars(select(Source).where(Source.chatbot_id == bot.id).order_by(Source.id)) if url.startswith(s.url)), None) \
        or db.scalar(select(Source).where(Source.chatbot_id == bot.id).order_by(Source.id).limit(1))
    if not src:
        raise HTTPException(400, "Add a source first.")
    if not p:
        p = Page(chatbot_id=bot.id, source_id=src.id, url=url, depth=1, title=url.rstrip("/").rsplit("/", 1)[-1], found_via="manual")
        db.add(p)
    p.status, p.skip_reason, p.content_hash, p.text, p.miss_count, p.source_id = "active", "Added by hand. It will be read at the next check.", None, None, 0, src.id
    p.keep = True                          # a person asked for this page, so the automatic check does not drop it
    if p.found_via != "link":
        p.found_via = "manual"
    record(db, bot.id, "pages", "page_added", who, f"Added the page {url} by hand", url=url)
    db.commit()
    return {"id": p.id}


class PagesIn(BaseModel):
    ids: list[int]
    action: str            # exclude | include


@api.post("/api/chatbots/{key}/pages/bulk")
def pages_bulk(b: PagesIn, bot: Chatbot = Depends(get_bot), who: str = Depends(actor), db: Session = Depends(get_db)):
    rows = db.scalars(select(Page).where(Page.chatbot_id == bot.id, Page.id.in_(b.ids))).all()
    done, proposals = [], 0
    for p in rows:
        if b.action == "exclude" and p.status in ("active", "error", "removed"):
            p.status, p.skip_reason, p.keep = "excluded", f"Taken out of crawling by {who}", False
            for e in db.scalars(select(Entry).where(Entry.page_id == p.id)):
                proposals += pipeline.propose_removal(db, e, f"{who} took the page out of crawling")
            done.append(p)
        elif b.action == "include" and p.status in ("excluded", "skipped", "removed", "error"):
            p.keep = p.keep or p.verdict == "fail"            # overrules the automatic check from now on
            p.status, p.skip_reason, p.content_hash, p.text, p.miss_count = "active", "Put back by a reviewer. It will be read at the next check.", None, None, 0
            done.append(p)
    if done:
        verb = "Took" if b.action == "exclude" else "Put"
        tail = "out of crawling" if b.action == "exclude" else "back into crawling"
        what = done[0].url if len(done) == 1 else f"{len(done)} pages"
        record(db, bot.id, "pages", "page_excluded" if b.action == "exclude" else "page_included", who,
               f"{verb} {what} {tail}" + (f"; {proposals} approved entries now need a removal decision" if proposals else ""),
               urls=[p.url for p in done][:200])
    db.commit()
    return {"done": len(done), "removal_proposals": proposals}


@api.get("/api/chatbots/{key}/activity")
def activity(area: str | None = None, actions: str | None = None, limit: int = 200, bot: Chatbot = Depends(get_bot),
             db: Session = Depends(get_db)):
    q = select(Activity).where(Activity.chatbot_id == bot.id)
    if area:
        q = q.where(Activity.area == area)
    if actions:
        q = q.where(Activity.action.in_(actions.split(",")))
    rows = db.scalars(q.order_by(Activity.id.desc()).limit(min(limit, 1000))).all()
    counts = dict(db.execute(select(Activity.area, func.count()).where(Activity.chatbot_id == bot.id).group_by(Activity.area)).all())
    by_action = dict(db.execute(select(Activity.action, func.count()).where(Activity.chatbot_id == bot.id).group_by(Activity.action)).all())
    return {"counts": counts, "actions": by_action, "items": [{"id": a.id, "area": a.area, "action": a.action, "actor": a.actor, "summary": a.summary,
                                         "detail": a.detail, "created_at": a.created_at} for a in rows]}


def event_dict(ev: PageEvent, p: Page, diff: bool = False) -> dict:
    d = {"id": ev.id, "kind": ev.kind, "added": ev.added, "removed": ev.removed, "created_at": ev.created_at, "run_id": ev.run_id,
         "page": {"id": p.id, "title": p.title, "url": p.url}}
    if diff:
        d["diff"] = ev.diff
    return d


@api.get("/api/pages/{pid}")
def page_detail(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = owned(db, Page, pid, user)
    if not p:
        raise HTTPException(404)
    events = db.scalars(select(PageEvent).where(PageEvent.page_id == pid).order_by(PageEvent.id.desc()).limit(30)).all()
    entries = db.scalars(select(Entry).where(Entry.page_id == pid).order_by(Entry.position)).all()
    return {"id": p.id, "url": p.url, "title": p.title, "status": p.status, "reason": p.skip_reason, "http_status": p.http_status,
            "first_seen_at": p.first_seen_at, "last_crawled_at": p.last_crawled_at, "last_changed_at": p.last_changed_at,
            "change_count": p.change_count, "found_via": p.found_via, "verdict": p.verdict, "checks": p.checks or [], "kept_by_person": bool(p.keep), "events": [event_dict(e, p, diff=i == 0 or e.kind != "new") for i, e in enumerate(events)],
            "entries": [entry_dict(e, None, topics=topic_names(db, p.chatbot_id)) for e in entries]}


@api.get("/api/chatbots/{key}/changes")
def changes(run_id: int | None = None, bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    runs_ = db.scalars(select(CrawlRun).where(CrawlRun.chatbot_id == bot.id, CrawlRun.status.in_(("done", "failed")))
                       .order_by(CrawlRun.id.desc()).limit(40)).all()
    rid = run_id or (runs_[0].id if runs_ else None)
    rows = db.execute(select(PageEvent, Page).join(Page, Page.id == PageEvent.page_id)
                      .where(PageEvent.chatbot_id == bot.id, PageEvent.run_id == rid).order_by(PageEvent.kind, Page.url)).all() if rid else []
    return {"runs": [run_dict(r) for r in runs_], "run_id": rid, "events": [event_dict(ev, p) for ev, p in rows]}


@api.get("/api/events/{eid}")
def event_detail(eid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ev = owned(db, PageEvent, eid, user)
    if not ev:
        raise HTTPException(404)
    return event_dict(ev, db.get(Page, ev.page_id), diff=True)


# ── categories ────────────────────────────────────────────────────────────────

class CategoryIn(BaseModel):
    name: str | None = None
    description: str | None = None
    keywords: list[str] | None = None
    color: str | None = None
    position: int | None = None


def cat_dict(c: Category) -> dict:
    return {"id": c.id, "key": c.key, "name": c.name, "description": c.description, "keywords": c.keywords or [],
            "color": c.color, "position": c.position}


@api.get("/api/chatbots/{key}/categories")
def categories(bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    cats = db.scalars(select(Category).where(Category.chatbot_id == bot.id).order_by(Category.position, Category.id)).all()
    counts = {c.id: {"total": 0, "waiting": 0, "also": 0} for c in cats}
    none = {"total": 0, "waiting": 0}
    for e in db.scalars(select(Entry).where(Entry.chatbot_id == bot.id, Entry.status.in_(QUEUE + ("approved",)))):
        s = shown(e)
        tgt = counts.get(s["category_id"], none)
        tgt["total"] += 1
        tgt["waiting"] += e.status in QUEUE
        for i in s["secondary_ids"]:
            if i in counts:
                counts[i]["also"] += 1
    return {"categories": [{**cat_dict(c), **counts[c.id]} for c in cats], "uncategorized": none, "ai": bool(OPENAI_API_KEY)}


@api.post("/api/chatbots/{key}/categories")
def add_category(b: CategoryIn, bot: Chatbot = Depends(get_bot), who: str = Depends(actor), db: Session = Depends(get_db)):
    name = (b.name or "").strip()
    k = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not k:
        raise HTTPException(400, "Give the category a name.")
    if db.scalar(select(Category).where(Category.chatbot_id == bot.id, Category.key == k)):
        raise HTTPException(400, "That category already exists.")
    n = db.scalar(select(func.count()).select_from(Category).where(Category.chatbot_id == bot.id)) or 0
    c = Category(chatbot_id=bot.id, key=k, name=name, description=(b.description or "").strip(), keywords=b.keywords or [],
                 color=b.color or categorize.COLORS[n % len(categorize.COLORS)], position=n)
    db.add(c)
    record(db, bot.id, "settings", "category_added", who, f"Created the category “{name}”")
    db.commit()
    return cat_dict(c)


@api.patch("/api/categories/{cid}")
def update_category(cid: int, b: CategoryIn, user: User = Depends(current_user), who: str = Depends(actor), db: Session = Depends(get_db)):
    c = owned(db, Category, cid, user)
    if not c:
        raise HTTPException(404)
    record(db, c.chatbot_id, "settings", "category_edited", who,
           f"Edited the category “{c.name}”" + (f" (renamed to “{b.name.strip()}”)" if b.name and b.name.strip() != c.name else ""))
    if b.name is not None and b.name.strip():
        c.name = b.name.strip()
    if b.description is not None:
        c.description = b.description.strip()
    if b.keywords is not None:
        c.keywords = [k.strip() for k in b.keywords if k.strip()]
    if b.color:
        c.color = b.color
    if b.position is not None:
        c.position = b.position
    db.commit()
    return cat_dict(c)


@api.delete("/api/categories/{cid}")
def delete_category(cid: int, user: User = Depends(current_user), who: str = Depends(actor), db: Session = Depends(get_db)):
    c = owned(db, Category, cid, user)
    if not c:
        return {"ok": True}
    used = db.scalar(select(func.count()).select_from(Entry).where(
        Entry.chatbot_id == c.chatbot_id, Entry.status.in_(QUEUE + ("approved",)),
        (Entry.category_id == cid) | (Entry.p_category_id == cid)))
    if used:
        raise HTTPException(400, f"{used} entries still use this category. Move them to another category first.")
    db.delete(c)
    db.commit()
    return {"ok": True}


@api.post("/api/chatbots/{key}/recategorize")
def recategorize(bot: Chatbot = Depends(get_bot), who: str = Depends(actor), db: Session = Depends(get_db)):
    if not OPENAI_API_KEY:
        raise HTTPException(400, "AI categorisation is off: add OPENAI_API_KEY to backend/.env and restart.")
    r = pipeline.recategorize(bot.id)
    record(db, bot.id, "settings", "recategorized", who, f"Re-filed waiting entries with AI: {r['moved']} of {r['entries']} moved to another category")
    db.commit()
    return r


# ── entries and review ────────────────────────────────────────────────────────

@api.get("/api/chatbots/{key}/entries")
def entries(status: str = "queue", category: str | None = None, q: str | None = None, label: str | None = None,
            page_id: int | None = None, scope_filter: str | None = Query(default=None, alias="scope"), topic: int | None = None, limit: int = 300, bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    statuses = QUEUE if status == "queue" else tuple(status.split(","))
    query = select(Entry, Page).outerjoin(Page, Page.id == Entry.page_id).where(Entry.chatbot_id == bot.id, Entry.status.in_(statuses))
    if page_id:
        query = query.where(Entry.page_id == page_id)
    if scope_filter == "in":
        query = query.where(Entry.in_scope.is_(True))
    elif scope_filter == "out":
        query = query.where(Entry.in_scope.is_(False))
    if topic:
        query = query.where(Entry.scope_topic_id == topic, Entry.in_scope.is_(True))
    names = topic_names(db, bot.id)
    out, total = [], 0
    ql = (q or "").lower().strip()
    for e, p in db.execute(query.order_by(Page.url, Entry.position)):
        s = shown(e)
        if category == "none":
            if s["category_id"]:
                continue
        elif category and int(category) != s["category_id"] and int(category) not in s["secondary_ids"]:
            continue
        if label and label not in s["labels"]:
            continue
        if ql and ql not in f"{s['title']} {s['content']} {p.url if p else ''}".lower():
            continue
        total += 1
        if len(out) < limit:
            out.append(entry_dict(e, p, topics=names))
    return {"total": total, "entries": out}


@api.get("/api/chatbots/{key}/review-summary")
def review_summary(bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    st = dict(db.execute(select(Entry.status, func.count()).where(Entry.chatbot_id == bot.id).group_by(Entry.status)).all())
    labels: dict[str, int] = {}
    for e in db.scalars(select(Entry).where(Entry.chatbot_id == bot.id, Entry.status.in_(QUEUE + ("approved",)))):
        for l in shown(e)["labels"]:
            labels[l] = labels.get(l, 0) + 1
    sc = dict(db.execute(select(Entry.in_scope, func.count()).where(Entry.chatbot_id == bot.id, Entry.status.in_(QUEUE)).group_by(Entry.in_scope)).all())
    has_scope = bool(db.scalar(select(func.count()).select_from(ScopeTopic).where(ScopeTopic.chatbot_id == bot.id)))
    return {"status": {s: st.get(s, 0) for s in ("new", "changed", "removal", "approved", "rejected", "removed")},
            "labels": sorted(labels.items(), key=lambda x: -x[1]),
            "scope": {"enabled": has_scope, "in": sc.get(True, 0), "out": sc.get(False, 0), "unchecked": sc.get(None, 0),
                      "clear": db.scalar(select(func.count()).select_from(Entry).where(
                          Entry.chatbot_id == bot.id, Entry.status == "new", Entry.in_scope.is_(False),
                          Entry.scope_score < (bot.scope_threshold or scope.DEFAULT_THRESHOLD) - scope.CLEAR_MARGIN)) or 0}}


def _entry(db: Session, eid: int, user: User) -> Entry:
    e = owned(db, Entry, eid, user)
    if not e:
        raise HTTPException(404, "Entry not found")
    return e


def _detail(db: Session, e: Entry) -> dict:
    p = db.get(Page, e.page_id) if e.page_id else None
    d = entry_dict(e, p, full=True, topics=topic_names(db, e.chatbot_id))
    d["approved"] = {"title": e.title, "content": e.content, "category_id": e.category_id,
                     "secondary_ids": e.secondary_ids or [], "labels": e.labels or []} if e.content is not None else None
    if e.status == "changed":
        d["diff"], d["added"], d["removed"] = line_diff(f"{e.title}\n{e.content}", f"{e.p_title}\n{e.p_content}", context=3)
    elif e.status == "removal":
        d["diff"], d["added"], d["removed"] = line_diff(f"{e.title}\n{e.content}", "")
    d["comments"] = [{"id": c.id, "author": c.author, "body": c.body, "created_at": c.created_at}
                     for c in db.scalars(select(Comment).where(Comment.entry_id == e.id).order_by(Comment.id))]
    d["history"] = [{"id": h.id, "action": h.action, "actor": h.actor, "detail": h.detail, "created_at": h.created_at}
                    for h in db.scalars(select(EntryEvent).where(EntryEvent.entry_id == e.id).order_by(EntryEvent.id.desc()).limit(40))]
    return d


@api.get("/api/entries/{eid}")
def entry_detail(eid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _detail(db, _entry(db, eid, user))


class EntryIn(BaseModel):
    title: str | None = None
    content: str | None = None
    category_id: int | None = None
    secondary_ids: list[int] | None = None
    labels: list[str] | None = None


@api.patch("/api/entries/{eid}")
def edit_entry(eid: int, b: EntryIn, user: User = Depends(current_user), who: str = Depends(actor), db: Session = Depends(get_db)):
    e = _entry(db, eid, user)
    guard(review.edit, db, e, who, **b.model_dump())
    changed = [k for k, v in b.model_dump().items() if v is not None]
    record(db, e.chatbot_id, "review", "edited", who, f"Edited “{shown(e)['title']}” ({', '.join(changed).replace('_ids', '').replace('_id', '')})", entry_id=e.id)
    db.commit()
    return _detail(db, e)


class NoteIn(BaseModel):
    note: str = ""


@api.post("/api/entries/{eid}/{action}")
def act(eid: int, action: str, b: NoteIn, user: User = Depends(current_user), who: str = Depends(actor), db: Session = Depends(get_db)):
    e = _entry(db, eid, user)
    was, name = e.status, shown(e)["title"]
    verbs = {"approve": {"removal": "Approved removing"}.get(was, "Approved the change to" if was == "changed" else "Approved"),
             "reject": {"removal": "Kept (rejected the removal of)", "changed": "Rejected the change to"}.get(was, "Rejected"),
             "reopen": "Reopened", "comment": "Commented on"}
    if action in verbs:
        record(db, e.chatbot_id, "review", action, who, f"{verbs[action]} “{name}”", entry_id=e.id, **({"note": b.note} if b.note else {}))
    if action == "approve":
        guard(review.approve, db, e, who)
    elif action == "reject":
        guard(review.reject, db, e, who, b.note)
    elif action == "reopen":
        guard(review.reopen, db, e, who)
    elif action == "comment":
        if not b.note.strip():
            raise HTTPException(400, "Write a comment first.")
        db.add(Comment(entry_id=e.id, author=who, body=b.note.strip()))
    else:
        raise HTTPException(404)
    db.commit()
    return _detail(db, e)


class BulkIn(BaseModel):
    ids: list[int]
    action: str


@api.post("/api/chatbots/{key}/entries/bulk")
def bulk(b: BulkIn, bot: Chatbot = Depends(get_bot), who: str = Depends(actor), db: Session = Depends(get_db)):
    done, skipped = 0, []
    for e in db.scalars(select(Entry).where(Entry.chatbot_id == bot.id, Entry.id.in_(b.ids))):
        if b.action == "approve" and e.duplicate_of and e.status == "new" and len(b.ids) > 1:
            skipped.append({"id": e.id, "reason": "Duplicate of another entry: review it on its own."})
            continue
        try:
            (review.approve if b.action == "approve" else review.reject)(db, e, who)
            done += 1
        except review.ReviewError as err:
            skipped.append({"id": e.id, "reason": str(err)})
    if done:
        record(db, bot.id, "review", "bulk_" + b.action, who, f"{'Approved' if b.action == 'approve' else 'Rejected'} {done} entries in one go", skipped=len(skipped))
    db.commit()
    return {"done": done, "skipped": skipped}


@api.post("/api/chatbots/{key}/entries/reject-outside")
def reject_outside(bot: Chatbot = Depends(get_bot), who: str = Depends(actor), db: Session = Depends(get_db)):
    """Reject every NEW entry that is clearly unrelated to the SME's KB. Borderline ones, changes and removals are left for a person."""
    n = 0
    cut = (bot.scope_threshold or scope.DEFAULT_THRESHOLD) - scope.CLEAR_MARGIN
    for e in db.scalars(select(Entry).where(Entry.chatbot_id == bot.id, Entry.status == "new", Entry.in_scope.is_(False), Entry.scope_score < cut)):
        review.reject(db, e, who, "Clearly unrelated to the SME's knowledge base")
        n += 1
    if n:
        record(db, bot.id, "review", "bulk_reject", who, f"Rejected {n} entries that are clearly unrelated to the SME's KB", count=n)
    db.commit()
    return {"done": n}


# ── the SME's own KB (scope) ──────────────────────────────────────────────────

def scope_dict(bot: Chatbot, db: Session) -> dict:
    topics = db.scalars(select(ScopeTopic).where(ScopeTopic.chatbot_id == bot.id).order_by(ScopeTopic.position)).all()
    stat: dict[int, dict] = {t.id: {"matched": 0, "waiting": 0, "approved": 0} for t in topics}
    outside = {"waiting": 0, "approved": 0}
    for tid, st, ins, n in db.execute(select(Entry.scope_topic_id, Entry.status, Entry.in_scope, func.count())
                                      .where(Entry.chatbot_id == bot.id, Entry.status.in_(QUEUE + ("approved",)))
                                      .group_by(Entry.scope_topic_id, Entry.status, Entry.in_scope)):
        if ins is False:
            outside["approved" if st == "approved" else "waiting"] += n
        elif ins and tid in stat:
            stat[tid]["matched"] += n
            stat[tid]["approved" if st == "approved" else "waiting"] += n
    return {"enabled": bool(topics), "threshold": bot.scope_threshold or scope.DEFAULT_THRESHOLD, "default_threshold": scope.DEFAULT_THRESHOLD,
            "ai": bool(OPENAI_API_KEY), "outside": outside,
            "topics": [{"id": t.id, "name": t.name, "group": t.group, "words": t.words, **stat[t.id]} for t in topics]}


@api.get("/api/chatbots/{key}/scope")
def get_scope(bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    return scope_dict(bot, db)


@api.get("/api/scope-topics/{tid}")
def scope_topic(tid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned(db, ScopeTopic, tid, user)
    if not t:
        raise HTTPException(404)
    return {"id": t.id, "name": t.name, "group": t.group, "words": t.words, "text": t.text[:20000], "truncated": len(t.text) > 20000}


class ScopeIn(BaseModel):
    threshold: float | None = None
    text: str | None = None


@api.put("/api/chatbots/{key}/scope")
def set_scope(b: ScopeIn, bot: Chatbot = Depends(get_bot), who: str = Depends(actor), db: Session = Depends(get_db)):
    if b.threshold is not None:
        if not 0.3 <= b.threshold <= 0.9:
            raise HTTPException(400, "Choose a value between 0.30 and 0.90.")
        bot.scope_threshold = round(b.threshold, 2)
        scope.apply_threshold(db, bot)
        record(db, bot.id, "settings", "scope_threshold", who, f"Set how closely entries must match the SME's KB to {bot.scope_threshold:.2f}")
    if b.text is not None:
        r = guard(scope.import_topics, db, bot, b.text)
        record(db, bot.id, "settings", "scope_import", who, f"Loaded the SME's KB: {r['topics']} topics")
    db.commit()
    return scope_dict(bot, db)


@api.post("/api/chatbots/{key}/scope/match")
def rematch(bot: Chatbot = Depends(get_bot), who: str = Depends(actor), db: Session = Depends(get_db)):
    r = guard(scope.match, bot.id)
    record(db, bot.id, "settings", "scope_match", who, f"Compared entries with the SME's KB: {r['in_scope']} inside, {r['outside']} outside")
    db.commit()
    return scope_dict(bot, db)


# ── publishing, versions, document ────────────────────────────────────────────

@api.get("/api/chatbots/{key}/draft")
def draft(bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    return publish.draft(db, bot)


def _docx_path(bot: Chatbot, n: int):
    return DATA_DIR / "versions" / bot.key / f"v{n:04d}.docx"


def _docx(bot: Chatbot, v: KbVersion) -> bytes:
    path = _docx_path(bot, v.number)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(docgen.build_docx(bot.name, v.number, v.created_at.strftime("%B %d, %Y"), v.items))
    return path.read_bytes()


def _sync_gdoc(db: Session, bot: Chatbot, v: KbVersion) -> None:
    try:
        gdocs.push(bot.gdoc_url, _docx(bot, v))
        bot.gdoc_synced_version, bot.gdoc_synced_at, bot.gdoc_error = v.number, now(), None
    except Exception as e:                                    # noqa: BLE001
        bot.gdoc_error = str(e)
    db.commit()


class PublishIn(BaseModel):
    note: str = ""


@api.post("/api/chatbots/{key}/publish")
def do_publish(b: PublishIn, bot: Chatbot = Depends(get_bot), who: str = Depends(actor), db: Session = Depends(get_db)):
    v = guard(publish.publish, db, bot, b.note, who)
    st = v.stats
    record(db, bot.id, "publish", "published", who, f"Published version {v.number}: {st.get('added', 0)} added, {st.get('modified', 0)} modified, "
           f"{st.get('removed', 0)} removed ({st.get('total', 0)} entries)" + (f" — “{v.note}”" if v.note else ""), version=v.number)
    db.commit()
    _docx(bot, v)
    if bot.gdoc_url and gdocs.configured():
        _sync_gdoc(db, bot, v)
    return version_dict(v)


@api.get("/api/chatbots/{key}/versions")
def versions(bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    return [version_dict(v) for v in db.scalars(select(KbVersion).where(KbVersion.chatbot_id == bot.id).order_by(KbVersion.number.desc()))]


def _version(db: Session, bot: Chatbot, number: int | None) -> KbVersion:
    v = publish.latest(db, bot) if not number else db.scalar(select(KbVersion).where(KbVersion.chatbot_id == bot.id, KbVersion.number == number))
    if not v:
        raise HTTPException(404, "Nothing has been published yet.")
    return v


@api.get("/api/chatbots/{key}/versions/{number}")
def version_detail(number: int, bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    v = _version(db, bot, number)
    cats = [cat_dict(c) for c in db.scalars(select(Category).where(Category.chatbot_id == bot.id).order_by(Category.position))]
    return {**version_dict(v, full=True), "categories": cats}


@api.get("/api/chatbots/{key}/compare")
def compare(a: int, b: int, bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    va, vb = _version(db, bot, a), _version(db, bot, b)
    ch = publish.compare(va.items, vb.items)
    return {"a": a, "b": b, "changes": ch, "counts": publish.counts(ch)}


@api.get("/api/chatbots/{key}/export")
def export(format: str = "docx", version: int | None = None, bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    v = _version(db, bot, version)
    when = v.created_at.strftime("%B %d, %Y")
    name = f"{bot.key}-kb-v{v.number}"
    if format == "docx":
        return Response(_docx(bot, v), media_type=gdocs.DOCX, headers={"Content-Disposition": f'attachment; filename="{name}.docx"'})
    if format == "md":
        return Response(docgen.build_markdown(bot.name, v.number, when, v.items), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}.md"'})
    if format == "json":
        return Response(json.dumps(docgen.build_json(bot.key, bot.name, v.number, v.created_at.isoformat(), v.items), ensure_ascii=False, indent=2),
                        media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{name}.json"'})
    raise HTTPException(400, "format must be docx, md or json")


def doc_dict(bot: Chatbot, db: Session) -> dict:
    v = publish.latest(db, bot)
    fid = gdocs.doc_id(bot.gdoc_url)
    return {"gdoc_url": bot.gdoc_url, "gdoc_id": fid, "google_connected": gdocs.configured(), "service_email": gdocs.service_email(),
            "synced_version": bot.gdoc_synced_version, "synced_at": bot.gdoc_synced_at, "error": bot.gdoc_error,
            "latest_version": v.number if v else None, "published_at": v.created_at if v else None,
            "llm_categorizer": bool(OPENAI_API_KEY)}


@api.get("/api/chatbots/{key}/document")
def document(bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    return doc_dict(bot, db)


class DocIn(BaseModel):
    gdoc_url: str = ""


@api.put("/api/chatbots/{key}/document")
def set_document(b: DocIn, bot: Chatbot = Depends(get_bot), who: str = Depends(actor), db: Session = Depends(get_db)):
    url = b.gdoc_url.strip()
    if url and not gdocs.doc_id(url):
        raise HTTPException(400, "Paste the full Google Doc link (https://docs.google.com/document/d/…).")
    bot.gdoc_url, bot.gdoc_synced_version, bot.gdoc_synced_at, bot.gdoc_error = url or None, None, None, None
    record(db, bot.id, "publish", "gdoc", who, f"Linked the Google Doc {url}" if url else "Unlinked the Google Doc")
    db.commit()
    return doc_dict(bot, db)


@api.post("/api/chatbots/{key}/document/sync")
def sync_document(bot: Chatbot = Depends(get_bot), db: Session = Depends(get_db)):
    if not bot.gdoc_url:
        raise HTTPException(400, "Link a Google Doc first.")
    _sync_gdoc(db, bot, _version(db, bot, None))
    if bot.gdoc_error:
        raise HTTPException(400, bot.gdoc_error)
    return doc_dict(bot, db)


# ── users (admin) ─────────────────────────────────────────────────────────────
# Admins add users with a starting password; users change it themselves in Settings. A forgotten password means
# delete and add again (History stores names as text, so it stays linked).

class NewUserIn(BaseModel):
    name: str
    password: str
    is_admin: bool = False
    kb_ids: list[int] = []


class UserIn(BaseModel):
    is_admin: bool | None = None
    kb_ids: list[int] | None = None


def user_dict(u: User) -> dict:
    return {"id": u.id, "name": u.name, "is_admin": bool(u.is_admin), "kb_ids": u.kb_ids or [], "created_at": u.created_at}


def _kb_ids(db: Session, ids: list[int]) -> list[int]:
    """The ids without repeats, or 400 if one isn't a real chatbot."""
    ids = list(dict.fromkeys(ids))
    if len(ids) != db.scalar(select(func.count()).select_from(Chatbot).where(Chatbot.id.in_(ids))):
        raise HTTPException(400, "Unknown knowledge base.")
    return ids


def _user(db: Session, uid: int) -> User:
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "User not found")
    return u


@api.get("/api/admin/users")
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [user_dict(u) for u in db.scalars(select(User).order_by(func.lower(User.name)))]


@api.post("/api/admin/users")
def create_user(b: NewUserIn, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    name = b.name.strip()
    if not name or len(name) > 80:
        raise HTTPException(400, "Name must be 1 to 80 characters.")
    if find_user(db, name):
        raise HTTPException(400, "A user with that name already exists.")
    if len(b.password) < MIN_PASSWORD:
        raise HTTPException(400, f"Password must be at least {MIN_PASSWORD} characters.")
    u = User(name=name, password_hash=hash_password(b.password), is_admin=b.is_admin, kb_ids=_kb_ids(db, b.kb_ids))
    db.add(u)
    db.commit()
    return user_dict(u)


@api.patch("/api/admin/users/{uid}")
def update_user(uid: int, b: UserIn, me: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = _user(db, uid)
    if b.is_admin is False and u.id == me.id:
        raise HTTPException(400, "You can't remove your own admin access.")
    if b.is_admin is not None:
        u.is_admin = b.is_admin
    if b.kb_ids is not None:
        u.kb_ids = _kb_ids(db, b.kb_ids)
    db.commit()
    return user_dict(u)


@api.delete("/api/admin/users/{uid}")
def delete_user(uid: int, me: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = _user(db, uid)
    if u.id == me.id:
        raise HTTPException(400, "You can't delete yourself.")
    db.execute(delete(LoginSession).where(LoginSession.user_id == u.id))  # signed out everywhere
    db.delete(u)
    db.commit()
    return {"ok": True}


app.include_router(api)  # last, after every @api route is defined
