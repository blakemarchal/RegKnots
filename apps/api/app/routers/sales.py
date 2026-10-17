"""Admin-lite for a salesperson (2026-10-16, for Jordan Hall): the accounts that
signed up from their pilot link and where each is in the funnel, a commission
estimate from what those accounts paid, and a lead tracker. Gated by
users.is_sales (an admin may look at any code with ?code=). Nothing here reaches
other customers' data: signups are matched on signup_attribution->>'src',
leads belong to their owner.
"""
from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import date, datetime
from typing import Annotated, Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import pilots
from app.sales_credit import CREDIT_CODE_SQL, USER_PAYING_SQL, WORKSPACE_PAYING_SQL
from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

router = APIRouter(prefix="/sales", tags=["sales"])
COMMISSION_RATE = 0.25
LEAD_STATUSES = ("new", "contacted", "demo", "trial", "paying", "lost")


class SalesCtx(BaseModel):
    user_id: str
    owner_id: str          # whose leads and whose code: the salesperson, or the one an admin is viewing
    code: str
    is_admin: bool


async def require_sales(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    code: str | None = Query(default=None, max_length=40),
) -> SalesCtx:
    row = await pool.fetchrow("SELECT is_sales, sales_code, is_admin FROM users WHERE id = $1", uuid.UUID(user.user_id))
    if row is None or not (row["is_sales"] or row["is_admin"] or user.is_admin):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sales access only")
    is_admin = bool(row["is_admin"] or user.is_admin)
    if row["is_sales"] and row["sales_code"] and not (is_admin and code):
        return SalesCtx(user_id=user.user_id, owner_id=user.user_id, code=row["sales_code"], is_admin=is_admin)
    if is_admin and code:
        # 2026-10-17 — any salesperson's code, with access on or off (Admin > Sales keeps the code).
        owner = await pool.fetchrow("SELECT id FROM users WHERE sales_code = $1", pilots.normalize_code(code))
        return SalesCtx(user_id=user.user_id, owner_id=str(owner["id"]) if owner else user.user_id,
                        code=pilots.normalize_code(code), is_admin=True)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                        detail="No sales code on this account" + (" (admins: add ?code=)" if is_admin else ""))


# ── Overview ─────────────────────────────────────────────────────────────────

class Fleet(BaseModel):
    id: str
    name: str
    status: str
    created_at: datetime
    trial_ends_at: datetime | None
    paying: bool
    boats: int


class Signup(BaseModel):
    id: str
    full_name: str | None
    email: str
    created_at: datetime
    questions: int
    fleets: list[Fleet]
    stage: str      # signed_up | asked | trial | paying


class Me(BaseModel):
    code: str
    link: str
    short_link: str
    rate: float
    is_admin: bool
    trial_days: int | None


def stage_of(questions: int, fleets: list[Fleet], user_paying: bool) -> str:
    if user_paying or any(f.paying for f in fleets):
        return "paying"
    if fleets:
        return "trial"
    if questions:
        return "asked"
    return "signed_up"


@router.get("/me", response_model=Me)
async def me(ctx: Annotated[SalesCtx, Depends(require_sales)], pool: Annotated[asyncpg.Pool, Depends(get_pool)]) -> Me:
    days = await pool.fetchval("SELECT trial_days FROM pilot_codes WHERE code = $1 AND active", ctx.code)
    return Me(code=ctx.code, link=pilots.signup_link(ctx.code), short_link=f"regknots.com/fleet?src=pilot-{ctx.code}",
              rate=COMMISSION_RATE, is_admin=ctx.is_admin, trial_days=days)


@router.get("/signups", response_model=list[Signup])
async def signups(ctx: Annotated[SalesCtx, Depends(require_sales)],
                  pool: Annotated[asyncpg.Pool, Depends(get_pool)]) -> list[Signup]:
    # 2026-10-17 — the link's code, or an admin's credit (app/sales_credit.py).
    users = await pool.fetch(
        f"""SELECT u.id, u.full_name, u.email, u.created_at, {USER_PAYING_SQL} AS paying,
                  (SELECT count(*) FROM messages m JOIN conversations c ON c.id = m.conversation_id
                    WHERE c.user_id = u.id AND m.role = 'user') AS questions
             FROM users u WHERE {CREDIT_CODE_SQL} = $1 ORDER BY u.created_at DESC""", ctx.code)
    out = []
    for u in users:
        fleets = await pool.fetch(
            f"""SELECT w.id, w.name, w.status, w.created_at, {pilots.TRIAL_END_SQL} AS trial_ends_at,
                       {WORKSPACE_PAYING_SQL} AS paying,
                       (SELECT count(*) FROM vessels v WHERE v.workspace_id = w.id) AS boats
                  FROM workspaces w WHERE w.owner_user_id = $1 ORDER BY w.created_at""", u["id"])
        fl = [Fleet(id=str(f["id"]), name=f["name"], status=f["status"], created_at=f["created_at"],
                    trial_ends_at=f["trial_ends_at"], paying=f["paying"], boats=f["boats"]) for f in fleets]
        out.append(Signup(id=str(u["id"]), full_name=u["full_name"], email=u["email"], created_at=u["created_at"],
                          questions=u["questions"], fleets=fl, stage=stage_of(u["questions"], fl, bool(u["paying"]))))
    return out


