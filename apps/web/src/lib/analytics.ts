/**
 * Product analytics (2026-10-14): PostHog, configured to set no cookies.
 *
 * Off unless NEXT_PUBLIC_POSTHOG_KEY is set at build time. When on:
 * persistence in localStorage (no cookies), Do Not Track respected, no
 * autocapture, no session recording, person profiles only for signed-in
 * users, and every URL scrubbed before it leaves the browser (scrubUrl):
 * only campaign parameters survive, and tokens in a path are masked.
 * The funnel events themselves (signup, first_question, paywall_hit,
 * checkout_*) are sent by the API (app/events.py) under the same user id.
 */

export const POSTHOG_KEY = process.env.NEXT_PUBLIC_POSTHOG_KEY ?? ''
export const POSTHOG_HOST = process.env.NEXT_PUBLIC_POSTHOG_HOST || 'https://us.i.posthog.com'

const KEEP_PARAMS = new Set([
  'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'src', 'ref',
])
// Path segments that are secrets or private ids: /invite/<token>, /shared/<token>,
// /study/<id>, /workspaces/<id>, /account/vessel/<id>, /admin/chat-preview/<id>.
const MASKED = [
  /^(\/invite\/)[^/?#]+/,
  /^(\/shared\/)[^/?#]+/,
  /^(\/study\/)[^/?#]+/,
  /^(\/workspaces\/)[^/?#]+/,
  /^(\/account\/vessel\/)[^/?#]+/,
  /^(\/admin\/chat-preview\/)[^/?#]+/,
]

/** The URL with only campaign parameters kept, no fragment, and private path
 * segments replaced by ":id". Unparseable input comes back empty. */
export function scrubUrl(raw: string | undefined | null): string {
  if (!raw) return ''
  let url: URL
  try {
    url = new URL(raw)
  } catch {
    return ''
  }
  for (const key of [...url.searchParams.keys()]) {
    if (!KEEP_PARAMS.has(key)) url.searchParams.delete(key)
  }
  url.hash = ''
  for (const re of MASKED) {
    if (re.test(url.pathname)) {
      url.pathname = url.pathname.replace(re, '$1:id')
      break
    }
  }
  return url.toString()
}

const URL_PROPS = ['$current_url', '$referrer', '$initial_referrer', '$initial_current_url', '$prev_pageview_url']
const PATH_PROPS = ['$pathname', '$prev_pageview_pathname']

/** Scrub every URL-like property of an outgoing event in place. */
export function scrubEventProperties(props: Record<string, unknown> | undefined): void {
  if (!props) return
  for (const key of URL_PROPS) {
    if (typeof props[key] === 'string' && props[key] !== '$direct') {
      props[key] = scrubUrl(props[key] as string) || null
    }
  }
  for (const key of PATH_PROPS) {
    if (typeof props[key] === 'string') {
      const path = new URL(scrubUrl(`https://x${props[key] as string}`) || 'https://x/').pathname
      props[key] = path
    }
  }
}
