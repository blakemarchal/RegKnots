// The PostHog URL scrubber (src/lib/analytics.ts). From apps/web: `pnpm test`.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { scrubEventProperties, scrubUrl } from './analytics.ts'

test('keeps campaign parameters and drops everything else', () => {
  assert.equal(
    scrubUrl('https://regknots.com/register?next=/workspaces&src=ob-0042&utm_source=email&email=a@b.c#x'),
    'https://regknots.com/register?src=ob-0042&utm_source=email',
  )
  assert.equal(scrubUrl('https://regknots.com/reset-password?token=abc123'), 'https://regknots.com/reset-password')
  assert.equal(scrubUrl('https://regknots.com/verify-email?token=abc'), 'https://regknots.com/verify-email')
})

test('masks secrets and private ids in the path', () => {
  assert.equal(scrubUrl('https://regknots.com/invite/tok_SECRET'), 'https://regknots.com/invite/:id')
  assert.equal(scrubUrl('https://regknots.com/shared/abc?x=1'), 'https://regknots.com/shared/:id')
  assert.equal(scrubUrl('https://regknots.com/workspaces/5f1c/settings'), 'https://regknots.com/workspaces/:id/settings')
  assert.equal(scrubUrl('https://regknots.com/practice'), 'https://regknots.com/practice')
  assert.equal(scrubUrl('not a url'), '')
  assert.equal(scrubUrl(undefined), '')
})

test('scrubs an event in place', () => {
  const props = {
    $current_url: 'https://regknots.com/invite/SECRET?token=1',
    $referrer: 'https://www.google.com/search?q=46+cfr+142',
    $initial_referrer: '$direct',
    $pathname: '/invite/SECRET',
    other: 'kept',
  }
  scrubEventProperties(props)
  assert.deepEqual(props, {
    $current_url: 'https://regknots.com/invite/:id',
    $referrer: 'https://www.google.com/search',
    $initial_referrer: '$direct',
    $pathname: '/invite/:id',
    other: 'kept',
  })
})

test('Sentry events lose tokens, bodies and emails', async () => {
  const { scrubSentryEvent } = await import('./sentryScrub.ts')
  const event = {
    request: {
      url: 'https://regknots.com/reset-password?token=SECRET', query_string: 'token=SECRET',
      data: '{"password":"x"}', cookies: { refresh_token: 'r' },
      headers: { Cookie: 'refresh_token=r', Authorization: 'Bearer t', 'User-Agent': 'UA' },
    },
    user: { id: 'u1', email: 'a@b.c' },
    breadcrumbs: [{ category: 'navigation', data: { from: '/invite/TOKEN', to: 'https://regknots.com/shared/ABC?x=1' } }],
  }
  scrubSentryEvent(event)
  assert.equal(event.request.url, 'https://regknots.com/reset-password')
  assert.equal(event.request.query_string, undefined)
  assert.equal(event.request.data, undefined)
  assert.equal(event.request.cookies, undefined)
  assert.deepEqual(event.request.headers, { 'User-Agent': 'UA' })
  assert.deepEqual(event.user, { id: 'u1' })
  assert.equal(event.breadcrumbs[0].data.from, '/invite/:id')   // relative paths are masked too
  assert.equal(event.breadcrumbs[0].data.to, 'https://regknots.com/shared/:id')
})
