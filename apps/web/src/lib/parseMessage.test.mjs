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

test('2026-09-30: chips for the inland / Coast Guard sources', () => {
  const hits = text => scanCitations(text).map(h => [h.sectionNumber, h.sourceHint])
  assert.deepEqual(hits('Per CG-CVC Policy Letter 23-05 CH-1 and CG-CVC PL 21-03, and CG-MMC PL 01-18.'), [
    ['CG-CVC PL 23-05 CH-1', 'uscg_cvc'],
    ['CG-CVC PL 21-03', 'uscg_cvc'],
    ['CG-MMC PL 01-18', 'nmc_policy'],
  ])
  assert.deepEqual(hits('CVC-WI-013(8), CG-CVC-WI-038, CVC-FM-840K and CG-MOC PL 99-002'), [
    ['CVC-WI-013', 'uscg_cvc'],
    ['CVC-WI-038', 'uscg_cvc'],
    ['CVC-FM-840K', 'uscg_cvc'],
    ['CG-MOC PL 99-002', 'uscg_cvc'],
  ])
  assert.deepEqual(hits('USCG SA 15-26, Marine Safety Alert 20-25 CH-1, USCG SA 10-10(b) and Finding of Concern 006-26'), [
    ['USCG SA 15-26', 'uscg_safety_alert'],
    ['USCG SA 20-25 CH-1', 'uscg_safety_alert'],
    ['USCG SA 10-10(b)', 'uscg_safety_alert'],
    ['USCG FOC 006-26', 'uscg_safety_alert'],
  ])
  assert.deepEqual(hits('See MCP-FM-NMC5-28 and the TOAR Western Rivers; Subchapter M FAQ Parts 1, 2 and 15; Sub M FAQ Part 138.'), [
    ['MCP-FM-NMC5-28', 'nmc_checklist'],
    ['TOAR Western Rivers', 'nmc_checklist'],
    ['Sub M FAQ Parts 1, 2 and 15', 'uscg_towing'],
    ['Sub M FAQ Part 138', 'uscg_towing'],
  ])
  assert.deepEqual(hits('COMDTINST M16721.48, Chapter 12 and COMDTINST M16721.48'), [
    ['COMDTINST M16721.48 Ch.12', 'uscg_msm'],
    ['COMDTINST M16721.48', 'uscg_msm'],
  ])
  assert.deepEqual(hits('EPA 2013 VGP 2.2.3, VGP Part 5.1, 2013 VGP Appendix A; the EPA VGP 2013 ended'), [
    ['EPA 2013 VGP 2.2.3', 'epa_vgp'],
    ['EPA 2013 VGP 5.1', 'epa_vgp'],
    ['EPA 2013 VGP App.A', 'epa_vgp'],
  ])
  assert.deepEqual(hits('Bowditch Art.1301, Bowditch Article 2405, Pub 1310 Ch.3 Sec.26, Pub. 102 Ch.2 Sec.1 and Pub 102 Appendix'), [
    ['Bowditch Art.1301', 'nga_pubs'],
    ['Bowditch Art.2405', 'nga_pubs'],
    ['Pub 1310 Ch.3 Sec.26', 'nga_pubs'],
    ['Pub 102 Ch.2 Sec.1', 'nga_pubs'],
    ['Pub 102 Appendix', 'nga_pubs'],
  ])
  assert.deepEqual(hits('40 CFR 139.21, 47 CFR 80.1085, 50 CFR 224.105, 29 CFR 1918.2 and 33 USC 1321'), [
    ['40 CFR 139.21', 'cfr_40'],
    ['47 CFR 80.1085', 'cfr_47'],
    ['50 CFR 224.105', 'cfr_50'],
    ['29 CFR 1918.2', 'cfr_29'],
    ['33 USC 1321', 'usc_33'],
  ])
})

test('2026-10-05: chips for the user own documents and the fleet company documents', () => {
  const hits = text => scanCitations(text).map(h => [h.sectionNumber, h.sourceHint])
  assert.deepEqual(hits('Your manual sets monthly drills [Doc: SMS Manual §8 Emergency Preparedness], stricter than [Company: TSMS Manual §4.2 Drills].'), [
    ['Doc: SMS Manual §8 Emergency Preparedness', 'doc'],
    ['Company: TSMS Manual §4.2 Drills', 'company'],
  ])
})
