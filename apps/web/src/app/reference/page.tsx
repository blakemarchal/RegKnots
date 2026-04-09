import type { Metadata } from 'next'
import Link from 'next/link'
import { OfflineIndicator } from '@/components/OfflineIndicator'
import { ReferenceAccordion } from './ReferenceAccordion'

export const metadata: Metadata = {
  title: 'Quick Reference — RegKnot',
  description:
    'Offline-available paraphrased summaries of COLREGs rules and key CFR maritime definitions.',
}

// ── Content ────────────────────────────────────────────────────────────────────
// All summaries below are ORIGINAL paraphrases written for quick reference.
// They are NOT verbatim reproductions of the COLREGs treaty text or the CFR.
// Always consult the authoritative source for compliance decisions.

interface RuleItem {
  n: string
  title: string
  summary: string
}

const COLREGS: RuleItem[] = [
  {
    n: '1',
    title: 'Application',
    summary:
      'Applies to all vessels on the high seas and connecting waters navigable by seagoing vessels. Special rules made by an appropriate authority for harbors, rivers, or inland waterways take precedence for those waters.',
  },
  {
    n: '2',
    title: 'Responsibility',
    summary:
      'Nothing in these rules exonerates a vessel, owner, master, or crew from the consequences of neglecting the rules or ordinary seamanship. Departure from the rules is allowed only when necessary to avoid immediate danger.',
  },
  {
    n: '3',
    title: 'General Definitions',
    summary:
      '"Vessel" covers any watercraft used or capable of being used as a means of transport on water, including non-displacement craft and seaplanes. "Power-driven" means propelled by machinery; "sailing" means under sail with any machinery not in use. "Not under command" covers vessels unable to maneuver due to exceptional circumstances; "restricted in ability to maneuver" covers those limited by the nature of their work. "Constrained by draft" is a power-driven vessel severely restricted by depth relative to available water. "Underway" means not at anchor, made fast to shore, or aground; "making way" means underway and actually moving through the water. Length and breadth refer to the vessel&rsquo;s overall length and greatest breadth.',
  },
  {
    n: '4',
    title: 'Application (Part B)',
    summary:
      'The steering and sailing rules in Part B apply in any condition of visibility.',
  },
  {
    n: '5',
    title: 'Look-out',
    summary:
      'Every vessel must at all times keep a proper look-out by sight, hearing, and all available means appropriate to the prevailing circumstances so as to make a full appraisal of the situation and the risk of collision.',
  },
  {
    n: '6',
    title: 'Safe Speed',
    summary:
      'Every vessel must proceed at a speed that allows proper and effective action to avoid collision and stop within a distance appropriate to the circumstances. Factors include visibility, traffic density, maneuverability, background lights at night, weather, draft relative to depth, and (for radar-equipped vessels) the characteristics and limitations of the radar.',
  },
  {
    n: '7',
    title: 'Risk of Collision',
    summary:
      'Every vessel must use all available means appropriate to the prevailing circumstances to determine if risk of collision exists. If in doubt, assume it does. Proper use of radar, systematic observation, and compass bearings of approaching vessels are required &mdash; risk is considered to exist if the bearing does not appreciably change.',
  },
  {
    n: '8',
    title: 'Action to Avoid Collision',
    summary:
      'Any action taken to avoid collision must be positive, made in ample time, and consistent with good seamanship. Alterations of course and/or speed should be large enough to be readily apparent. If necessary, slacken speed, stop, or reverse propulsion.',
  },
  {
    n: '9',
    title: 'Narrow Channels',
    summary:
      'A vessel proceeding along a narrow channel or fairway must keep as near the outer limit on its starboard side as is safe and practicable. Vessels under 20 meters, sailing vessels, fishing vessels, and those crossing must not impede the passage of a vessel that can safely navigate only within the channel.',
  },
  {
    n: '10',
    title: 'Traffic Separation Schemes',
    summary:
      'Vessels using a traffic separation scheme must proceed in the appropriate lane in the general direction of traffic flow, keep clear of the separation line or zone, and normally join or leave at the termini (or at a small angle if joining from the side). Vessels not using the scheme should avoid it by as wide a margin as practicable.',
  },
  {
    n: '11',
    title: 'Application (Part C)',
    summary:
      'Section II of Part B (rules for vessels in sight of one another) applies only when vessels are visible to each other.',
  },
  {
    n: '12',
    title: 'Sailing Vessels',
    summary:
      'When two sailing vessels approach with risk of collision: the vessel with wind on the port side gives way to the one with wind on the starboard side. If both have wind on the same side, the windward vessel gives way to the leeward. If a vessel with wind on port sees a windward vessel and cannot determine which tack it is on, it gives way.',
  },
  {
    n: '13',
    title: 'Overtaking',
    summary:
      'A vessel overtaking another must keep out of the way of the overtaken vessel, regardless of any other rule. A vessel is overtaking when coming up from a direction more than 22.5 degrees abaft the beam of the other vessel. Any subsequent change of bearing does not relieve the overtaking vessel of this duty.',
  },
  {
    n: '14',
    title: 'Head-on Situation',
    summary:
      'When two power-driven vessels meet on reciprocal or nearly reciprocal courses with risk of collision, each must alter course to starboard so that both pass on the port side of the other. If in any doubt, assume the situation exists.',
  },
  {
    n: '15',
    title: 'Crossing Situation',
    summary:
      'When two power-driven vessels are crossing with risk of collision, the vessel that has the other on her own starboard side is the give-way vessel and must keep out of the way. The give-way vessel should, if the circumstances allow, avoid crossing ahead of the other.',
  },
  {
    n: '16',
    title: 'Action by Give-way Vessel',
    summary:
      'A vessel directed to keep out of the way of another must, so far as possible, take early and substantial action to keep well clear.',
  },
  {
    n: '17',
    title: 'Action by Stand-on Vessel',
    summary:
      'The stand-on vessel must keep her course and speed, but may take action to avoid collision by her maneuver alone as soon as it becomes apparent the give-way vessel is not taking appropriate action. When so close that collision cannot be avoided by the give-way vessel alone, the stand-on vessel must take the best action to avoid collision.',
  },
  {
    n: '18',
    title: 'Responsibilities Between Vessels',
    summary:
      'Establishes the priority of who gives way. A power-driven vessel keeps out of the way of vessels not under command, vessels restricted in their ability to maneuver, vessels engaged in fishing, and sailing vessels. A sailing vessel keeps out of the way of vessels not under command, restricted in ability to maneuver, and engaged in fishing. Vessels engaged in fishing, when underway, must so far as possible keep clear of vessels not under command or restricted in ability to maneuver.',
  },
  {
    n: '19',
    title: 'Conduct in Restricted Visibility',
    summary:
      'In or near areas of restricted visibility, every vessel must proceed at a safe speed adapted to the circumstances, with engines ready for immediate maneuver. When detecting another vessel by radar alone, take early avoiding action; in particular, avoid an alteration of course to port for a vessel forward of the beam (other than one being overtaken), and avoid an alteration of course toward a vessel abeam or abaft the beam.',
  },
]

