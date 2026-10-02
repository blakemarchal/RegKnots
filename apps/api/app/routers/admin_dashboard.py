"""2026-09-29 — admin dashboard: trends, funnel, revenue, answer quality, recent activity.

One read-only call behind the redesigned /admin overview. /admin/stats keeps
serving the headline counters (and the milestone celebration); this adds what
it can't show: weekly trends, where users drop out of the funnel, money, which
answers hedged and why, and what happened lately.

Counts external users only unless exclude_internal=false (same filter as
/admin/stats: is_internal and is_admin accounts are left out).
"""
from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.auth.schemas import CurrentUser
from app.config import settings
from app.db import get_pool
from app.routers.admin import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])

EXTERNAL = " AND u.is_internal IS NOT TRUE AND u.is_admin IS NOT TRUE"
PAID = "u.subscription_tier IN ('cadet', 'mate', 'captain', 'pro') AND u.subscription_status = 'active'"


class WeekPoint(BaseModel):
    week_start: date
    signups: int
    active_users: int      # distinct users who asked at least one question that week
    questions: int
    new_paying: int        # first paid invoice that week


class Funnel(BaseModel):
    signed_up: int
    asked: int             # asked at least one question, ever
    returned: int          # asked on two or more different days
    active_30d: int        # asked in the last 30 days
    paying: int            # active paid subscription now


class Revenue(BaseModel):
    mrr_cents: int         # each active subscriber's latest invoice, annual plans divided by 12
    paid_30d_cents: int
    paid_alltime_cents: int
    invoices: int
    last_payment_at: datetime | None


class Quality(BaseModel):
    answers_7d: int
    # Answers by messages.model_used ("opus", "sonnet", "haiku", "fallback_gpt4o", ...).
    # A fallback_gpt4o count means Claude was unavailable (e.g. credits ran out).
    models_7d: dict[str, int] = {}
    hedged_7d: int                       # answers the hedge detector flagged (retrieval_misses)
    judge_7d: dict[str, int]             # the hedge judge's verdicts on those, "unjudged" when empty
    hedge_audits_new_7d: int
    hedge_audits_open: int
    open_audit_causes: dict[str, int]    # open hedge audits by classifier cause


class Attention(BaseModel):
    trials_ending_7d: int


class Growth(BaseModel):
    """2026-10-02 — the free practice page and the free plan."""
    practice_quizzes_7d: int
    practice_quizzes_30d: int
    practice_signups_30d: int       # signed up from a /practice link or landing
    free_plan_answers_month: int    # free-plan answers this calendar month
    free_plan_cap_month: int        # settings.free_plan_global_monthly_cap


class RecentSignup(BaseModel):
    id: str
    email: str
    full_name: str | None
    role: str | None
    created_at: datetime
    signup_source: str | None
    questions: int


class RecentQuestion(BaseModel):
    conversation_id: str
    user_email: str
    user_name: str | None
    preview: str
    created_at: datetime


class RecentPayment(BaseModel):
    user_email: str | None  # None once the account has been deleted (the payment stays, migration 0118)
    amount_cents: int
    subscription_tier: str | None
    billing_interval: str | None
    paid_at: datetime


class Dashboard(BaseModel):
    generated_at: datetime
    weeks: list[WeekPoint]
    funnel: Funnel
    revenue: Revenue
    quality: Quality
    attention: Attention
    growth: Growth
    recent_signups: list[RecentSignup]
    recent_questions: list[RecentQuestion]
    recent_payments: list[RecentPayment]


def _counts(rows, key: str, empty: str = "unjudged") -> dict[str, int]:
    """{label: count} from (label, n) rows; a NULL label becomes `empty`."""
    return {(r[key] or empty): r["n"] for r in rows}


