// 2026-10-16 security review — what leaves the browser / web server for Sentry.
// The SDK's defaults already omit cookies and IPs (sendDefaultPii is off);
// this removes what they don't: tokens in page addresses (/reset-password?
// token=…, /invite/<token>), request bodies, and the user's email. URLs go
// through the same scrubber as analytics (lib/analytics.ts scrubUrl).

// .ts extension: the node:test runner (pnpm test) loads this file directly.
import { scrubUrl } from './analytics.ts'

type Obj = Record<string, unknown>

function cleanUrl(value: unknown): unknown {
  if (typeof value !== 'string' || !value) return value
  if (value.startsWith('/')) {          // a path: mask it like a full URL, keep it relative
    const scrubbed = scrubUrl(`https://relative.invalid${value}`)
    return scrubbed ? scrubbed.slice('https://relative.invalid'.length) : value.split(/[?#]/)[0]
  }
  return scrubUrl(value) || value.split(/[?#]/)[0]
}

export function scrubSentryEvent<E>(event: E): E {
  const e = event as unknown as Obj
  const request = e.request as Obj | undefined
  if (request) {
    request.url = cleanUrl(request.url)
    delete request.query_string
    delete request.cookies
    delete request.data
    const headers = request.headers as Obj | undefined
    if (headers) {
      for (const key of Object.keys(headers)) {
        if (/^(cookie|authorization|referer|x-forwarded-for)$/i.test(key)) delete headers[key]
      }
    }
  }
  const user = e.user as Obj | undefined
  if (user) e.user = user.id ? { id: user.id } : undefined
  const breadcrumbs = e.breadcrumbs as Obj[] | undefined
  if (Array.isArray(breadcrumbs)) breadcrumbs.forEach(scrubSentryBreadcrumb)
  return event
}

export function scrubSentryBreadcrumb<B>(breadcrumb: B): B {
  const data = (breadcrumb as unknown as Obj).data as Obj | undefined
  if (data) {
    for (const key of ['url', 'from', 'to']) {
      if (key in data) data[key] = cleanUrl(data[key])
    }
  }
  return breadcrumb
}
