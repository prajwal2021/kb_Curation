"""Login, sessions and the lock on every route. A fake database stands in for Postgres."""
from datetime import timedelta

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.db import get_db
from app import sn_api
from app.main import api, app, current_user
from app.models import LoginSession, User, now
from app.users import hash_password, token_hash, verify_password


class FakeDB:
    """Just enough of a SQLAlchemy session for the auth routes: one user, at most one session row."""

    def __init__(self, user: User | None = None, session: LoginSession | None = None) -> None:
        self.user, self.session = user, session
        self.added: list = []
        self.deleted: list = []
        self.executed: list = []

    def scalar(self, _stmt):  # find_user
        return self.user

    def get(self, model, _key):
        return self.session if model is LoginSession else self.user

    def add(self, obj) -> None:
        self.added.append(obj)

    def delete(self, obj) -> None:
        self.deleted.append(obj)

    def execute(self, stmt) -> None:
        self.executed.append(stmt)

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass


@pytest.fixture
def jane() -> User:
    return User(id=1, name="Jane Doe", password_hash=hash_password("correct horse"))


def client_with(db: FakeDB, token: str | None = None) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)
    if token:
        c.cookies.set("kb_session", token)
    return c


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_routes_need_login() -> None:
    c = client_with(FakeDB())
    assert c.get("/api/chatbots").status_code == 401
    assert c.get("/api/chatbots/k12/export?format=json").status_code == 401
    assert c.post("/api/chatbots", json={"name": "x"}).status_code == 401


def test_only_login_is_public() -> None:
    def needs_login(r: APIRoute) -> bool:
        return any(d.call is current_user for d in r.dependant.dependencies)

    # routes added straight on `app` are the only ones outside the locked router
    direct = [r for r in app.routes if isinstance(r, APIRoute)]
    assert {r.path for r in direct if not needs_login(r)} == {"/api/login"}
    locked = [r for r in api.routes if isinstance(r, APIRoute)]
    assert len(locked) >= 44 and all(needs_login(r) for r in locked)  # >= 44 so an empty list can't pass


def test_servicenow_routes_need_login_except_images_and_import() -> None:
    def needs_login(r: APIRoute) -> bool:
        return any(d.call is current_user for d in r.dependant.dependencies)

    locked = [r for r in sn_api.router.routes if isinstance(r, APIRoute)]
    assert len(locked) >= 20 and all(needs_login(r) for r in locked)
    # images are linked from published exports; the import uses its own token, sent from the ServiceNow site
    public = [r for r in sn_api.public.routes if isinstance(r, APIRoute)]
    assert {r.path for r in public} == {"/api/servicenow/assets/{sid}", "/api/servicenow/import/{key}",
                                        "/api/servicenow/import-assets/missing", "/api/servicenow/import-assets/{sid}"}
    assert not any(needs_login(r) for r in public)
    imports = [r for r in public if "import" in r.path]
    assert all(any(d.call is sn_api.import_auth for d in r.dependant.dependencies) for r in imports)


def test_servicenow_route_refuses_without_login() -> None:
    c = client_with(FakeDB())
    assert c.get("/api/chatbots/k12/servicenow/overview").status_code == 401
    assert c.post("/api/servicenow/import/k12", json={}).status_code == 403  # token, not login


def test_wrong_password_and_unknown_name_look_the_same(jane: User) -> None:
    for db in (FakeDB(user=jane), FakeDB(user=None)):
        r = client_with(db).post("/api/login", json={"name": "Jane Doe", "password": "wrong horse"})
        assert r.status_code == 401
        assert r.json()["detail"] == "Wrong name or password"


def test_login_sets_httponly_cookie_and_stores_only_the_hash(jane: User) -> None:
    db = FakeDB(user=jane)
    r = client_with(db).post("/api/login", json={"name": "jane doe", "password": "correct horse"})
    assert r.status_code == 200 and r.json() == {"name": "Jane Doe"}
    cookie = r.headers["set-cookie"]
    assert "kb_session=" in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    token = r.cookies["kb_session"]
    (s,) = db.added
    assert s.token_hash == token_hash(token) != token
    assert timedelta(days=29) < s.expires_at - now() <= timedelta(days=30)


def test_valid_session_gives_me(jane: User) -> None:
    s = LoginSession(token_hash=token_hash("tok"), user_id=1, expires_at=now() + timedelta(days=1))
    r = client_with(FakeDB(user=jane, session=s), "tok").get("/api/me")
    assert r.status_code == 200 and r.json() == {"id": 1, "name": "Jane Doe", "is_admin": False}


def test_expired_session_is_refused_and_removed(jane: User) -> None:
    s = LoginSession(token_hash=token_hash("tok"), user_id=1, expires_at=now() - timedelta(seconds=1))
    db = FakeDB(user=jane, session=s)
    r = client_with(db, "tok").get("/api/me")
    assert r.status_code == 401 and r.json()["detail"] == "Please sign in"
    assert db.deleted == [s]


def test_change_password_rules(jane: User) -> None:
    s = LoginSession(token_hash=token_hash("tok"), user_id=1, expires_at=now() + timedelta(days=1))
    db = FakeDB(user=jane, session=s)
    c = client_with(db, "tok")

    r = c.post("/api/me/password", json={"current": "nope nope", "new": "brand new pw"})
    assert r.status_code == 400 and r.json()["detail"] == "Current password is wrong"

    r = c.post("/api/me/password", json={"current": "correct horse", "new": "short"})
    assert r.status_code == 400 and r.json()["detail"] == "New password must be at least 8 characters"

    r = c.post("/api/me/password", json={"current": "correct horse", "new": "brand new pw"})
    assert r.status_code == 200
    assert verify_password("brand new pw", jane.password_hash)
    assert len(db.executed) == 1  # the delete of this user's other sessions
