"""2026-10-16 — Report a problem, the runner's token gate, and the sales admin-lite."""
import asyncio

import pytest
from fastapi import HTTPException

from app.routers import runner, sales, support_reports


def test_problem_context_keeps_only_known_short_fields():
    raw = '{"conversation_id": "abc", "user_agent": "' + "x" * 500 + '", "evil": "<script>", "online": true, "viewport": 12}'
    ctx = support_reports.clean_context(raw)
    assert set(ctx) == {"conversation_id", "user_agent", "online", "viewport"}
    assert len(ctx["user_agent"]) == 300 and ctx["online"] == "True" and ctx["viewport"] == "12"
    assert support_reports.clean_context("not json") == {} and support_reports.clean_context("[1,2]") == {}


def test_runner_routes_hide_without_a_token_and_check_it(monkeypatch):
    monkeypatch.setattr(runner.settings, "runner_token", "")
    with pytest.raises(HTTPException) as exc:
        runner.require_runner("Bearer anything")
    assert exc.value.status_code == 404
    monkeypatch.setattr(runner.settings, "runner_token", "s3cret-token")
    with pytest.raises(HTTPException) as exc:
        runner.require_runner("Bearer wrong")
    assert exc.value.status_code == 401
    with pytest.raises(HTTPException):
        runner.require_runner(None)
    assert runner.require_runner("Bearer s3cret-token") == "runner"


def _fleet(paying: bool) -> sales.Fleet:
    from datetime import datetime, timezone
    return sales.Fleet(id="f", name="Boat", status="active", created_at=datetime.now(timezone.utc),
                       trial_ends_at=None, paying=paying, boats=1)


def test_signup_stage():
    assert sales.stage_of(0, [], False) == "signed_up"
    assert sales.stage_of(3, [], False) == "asked"
    assert sales.stage_of(3, [_fleet(False)], False) == "trial"
    assert sales.stage_of(0, [_fleet(True)], False) == "paying"
    assert sales.stage_of(0, [], True) == "paying"


class _Pool:
    def __init__(self, row):
        self.row = row

    async def fetchrow(self, sql, *args):
        if "sales_code = $1" in sql:
            return {"id": "00000000-0000-0000-0000-000000000002"}
        return self.row


def _user(is_admin=False):
    from app.auth.schemas import CurrentUser
    return CurrentUser(user_id="00000000-0000-0000-0000-000000000001", email="j@example.com", role="other",
                       tier="free", is_admin=is_admin)


def test_sales_gate():
    # a salesperson sees their own code
    ctx = asyncio.run(sales.require_sales(_user(), _Pool({"is_sales": True, "sales_code": "jordan", "is_admin": False}), None))
    assert ctx.code == "jordan" and ctx.owner_id == ctx.user_id and not ctx.is_admin
    # a plain user is refused
    with pytest.raises(HTTPException) as exc:
        asyncio.run(sales.require_sales(_user(), _Pool({"is_sales": False, "sales_code": None, "is_admin": False}), None))
    assert exc.value.status_code == 403
    # an admin needs ?code= and then views that salesperson's data
    with pytest.raises(HTTPException) as exc:
        asyncio.run(sales.require_sales(_user(True), _Pool({"is_sales": False, "sales_code": None, "is_admin": True}), None))
    assert exc.value.status_code == 404
    ctx = asyncio.run(sales.require_sales(_user(True), _Pool({"is_sales": False, "sales_code": None, "is_admin": True}), "Jordan"))
    assert ctx.code == "jordan" and ctx.owner_id.endswith("0002") and ctx.is_admin
