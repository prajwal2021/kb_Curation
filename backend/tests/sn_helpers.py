"""Builders for ServiceNow tests: import records like the export file has, and article rows."""
from __future__ import annotations

import hashlib
import uuid

from app.models import SnArticle

T1 = "2026-01-01 00:00:00"
T2 = "2026-02-01 00:00:00"
CATS = [{"sys_id": "a" * 32, "label": "Financial Questions", "parent": None, "active": True},
        {"sys_id": "b" * 32, "label": "Refunds", "parent": "a" * 32, "active": True}]


def rec(number, state, version="1.0", *, sys_id=None, updated=T1, body="Body", title=None, can_read=("Public view",)) -> dict:
    """One ServiceNow record in category Refunds. Its sys_id stays the same for a number and version, as in ServiceNow."""
    return {"sys_id": sys_id or hashlib.md5(f"{number}-{version}".encode()).hexdigest(), "number": number,
            "title": title or f"Article {number}", "state": state, "category": "b" * 32, "template": "kb_template_how_to",
            "valid_to": "2100-01-01", "version": version, "latest": True, "can_read": list(can_read), "updated": updated,
            "parts": [], "text": f"<p>{body}</p>"}


def published(s, bot, content, **kw) -> SnArticle:
    """A committed published article; any field can be overridden."""
    a = SnArticle(**{"chatbot_id": bot.id, "sys_id": uuid.uuid4().hex, "status": "published", "title": "T",
                     "content": content, "sn_content": content, **kw})
    s.add(a)
    s.commit()
    return a
