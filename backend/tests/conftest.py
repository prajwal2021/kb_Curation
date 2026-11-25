"""Shared fixtures. Database tests need a throwaway Postgres database: set SN_TEST_DATABASE_URL
(e.g. postgresql+psycopg://localhost:5432/kb_curation_sntest); they are skipped otherwise."""
from __future__ import annotations

import os

import pytest

DB = os.getenv("SN_TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB, reason="set SN_TEST_DATABASE_URL to run database tests")


@pytest.fixture()
def env(monkeypatch):
    os.environ["DATABASE_URL"] = DB
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import db as dbmod, servicenow as sn
    from app.db import Base
    from app.models import Chatbot

    eng = create_engine(DB)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    S = sessionmaker(eng, expire_on_commit=False)
    monkeypatch.setattr(dbmod, "SessionLocal", S)
    monkeypatch.setattr(sn, "SessionLocal", S)
    s = S()
    bot = Chatbot(key="k12", name="TTU K-12", description="")
    s.add(bot)
    s.commit()
    yield s, bot, sn
    s.close()
    Base.metadata.drop_all(eng)


@pytest.fixture()
def api_client(env):
    """The real app on the test session, signed in as Pat."""
    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import app
    from app.models import User
    from app.users import current_user

    app.dependency_overrides[get_db] = lambda: env[0]
    app.dependency_overrides[current_user] = lambda: User(id=1, name="Pat", password_hash="x")
    yield TestClient(app)
    app.dependency_overrides.clear()