@router.get("/dashboard", response_model=Dashboard)
async def dashboard(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    exclude_internal: bool = Query(default=True),
    weeks: int = Query(default=26, ge=4, le=104),
) -> Dashboard:
    uf = EXTERNAL if exclude_internal else ""
    pool = await get_pool()
    async with pool.acquire() as conn:
        week_rows = await conn.fetch(
            f"""
            WITH weeks AS (
              SELECT generate_series(date_trunc('week', now()) - ($1 - 1) * interval '1 week',
                                     date_trunc('week', now()), interval '1 week') AS wk
            ), su AS (
              SELECT date_trunc('week', u.created_at) AS wk, count(*) AS n
              FROM users u WHERE u.created_at >= (SELECT min(wk) FROM weeks){uf}
              GROUP BY 1
            ), q AS (
              SELECT date_trunc('week', m.created_at) AS wk, count(*) AS questions,
                     count(DISTINCT c.user_id) AS active
              FROM messages m
              JOIN conversations c ON c.id = m.conversation_id
              JOIN users u ON u.id = c.user_id
              WHERE m.role = 'user' AND m.created_at >= (SELECT min(wk) FROM weeks){uf}
              GROUP BY 1
            ), fp AS (
              SELECT date_trunc('week', f.first_paid) AS wk, count(*) AS n
              FROM (SELECT be.user_id, min(be.paid_at) AS first_paid
                    FROM billing_events be JOIN users u ON u.id = be.user_id
                    WHERE be.amount_paid_cents > 0{uf}
                    GROUP BY be.user_id) f
              GROUP BY 1
            )
            SELECT w.wk::date AS week_start, COALESCE(su.n, 0) AS signups,
                   COALESCE(q.active, 0) AS active_users, COALESCE(q.questions, 0) AS questions,
                   COALESCE(fp.n, 0) AS new_paying
            FROM weeks w
            LEFT JOIN su ON su.wk = w.wk LEFT JOIN q ON q.wk = w.wk LEFT JOIN fp ON fp.wk = w.wk
            ORDER BY w.wk
            """,
            weeks,
        )
        funnel = await conn.fetchrow(
            f"""
            WITH qs AS (
              SELECT c.user_id, count(*) AS n, count(DISTINCT date_trunc('day', m.created_at)) AS days,
                     max(m.created_at) AS last_q
              FROM messages m JOIN conversations c ON c.id = m.conversation_id
              WHERE m.role = 'user' GROUP BY c.user_id
            )
            SELECT count(*) AS signed_up,
                   count(*) FILTER (WHERE qs.n > 0) AS asked,
                   count(*) FILTER (WHERE qs.days >= 2) AS returned,
                   count(*) FILTER (WHERE qs.last_q > now() - interval '30 days') AS active_30d,
                   count(*) FILTER (WHERE {PAID}) AS paying
            FROM users u LEFT JOIN qs ON qs.user_id = u.id
            WHERE TRUE{uf}
            """
        )
        mrr = await conn.fetchval(
            f"""
            SELECT COALESCE(sum(CASE WHEN le.billing_interval = 'year'
                                     THEN le.amount_paid_cents / 12.0
                                     ELSE le.amount_paid_cents END), 0)::int
            FROM users u
            JOIN LATERAL (SELECT be.amount_paid_cents, be.billing_interval FROM billing_events be
                          WHERE be.user_id = u.id AND be.paid_at IS NOT NULL
                          ORDER BY be.paid_at DESC LIMIT 1) le ON TRUE
            WHERE {PAID}{uf}
            """
        )
        money = await conn.fetchrow(
            f"""
            SELECT COALESCE(sum(be.amount_paid_cents) FILTER (WHERE be.paid_at > now() - interval '30 days'), 0) AS d30,
                   COALESCE(sum(be.amount_paid_cents), 0) AS alltime,
                   count(*) AS invoices, max(be.paid_at) AS last_paid
            FROM billing_events be LEFT JOIN users u ON u.id = be.user_id
            WHERE TRUE{uf}
            """
        )
        model_rows = await conn.fetch(
            f"""
            SELECT m.model_used AS model, count(*) AS n FROM messages m
            JOIN conversations c ON c.id = m.conversation_id JOIN users u ON u.id = c.user_id
            WHERE m.role = 'assistant' AND m.created_at > now() - interval '7 days'{uf}
            GROUP BY 1 ORDER BY 2 DESC
            """
        )
        answers_7d = sum(r["n"] for r in model_rows)
        judge_rows = await conn.fetch(
            f"""
            SELECT rm.judge_verdict AS verdict, count(*) AS n FROM retrieval_misses rm
            LEFT JOIN users u ON u.id = rm.user_id
            WHERE rm.created_at > now() - interval '7 days'{uf}
            GROUP BY 1 ORDER BY 2 DESC
            """
        )
        audits = await conn.fetchrow(
            f"""
            SELECT count(*) FILTER (WHERE h.created_at > now() - interval '7 days') AS new_7d,
                   count(*) FILTER (WHERE h.status = 'open') AS open
            FROM hedge_audits h LEFT JOIN users u ON u.id = h.user_id
            WHERE TRUE{uf}
            """
        )
        cause_rows = await conn.fetch(
            f"""
            SELECT h.classification AS cause, count(*) AS n FROM hedge_audits h
            LEFT JOIN users u ON u.id = h.user_id
            WHERE h.status = 'open'{uf}
            GROUP BY 1 ORDER BY 2 DESC
            """
        )
        trials_ending = await conn.fetchval(
            f"""
            SELECT count(*) FROM users u
            WHERE u.subscription_tier = 'free'
              AND u.trial_ends_at BETWEEN now() AND now() + interval '7 days'{uf}
            """
        )
        signups = await conn.fetch(
            f"""
            SELECT u.id, u.email, u.full_name, u.role, u.created_at, u.signup_source,
                   (SELECT count(*) FROM messages m JOIN conversations c ON c.id = m.conversation_id
                    WHERE c.user_id = u.id AND m.role = 'user') AS questions
            FROM users u WHERE TRUE{uf}
            ORDER BY u.created_at DESC LIMIT 8
            """
        )
        questions = await conn.fetch(
            rf"""
            SELECT c.id AS conversation_id, u.email, u.full_name, m.created_at,
                   left(regexp_replace(m.content, '\s+', ' ', 'g'), 180) AS preview
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id JOIN users u ON u.id = c.user_id
            WHERE m.role = 'user'{uf}
            ORDER BY m.created_at DESC LIMIT 8
            """
        )
        practice = await conn.fetchrow(
            """
            SELECT count(*) FILTER (WHERE created_at > now() - interval '7 days') AS q7,
                   count(*) FILTER (WHERE created_at > now() - interval '30 days') AS q30
            FROM practice_quiz_starts
            """
        )
        practice_signups = await conn.fetchval(
            f"""
            SELECT count(*) FROM users u
            WHERE u.created_at > now() - interval '30 days'
              AND (u.signup_source = 'src:practice'
                   OR u.signup_attribution->>'landing_path' LIKE '/practice%'){uf}
            """
        )
        free_answers = await conn.fetchval(
            "SELECT answers FROM free_plan_usage WHERE month = date_trunc('month', now())::date"
        )
        payments = await conn.fetch(
            f"""
            SELECT u.email, be.amount_paid_cents, be.subscription_tier, be.billing_interval, be.paid_at
            FROM billing_events be LEFT JOIN users u ON u.id = be.user_id
            WHERE be.paid_at IS NOT NULL{uf}
            ORDER BY be.paid_at DESC LIMIT 6
            """
        )

    return Dashboard(
        generated_at=datetime.now(timezone.utc),
        weeks=[WeekPoint(**dict(r)) for r in week_rows],
        funnel=Funnel(**dict(funnel)),
        revenue=Revenue(
            mrr_cents=mrr or 0,
            paid_30d_cents=money["d30"] or 0,
            paid_alltime_cents=money["alltime"] or 0,
            invoices=money["invoices"] or 0,
            last_payment_at=money["last_paid"],
        ),
        quality=Quality(
            answers_7d=answers_7d or 0,
            models_7d=_counts(model_rows, "model", empty="unknown"),
            hedged_7d=sum(r["n"] for r in judge_rows),
            judge_7d=_counts(judge_rows, "verdict"),
            hedge_audits_new_7d=audits["new_7d"] or 0,
            hedge_audits_open=audits["open"] or 0,
            open_audit_causes=_counts(cause_rows, "cause", empty="unclassified"),
        ),
        attention=Attention(trials_ending_7d=trials_ending or 0),
        growth=Growth(
            practice_quizzes_7d=practice["q7"] or 0,
            practice_quizzes_30d=practice["q30"] or 0,
            practice_signups_30d=practice_signups or 0,
            free_plan_answers_month=free_answers or 0,
            free_plan_cap_month=settings.free_plan_global_monthly_cap,
        ),
        recent_signups=[
            RecentSignup(id=str(r["id"]), email=r["email"], full_name=r["full_name"], role=r["role"],
                         created_at=r["created_at"], signup_source=r["signup_source"], questions=r["questions"])
            for r in signups
        ],
        recent_questions=[
            RecentQuestion(conversation_id=str(r["conversation_id"]), user_email=r["email"],
                           user_name=r["full_name"], preview=r["preview"] or "", created_at=r["created_at"])
            for r in questions
        ],
        recent_payments=[
            RecentPayment(user_email=r["email"], amount_cents=r["amount_paid_cents"] or 0,
                          subscription_tier=r["subscription_tier"], billing_interval=r["billing_interval"],
                          paid_at=r["paid_at"])
            for r in payments
        ],
    )
