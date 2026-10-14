"""2026-10-14 — Wheelhouse pilots: codes, the pilot trial on a new workspace,
and the state machine reading the per-workspace trial end (app/pilots.py)."""
import asyncio
import inspect
import uuid

from app import pilots, tasks


def test_codes_and_links():
    assert pilots.normalize_code("  Gulf Coast Towing! ") == "gulf-coast-towing"
    assert pilots.CODE_RE.match("gulf-coast-towing")
    assert not pilots.CODE_RE.match("-bad") and not pilots.CODE_RE.match("x")
    assert pilots.code_from_src("pilot-acme") == "acme"
    assert pilots.code_from_src("PILOT-Acme") == "acme"
    assert pilots.code_from_src("ob-0042") is None and pilots.code_from_src(None) is None
    assert pilots.signup_link("acme") == "https://regknots.com/register?next=/workspaces&src=pilot-acme"


class Conn:
    def __init__(self, src, days):
        self.src, self.days, self.updates = src, days, []

    async def fetchval(self, sql, *args):
        return self.src if "signup_attribution" in sql else self.days

    async def execute(self, sql, *args):
        self.updates.append(args)


def test_new_workspace_gets_the_owners_pilot_trial():
    ws, owner = uuid.uuid4(), uuid.uuid4()
    conn = Conn("pilot-acme", 90)
    assert asyncio.run(pilots.apply_signup_pilot(conn, ws, owner)) == {"code": "acme", "trial_days": 90}
    assert conn.updates == [(ws, 90)]
    for src, days in [("ob-0042", 90), (None, 90), ("pilot-paused", None)]:
        conn = Conn(src, days)
        assert asyncio.run(pilots.apply_signup_pilot(conn, ws, owner)) is None and conn.updates == []


def test_state_machine_reads_the_trial_end():
    source = inspect.getsource(tasks._workspace_state_transitions_async)
    assert source.count("COALESCE(w.trial_ends_at, w.created_at + INTERVAL '30 days')") == 2   # the reminder
    assert "COALESCE(trial_ends_at, created_at + INTERVAL '30 days') < now()" in source        # card_pending
    assert "created_at < now() - INTERVAL '30 days'" not in source.split("Sub-task 3")[0]
