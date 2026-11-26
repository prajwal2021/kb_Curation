"""Data model.

chatbot -> sources (root URLs) -> pages (every URL found) -> entries (one reviewable piece of knowledge)
crawl_runs / page_events record what each crawl found; kb_versions are immutable published snapshots.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


TS = DateTime(timezone=True)


class Chatbot(Base):
    __tablename__ = "chatbots"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    gdoc_url: Mapped[str | None] = mapped_column(Text)
    gdoc_synced_version: Mapped[int | None] = mapped_column(Integer)
    gdoc_synced_at: Mapped[datetime | None] = mapped_column(TS)
    gdoc_error: Mapped[str | None] = mapped_column(Text)
    scope_threshold: Mapped[float | None] = mapped_column(Float)     # how close to Ryan's KB an entry must be
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    chatbot_id: Mapped[int] = mapped_column(ForeignKey("chatbots.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(String(120), default="")
    max_pages: Mapped[int] = mapped_column(Integer, default=2500)
    exclude: Mapped[list] = mapped_column(JSONB, default=list)        # path fragments that are never read
    schedule_hours: Mapped[int | None] = mapped_column(Integer)      # None = manual only
    next_run_at: Mapped[datetime | None] = mapped_column(TS)
    last_run_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class CrawlRun(Base):
    __tablename__ = "crawl_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    chatbot_id: Mapped[int] = mapped_column(ForeignKey("chatbots.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"))
    trigger: Mapped[str] = mapped_column(String(20), default="manual")     # manual | schedule
    status: Mapped[str] = mapped_column(String(12), default="queued")      # queued | running | done | failed
    stage: Mapped[str] = mapped_column(String(20), default="queued")       # discovering | extracting | comparing | done
    progress: Mapped[dict] = mapped_column(JSONB, default=dict)
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(80), default="system")
    created_at: Mapped[datetime] = mapped_column(TS, default=now)
    started_at: Mapped[datetime | None] = mapped_column(TS)
    finished_at: Mapped[datetime | None] = mapped_column(TS)


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("chatbot_id", "url"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    chatbot_id: Mapped[int] = mapped_column(ForeignKey("chatbots.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"))
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="")
    # active | removed | error | skipped | excluded
    # skipped = found but not knowledge (files, templates); excluded = a person chose not to crawl it
    status: Mapped[str] = mapped_column(String(10), default="active", index=True)
    skip_reason: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    found_via: Mapped[str] = mapped_column(String(10), default="link")   # link | sitemap (listed only in sitemap.xml)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    text: Mapped[str | None] = mapped_column(Text)                   # normalized text of the latest crawl
    verdict: Mapped[str | None] = mapped_column(String(8))           # ok | fail (automatic verification)
    checks: Mapped[list] = mapped_column(JSONB, default=list)        # [{name, ok, note}]
    verified_hash: Mapped[str | None] = mapped_column(String(64))    # content the verdict was given for
    keep: Mapped[bool] = mapped_column(Boolean, default=False)       # a person overruled a failed check
    miss_count: Mapped[int] = mapped_column(Integer, default=0)      # consecutive 404/410
    change_count: Mapped[int] = mapped_column(Integer, default=0)
    last_change_kind: Mapped[str | None] = mapped_column(String(10))
    last_run_id: Mapped[int | None] = mapped_column(Integer)
    changed_run_id: Mapped[int | None] = mapped_column(Integer)
    first_seen_at: Mapped[datetime] = mapped_column(TS, default=now)
    last_crawled_at: Mapped[datetime | None] = mapped_column(TS)
    last_changed_at: Mapped[datetime | None] = mapped_column(TS)


class PageEvent(Base):
    """One detected change of a page in one crawl, with the line diff."""
    __tablename__ = "page_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    chatbot_id: Mapped[int] = mapped_column(ForeignKey("chatbots.id", ondelete="CASCADE"), index=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("crawl_runs.id", ondelete="SET NULL"), index=True)
    kind: Mapped[str] = mapped_column(String(10))                    # new | changed | removed | restored
    added: Mapped[int] = mapped_column(Integer, default=0)
    removed: Mapped[int] = mapped_column(Integer, default=0)
    diff: Mapped[list] = mapped_column(JSONB, default=list)          # [{t: "+"|"-"|" "|"@", s: line}]
    created_at: Mapped[datetime] = mapped_column(TS, default=now, index=True)


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("chatbot_id", "key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    chatbot_id: Mapped[int] = mapped_column(ForeignKey("chatbots.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    keywords: Mapped[list] = mapped_column(JSONB, default=list)
    color: Mapped[str] = mapped_column(String(12), default="slate")
    position: Mapped[int] = mapped_column(Integer, default=0)


class Entry(Base):
    """One piece of knowledge taken from one section of a page.

    title/content/category_id/secondary_ids/labels = the approved values (None until first approval).
    p_* = what the latest crawl proposes; empty when nothing is waiting for review.
    status: new | changed | removal | approved | rejected | removed
    """
    __tablename__ = "entries"
    __table_args__ = (Index("ix_entries_bot_status", "chatbot_id", "status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    chatbot_id: Mapped[int] = mapped_column(ForeignKey("chatbots.id", ondelete="CASCADE"), index=True)
    page_id: Mapped[int | None] = mapped_column(ForeignKey("pages.id", ondelete="SET NULL"), index=True)
    key: Mapped[str] = mapped_column(String(200))                    # stable id of the section within the page
    position: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(10), default="new")
    title: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(Integer)
    secondary_ids: Mapped[list] = mapped_column(JSONB, default=list)
    labels: Mapped[list] = mapped_column(JSONB, default=list)
    p_title: Mapped[str | None] = mapped_column(Text)
    p_content: Mapped[str | None] = mapped_column(Text)
    p_category_id: Mapped[int | None] = mapped_column(Integer)
    p_secondary_ids: Mapped[list] = mapped_column(JSONB, default=list)
    p_labels: Mapped[list] = mapped_column(JSONB, default=list)
    p_edited: Mapped[bool] = mapped_column(Boolean, default=False)   # reviewer edited the proposal
    source_hash: Mapped[str | None] = mapped_column(String(64))      # hash of the section as last seen on the site
    rejected_hash: Mapped[str | None] = mapped_column(String(64))    # a rejected proposal is not proposed again
    duplicate_of: Mapped[int | None] = mapped_column(Integer)        # entry on another page with identical text
    manual_edit: Mapped[bool] = mapped_column(Boolean, default=False)  # approved text differs from the website
    scope_topic_id: Mapped[int | None] = mapped_column(Integer)       # closest topic in the SME's own KB
    scope_score: Mapped[float | None] = mapped_column(Float)          # 0-1 similarity to that topic
    in_scope: Mapped[bool | None] = mapped_column(Boolean)            # None = not checked yet
    scope_verdict: Mapped[bool | None] = mapped_column(Boolean)       # an AI reading of a borderline entry (None = score decided)
    reviewer: Mapped[str | None] = mapped_column(String(80))
    reviewed_at: Mapped[datetime | None] = mapped_column(TS)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    detected_at: Mapped[datetime] = mapped_column(TS, default=now)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)
    updated_at: Mapped[datetime] = mapped_column(TS, default=now, onupdate=now)


class Comment(Base):
    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id", ondelete="CASCADE"), index=True)
    author: Mapped[str] = mapped_column(String(80))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class EntryEvent(Base):
    """Audit trail of an entry: detected, edited, approved, rejected, restored..."""
    __tablename__ = "entry_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    chatbot_id: Mapped[int] = mapped_column(Integer, index=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(20))
    actor: Mapped[str] = mapped_column(String(80), default="system")
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class KbVersion(Base):
    """An immutable published snapshot of every approved entry."""
    __tablename__ = "kb_versions"
    __table_args__ = (UniqueConstraint("chatbot_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    chatbot_id: Mapped[int] = mapped_column(ForeignKey("chatbots.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(80), default="unknown")
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)
    items: Mapped[list] = mapped_column(JSONB, default=list)         # full snapshot
    changes: Mapped[list] = mapped_column(JSONB, default=list)       # what changed vs the previous version
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class Activity(Base):
    """One line per thing somebody (or the schedule) did: the audit history shown in the UI."""
    __tablename__ = "activity"
    id: Mapped[int] = mapped_column(primary_key=True)
    chatbot_id: Mapped[int] = mapped_column(ForeignKey("chatbots.id", ondelete="CASCADE"), index=True)
    area: Mapped[str] = mapped_column(String(12))                    # pages | review | publish | settings
    action: Mapped[str] = mapped_column(String(30))
    actor: Mapped[str] = mapped_column(String(80), default="system")
    summary: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=now, index=True)


class ScopeTopic(Base):
    """One topic of the knowledge base the SME maintains by hand ("If asked about X, answer with ...")."""
    __tablename__ = "scope_topics"
    id: Mapped[int] = mapped_column(primary_key=True)
    chatbot_id: Mapped[int] = mapped_column(ForeignKey("chatbots.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(Text)
    group: Mapped[str] = mapped_column(String(60), default="General")
    position: Mapped[int] = mapped_column(Integer, default=0)
    words: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, default="")


class ScopeChunk(Base):
    __tablename__ = "scope_chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    chatbot_id: Mapped[int] = mapped_column(Integer, index=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("scope_topics.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    emb: Mapped[list] = mapped_column(JSONB)


class User(Base):
    """A reviewer who signs in. Created with `python -m app.users add "Name"`; the name is what History shows."""
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)   # opens every KB and manages users
    kb_ids: Mapped[list] = mapped_column(JSONB, default=list)        # chatbot ids a non-admin may open
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class LoginSession(Base):
    """One signed-in browser. Only a hash of the cookie's token is stored, so a leaked table can't be used to sign in."""
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(TS)


# ── ServiceNow curation ───────────────────────────────────────────────────────
# A one-time import of ServiceNow knowledge articles, kept up to date from web pages ("links") that a person
# attaches to a category. Separate from the website crawl above: its own review queue and published versions.

class SnCategory(Base):
    __tablename__ = "sn_categories"
    __table_args__ = (UniqueConstraint("chatbot_id", "sys_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    chatbot_id: Mapped[int] = mapped_column(ForeignKey("chatbots.id", ondelete="CASCADE"), index=True)
    sys_id: Mapped[str] = mapped_column(String(32))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("sn_categories.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text)                          # "Parent > Child > Name"
    position: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class SnArticle(Base):
    """One knowledge article (one KB number). status is its ServiceNow-style state; title/content is the published text.
    p_* holds the text of a draft or review article, or a pending change (p_stage) on a published one."""
    __tablename__ = "sn_articles"
    id: Mapped[int] = mapped_column(primary_key=True)
    chatbot_id: Mapped[int] = mapped_column(ForeignKey("chatbots.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("sn_categories.id", ondelete="SET NULL"), index=True)
    sys_id: Mapped[str | None] = mapped_column(String(32), index=True)     # None = proposed by the AI from a link
    number: Mapped[str | None] = mapped_column(String(40))
    sn_state: Mapped[str | None] = mapped_column(String(30))         # workflow state in ServiceNow at import
    sn_template: Mapped[str | None] = mapped_column(String(60))
    valid_to: Mapped[str | None] = mapped_column(String(20))
    sn_updated: Mapped[str | None] = mapped_column(String(30))
    source_html: Mapped[str | None] = mapped_column(Text)            # the article as imported, for reference
    sn_content: Mapped[str | None] = mapped_column(Text)             # the imported text, before anyone changed it
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)   # draft|review|published|pending_retirement|retired
    title: Mapped[str | None] = mapped_column(Text)                  # approved
    content: Mapped[str | None] = mapped_column(Text)
    labels: Mapped[list] = mapped_column(JSONB, default=list)
    p_title: Mapped[str | None] = mapped_column(Text)                # proposal waiting for review
    p_content: Mapped[str | None] = mapped_column(Text)
    p_category_id: Mapped[int | None] = mapped_column(Integer)
    p_labels: Mapped[list] = mapped_column(JSONB, default=list)
    p_kind: Mapped[str | None] = mapped_column(String(10))           # import | update | new | remove
    p_reason: Mapped[str | None] = mapped_column(Text)               # why the AI proposed it
    p_link_id: Mapped[int | None] = mapped_column(Integer)
    p_event_id: Mapped[int | None] = mapped_column(Integer)
    p_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    p_stage: Mapped[str | None] = mapped_column(String(10))         # draft|review: stage of a pending change on a published article
    app_changed: Mapped[bool] = mapped_column(Boolean, default=False)   # a person changed text, flags or state in the app since it came from ServiceNow
    reviewer: Mapped[str | None] = mapped_column(String(80))
    reviewed_at: Mapped[datetime | None] = mapped_column(TS)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    detected_at: Mapped[datetime] = mapped_column(TS, default=now)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)
    updated_at: Mapped[datetime] = mapped_column(TS, default=now, onupdate=now)


class SnArticleEvent(Base):
    __tablename__ = "sn_article_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("sn_articles.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(24))
    actor: Mapped[str] = mapped_column(String(80), default="system")
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class SnLink(Base):
    """A web page that the articles of one category (or one pinned article) are kept in line with."""
    __tablename__ = "sn_links"
    __table_args__ = (UniqueConstraint("category_id", "url"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    chatbot_id: Mapped[int] = mapped_column(ForeignKey("chatbots.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("sn_categories.id", ondelete="CASCADE"), index=True)
    article_id: Mapped[int | None] = mapped_column(ForeignKey("sn_articles.id", ondelete="SET NULL"))
    url: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(String(120), default="")
    schedule_hours: Mapped[int | None] = mapped_column(Integer, default=24)
    next_run_at: Mapped[datetime | None] = mapped_column(TS)
    last_checked_at: Mapped[datetime | None] = mapped_column(TS)
    last_changed_at: Mapped[datetime | None] = mapped_column(TS)
    status: Mapped[str] = mapped_column(String(12), default="pending")   # pending|ok|error|checking
    error: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    text: Mapped[str | None] = mapped_column(Text)                   # page text at the last check
    created_by: Mapped[str] = mapped_column(String(80), default="system")
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class SnLinkEvent(Base):
    """One check of a link that found something: the page diff and what the AI decided to do about it."""
    __tablename__ = "sn_link_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    chatbot_id: Mapped[int] = mapped_column(Integer, index=True)
    link_id: Mapped[int] = mapped_column(ForeignKey("sn_links.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))                    # baseline | changed | audit | error
    trigger: Mapped[str] = mapped_column(String(12), default="manual")
    actor: Mapped[str] = mapped_column(String(80), default="system")
    added: Mapped[int] = mapped_column(Integer, default=0)
    removed: Mapped[int] = mapped_column(Integer, default=0)
    diff: Mapped[list] = mapped_column(JSONB, default=list)
    decisions: Mapped[list] = mapped_column(JSONB, default=list)     # [{action, article_id, title, reason}]
    summary: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, default=now, index=True)


class SnVersion(Base):
    __tablename__ = "sn_versions"
    __table_args__ = (UniqueConstraint("chatbot_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    chatbot_id: Mapped[int] = mapped_column(ForeignKey("chatbots.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(80), default="unknown")
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)
    items: Mapped[list] = mapped_column(JSONB, default=list)
    changes: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class SnAsset(Base):
    """An image copied from a ServiceNow attachment; the file lives under DATA_DIR/servicenow/assets."""
    __tablename__ = "sn_assets"
    sys_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    content_type: Mapped[str] = mapped_column(String(80))
    size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)
