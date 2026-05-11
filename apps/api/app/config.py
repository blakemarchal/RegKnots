from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolves to the monorepo root regardless of working directory
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    database_url: str = "postgresql://regknots:regknots_dev@localhost:5432/regknots"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = ["http://localhost:3000"]
    environment: str = "development"

    # JWT
    jwt_secret_key: str = "dev-secret-key-change-in-production-use-REGKNOTS_JWT_SECRET_KEY"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # AI API keys — no REGKNOTS_ prefix in .env
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    # Sprint D6.58 (Slice 3) — xAI / Grok API key for the Big-3 ensemble
    # web fallback. Empty in dev; the ensemble path falls back to
    # Anthropic+OpenAI only when this is unset (graceful degrade).
    xai_api_key: str = Field(default="", validation_alias="XAI_API_KEY")

    # Email — no REGKNOTS_ prefix in .env
    resend_api_key: str = Field(default="", validation_alias="RESEND_API_KEY")

    # Legacy pre-launch pilot gate. Keep False post-launch — the standard
    # subscription gate in chat.py now handles trial expiry and limits.
    pilot_mode: bool = False

    # Stripe — no REGKNOTS_ prefix in .env
    stripe_secret_key: str = Field(default="", validation_alias="STRIPE_SECRET_KEY")
    stripe_webhook_secret: str = Field(default="", validation_alias="STRIPE_WEBHOOK_SECRET")
    # Legacy pre-D6.1 single-tier price IDs. Retained for backward compat
    # with any stale webhook traffic; new checkout flows do not use them.
    # Safe to unset once D6.1 two-tier pricing is verified live.
    stripe_price_id: str = Field(default="", validation_alias="STRIPE_PRICE_ID")
    stripe_annual_price_id: str = Field(default="", validation_alias="STRIPE_ANNUAL_PRICE_ID")
    # Sprint D6.1 two-tier pricing — six Stripe price IDs across Mate and
    # Captain products. See apps/api/app/plans.py for how these map to
    # subscription_tier + billing_interval + promo flag.
    stripe_price_mate_monthly: str = Field(
        default="", validation_alias="STRIPE_PRICE_MATE_MONTHLY"
    )
    stripe_price_mate_annual: str = Field(
        default="", validation_alias="STRIPE_PRICE_MATE_ANNUAL"
    )
    stripe_price_mate_promo: str = Field(
        default="", validation_alias="STRIPE_PRICE_MATE_PROMO"
    )
    stripe_price_captain_monthly: str = Field(
        default="", validation_alias="STRIPE_PRICE_CAPTAIN_MONTHLY"
    )
    stripe_price_captain_annual: str = Field(
        default="", validation_alias="STRIPE_PRICE_CAPTAIN_ANNUAL"
    )
    stripe_price_captain_promo: str = Field(
        default="", validation_alias="STRIPE_PRICE_CAPTAIN_PROMO"
    )
    # Sprint D6.54 — Wheelhouse (crew tier) pricing. One product, two
    # billing intervals. No promo variants by design — margin risk on
    # multi-seat tier is too high to discount. See plans_workspace.py
    # for the price_id → workspace mapping logic.
    stripe_price_wheelhouse_monthly: str = Field(
        default="", validation_alias="STRIPE_PRICE_WHEELHOUSE_MONTHLY"
    )
    stripe_price_wheelhouse_annual: str = Field(
        default="", validation_alias="STRIPE_PRICE_WHEELHOUSE_ANNUAL"
    )
    app_url: str = "https://regknots.com"

    # File uploads
    upload_dir: str = str(_REPO_ROOT / "data" / "uploads" / "documents")

    # Sprint D6.7 — Caddy access-log analytics. Path to the directory
    # holding `regknots-access.log` and its rotated siblings. Set to ""
    # in dev (no Caddy running locally) — the /admin/traffic endpoint
    # returns an empty summary in that case instead of erroring.
    caddy_access_log_dir: str = Field(default="/var/log/caddy", validation_alias="CADDY_ACCESS_LOG_DIR")

    # ── Crew tier (D6.49) ────────────────────────────────────────────────
    # Master enable for the crew-tier feature. When false, the workspace
    # endpoints + UI are hidden from non-internal users; the migration
    # data model is harmless.
    crew_tier_enabled: bool = Field(
        default=False, validation_alias="CREW_TIER_ENABLED",
    )
    # Internal-only mode — when true (and crew_tier_enabled), only users
    # with is_internal=true can create or join workspaces. Used during
    # staged rollout for self-review before lifting to all users.
    crew_tier_internal_only: bool = Field(
        default=True, validation_alias="CREW_TIER_INTERNAL_ONLY",
    )

    # ── Web search fallback (D6.48 Phase 2) ──────────────────────────────
    # Master kill switch — flip to false on prod to disable fallback firing
    # for all users instantly without redeploying.
    web_fallback_enabled: bool = Field(
        default=True, validation_alias="WEB_FALLBACK_ENABLED",
    )
    # Cosine threshold below which we treat retrieval as a true corpus
    # gap and consider firing fallback. v1 was 0.5; audit (D6.48 Phase 2,
    # 2026-05-02) showed real-world hedges fire with top-1 cosine in the
    # 0.55-0.70 band ("nearby but not the answer"), making 0.5 a silent
    # blocker. Bumped to 0.7 so the hedge classifier is the dominant
    # signal and cosine only catches truly-confident corpus answers
    # the model still hedged on (rare).
    web_fallback_cosine_threshold: float = Field(
        default=0.7, validation_alias="WEB_FALLBACK_COSINE_THRESHOLD",
    )
    # Per-user daily cap. Raises a soft block — user gets the original
    # hedge instead of a fallback after exceeding their daily quota.
    web_fallback_daily_cap: int = Field(
        default=10, validation_alias="WEB_FALLBACK_DAILY_CAP",
    )
    # ── D6.59 Cascading ensemble ─────────────────────────────────────
    # When true, the Big-3 ensemble probes Claude alone first and only
    # fans out to GPT + Grok if Claude's result doesn't pass the stop
    # gate (verified quote on a trusted domain at confidence ≥4). Cuts
    # ensemble cost roughly in half on common CFR / class society
    # questions where Claude alone has the answer. Falls back to the
    # legacy parallel fan-out (`attempt_ensemble_fallback`) when false.
    # See docs/proposals/d6-59-cascading-ensemble.md.
    web_fallback_cascade_enabled: bool = Field(
        default=True, validation_alias="WEB_FALLBACK_CASCADE_ENABLED",
    )
    # ── D6.60 Hedge judge ────────────────────────────────────────────
    # When true, every regex hedge match runs through a Haiku judge
    # that classifies the hedge as complete_miss / partial_miss /
    # precision_callout / false_hedge. Only the first two fire the
    # ensemble; precision callouts (e.g. "I gave you 8 citations, btw
    # niche detail X isn't in my context") suppress, saving the spend
    # and avoiding redundant yellow cards. False = legacy regex-only
    # behavior (every regex match fires fallback).
    # See packages/rag/rag/hedge_judge.py for the judge prompt and
    # docs/proposals/d6-60-hedge-judge.md (forthcoming) for the
    # design rationale.
    hedge_judge_enabled: bool = Field(
        default=True, validation_alias="HEDGE_JUDGE_ENABLED",
    )
    # ── D6.66 Sprint 5 — multi-query rewrite + reranker ──────────────
    # query_rewrite_enabled: every chat fire runs the user's query
    # through Haiku to produce 2-3 alternative phrasings, then
    # retrieves against the union of all variants. Closes the
    # vocabulary-mismatch gap on retrieval (e.g., "stencil" vs
    # "marking", "lifejacket" vs "lifesaving appliance").
    # ~$0.001 + ~400ms per chat. Default on.
    #
    # reranker_enabled: after cosine retrieval, pull top-30
    # candidates and ask Haiku to score each on actual relevance to
    # the question 1-5. Reorder, return top-K. Catches the
    # "controlling section was in candidates but ranked 12th by
    # cosine" failure mode. ~$0.002 + ~600ms per chat. Default on.
    #
    # Flags are independent — either can be off without disabling
    # the other. Setting both to false reverts to the legacy
    # single-query, cosine-ordered retrieval path.
    query_rewrite_enabled: bool = Field(
        default=True, validation_alias="QUERY_REWRITE_ENABLED",
    )
    reranker_enabled: bool = Field(
        default=True, validation_alias="RERANKER_ENABLED",
    )

    # ── D6.70 Sprint 8 — Citation oracle (Layer-2 retrieval intervention) ──
    # When true, hedge events fire a Haiku-with-web-search call to identify
    # the controlling CFR / SOLAS / MARPOL / NVIC / STCW section, look it
    # up in OUR corpus, and synthesize a verbatim-quote-anchored answer
    # from the matched corpus chunks. If the oracle locates a corpus-
    # backed answer, we surface a 'verified' tier card and skip the
    # existing web fallback entirely. On any failure (no citation, not
    # in corpus, synthesis hedged, etc.) we fall through to today's
    # web fallback — additive-only contract, never worse than today.
    # ~$0.002 + ~1.5-2.5s per intervention. Only fires on hedge.
    # See packages/rag/rag/citation_oracle.py.
    citation_oracle_enabled: bool = Field(
        default=True, validation_alias="CITATION_ORACLE_ENABLED",
    )

    # ── D6.71 Sprint 7 — Hybrid BM25 + dense retrieval ──────────────────
    # When true, every chat retrieval runs both dense (cosine over
    # pgvector embeddings) AND lexical (ts_rank_cd over the FTS
    # tsvector index added in migration 0088), then fuses the two
    # rankings via Reciprocal Rank Fusion (RRF, k=60). Closes the
    # vocab-mismatch failure mode where the user types literal CFR
    # vocabulary ("subchapter M", "TSMS", "TPO") that embedding
    # similarity can't reliably route to.
    #
    # Default OFF — dark-launched. Migration 0088 adds the column and
    # index but no app code references it until this flag flips. When
    # off, behavior is bit-for-bit identical to the pre-D6.71 path.
    #
    # See packages/rag/rag/retriever.py::retrieve_hybrid().
    hybrid_retrieval_enabled: bool = Field(
        default=False, validation_alias="HYBRID_RETRIEVAL_ENABLED",
    )
    # RRF constant. Higher k = ranks deeper in the lists matter less.
    # 60 is canonical (Cormack et al. 2009). Tune lower (e.g. 30) to
    # weight top-ranked chunks more heavily; higher (e.g. 100) to
    # smooth across the candidate pool.
    hybrid_rrf_k: int = Field(
        default=60, validation_alias="HYBRID_RRF_K",
    )

    # ── D6.86 — Hedge judge fires on every cited answer ────────────────
    # When true, hedge_judge runs whenever the assistant produces an
    # answer with ≥1 verified citation, even if the regex hedge
    # detector didn't match anything. Captures the partial-miss
    # signal on answers like the 2026-05-11 gasket question where the
    # model used clinical "does not specify" prose the regex missed.
    # Cost: ~$0.004/cited answer; current traffic adds <$1/day.
    # The judge verdict feeds the tier router; web fallback firing is
    # NOT changed by this flag (web fallback still requires the regex
    # to have matched, preserving legacy behavior until Phase 2).
    judge_on_cited_enabled: bool = Field(
        default=True, validation_alias="JUDGE_ON_CITED_ENABLED",
    )

    # ── D6.86 — Lead-with-answer synthesis prompt ──────────────────────
    # When true, the system prompt instructs the model to lead every
    # answer with the practical conclusion, then expand. Mariners
    # skim first paragraphs; burying the answer at the end of a long
    # response is read as "no answer." Default on; toggle off via env
    # if this produces worse answers in some category we haven't seen.
    # See packages/rag/rag/prompts.py::LEAD_WITH_ANSWER_BLOCK.
    lead_with_answer_enabled: bool = Field(
        default=True, validation_alias="LEAD_WITH_ANSWER_ENABLED",
    )

    # ── D6.84 Sprint A — Confidence tier router ──────────────────────────
    # Three-mode flag controlling the additive tier_router layer.
    #
    #   off    — tier_router code is skipped entirely. Zero cost,
    #            zero behavior change. Default.
    #   shadow — tier_router runs in PARALLEL with today's pipeline.
    #            ChatResponse renders today's behavior unchanged. The
    #            shadow tier decision + classifier + self-consistency
    #            outcome is written to tier_router_shadow_log so
    #            admin can compare side-by-side.
    #   live   — tier_router runs and its decision drives the rendered
    #            answer. Today's pre-tier answer is still computed and
    #            logged to tier_router_shadow_log for forensics.
    #
    # See packages/rag/rag/tier_router.py and migration 0093 for the
    # full design. Phase E flip from shadow → live is operator-driven.
    confidence_tiers_mode: str = Field(
        default="off", validation_alias="CONFIDENCE_TIERS_MODE",
    )

    # Monitoring
    sentry_dsn: str = Field(default="", validation_alias="SENTRY_DSN")
    sentry_auth_token: str = Field(default="", validation_alias="SENTRY_AUTH_TOKEN")
    sentry_org: str = Field(default="", validation_alias="SENTRY_ORG")
    # Optional override for the /admin/sentry-issues project scope.
    # If unset, the endpoint queries the default list hardcoded in admin.py
    # (regknots-api + regknots-web). If set to a single slug, only that
    # project is queried. Comma-separated values are also accepted.
    sentry_project: str = Field(default="", validation_alias="SENTRY_PROJECT")

    @property
    def is_dev(self) -> bool:
        return self.environment == "development"

    model_config = SettingsConfigDict(
        env_prefix="REGKNOTS_",
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )


settings = Settings()