interface CfrItem {
  citation: string
  title: string
  summary: string
}

const CFR_ITEMS: CfrItem[] = [
  {
    citation: '46 CFR 2.01-7',
    title: 'Deadweight tonnage',
    summary:
      'Defines deadweight as the difference between a vessel&rsquo;s loaded and lightweight displacement &mdash; expressed in long tons, it represents the cargo, fuel, stores, crew, and supplies the vessel can actually carry.',
  },
  {
    citation: '46 CFR 67.3',
    title: 'Documented vessel',
    summary:
      'A documented vessel is one that holds a valid Certificate of Documentation issued by the Coast Guard National Vessel Documentation Center under Title 46.',
  },
  {
    citation: '46 CFR 175.400',
    title: 'Passenger vessel capacity thresholds (under 100 GT)',
    summary:
      'Subchapter T divides small passenger vessels into capacity tiers (6 or fewer passengers, up to 150, etc.) that drive which inspection, stability, and equipment requirements apply to the vessel.',
  },
  {
    citation: '46 CFR 180.210',
    title: 'Life preserver requirements',
    summary:
      'Small passenger vessels must carry a Coast Guard approved life preserver for every person on board. When children are carried, a sufficient number must be sized for children.',
  },
  {
    citation: '33 CFR 83.03',
    title: 'Inland Rules general definitions',
    summary:
      'Provides the Inland Navigation Rules definitions (vessel, power-driven, sailing, underway, length/breadth, and the various special-status vessels). Mirrors COLREGs Rule 3 with US-specific additions such as "Western Rivers" and "Great Lakes" exceptions.',
  },
  {
    citation: '33 CFR 164.01',
    title: 'Navigation safety equipment applicability',
    summary:
      'Sets out which vessels (generally self-propelled commercial vessels of 1,600 gross tons or more in US navigable waters) must comply with the bridge navigation equipment, charts, publications, and watchkeeping requirements of Part 164.',
  },
  {
    citation: '33 CFR 26.03',
    title: 'Bridge-to-bridge radiotelephone',
    summary:
      'Power-driven vessels 20 meters or more in length, commercial vessels 26 feet or more carrying passengers for hire, dredges and floating plants in or near a channel, and towing vessels 26 feet or more must maintain a listening watch on the designated bridge-to-bridge VHF channel while navigating.',
  },
  {
    citation: '46 CFR 15.812',
    title: 'Able seaman requirements',
    summary:
      'Specifies the minimum proportion of the deck crew on inspected vessels who must hold an Able Seaman endorsement, with the required ratio depending on vessel size, route, and service.',
  },
]

