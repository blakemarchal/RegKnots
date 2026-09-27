/**
 * First-touch signup attribution (2026-09-26).
 *
 * None of the 64 external users had a recorded source, so there was no way
 * to tell which channel brought anyone in. On a visit we keep the UTM
 * parameters, an outreach code (?src=), a partner code (?ref=), the external
 * referrer and the landing path; registration sends them to the API
 * (users.signup_source / signup_attribution).
 *
 * The first campaign touch wins: a stored entry is replaced only when it has
 * no campaign code and this visit has one (someone who browsed in directly,
 * then clicked an outreach link, counts as outreach).
 *
 * Separate from `regknot_referral_source`, which carries a charity-partner
 * code to checkout and grants promo pricing.
 */

const KEY = 'rk_attribution'
const CAMPAIGN_PARAMS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'src', 'ref'] as const
const MAX_LEN = 120

type Field = (typeof CAMPAIGN_PARAMS)[number] | 'referrer_host' | 'landing_path' | 'first_seen_at'
export type Attribution = Partial<Record<Field, string>>

function hasCampaign(a: Attribution | null): boolean {
  return !!a && CAMPAIGN_PARAMS.some((p) => a[p])
}

export function readAttribution(): Attribution | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as Attribution) : null
  } catch {
    return null
  }
}

export function captureFirstTouch(): void {
  if (typeof window === 'undefined') return
  try {
    const url = new URL(window.location.href)
    const touch: Attribution = {}
    for (const p of CAMPAIGN_PARAMS) {
      const v = url.searchParams.get(p)
      if (v) touch[p] = v.slice(0, MAX_LEN)
    }
    const stored = readAttribution()
    if (stored && (hasCampaign(stored) || !hasCampaign(touch))) return

    if (document.referrer) {
      const host = new URL(document.referrer).host
      if (host && host !== window.location.host) touch.referrer_host = host.slice(0, MAX_LEN)
    }
    touch.landing_path = url.pathname.slice(0, MAX_LEN)
    touch.first_seen_at = new Date().toISOString()
    window.localStorage.setItem(KEY, JSON.stringify(touch))
  } catch {
    // storage blocked or a malformed referrer: no attribution for this visitor
  }
}
