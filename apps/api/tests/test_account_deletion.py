"""2026-09-29 — account deletion: Stripe first, then rows in one transaction, then
files; and the self-serve route's guards (typed DELETE, password, admins, shared
Wheelhouse)."""
import asyncio
import importlib
import json
import uuid

import pytest
import stripe
from fastapi import HTTPException

from app.auth.schemas import CurrentUser

DEL = importlib.import_module("app.account_deletion")
AUTH = importlib.import_module("app.routers.auth")

UID = uuid.uuid4()
WS = uuid.uuid4()
USER = CurrentUser(user_id=str(UID), email="m@example.com", role="captain", tier="captain")


class _Conn:
    def __init__(self, db):
        self.db = db

    async def execute(self, sql, *args):
        if self.db.fail_on_user_delete and "DELETE FROM users" in sql:
            raise RuntimeError("db down")
        self.db.executed.append(sql.strip())

    def transaction(self):
        class _Tx:
            async def __aenter__(self_inner):
                return None

            async def __aexit__(self_inner, *exc):
                return False
        return _Tx()


class _DB:
    """Answers each query by a fragment of its SQL."""

    def __init__(self, *, sub=None, owned=(), files=(), shared=(), is_admin=False, password="right"):
        self.sub, self.owned, self.files, self.shared = sub, list(owned), list(files), list(shared)
        self.is_admin, self.password = is_admin, password
        self.executed: list[str] = []
        self.fail_on_user_delete = False

    async def fetchrow(self, sql, *args):
        if "SELECT email, stripe_subscription_id FROM users" in sql:
            return {"email": USER.email, "stripe_subscription_id": self.sub}
        if "SELECT hashed_password, is_admin FROM users" in sql:
            return {"hashed_password": self.password, "is_admin": self.is_admin}
        raise AssertionError(sql[:80])

    async def fetch(self, sql, *args):
        if "FROM workspaces WHERE owner_user_id" in sql:
            return self.owned
        if "FROM vessel_documents" in sql:
            return [{"file_path": f} for f in self.files]
        if "SELECT w.name FROM workspaces w" in sql:
            return [{"name": n} for n in self.shared]
        raise AssertionError(sql[:80])

    def acquire(self):
        conn = _Conn(self)

        class _Ctx:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *exc):
                return False
        return _Ctx()


@pytest.fixture
def canceled(monkeypatch):
    """Record Stripe cancellations instead of calling Stripe."""
    calls: list[str] = []

    def fake_cancel(sub_id):
        calls.append(sub_id)
        return True

    monkeypatch.setattr(DEL, "_cancel_subscription", fake_cancel)
    return calls


def test_cancels_every_subscription_then_deletes_workspaces_before_the_user(canceled, tmp_path, monkeypatch):
    monkeypatch.setattr(DEL.settings, "upload_dir", str(tmp_path))
    db = _DB(sub="sub_user", owned=[{"id": WS, "name": "Bay Pioneer", "status": "active", "stripe_subscription_id": "sub_ws"}])
    summary = asyncio.run(DEL.delete_account(db, UID))
    assert canceled == ["sub_user", "sub_ws"]
    assert summary.subscriptions_canceled == 2
    assert db.executed[0].startswith("DELETE FROM workspaces")  # owner_user_id is ON DELETE RESTRICT
    assert db.executed[1].startswith("DELETE FROM users")
    assert summary.workspaces_deleted[0]["name"] == "Bay Pioneer"


def test_a_stripe_failure_deletes_nothing(monkeypatch):
    def refuse(sub_id):
        raise stripe.APIConnectionError("stripe down")

    monkeypatch.setattr(DEL, "_cancel_subscription", refuse)
    db = _DB(sub="sub_user")
    with pytest.raises(stripe.APIConnectionError):
        asyncio.run(DEL.delete_account(db, UID))
    assert db.executed == []