// ── Page ───────────────────────────────────────────────────────────────────────

export default function ReferencePage() {
  return (
    <div className="min-h-screen bg-[#0a0e1a] text-[#f0ece4]">
      {/* Simple top bar — avoids pulling in the auth-dependent AppHeader so
          this page stays fully static and available offline. */}
      <header className="border-b border-white/8 bg-[#111827]/95 backdrop-blur-md">
        <div className="max-w-3xl mx-auto flex items-center justify-between px-5 py-4">
          <div className="flex items-center gap-2">
            <Link href="/" className="flex items-center gap-2.5 group">
              <svg
                className="w-6 h-6 text-[#2dd4bf] flex-shrink-0"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                aria-hidden="true"
              >
                <circle cx="12" cy="12" r="10" />
                <path d="M12 2v4M12 18v4M2 12h4M18 12h4" strokeLinecap="round" />
                <path d="M12 8l1.5 3.5L12 16l-1.5-4.5L12 8z" fill="currentColor" stroke="none" />
              </svg>
              <span className="font-display text-xl font-bold tracking-wide leading-none
                group-hover:text-[#2dd4bf] transition-colors duration-150">
                RegKnot
              </span>
            </Link>
            <OfflineIndicator />
          </div>
          <Link
            href="/"
            className="font-mono text-xs text-[#6b7594] hover:text-[#f0ece4]/80 transition-colors"
          >
            &larr; Back
          </Link>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-5 py-10 md:py-14">
        <div className="mb-8">
          <h1 className="font-display text-3xl md:text-4xl font-black tracking-tight">
            Quick <span className="text-[#2dd4bf]">Reference</span>
          </h1>
          <p className="font-mono text-xs text-[#6b7594] mt-2 leading-relaxed">
            Key rules available offline. Always current as of last app update.
          </p>
        </div>

        {/* Disclaimer — teal-bordered info box */}
        <div className="mb-8 rounded-xl border border-[#2dd4bf]/30 bg-[#2dd4bf]/5 px-4 py-3">
          <p className="font-mono text-xs text-[#f0ece4]/90 leading-relaxed">
            This quick reference contains paraphrased summaries for general guidance only.
            Always consult the authoritative source for compliance decisions.{' '}
            <span className="text-[#6b7594]">Not legal advice.</span>
          </p>
        </div>

        <div className="flex flex-col gap-4">
          {/* ── Section 1: COLREGs ─────────────────────────────────────── */}
          <ReferenceAccordion title="COLREGs: Rules of the Road" defaultOpen>
            <ol className="flex flex-col gap-4 mt-3">
              {COLREGS.map(rule => (
                <li key={rule.n} className="flex flex-col gap-1">
                  <p className="font-display text-sm font-bold text-[#2dd4bf] tracking-wide">
                    Rule {rule.n} &mdash; {rule.title}
                  </p>
                  <p
                    className="font-mono text-xs text-[#f0ece4]/85 leading-relaxed"
                    dangerouslySetInnerHTML={{ __html: rule.summary }}
                  />
                </li>
              ))}
            </ol>
          </ReferenceAccordion>

          {/* ── Section 2: Key CFR Definitions & Thresholds ─────────────── */}
          <ReferenceAccordion title="Key CFR Definitions & Thresholds">
            <ul className="flex flex-col gap-4 mt-3">
              {CFR_ITEMS.map(item => (
                <li key={item.citation} className="flex flex-col gap-1">
                  <p className="font-display text-sm font-bold text-[#2dd4bf] tracking-wide">
                    {item.citation}
                    <span className="text-[#f0ece4]/70 font-normal">
                      {' '}&mdash; {item.title}
                    </span>
                  </p>
                  <p
                    className="font-mono text-xs text-[#f0ece4]/85 leading-relaxed"
                    dangerouslySetInnerHTML={{ __html: item.summary }}
                  />
                </li>
              ))}
            </ul>
          </ReferenceAccordion>
        </div>

        <p className="font-mono text-[10px] text-[#6b7594]/70 text-center mt-10 leading-relaxed">
          Navigation aid only &mdash; not legal advice. Cached locally for offline use.
        </p>
      </main>
    </div>
  )
}
