"""Admin: sales (2026-10-17).

Blake: "an admin page where I can see sales data ... to make sure Jordan, and
whoever else we may get, has the right data and that we are organized."

One overview: every salesperson (users.sales_code; is_sales = access to /sales),
the accounts credited to each (app/sales_credit.py: an admin's credit, else the
pilot code in the signup link), what those accounts paid by month and the
commission on it, their lead lists, and checks for anything that would make a
salesperson's numbers wrong. Writes: add a salesperson (their pilot code is
created if missing), turn access off or on (the code stays theirs, so link
credit and commission history stay put), credit an account by hand, and import
leads. Every write goes to the admin audit log.
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import pilots
from app.auth.schemas import CurrentUser
from app.db import get_pool
from app.routers.admin import audit_log, require_admin, require_write_admin
from app.routers.sales import COMMISSION_RATE, LEAD_STATUSES, stage_of
from app.sales_credit import (CREDIT_CODE_SQL, CREDIT_SOURCE_SQL, USER_PAYING_SQL, WORKSPACE_PAYING_SQL,
                              credit_code_sql)
from app.sales_leads_import import import_lead_rows

router = APIRouter(prefix="/admin/sales", tags=["admin"])

MAX_IMPORT_BYTES = 5_000_000


class SalesFleet(BaseModel):
    id: str
    name: str
    status: str
    boats: int
    paying: bool
    invoiced: bool
    internal_only: bool
    trial_ends_at: datetime | None
    trial_custom: bool


class SalesAccount(BaseModel):
    user_id: str
    name: str | None
    email: str
    created_at: datetime
    code: str
    credit: str                 # 'link' | 'admin'
    signup_src: str | None
    stage: str                  # signed_up | asked | trial | paying
    questions: int
    paying_plan: bool
    internal: bool
    fleets: list[SalesFleet]
    paid_total: float


class Salesperson(BaseModel):
    user_id: str
    name: str | None
    email: str
    code: str | None
    access: bool
    pilot_label: str | None
    pilot_active: bool | None   # None: no pilot code
    trial_days: int | None
    short_link: str | None
    accounts: int
    stages: dict[str, int]
    boats_paying: int
    revenue_total: float
    commission_total: float
    commission_this_month: float
    commission_last_month: float
    leads_total: int
    leads_by_status: dict[str, int]
    leads_overdue: int
    last_lead_update: datetime | None
    last_seen: datetime | None


class PayoutRow(BaseModel):
    month: str
    code: str
    revenue: float
    commission: float


class Issue(BaseModel):
    level: str                  # error | warn | info
    code: str | None = None
    text: str
    user_id: str | None = None  # the account a one-click fix applies to
    fix: str | None = None      # 'credit_owner': credit user_id to code


class SalesOverview(BaseModel):
    rate: float
    this_month: str
    last_month: str
    people: list[Salesperson]
    accounts: list[SalesAccount]
    payouts: list[PayoutRow]
    issues: list[Issue]


class ActionResult(BaseModel):
    ok: bool
    message: str = ""


def month_keys(now: datetime) -> tuple[str, str]:
    first = now.replace(day=1)
    return first.strftime("%Y-%m"), (first - timedelta(days=1)).strftime("%Y-%m")


def build_issues(people: list[dict], accounts: list[SalesAccount], unknown_codes: list[tuple[str, int]],
                 dup_leads: list[tuple[str, list[str]]], member_gaps: list[dict],
                 pilot_days: dict[str, int]) -> list[Issue]:
    """Everything that would make a salesperson's numbers or link wrong. Pure, for tests."""
    out: list[Issue] = []
    for p in people:
        who = p["name"] or p["email"]
        if p["access"] and not p["code"]:
            out.append(Issue(level="error", text=f"{who} has sales access but no code, so their pages are empty."))
        elif p["code"] and p["pilot_active"] is None:
            out.append(Issue(level="error", code=p["code"],
                             text=f"There is no pilot code '{p['code']}', so {who}'s link gives the standard "
                                  f"30-day trial. Create it in Pilots."))
        elif p["code"] and p["access"] and p["pilot_active"] is False:
            out.append(Issue(level="warn", code=p["code"],
                             text=f"Pilot code '{p['code']}' is paused: new fleets from {who}'s link get the "
                                  f"standard 30-day trial."))
        if not p["access"] and p["code"] and p["paying_accounts"]:
            out.append(Issue(level="info", code=p["code"],
                             text=f"{who}'s sales access is off, and {p['paying_accounts']} of their accounts "
                                  f"still pay, so commission is still owed."))
    for a in accounts:
        for f in a.fleets:
            if f.paying and not f.invoiced:
                out.append(Issue(level="warn", code=a.code, user_id=a.user_id,
                                 text=f"{f.name} ({a.email}) pays through Stripe but no invoice is recorded, so its "
                                      f"commission shows as $0. Check the Stripe webhook."))
            days = pilot_days.get(a.code)
            if (a.credit == "link" and f.status in ("trialing", "card_pending") and not f.trial_custom
                    and days and days != pilots.STANDARD_TRIAL_DAYS):
                out.append(Issue(level="warn", code=a.code, user_id=a.user_id,
                                 text=f"{f.name} ({a.email}) came from the '{a.code}' link but is on the standard "
                                      f"30-day trial, not {days} days. Set its trial in Pilots."))
    for code, n in unknown_codes:
        out.append(Issue(level="warn", code=code,
                         text=f"{n} account{'s' if n != 1 else ''} signed up with pilot code '{code}', which doesn't "
                              f"exist: a mistyped or old link is going around."))
    for company, owners in dup_leads:
        out.append(Issue(level="warn", text=f"{company} is in the lead lists of {' and '.join(owners)}. "
                                            f"Agree who has it before both call."))
    for g in member_gaps:
        out.append(Issue(level="warn", code=g["code"], user_id=g["owner_id"], fix="credit_owner",
                         text=f"{g['member_email']} counts toward '{g['code']}' and is in {g['workspace']}, "
                              f"but the fleet's owner {g['owner_email']} doesn't, so the fleet's payments "
                              f"don't count for '{g['code']}'."))
    return out


