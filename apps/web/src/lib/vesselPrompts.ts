/**
 * Vessel-tailored starter prompts for the empty-chat state.
 *
 * Given a vessel profile (type, subchapter, routes, cargo), returns 4 context-aware
 * prompts that are more likely to convert a first session than generic ones.
 *
 * Deterministic client-side lookup — no LLM call, no network hop. Easy to tune without
 * a deploy: edit the bucket arrays below.
 */

export interface VesselProfileForPrompts {
  id: string
  name: string
  vessel_type: string
  subchapter: string | null
  route_types: string[]
  cargo_types: string[]
}

const GENERIC_PROMPTS = [
  'What fire safety equipment does my cargo vessel need?',
  'Explain COLREGs Rule 15 — crossing situations',
  'What SOLAS certificates need annual renewal?',
  'NVIC guidelines for ballast water management',
]

/**
 * Pick 4 prompts from the best-matching bucket for this vessel. Falls back to
 * generics if the profile doesn't match anything specific.
 */
export function getTailoredPrompts(vessel: VesselProfileForPrompts | null): {
  prompts: string[]
  tailored: boolean
} {
  if (!vessel) return { prompts: GENERIC_PROMPTS, tailored: false }

  const prompts = matchBucket(vessel)
  if (!prompts) return { prompts: GENERIC_PROMPTS, tailored: false }

  // Pad to 4 from generics if bucket is short, or truncate if long.
  const four = [...prompts]
  while (four.length < 4) four.push(GENERIC_PROMPTS[four.length])
  return { prompts: four.slice(0, 4), tailored: true }
}

function matchBucket(v: VesselProfileForPrompts): string[] | null {
  const t = v.vessel_type
  const sub = v.subchapter ?? ''
  const routes = v.route_types ?? []
  const cargo = v.cargo_types ?? []
  const inland = routes.includes('inland')
  const international = routes.includes('international')
  const carriesPassengers = cargo.includes('Passengers') || t === 'Passenger Vessel' || t === 'Ferry'
  const carriesOil = cargo.includes('Petroleum / Oil')
  const carriesChem = cargo.includes('Chemicals')
  const carriesGas = cargo.includes('Liquefied Gas')
  const carriesHaz = cargo.includes('Hazardous Materials')

  // ── Passenger / Ferry ────────────────────────────────────────────────
  if (carriesPassengers) {
    if (sub === 'T' || (inland && (t === 'Passenger Vessel' || t === 'Ferry'))) {
      return [
        `What manning do I need for ${v.name} on my current route?`,
        'Annual COI inspection prep checklist for small passenger vessels',
        'Lifejacket stowage and accessibility rules for my passenger count',
        'Drug & alcohol testing program requirements under 46 CFR Part 16',
      ]
    }
    if (sub === 'K') {
      return [
        `Subchapter K inspection prep for ${v.name}`,
        'Manning requirements for K-boats over 100 GT',
        'Emergency evacuation plan elements the USCG expects',
        'Subchapter K lifesaving equipment inventory',
      ]
    }
    if (sub === 'H' || international) {
      return [
        'SOLAS passenger ship certificate renewal timeline',
        `What emergency drills does ${v.name} need to log weekly?`,
        'ISM Code internal audit scope for passenger ships',
        'STCW endorsements required for passenger ship crew',
      ]
    }
    // Generic passenger fallback
    return [
      `Compliance priorities for ${v.name} in the next 30 days`,
      'Most common PSC deficiencies on passenger vessels',
      'Life raft servicing intervals and documentation',
      'Muster list requirements under 46 CFR',
    ]
  }

  // ── Tanker ───────────────────────────────────────────────────────────
  if (t === 'Tanker') {
    if (carriesOil) {
      return [
        `OPA 90 vessel response plan requirements for ${v.name}`,
        'MARPOL Annex I oil record book — what entries are mandatory?',
        'STCW tanker endorsements my crew needs for oil cargo',
        'Pre-transfer checklist for a tank barge loading oil',
      ]
    }
    if (carriesChem) {
      return [
        'IBC Code cargo compatibility rules',
        'MARPOL Annex II procedures and arrangements manual',
        'Chemical tanker STCW advanced endorsements',
        'USCG inspection prep for chemical tank vessels',
      ]
    }
    if (carriesGas) {
      return [
        'IGC Code safety equipment requirements',
        'LNG/LPG cargo handling training under STCW',
        'MARPOL Annex VI compliance for gas carriers',
        'Emergency shutdown system testing interval',
      ]
    }
    return [
      `USCG inspection prep for ${v.name}`,
      'MARPOL record book requirements by annex',
      'STCW tanker endorsements — officer-level',
      'Tank vessel pollution prevention plans',
    ]
  }

  // ── Towing / Tugboat ─────────────────────────────────────────────────
  if (t === 'Towing / Tugboat') {
    return [
      `Subchapter M TSMS requirements for ${v.name}`,
      'Towing vessel annual survey preparation checklist',
      'Drug & alcohol testing under 46 CFR Part 16 for tugs',
      'Subchapter M crewmember documentation — what USCG checks',
    ]
  }

  // ── OSV ──────────────────────────────────────────────────────────────
  if (t === 'OSV / Offshore Support') {
    return [
      `Subchapter L manning rules for ${v.name}`,
      'OSV STCW endorsements — what my crew needs',
      'USCG inspection prep for offshore supply vessels',
      'DP operator certification requirements',
    ]
  }

  // ── Containership ────────────────────────────────────────────────────
  if (t === 'Containership') {
    return [
      `SOLAS container weight verification (VGM) rules for ${v.name}`,
      'IMDG Code declaration and stowage for hazmat containers',
      'ISM Code internal audit scope for a containership',
      'USCG PSC priorities for container vessels',
    ]
  }

  // ── Bulk Carrier ─────────────────────────────────────────────────────
  if (t === 'Bulk Carrier') {
    return [
      'IMSBC Code cargo declaration requirements',
      `Hold inspection prep for ${v.name} before grain loading`,
      'SOLAS Chapter XII structural requirements',
      'Most common PSC deficiencies on bulkers',
    ]
  }

  // ── Fish Processing ──────────────────────────────────────────────────
  if (t === 'Fish Processing') {
    return [
      `Fish processing vessel safety requirements for ${v.name}`,
      'Commercial fishing industry vessel safety act compliance',
      'Stability instructions for a fish processor',
      'Onboard safety equipment — USCG Fish Vessel exam',
    ]
  }

  // ── Research ─────────────────────────────────────────────────────────
  if (t === 'Research Vessel') {
    return [
      `Oceanographic research vessel (ORV) compliance for ${v.name}`,
      'STCW manning for research vessels under 46 CFR',
      'Science personnel vs. crew — manning rule differences',
      'USCG inspection scope for research vessels',
    ]
  }

  // ── Hazmat fallback (any vessel carrying hazmat without a type-specific bucket) ─
  if (carriesHaz) {
    return [
      `IMDG Code documentation requirements for ${v.name}`,
      'CFR 176 regulations for hazmat on vessels',
      'Emergency response resources for hazmat incidents (ERG)',
      'Hazmat crew training under 49 CFR',
    ]
  }

  return null
}