class CommissionMonth(BaseModel):
    month: str
    revenue: float
    commission: float


class Commission(BaseModel):
    rate: float
    months: list[CommissionMonth]
    total_revenue: float
    total_commission: float


@router.get("/commission", response_model=Commission)
async def commission(ctx: Annotated[SalesCtx, Depends(require_sales)],
                     pool: Annotated[asyncpg.Pool, Depends(get_pool)]) -> Commission:
    """What the accounts from this code paid, by month, from our own billing
    records (workspace invoices and personal invoices); refunds are not netted
    here, the monthly report (scripts/sales/commission_report.py) does that."""
    rows = await pool.fetch(
        f"""WITH people AS (SELECT u.id FROM users u WHERE {CREDIT_CODE_SQL} = $1)
           SELECT to_char(e.created_at, 'YYYY-MM') AS month,
                  sum(COALESCE((e.details->>'amount_paid_cents')::bigint, 0)) AS cents
             FROM workspace_billing_events e JOIN workspaces w ON w.id = e.workspace_id
            WHERE e.event_type = 'invoice_paid' AND w.owner_user_id IN (SELECT id FROM people)
            GROUP BY 1
           UNION ALL
           SELECT to_char(COALESCE(b.paid_at, b.created_at), 'YYYY-MM'), sum(COALESCE(b.amount_paid_cents, 0))
             FROM billing_events b WHERE b.user_id IN (SELECT id FROM people) GROUP BY 1""", ctx.code)
    by_month: dict[str, int] = {}
    for r in rows:
        by_month[r["month"]] = by_month.get(r["month"], 0) + int(r["cents"] or 0)
    months = [CommissionMonth(month=m, revenue=c / 100, commission=round(c / 100 * COMMISSION_RATE, 2))
              for m, c in sorted(by_month.items())]
    total = sum(by_month.values()) / 100
    return Commission(rate=COMMISSION_RATE, months=months, total_revenue=total,
                      total_commission=round(total * COMMISSION_RATE, 2))


# ── Leads ────────────────────────────────────────────────────────────────────

class LeadIn(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    dba: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=40)
    phone: str | None = Field(default=None, max_length=60)
    website: str | None = Field(default=None, max_length=300)
    contact_name: str | None = Field(default=None, max_length=120)
    contact_role: str | None = Field(default=None, max_length=120)
    contact_email: str | None = Field(default=None, max_length=200)
    towboats: int | None = None
    tugs: int | None = None
    passenger: int | None = None
    osv: int | None = None
    service: str | None = Field(default=None, max_length=300)
    area: str | None = Field(default=None, max_length=300)
    source: str | None = Field(default=None, max_length=60)
    status: str = Field(default="new", pattern="^(new|contacted|demo|trial|paying|lost)$")
    next_step: str | None = Field(default=None, max_length=300)
    next_step_at: date | None = None
    notes: str | None = Field(default=None, max_length=8000)


class LeadPatch(BaseModel):
    company: str | None = Field(default=None, min_length=1, max_length=200)
    dba: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=40)
    phone: str | None = Field(default=None, max_length=60)
    website: str | None = Field(default=None, max_length=300)
    contact_name: str | None = Field(default=None, max_length=120)
    contact_role: str | None = Field(default=None, max_length=120)
    contact_email: str | None = Field(default=None, max_length=200)
    towboats: int | None = None
    tugs: int | None = None
    passenger: int | None = None
    osv: int | None = None
    service: str | None = Field(default=None, max_length=300)
    area: str | None = Field(default=None, max_length=300)
    status: str | None = Field(default=None, pattern="^(new|contacted|demo|trial|paying|lost)$")
    next_step: str | None = Field(default=None, max_length=300)
    next_step_at: date | None = None
    notes: str | None = Field(default=None, max_length=8000)


class Lead(LeadIn):
    id: str
    lead_ref: str | None
    commodities: str | None
    created_at: datetime
    updated_at: datetime


_LEAD_COLS = ("id, lead_ref, company, dba, city, state, phone, website, contact_name, contact_role, contact_email, "
              "towboats, tugs, passenger, osv, service, commodities, area, source, status, next_step, next_step_at, "
              "notes, created_at, updated_at")


