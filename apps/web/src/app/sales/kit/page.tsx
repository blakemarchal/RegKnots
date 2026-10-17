'use client'

// 2026-10-16 — the salesperson's kit: the link, the codes, the pitch, the
// one-pager, and where to send people. The long form lives in docs/sales/.

import { useSales } from '../layout'

export default function SalesKit() {
  const { me } = useSales()
  const link = me ? `https://${me.short_link}` : ''
  return (
    <div className="space-y-8 font-mono text-sm text-[#f0ece4]/85 leading-relaxed">
      <section>
        <h2 className="font-display text-xl font-bold text-[#f0ece4] mb-2">The link and the codes</h2>
        <ul className="list-disc pl-5 space-y-1">
          <li>Your link: <code className="text-[#2dd4bf]">{me?.short_link ?? '…'}</code>{me?.trial_days ? ` (${me.trial_days} days free, no card)` : ''}</li>
          <li>Fleet rates at checkout: <code className="text-[#2dd4bf]">FLEET5</code> for 5 to 9 boats ($89.99/boat/mo), <code className="text-[#2dd4bf]">FLEET10</code> for 10 or more ($79.99). 1 to 4 boats are $99.99. Annual is about 10% less.</li>
          <li>Bigger fleets, or one invoice for the whole company: hello@regknots.com and we quote it.</li>
        </ul>
      </section>
      <section>
        <h2 className="font-display text-xl font-bold text-[#f0ece4] mb-2">The pitch, in one breath</h2>
        <p className="rounded-xl border border-[#2dd4bf]/30 bg-[#0d1225] p-4">
          &ldquo;Your crew gets a cited answer in thirty seconds instead of a guess. Your TSMS lives in the same chat. And the audit log shows the TPO that your people are actually using it. First boat free, no card, set up in ten minutes.&rdquo;
        </p>
      </section>
      <section>
        <h2 className="font-display text-xl font-bold text-[#f0ece4] mb-2">What to send</h2>
        <ul className="list-disc pl-5 space-y-1">
          <li><a className="text-[#2dd4bf] hover:underline" href="/sales/RegKnot-for-fleets.pdf" target="_blank" rel="noopener noreferrer">The fleet one-pager (PDF)</a>, after the first call.</li>
          <li>A prospect who wants to try it first: <a className="text-[#2dd4bf] hover:underline" href={link}>{me?.short_link}</a>. One who wants to read first: <a className="text-[#2dd4bf] hover:underline" href="/regs" target="_blank">regknots.com/regs</a>.</li>
          <li>Anyone who wants to hear it from the captain: <code className="text-[#2dd4bf]">captain@regknots.com</code> reaches Karynn directly.</li>
          <li>The ads (45 s and two 15 s cuts): Blake has the files.</li>
        </ul>
      </section>
      <section>
        <h2 className="font-display text-xl font-bold text-[#f0ece4] mb-2">Who to talk to</h2>
        <p>Subchapter M towing companies with 3 to 30 boats: the owner, the safety manager or the DPA. The fastest way in is whoever already knows them: marine insurance brokers and underwriters, the TPOs that audit them, maritime lawyers and surveyors, towing associations, training schools.</p>
      </section>
      <section>
        <h2 className="font-display text-xl font-bold text-[#f0ece4] mb-2">Two answers you can quote</h2>
        <ul className="list-disc pl-5 space-y-2">
          <li><b>Does a new deckhand need a safety orientation before we get underway?</b> Yes: ten topics, logged with names and signatures, before the boat first gets underway (46 CFR 140.410).</li>
          <li><b>What records does a Subchapter M towboat have to keep?</b> Ten kinds, in the Towing Vessel Record, the logbook or the TSMS (46 CFR 140.915).</li>
        </ul>
        <p className="text-[#8a94ad] mt-2">Never answer a regulatory question yourself on a call. Put it into RegKnot and read the answer, or offer to send it.</p>
      </section>
      <section>
        <h2 className="font-display text-xl font-bold text-[#f0ece4] mb-2">How you get paid</h2>
        <p>25% of what a fleet you brought in pays us, for as long as it pays, monthly as the money arrives. The Overview tab shows what your accounts have paid so far.</p>
      </section>
    </div>
  )
}
