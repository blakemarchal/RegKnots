// Citation chips in answer text. From apps/web: `pnpm test`, i.e.
//   node --test --experimental-strip-types "src/**/*.test.mjs"
// Node 22.6+ loads parseMessage.ts directly; nothing to install.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { scanCitations, extractFooterCitations } from './parseMessage.ts'

/** The text as ChatMessage renders it, each chip written as [label]. */
function render(text) {
  let out = ''
  let last = 0
  for (const hit of scanCitations(text)) {
    out += text.slice(last, hit.index) + `[${hit.label}]`
    last = hit.index + hit.length
  }
  return out + text.slice(last)
}

/** Every "(" closed, in order, counting chip labels and plain text alike. */
function balanced(s) {
  let depth = 0
  for (const c of s) {
    if (c === '(') depth++
    if (c === ')' && --depth < 0) return false
  }
  return depth === 0
}

function expectRendered(pairs) {
  for (const [input, expected] of pairs) {
    const out = render(input)
    assert.equal(out, expected)
    assert.ok(balanced(out), `unbalanced: ${out}`)
  }
}

const sections = text => scanCitations(text).map(h => h.sectionNumber)

test('the 2026-09-29 answer: a wrapped citation with a paragraph', () => {
  // Rendered "first time [46 CFR 140.410](b)). The" before the fix.
  expectRendered([
    ['first time (46 CFR 140.410(b)). The', 'first time [46 CFR 140.410(b)]. The'],
    ['What the orientation must cover (46 CFR 140.410(b))',
      'What the orientation must cover [46 CFR 140.410(b)]'],
  ])
  const [hit] = scanCitations('first time (46 CFR 140.410(b)). The')
  assert.equal(hit.sectionNumber, '46 CFR 140.410')
  assert.equal(hit.sourceHint, 'cfr_46')
})

test('paragraph paths and ranges stay in the label; the chip opens the section', () => {
  expectRendered([
    ['(46 CFR 140.410(b)(1))', '[46 CFR 140.410(b)(1)]'],
    ['46 CFR 15.401(b)(1)(ii)(A) applies', '[46 CFR 15.401(b)(1)(ii)(A)] applies'],
    ['under 46 CFR 140.910(c)–(d), the', 'under [46 CFR 140.910(c)–(d)], the'],
    ['(46 CFR 140.910(c)-(d))', '[46 CFR 140.910(c)-(d)]'],
    ['(46 CFR 199.180(d)(1)–(3))', '[46 CFR 199.180(d)(1)–(3)]'],
  ])
  assert.deepEqual(
    sections('(46 CFR 140.410(b)(1)) and 46 CFR 140.910(c)–(d)'),
    ['46 CFR 140.410', '46 CFR 140.910'],
  )
})

test('citations without a paragraph, and punctuation after a chip', () => {
  expectRendered([
    ['stowed as required (46 CFR 199.261).', 'stowed as required [46 CFR 199.261].'],
    ['per 46 CFR 91.60-10, the master', 'per [46 CFR 91.60-10], the master'],
    ['(33 CFR 1.01-1);', '[33 CFR 1.01-1];'],
    ['33 CFR 153 applies.', '[33 CFR 153] applies.'],
    ['see 49 CFR 172.101.', 'see [49 CFR 172.101].'],
    ['required by 46 CFR 140.410.', 'required by [46 CFR 140.410].'],
  ])
  assert.deepEqual(scanCitations('see 49 CFR 172.101.').map(h => h.sourceHint), ['cfr_49'])
})

test('parentheses that do not wrap the whole citation stay in the text', () => {
  expectRendered([
    ['(see 46 CFR 140.410(b))', '(see [46 CFR 140.410(b)])'],
    ['(46 CFR 140.410(b), 140.420)', '([46 CFR 140.410(b)], 140.420)'],
    ['(46 CFR 140.410 and 33 CFR 164.01)', '([46 CFR 140.410] and [33 CFR 164.01])'],
    ['(46 CFR 140.410(a) or (b))', '([46 CFR 140.410(a)] or (b))'],
    // not a paragraph written onto the section
    ['46 CFR 140.410 (b)', '[46 CFR 140.410] (b)'],
    ['46 CFR 140.410(see below)', '[46 CFR 140.410](see below)'],
  ])
})

test('SOLAS and MARPOL chips leave parentheses in the text', () => {
  expectRendered([
    ['(SOLAS Ch.III Reg.20)', '([SOLAS Ch.III Reg.20])'],
    ['(SOLAS Chapter II-2, Regulation 10(b))', '([SOLAS Ch.II-2 Reg.10](b))'],
    ['(MARPOL Annex VI Reg.14.1)', '([MARPOL Annex VI Reg.14.1])'],
    // 2026-09-27: the letter suffix is part of the regulation
    ['MARPOL Annex I Regulation 12A(2)', '[MARPOL Annex I Regulation 12A](2)'],
  ])
})

test('the footer lists each section once, under the key the citation map uses', () => {
  const text = 'Orientation (46 CFR 140.410(b)) and drills (46 CFR 140.410(c)); see also 46 CFR 199.180.'
  const map = new Map([['46 CFR 140.410', { source: 'cfr_46', title: 'Safety orientation' }]])
  assert.deepEqual(extractFooterCitations(text, map), [
    { sectionNumber: '46 CFR 140.410', source: 'cfr_46', title: 'Safety orientation' },
    { sectionNumber: '46 CFR 199.180', source: 'cfr_46', title: '' },
  ])
})