@router.get("", response_model=SalesOverview)
async def overview(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> SalesOverview:
    this_month, last_month = month_keys(datetime.now(timezone.utc))
    prow = await pool.fetch(
        """SELECT u.id, u.full_name, u.email, u.sales_code, u.is_sales, p.label, p.active, p.trial_days,
                  (SELECT max(r.created_at) FROM refresh_tokens r WHERE r.user_id = u.id) AS last_seen
             FROM users u LEFT JOIN pilot_codes p ON p.code = u.sales_code
            WHERE u.is_sales OR u.sales_code IS NOT NULL
            ORDER BY u.is_sales DESC, u.created_at""")
    codes = [r["sales_code"] for r in prow if r["sales_code"]]

    arows = await pool.fetch(
        f"""SELECT u.id, u.full_name, u.email, u.created_at, {CREDIT_CODE_SQL} AS code,
                   {CREDIT_SOURCE_SQL} AS credit, u.signup_attribution->>'src' AS src,
                   {USER_PAYING_SQL} AS paying_plan, (u.is_internal OR u.is_admin) AS internal,
                   (SELECT count(*) FROM messages m JOIN conversations c ON c.id = m.conversation_id
                     WHERE c.user_id = u.id AND m.role = 'user') AS questions
              FROM users u WHERE {CREDIT_CODE_SQL} = ANY($1::text[])
             ORDER BY u.created_at DESC""", codes)
    ids = [r["id"] for r in arows]
    frows = await pool.fetch(
        f"""SELECT w.id, w.owner_user_id, w.name, w.status, w.internal_only,
                   (w.trial_ends_at IS NOT NULL) AS trial_custom, {pilots.TRIAL_END_SQL} AS trial_ends_at,
                   {WORKSPACE_PAYING_SQL} AS paying,
                   (SELECT count(*) FROM vessels v WHERE v.workspace_id = w.id) AS boats,
                   EXISTS (SELECT 1 FROM workspace_billing_events e
                            WHERE e.workspace_id = w.id AND e.event_type = 'invoice_paid') AS invoiced
              FROM workspaces w WHERE w.owner_user_id = ANY($1::uuid[]) ORDER BY w.created_at""", ids)
    paid = await pool.fetch(
        """SELECT w.owner_user_id AS uid, sum(COALESCE((e.details->>'amount_paid_cents')::bigint, 0)) AS cents
             FROM workspace_billing_events e JOIN workspaces w ON w.id = e.workspace_id
            WHERE e.event_type = 'invoice_paid' AND w.owner_user_id = ANY($1::uuid[]) GROUP BY 1
           UNION ALL
           SELECT b.user_id, sum(COALESCE(b.amount_paid_cents, 0)) FROM billing_events b
            WHERE b.user_id = ANY($1::uuid[]) GROUP BY 1""", ids)
    paid_by: dict = {}
    for r in paid:
        paid_by[r["uid"]] = paid_by.get(r["uid"], 0) + int(r["cents"] or 0)
    fleets_by: dict = {}
    for f in frows:
        fleets_by.setdefault(f["owner_user_id"], []).append(SalesFleet(
            id=str(f["id"]), name=f["name"], status=f["status"], boats=f["boats"], paying=f["paying"],
            invoiced=f["invoiced"], internal_only=f["internal_only"], trial_ends_at=f["trial_ends_at"],
            trial_custom=f["trial_custom"]))
    accounts = []
    for r in arows:
        fl = fleets_by.get(r["id"], [])
        accounts.append(SalesAccount(
            user_id=str(r["id"]), name=r["full_name"], email=r["email"], created_at=r["created_at"], code=r["code"],
            credit=r["credit"], signup_src=r["src"], stage=stage_of(r["questions"], fl, bool(r["paying_plan"])),
            questions=r["questions"], paying_plan=bool(r["paying_plan"]), internal=bool(r["internal"]), fleets=fl,
            paid_total=paid_by.get(r["id"], 0) / 100))

    pay = await pool.fetch(
        f"""WITH people AS (SELECT u.id, {CREDIT_CODE_SQL} AS code FROM users u
                             WHERE {CREDIT_CODE_SQL} = ANY($1::text[]))
            SELECT to_char(e.created_at, 'YYYY-MM') AS month, p.code,
                   sum(COALESCE((e.details->>'amount_paid_cents')::bigint, 0)) AS cents
              FROM workspace_billing_events e JOIN workspaces w ON w.id = e.workspace_id
              JOIN people p ON p.id = w.owner_user_id
             WHERE e.event_type = 'invoice_paid' GROUP BY 1, 2
            UNION ALL
            SELECT to_char(COALESCE(b.paid_at, b.created_at), 'YYYY-MM'), p.code, sum(COALESCE(b.amount_paid_cents, 0))
              FROM billing_events b JOIN people p ON p.id = b.user_id GROUP BY 1, 2""", codes)
    cents_by: dict[tuple[str, str], int] = {}
    for r in pay:
        key = (r["month"], r["code"])
        cents_by[key] = cents_by.get(key, 0) + int(r["cents"] or 0)
    payouts = [PayoutRow(month=m, code=c, revenue=v / 100, commission=round(v / 100 * COMMISSION_RATE, 2))
               for (m, c), v in sorted(cents_by.items(), reverse=True) if v]

    leads = await pool.fetch(
        """SELECT owner_user_id, status, count(*) AS n,
                  count(*) FILTER (WHERE next_step_at < current_date AND status NOT IN ('paying', 'lost')) AS overdue,
                  max(updated_at) AS last
             FROM sales_leads GROUP BY 1, 2""")
    leads_by: dict = {}
    for r in leads:
        d = leads_by.setdefault(r["owner_user_id"], {"by": {}, "overdue": 0, "last": None})
        d["by"][r["status"]] = r["n"]
        d["overdue"] += r["overdue"]
        d["last"] = max(d["last"], r["last"]) if d["last"] else r["last"]

    people, people_for_checks = [], []
    for r in prow:
        code = r["sales_code"]
        mine = [a for a in accounts if a.code == code] if code else []
        stages = {s: 0 for s in ("signed_up", "asked", "trial", "paying")}
        for a in mine:
            stages[a.stage] = stages.get(a.stage, 0) + 1
        revenue = sum(v for (m, c), v in cents_by.items() if c == code) / 100
        ld = leads_by.get(r["id"], {"by": {}, "overdue": 0, "last": None})
        people.append(Salesperson(
            user_id=str(r["id"]), name=r["full_name"], email=r["email"], code=code, access=bool(r["is_sales"]),
            pilot_label=r["label"], pilot_active=r["active"], trial_days=r["trial_days"],
            short_link=f"regknots.com/fleet?src={pilots.SRC_PREFIX}{code}" if code else None,
            accounts=len(mine), stages=stages,
            boats_paying=sum(f.boats for a in mine for f in a.fleets if f.paying),
            revenue_total=revenue, commission_total=round(revenue * COMMISSION_RATE, 2),
            commission_this_month=round(cents_by.get((this_month, code), 0) / 100 * COMMISSION_RATE, 2),
            commission_last_month=round(cents_by.get((last_month, code), 0) / 100 * COMMISSION_RATE, 2),
            leads_total=sum(ld["by"].values()), leads_by_status={s: ld["by"].get(s, 0) for s in LEAD_STATUSES},
            leads_overdue=ld["overdue"], last_lead_update=ld["last"], last_seen=r["last_seen"]))
        people_for_checks.append({"name": r["full_name"], "email": r["email"], "code": code,
                                  "access": bool(r["is_sales"]), "pilot_active": r["active"],
                                  "paying_accounts": stages["paying"]})

    unknown = await pool.fetch(
        f"""SELECT substr(lower(signup_attribution->>'src'), {len(pilots.SRC_PREFIX) + 1}) AS code, count(*) AS n
              FROM users WHERE lower(signup_attribution->>'src') LIKE '{pilots.SRC_PREFIX}%'
               AND substr(lower(signup_attribution->>'src'), {len(pilots.SRC_PREFIX) + 1})
                   NOT IN (SELECT code FROM pilot_codes)
             GROUP BY 1 ORDER BY 2 DESC""")
    dups = await pool.fetch(
        """SELECT min(l.company) AS company, array_agg(DISTINCT COALESCE(u.full_name, u.email)) AS owners
             FROM sales_leads l JOIN users u ON u.id = l.owner_user_id
            WHERE l.status <> 'lost'
            GROUP BY lower(btrim(l.company)) HAVING count(DISTINCT l.owner_user_id) > 1
            ORDER BY 1 LIMIT 25""")
    gaps = await pool.fetch(
        f"""SELECT DISTINCT ON (w.id) w.name AS workspace, {credit_code_sql('u')} AS code, u.email AS member_email,
                   o.id AS owner_id, o.email AS owner_email
              FROM workspace_members m JOIN users u ON u.id = m.user_id
              JOIN workspaces w ON w.id = m.workspace_id JOIN users o ON o.id = w.owner_user_id
             WHERE m.user_id <> w.owner_user_id AND w.status <> 'archived'
               AND {credit_code_sql('u')} = ANY($1::text[])
               AND o.credited_sales_code IS NULL AND {credit_code_sql('o')} IS NULL""", codes)
    pilot_days = {r["sales_code"]: r["trial_days"] for r in prow if r["sales_code"] and r["trial_days"]}
    issues = build_issues(
        people_for_checks, accounts, [(r["code"], r["n"]) for r in unknown],
        [(r["company"], list(r["owners"])) for r in dups],
        [{**dict(g), "owner_id": str(g["owner_id"])} for g in gaps], pilot_days)
    return SalesOverview(rate=COMMISSION_RATE, this_month=this_month, last_month=last_month, people=people,
                         accounts=accounts, payouts=payouts, issues=issues)


class AddSalesperson(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    code: str = Field(min_length=2, max_length=39)
    trial_days: int = Field(default=90, ge=1, le=365)


@router.post("/people", response_model=ActionResult)
async def add_salesperson(
    body: AddSalesperson,
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> ActionResult:
    code = pilots.normalize_code(body.code)
    if not pilots.CODE_RE.match(code):
        raise HTTPException(status_code=422, detail="Use 2-39 lowercase letters, digits or hyphens.")
    user = await pool.fetchrow("SELECT id, full_name, email, sales_code FROM users WHERE lower(email) = lower($1)",
                               body.email.strip())
    if user is None:
        raise HTTPException(status_code=404,
                            detail="No account with that email. They sign up first, then you add them here.")
    if user["sales_code"] and user["sales_code"] != code:
        raise HTTPException(status_code=409, detail=f"They already sell under '{user['sales_code']}'. "
                                                    "A code stays with its salesperson.")
    taken = await pool.fetchval("SELECT email FROM users WHERE sales_code = $1 AND id <> $2", code, user["id"])
    if taken:
        raise HTTPException(status_code=409, detail=f"'{code}' belongs to {taken}.")
    existing = await pool.fetchrow("SELECT label, trial_days FROM pilot_codes WHERE code = $1", code)
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                if existing is None:
                    await conn.execute(
                        "INSERT INTO pilot_codes (code, label, trial_days, notes, created_by) "
                        "VALUES ($1, $2, $3, 'sales', $4)",
                        code, f"{user['full_name'] or user['email']} (sales)"[:120], body.trial_days,
                        uuid.UUID(admin.user_id))
                await conn.execute("UPDATE users SET is_sales = TRUE, sales_code = $2 WHERE id = $1",
                                   user["id"], code)
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail=f"'{code}' was just taken. Pick another code.")
    await audit_log(pool, admin, "add_salesperson", str(user["id"]),
                    {"email": user["email"], "code": code, "pilot_created": existing is None})
    note = (f"Created pilot code '{code}' ({body.trial_days} days)." if existing is None
            else f"Using the existing pilot code '{code}' ({existing['label']}, {existing['trial_days']} days).")
    return ActionResult(ok=True, message=f"{user['email']} can open /sales now. {note} "
                                         "The Sales menu item appears after their next sign-in.")


class AccessBody(BaseModel):
    active: bool


@router.post("/people/{user_id}/access", response_model=ActionResult)
async def set_access(
    user_id: uuid.UUID,
    body: AccessBody,
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> ActionResult:
    """Access on or off. The code stays theirs: link credit and commission history don't move."""
    code = await pool.fetchval("SELECT sales_code FROM users WHERE id = $1", user_id)
    if not code:
        raise HTTPException(status_code=404, detail="Not a salesperson")
    await pool.execute("UPDATE users SET is_sales = $2 WHERE id = $1", user_id, body.active)
    await audit_log(pool, admin, "set_sales_access", str(user_id), {"code": code, "active": body.active})
    return ActionResult(ok=True, message="Access on." if body.active else
                        f"Access off. Accounts credited to '{code}' stay credited.")


class CreditBody(BaseModel):
    user_id: uuid.UUID | None = None
    email: str | None = Field(default=None, max_length=200)
    credit: str | None = Field(default=None, max_length=39)   # a salesperson's code; '' = no one; null = the link


@router.post("/credit", response_model=ActionResult)
async def set_credit(
    body: CreditBody,
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> ActionResult:
    if body.user_id:
        row = await pool.fetchrow("SELECT id, email FROM users WHERE id = $1", body.user_id)
    elif body.email:
        row = await pool.fetchrow("SELECT id, email FROM users WHERE lower(email) = lower($1)", body.email.strip())
    else:
        raise HTTPException(status_code=422, detail="Which account?")
    if row is None:
        raise HTTPException(status_code=404, detail="No account with that email.")
    value = body.credit
    if value:
        value = pilots.normalize_code(value)
        if not await pool.fetchval("SELECT 1 FROM users WHERE sales_code = $1", value):
            raise HTTPException(status_code=422, detail=f"No salesperson has the code '{value}'.")
    await pool.execute("UPDATE users SET credited_sales_code = $2 WHERE id = $1", row["id"], value)
    await audit_log(pool, admin, "set_sales_credit", str(row["id"]), {"email": row["email"], "credit": value})
    what = (f"credited to '{value}'" if value else "credited to no one" if value == ""
            else "credited by its signup link again")
    return ActionResult(ok=True, message=f"{row['email']} is {what}.")


class ImportResult(BaseModel):
    inserted: int
    updated: int
    skipped: int
    rows: int


@router.post("/people/{user_id}/leads/import", response_model=ImportResult)
async def import_leads(
    user_id: uuid.UUID,
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    file: UploadFile = File(...),
    niche: str = Form(default="towing", max_length=40),
) -> ImportResult:
    """The outreach list's CSV (data/outreach/leads.csv) into a salesperson's leads."""
    if not await pool.fetchval("SELECT 1 FROM users WHERE id = $1 AND sales_code IS NOT NULL", user_id):
        raise HTTPException(status_code=404, detail="Not a salesperson")
    raw = await file.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="That file is over 5 MB.")
    try:
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    except (UnicodeDecodeError, csv.Error):
        raise HTTPException(status_code=422, detail="That isn't a UTF-8 CSV file.")
    if not rows or "company" not in rows[0] or "id" not in rows[0]:
        raise HTTPException(status_code=422, detail="Expected the outreach leads CSV (columns id, niche, company, …).")
    res = await import_lead_rows(pool, user_id, rows, niche.strip() or None)
    await audit_log(pool, admin, "import_sales_leads", str(user_id), {"file": (file.filename or "")[:120],
                                                                       "niche": niche, **res})
    return ImportResult(**res)


@router.get("/payouts.csv")
async def payouts_csv(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    month: str = Query(pattern=r"^\d{4}-\d{2}$"),
):
    """Every payment in a month from accounts credited to a salesperson, with the commission on it.
    Refunds are not netted here; scripts/sales/commission_report.py nets them from Stripe."""
    rows = await pool.fetch(
        f"""WITH people AS (SELECT u.id, u.email, {CREDIT_CODE_SQL} AS code FROM users u
                             WHERE {CREDIT_CODE_SQL} IN (SELECT sales_code FROM users WHERE sales_code IS NOT NULL))
            SELECT p.code, e.created_at AS paid_at, p.email AS account, 'fleet: ' || w.name AS what,
                   e.details->>'stripe_invoice_id' AS invoice,
                   COALESCE((e.details->>'amount_paid_cents')::bigint, 0) AS cents
              FROM workspace_billing_events e JOIN workspaces w ON w.id = e.workspace_id
              JOIN people p ON p.id = w.owner_user_id
             WHERE e.event_type = 'invoice_paid' AND to_char(e.created_at, 'YYYY-MM') = $1
            UNION ALL
            SELECT p.code, COALESCE(b.paid_at, b.created_at), p.email, 'plan: ' || COALESCE(b.subscription_tier, ''),
                   b.stripe_invoice_id, COALESCE(b.amount_paid_cents, 0)
              FROM billing_events b JOIN people p ON p.id = b.user_id
             WHERE to_char(COALESCE(b.paid_at, b.created_at), 'YYYY-MM') = $1
            ORDER BY 1, 2""", month)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["salesperson_code", "paid_at", "account", "what", "stripe_invoice", "amount_usd", "commission_usd"])
    for r in rows:
        amount = int(r["cents"] or 0) / 100
        w.writerow([r["code"], r["paid_at"].strftime("%Y-%m-%d"), r["account"], r["what"], r["invoice"] or "",
                    f"{amount:.2f}", f"{amount * COMMISSION_RATE:.2f}"])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="sales-payouts-{month}.csv"'})