def test_removes_uploads_but_never_touches_files_outside_the_upload_dir(canceled, tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    inside = uploads / "coi.pdf"
    inside.write_bytes(b"%PDF")
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("keep")
    monkeypatch.setattr(DEL.settings, "upload_dir", str(uploads))
    db = _DB(files=[str(inside), str(outside), str(uploads / "already-gone.pdf")])
    summary = asyncio.run(DEL.delete_account(db, UID))
    assert not inside.exists()
    assert outside.exists()
    assert summary.files_removed == 1


def test_files_stay_when_the_row_delete_fails(canceled, tmp_path, monkeypatch):
    monkeypatch.setattr(DEL.settings, "upload_dir", str(tmp_path))
    doc = tmp_path / "coi.pdf"
    doc.write_bytes(b"%PDF")
    db = _DB(files=[str(doc)])
    db.fail_on_user_delete = True
    with pytest.raises(RuntimeError):
        asyncio.run(DEL.delete_account(db, UID))
    assert doc.exists()


def test_cancel_skips_subscriptions_that_are_already_over(monkeypatch):
    cancels: list[str] = []
    monkeypatch.setattr(stripe.Subscription, "cancel", lambda sub_id, **kw: cancels.append(sub_id))

    monkeypatch.setattr(stripe.Subscription, "retrieve", lambda sub_id, **kw: type("S", (), {"status": "canceled"})())
    assert DEL._cancel_subscription("sub_old") is False

    def missing(sub_id, **kw):
        raise stripe.InvalidRequestError("No such subscription", param="id", code="resource_missing")

    monkeypatch.setattr(stripe.Subscription, "retrieve", missing)
    assert DEL._cancel_subscription("sub_gone") is False

    monkeypatch.setattr(stripe.Subscription, "retrieve", lambda sub_id, **kw: type("S", (), {"status": "active"})())
    assert DEL._cancel_subscription("sub_live") is True
    assert cancels == ["sub_live"]


# ── POST /auth/delete-account ────────────────────────────────────────────────

@pytest.fixture
def route(monkeypatch):
    """Wire the route to a fake DB and a fake delete; returns (set_db, deleted)."""
    state = {"db": _DB()}
    deleted: list[uuid.UUID] = []

    async def get_pool():
        return state["db"]

    async def fake_delete(pool, uid):
        deleted.append(uid)
        return DEL.DeletionSummary(email=USER.email, subscriptions_canceled=1)

    monkeypatch.setattr(AUTH, "get_pool", get_pool)
    monkeypatch.setattr(AUTH, "verify_password", lambda plain, hashed: plain == hashed)
    monkeypatch.setattr(DEL, "delete_account", fake_delete)

    def set_db(db):
        state["db"] = db

    return set_db, deleted


def _call(password="right", confirm="DELETE"):
    body = AUTH.DeleteAccountRequest(password=password, confirm=confirm)
    return asyncio.run(AUTH.delete_own_account(body=body, user=USER))


def test_route_needs_the_typed_word_and_the_password(route):
    _, deleted = route
    for kwargs in ({"confirm": "yes"}, {"password": "wrong"}):
        with pytest.raises(HTTPException) as err:
            _call(**kwargs)
        # 400, not 401: a 401 would make the web client try to refresh the session.
        assert err.value.status_code == 400
    assert deleted == []


def test_route_refuses_admins_and_owners_of_a_shared_wheelhouse(route):
    set_db, deleted = route
    set_db(_DB(is_admin=True))
    with pytest.raises(HTTPException) as err:
        _call()
    assert err.value.status_code == 403
    set_db(_DB(shared=["Bay Pioneer"]))
    with pytest.raises(HTTPException) as err:
        _call()
    assert err.value.status_code == 409 and "Bay Pioneer" in err.value.detail
    assert deleted == []


def test_route_deletes_and_clears_the_session_cookie(route):
    _, deleted = route
    resp = _call(confirm=" delete ")
    assert deleted == [UID]
    assert json.loads(resp.body) == {"deleted": True, "subscriptions_canceled": 1}
    cookie = resp.headers.get("set-cookie", "")
    assert "refresh_token=" in cookie and ("Max-Age=0" in cookie or "expires=" in cookie.lower())


def test_route_reports_a_failed_deletion_as_502(route, monkeypatch):
    async def boom(pool, uid):
        raise RuntimeError("stripe down")

    monkeypatch.setattr(DEL, "delete_account", boom)
    with pytest.raises(HTTPException) as err:
        _call()
    assert err.value.status_code == 502
