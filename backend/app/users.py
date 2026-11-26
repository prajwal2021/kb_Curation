"""Reviewer accounts: password hashing and the command that creates them.

    python -m app.users add "Jane Doe"     # asks for the password; makes an admin; on an existing name, resets it
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import secrets
import sys

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .db import get_db
from .models import LoginSession, User, now

MIN_PASSWORD = 8
# scrypt cost: ~50 ms per hash, slow enough to make guessing billions of passwords impractical
N, R, P = 2**14, 8, 1


def hash_password(pw: str) -> str:
    """Return a one-way, salted hash in the form 'scrypt$<salt hex>$<hash hex>'."""
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=N, r=R, p=P)
    return f"scrypt${salt.hex()}${h.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    """True if `pw` produces `stored`. A malformed stored value is a mismatch, not an error."""
    try:
        algo, salt_hex, hash_hex = stored.split("$")
        if algo != "scrypt":
            return False
        h = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt_hex), n=N, r=R, p=P)
    except ValueError:
        return False
    return hmac.compare_digest(h, bytes.fromhex(hash_hex))  # same time whether close or not


def add_user_columns(con) -> None:
    """Add the role columns to a users table made before roles existed. Safe to run on every start."""
    # DEFAULT true first, so every user from before roles becomes an admin exactly once; new rows then get false
    con.exec_driver_sql("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT true")
    con.exec_driver_sql("ALTER TABLE users ALTER COLUMN is_admin SET DEFAULT false")
    con.exec_driver_sql("ALTER TABLE users ADD COLUMN IF NOT EXISTS kb_ids JSONB NOT NULL DEFAULT '[]'::jsonb")


def token_hash(token: str) -> str:
    """The session token as stored in the database (sha256 hex): the raw token only ever lives in the cookie."""
    return hashlib.sha256(token.encode()).hexdigest()


def find_user(db: Session, name: str) -> User | None:
    """Look up a user by name, ignoring case ('jane doe' finds 'Jane Doe')."""
    return db.scalar(select(User).where(func.lower(User.name) == name.strip().lower()))


def current_user(kb_session: str | None = Cookie(default=None), db: Session = Depends(get_db)) -> User:
    """The signed-in user, from the session cookie. 401 when missing, unknown or expired."""
    s = db.get(LoginSession, token_hash(kb_session)) if kb_session else None
    if s and s.expires_at < now():
        db.delete(s)
        db.commit()
        s = None
    user = db.get(User, s.user_id) if s else None
    if not user:
        raise HTTPException(401, "Please sign in")
    return user


def can_open(user: User, chatbot_id: int) -> bool:
    """True if the user may see and change this KB. Routes answer a KB or item they can't open as if it didn't exist."""
    return bool(user.is_admin) or chatbot_id in (user.kb_ids or [])


def require_admin(user: User = Depends(current_user)) -> User:
    """The signed-in user, if they are an admin. 403 otherwise."""
    if not user.is_admin:
        raise HTTPException(403, "Admins only")
    return user


def owned(db: Session, model, row_id: int, user: User):
    """The row, or None when it is missing or in a KB the user can't open: callers answer both the same way."""
    row = db.get(model, row_id)
    return row if row and can_open(user, row.chatbot_id) else None


def actor(user: User = Depends(current_user)) -> str:
    """Who did it, for History: the signed-in name (FastAPI runs current_user once per request)."""
    return user.name


def add_user(name: str) -> None:
    """Create the user, or reset the password of an existing one. Prompts for the password twice."""
    from .db import Base, SessionLocal, engine  # only the command needs these

    name = name.strip()
    if not name or len(name) > 80:
        sys.exit("Name must be 1 to 80 characters.")
    pw = getpass.getpass("Password: ")
    if len(pw) < MIN_PASSWORD:
        sys.exit(f"Password must be at least {MIN_PASSWORD} characters.")
    if getpass.getpass("Again:    ") != pw:
        sys.exit("Passwords don't match.")

    Base.metadata.create_all(engine, tables=[User.__table__, LoginSession.__table__])  # works before the API first starts
    with engine.begin() as con:
        add_user_columns(con)
    with SessionLocal() as db:
        user = find_user(db, name)
        if user:
            user.password_hash = hash_password(pw)
            user.is_admin = True  # the CLI is the way back in after a lockout
            db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))  # signed out everywhere
            msg = f"Password reset for {user.name} (admin)"
        else:
            db.add(User(name=name, password_hash=hash_password(pw), is_admin=True))
            msg = f"Added {name} (admin)"
        db.commit()
    print(msg)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="python -m app.users")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("add", help="add a user or reset their password").add_argument("name")
    add_user(ap.parse_args().name)
