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
