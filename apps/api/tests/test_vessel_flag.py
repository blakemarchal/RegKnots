"""2026-09-26 — vessel flag_state on create / update / list.

create_vessel wrote "Unknown" for every vessel and neither the create nor
the update body accepted a flag (51 of 56 prod vessels were Unknown), which
switches off jurisdiction scoping. The chat UI now asks for it.
"""
import asyncio
import importlib
import uuid

import pytest
from fastapi import HTTPException

from app.auth.schemas import CurrentUser

V = importlib.import_module("app.routers.vessels")

USER = CurrentUser(user_id=str(uuid.uuid4()), email="m@x", role="captain", tier="captain")


def _row(**kw):
    row = {"id": uuid.uuid4(), "name": "Kinloss", "vessel_type": "Containership", "gross_tonnage": None,
           "route_types": ["international"], "cargo_types": [], "workspace_id": None,
           "flag_state": "Unknown", "classification_society": None, "classification_society_source": None}
    row.update(kw)
    return row


class _Conn:
    def __init__(self, returned):
        self.calls, self.returned = [], returned

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        if sql.lstrip().startswith("SELECT user_id, workspace_id"):
            return {"user_id": uuid.UUID(USER.user_id), "workspace_id": None}
        return self.returned

    async def fetchval(self, sql, *args):
        return None


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False
        return _Ctx()


@pytest.mark.parametrize("given,stored", [
    (" United   States ", "United States"), ("", None), ("   ", None), (None, None), ("Liberia", "Liberia"),
])
def test_clean_flag(given, stored):
    assert V._clean_flag(given) == stored


def test_clean_flag_rejects_an_overlong_value():
    with pytest.raises(HTTPException) as e:
        V._clean_flag("x" * 61)
    assert e.value.status_code == 422


def test_update_sets_the_flag():
    conn = _Conn(_row(flag_state="United States"))
    body = V.VesselUpdate(flag_state="United States")
    out = asyncio.run(V.update_vessel(str(uuid.uuid4()), body, USER, _Pool(conn)))
    sql, args = conn.calls[-1]
    assert "UPDATE vessels SET flag_state = $1" in sql and args[0] == "United States"
    assert "flag_state" in sql.split("RETURNING")[1] and out.flag_state == "United States"


def test_create_keeps_unknown_only_when_no_flag_is_given():
    for given, stored in [(None, "Unknown"), ("Marshall Islands", "Marshall Islands")]:
        conn = _Conn(_row(flag_state=stored))
        body = V.VesselCreate(name="Kinloss", vessel_type="Containership", route_types=["international"],
                              flag_state=given)
        out = asyncio.run(V.create_vessel(body, USER, _Pool(conn)))
        sql, args = conn.calls[0]
        assert sql.lstrip().startswith("INSERT INTO vessels") and args[6] == stored
        assert out.flag_state == stored


def test_list_returns_the_flag():
    assert "flag_state" in V.VesselListItem.model_fields
    src = open(V.__file__, encoding="utf-8").read()
    assert src.count("additional_details, flag_state,") == 2      # personal and workspace queries
