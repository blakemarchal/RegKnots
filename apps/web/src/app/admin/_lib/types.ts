// Shapes returned by the admin API (apps/api/app/routers/admin.py, admin_dashboard.py).

// Sprint D6.32 — restructured shape. See backend AdminStats model for the
// section breakdown rationale.
export interface TierBreakdown {
  // Sprint D6.91 — `cadet` joined the schema (entry-level tier).
  cadet?: number
  mate: number
  captain: number
  pro_legacy: number
}

export interface AdminStats {
  total_users: number
  total_questions: number
  active_users_7d: number
  questions_7d: number
  bad_answer_rate_7d: number
  subs_active: TierBreakdown
  subs_past_due: number
  subs_paused: number
  trial_active: number
  trial_expired: number
  subs_monthly: number
  subs_annual: number
  paid_users_alltime: number
  questions_today: number
  avg_questions_per_active_user_7d: number
  total_conversations: number
  conversations_today: number
  conversations_7d: number
  active_users_24h: number
  citation_errors_7d: number
  retrieval_misses_7d: number
  hedge_rate_7d: number             // regex-flagged answers / answers
  hedges_presented_7d?: number      // judge-confirmed misses only
  hedges_presented_rate_7d?: number
  message_limit_reached: number
  conversion_rate?: number
  cap_saturation_rate?: number
  support_tickets_open?: number
  survey_responses_7d?: number
  web_fallback_attempts_7d?: number
  web_fallback_surfaced_7d?: number
  web_fallback_surface_rate_7d?: number
  web_fallback_thumbs_up_7d?: number
  web_fallback_thumbs_down_7d?: number
  total_chunks: number
  chunks_by_source: Record<string, number>
}

// 2026-09-29 — GET /admin/dashboard
export interface WeekPoint {
  week_start: string
  signups: number
  active_users: number
  questions: number
  new_paying: number
}

export interface DashboardData {
  generated_at: string
  weeks: WeekPoint[]
  funnel: { signed_up: number; asked: number; returned: number; active_30d: number; paying: number }
  revenue: {
    mrr_cents: number
    paid_30d_cents: number
    paid_alltime_cents: number
    invoices: number
    last_payment_at: string | null
  }
  quality: {
    answers_7d: number
    hedged_7d: number
    judge_7d: Record<string, number>
    hedge_audits_new_7d: number
    hedge_audits_open: number
    open_audit_causes: Record<string, number>
  }
  attention: { trials_ending_7d: number }
  recent_signups: {
    id: string
    email: string
    full_name: string | null
    role: string | null
    created_at: string
    signup_source: string | null
    questions: number
  }[]
  recent_questions: {
    conversation_id: string
    user_email: string
    user_name: string | null
    preview: string
    created_at: string
  }[]
  recent_payments: {
    user_email: string
    amount_cents: number
    subscription_tier: string | null
    billing_interval: string | null
    paid_at: string
  }[]
}

export interface AdminUser {
  id: string
  email: string
  full_name: string | null
  role: string
  subscription_tier: string
  subscription_status: string
  billing_interval: string | null
  cancel_at_period_end: boolean
  current_period_end: string | null
  message_count: number
  vessel_count: number
  trial_ends_at: string | null
  created_at: string
  last_active_at: string | null
  is_admin: boolean
  // 2026-09-26 — first-touch attribution label
  signup_source?: string | null
}

export interface SentryIssue {
  id: string
  title: string
  level: string
  count: number
  first_seen: string | null
  last_seen: string
  permalink: string
  link: string  // legacy alias, same value as permalink
  project: string
}

export interface CitationError {
  id: string
  conversation_id: string
  unverified_citation: string
  model_used: string | null
  message_preview: string
  created_at: string
}

export interface SurveyResponse {
  id: string
  email: string
  full_name: string | null
  overall_rating: number
  usefulness: string | null
  favorite_feature: string | null
  missing_feature: string | null
  would_subscribe: boolean | null
  price_feedback: string | null
  vessel_type_used: string | null
  additional_comments: string | null
  created_at: string
}

export interface SurveyAggregates {
  total_responses: number
  average_rating: number
  would_subscribe_pct: number
  top_missing_feature: string | null
  responses: SurveyResponse[]
}

export interface TopCitation {
  source: string
  section_number: string
  section_title: string | null
  cite_count: number
}

export interface RoleUsage {
  role: string
  message_count: number
  user_count: number
}

export interface ModelUsageItem {
  model: string
  message_count: number
  total_input_tokens: number
  total_output_tokens: number
}

export interface SupportTicket {
  id: string
  user_id: string
  user_email: string
  user_name: string | null
  subject: string
  message: string
  status: 'open' | 'replied' | 'closed'
  admin_reply: string | null
  replied_at: string | null
  created_at: string
}

export interface AdminNotification {
  id: string
  title: string
  body: string
  notification_type: string
  source: string | null
  is_active: boolean
  created_at: string
}

export type Toast = { msg: string; ok: boolean } | null