def _lead(r) -> Lead:
    d = dict(r)
    d["id"] = str(d["id"])
    return Lead(**d)


@router.get("/leads", response_model=list[Lead])
async def list_leads(
    ctx: Annotated[SalesCtx, Depends(require_sales)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    status_filter: str | None = Query(default=None, alias="status", pattern="^(new|contacted|demo|trial|paying|lost)$"),
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=500, ge=1, le=2000),
) -> list[Lead]:
    where, args = ["owner_user_id = $1"], [uuid.UUID(ctx.owner_id)]
    if status_filter:
        args.append(status_filter)
        where.append(f"status = ${len(args)}")
    if q:
        args.append(f"%{q.strip()}%")
        n = len(args)
        where.append(f"(company ILIKE ${n} OR dba ILIKE ${n} OR city ILIKE ${n} OR contact_name ILIKE ${n} OR notes ILIKE ${n})")
    args.append(limit)
    rows = await pool.fetch(
        f"SELECT {_LEAD_COLS} FROM sales_leads WHERE {' AND '.join(where)} "
        f"ORDER BY next_step_at NULLS LAST, updated_at DESC LIMIT ${len(args)}", *args)
    return [_lead(r) for r in rows]


@router.post("/leads", response_model=Lead, status_code=status.HTTP_201_CREATED)
async def create_lead(body: LeadIn, ctx: Annotated[SalesCtx, Depends(require_sales)],
                      pool: Annotated[asyncpg.Pool, Depends(get_pool)]) -> Lead:
    d = body.model_dump()
    row = await pool.fetchrow(
        f"""INSERT INTO sales_leads (owner_user_id, company, dba, city, state, phone, website, contact_name, contact_role,
                                     contact_email, towboats, tugs, passenger, osv, service, area, source, status,
                                     next_step, next_step_at, notes)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, COALESCE($17, 'manual'), $18,
                    $19, $20, $21)
            RETURNING {_LEAD_COLS}""",
        uuid.UUID(ctx.owner_id), d["company"], d["dba"], d["city"], d["state"], d["phone"], d["website"],
        d["contact_name"], d["contact_role"], d["contact_email"], d["towboats"], d["tugs"], d["passenger"], d["osv"],
        d["service"], d["area"], d["source"], d["status"], d["next_step"], d["next_step_at"], d["notes"])
    return _lead(row)


@router.patch("/leads/{lead_id}", response_model=Lead)
async def update_lead(lead_id: uuid.UUID, body: LeadPatch, ctx: Annotated[SalesCtx, Depends(require_sales)],
                      pool: Annotated[asyncpg.Pool, Depends(get_pool)]) -> Lead:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Nothing to change")
    sets, args = [], [lead_id, uuid.UUID(ctx.owner_id)]
    for k, v in changes.items():
        args.append(v)
        sets.append(f"{k} = ${len(args)}")
    row = await pool.fetchrow(
        f"UPDATE sales_leads SET {', '.join(sets)}, updated_at = now() WHERE id = $1 AND owner_user_id = $2 "
        f"RETURNING {_LEAD_COLS}", *args)
    if row is None:
        raise HTTPException(status_code=404, detail="No such lead")
    return _lead(row)


@router.get("/leads/export")
async def export_leads(ctx: Annotated[SalesCtx, Depends(require_sales)],
                       pool: Annotated[asyncpg.Pool, Depends(get_pool)]):
    rows = await pool.fetch(f"SELECT {_LEAD_COLS} FROM sales_leads WHERE owner_user_id = $1 ORDER BY company",
                            uuid.UUID(ctx.owner_id))
    buf = io.StringIO()
    cols = [c.strip() for c in _LEAD_COLS.split(",")]
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for r in rows:
        w.writerow({c: ("" if r[c] is None else r[c]) for c in cols})
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="leads-{ctx.code}.csv"'})


@router.get("/lookup", response_model=list[Lead])
async def lookup(ctx: Annotated[SalesCtx, Depends(require_sales)],
                 pool: Annotated[asyncpg.Pool, Depends(get_pool)],
                 q: str = Query(min_length=2, max_length=100)) -> list[Lead]:
    """What we already hold on a company: the imported Coast Guard records
    (vessel counts, service, area) and any contact found so far."""
    rows = await pool.fetch(
        f"""SELECT {_LEAD_COLS} FROM sales_leads
             WHERE owner_user_id = $1 AND (company ILIKE $2 OR dba ILIKE $2 OR city ILIKE $2)
             ORDER BY COALESCE(towboats, 0) + COALESCE(tugs, 0) DESC, company LIMIT 20""",
        uuid.UUID(ctx.owner_id), f"%{q.strip()}%")
    return [_lead(r) for r in rows]
