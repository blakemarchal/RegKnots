// Sprint D6.15 — single source of truth for the regulation corpus.
//
// The list of regs RegKnot indexes appears on /landing, /pricing,
// /womenoffshore, /captainkarynn, /ass, plus various inline copy.
// Maintaining the same string in 5+ places drifts as we add sources
// (we already shipped MARPOL/IMDG/USC 46/etc. without updating the
// landing copy). This component is the canonical render point.
//
// Two modes:
//   categorized — three-bucket chip cloud (international / U.S. federal
//                 / reference). Use as a dedicated "what we know"
//                 section on landing pages.
//   inline      — prose string for hero subheads and body copy.

interface CorpusSource {
  short: string
  full: string
  category: 'international' | 'us_federal' | 'flag_state' | 'reference'
  url?: string
  /** ISO 3166-1 alpha-2 country code; used to render the flag inside
   *  flag_state chips. SVGs live in /brand/flags/<flagCC>.svg. */
  flagCC?: string
}

// Adding a new source: drop a row in here. Both modes auto-pick it up.
const CORPUS: CorpusSource[] = [
  // ── International conventions (IMO + WHO) ─────────────────────────────
  {
    short: 'SOLAS',
    full: 'International Convention for the Safety of Life at Sea',
    category: 'international',
    url: 'https://www.imo.org/en/About/Conventions/Pages/International-Convention-for-the-Safety-of-Life-at-Sea-(SOLAS),-1974.aspx',
  },
  {
    short: 'MARPOL',
    full: 'International Convention for the Prevention of Pollution from Ships',
    category: 'international',
    url: 'https://www.imo.org/en/About/Conventions/Pages/International-Convention-for-the-Prevention-of-Pollution-from-Ships-(MARPOL).aspx',
  },
  {
    short: 'IMDG Code',
    full: 'International Maritime Dangerous Goods Code',
    category: 'international',
    url: 'https://www.imo.org/en/OurWork/Safety/Pages/DangerousGoods-default.aspx',
  },
  {
    short: 'COLREGs',
    full: 'International Regulations for Preventing Collisions at Sea',
    category: 'international',
    url: 'https://www.imo.org/en/About/Conventions/Pages/COLREG.aspx',
  },
  {
    short: 'STCW',
    full: 'Standards of Training, Certification and Watchkeeping for Seafarers',
    category: 'international',
    url: 'https://www.imo.org/en/OurWork/HumanElement/Pages/STCW-Convention.aspx',
  },
  {
    short: 'ISM Code',
    full: 'International Safety Management Code',
    category: 'international',
    url: 'https://www.imo.org/en/OurWork/HumanElement/Pages/ISMCode.aspx',
  },
  {
    short: 'HSC Code',
    full: 'International Code of Safety for High-Speed Craft (HSC Code 2000)',
    category: 'international',
    url: 'https://www.imo.org/en/OurWork/Safety/Pages/HSC.aspx',
  },
  {
    short: 'IGC Code',
    full: 'International Code for the Construction and Equipment of Ships Carrying Liquefied Gases in Bulk',
    category: 'international',
    url: 'https://www.imo.org/en/OurWork/Safety/Pages/IGC-Code.aspx',
  },
  {
    short: 'IBC Code',
    full: 'International Bulk Chemicals Code',
    category: 'international',
  },
  {
    short: 'CSS Code',
    full: 'Code of Safe Practice for Cargo Stowage and Securing',
    category: 'international',
  },
  // Sprint D6.41 — three IMO instruments added per the post-D6.36 corpus
  // gap audit. BWM Convention is paywalled at the IMO consolidated text
  // level, but the operational MEPC resolutions (D-1/D-2 standards, BWMS
  // Code, biofouling guidelines, PSC sampling) are all free and ingested.
  {
    short: 'BWM',
    full: 'Ballast Water Management Convention (via implementing MEPC resolutions: BWMS Code, D-1/D-2 standards, biofouling guidelines)',
    category: 'international',
    url: 'https://www.imo.org/en/About/Conventions/Pages/International-Convention-for-the-Control-and-Management-of-Ships%27-Ballast-Water-and-Sediments-(BWM).aspx',
  },
  {
    short: 'Polar Code',
    full: 'International Code for Ships Operating in Polar Waters (Polar Code) — MSC.385/.386 + MEPC.264/.265',
    category: 'international',
    url: 'https://www.imo.org/en/MediaCentre/HotTopics/polar/Pages/default.aspx',
  },
  {
    short: 'IGF Code',
    full: 'International Code of Safety for Ships using Gases or Other Low-flashpoint Fuels (IGF Code) — MSC.391 + MSC.392',
    category: 'international',
    url: 'https://www.imo.org/en/OurWork/Safety/Pages/IGF-Code.aspx',
  },
  // Sprint D6.36 — "Load Lines" temporarily removed from advertising.
  // We have 4 chunks (MSC.375(93) 2014 amendments only); the 1966
  // Convention + 1988 Protocol consolidated text isn't freely available
  // online and the ingest can't yet stand behind a "Load Lines" chip
  // claim. Re-add when we source the consolidated edition.
  {
    short: 'IACS PR',
    full: 'IACS Procedural Requirements (PR series) — class-society procedures for class entry, transfer of class, surveys, member audits, casualty investigation',
    category: 'international',
    url: 'https://iacs.org.uk/resolutions/procedural-requirements',
  },
  {
    short: 'IACS UR',
    full: 'IACS Unified Requirements (technical class-society standards)',
    category: 'international',
    url: 'https://iacs.org.uk/resolutions/unified-requirements',
  },
  // Sprint D6.93 — first per-society class rule books on top of the
  // IACS umbrella standards. ABS (~70% of U.S.-flag commercial vessels)
  // and Lloyd's Register (LR-CO-001 lifting code + LR-RU-001 full
  // classification rules). DNV/BV/ClassNK are deferred — they don't
  // publish freely scrapable rule sets (DNV needs an authenticated
  // browser session, BV/ClassNK gate behind member portals).
  {
    short: 'ABS Rules',
    full: 'American Bureau of Shipping — Rules for Building and Classing Marine Vessels (hull, machinery, electrical, surveys, vessel-type-specific construction)',
    category: 'international',
    url: 'https://ww2.eagle.org/en/rules-and-resources/rules-and-guides.html',
  },
  {
    short: 'LR Rules',
    full: "Lloyd's Register — Rules and Regulations for the Classification of Ships (LR-RU-001) plus Code for Lifting Appliances in a Marine Environment (LR-CO-001)",
    category: 'international',
    url: 'https://www.lr.org/en/rules-and-regulations/',
  },

  // ── Non-U.S. flag-state regulators ────────────────────────────────────
  // Sprint D6.26 — flagCC drives a small flag chip rendered inside each
  // chip so users can scan the section by country at a glance.
  {
    short: 'UK MCA',
    full: 'UK Maritime and Coastguard Agency — Marine Guidance Notes (MGN) and Merchant Shipping Notices (MSN)',
    category: 'flag_state',
    flagCC: 'gb',
    url: 'https://www.gov.uk/government/organisations/maritime-and-coastguard-agency',
  },
  {
    short: 'AMSA',
    full: 'Australian Maritime Safety Authority — Marine Orders',
    category: 'flag_state',
    flagCC: 'au',
    url: 'https://www.amsa.gov.au/about/regulations-and-standards/marine-orders',
  },
  {
    short: 'MPA SG',
    full: 'Maritime and Port Authority of Singapore — Shipping Circulars, Port Marine Circulars, Port Marine Notices',
    category: 'flag_state',
    flagCC: 'sg',
    url: 'https://www.mpa.gov.sg/',
  },
  {
    short: 'HK MD',
    full: 'Hong Kong Marine Department — Merchant Shipping Information Notes (MSIN)',
    category: 'flag_state',
    flagCC: 'hk',
    url: 'https://www.mardep.gov.hk/',
  },
  {
    short: 'NMA Norway',
    full: 'Norwegian Maritime Authority (Sjøfartsdirektoratet) — RSR/RSV/SM circulars',
    category: 'flag_state',
    flagCC: 'no',
    url: 'https://www.sdir.no/en/',
  },
  {
    short: 'LISCR',
    full: 'Liberian International Ship and Corporate Registry — Marine Notices',
    category: 'flag_state',
    flagCC: 'lr',
    url: 'https://www.liscr.com/',
  },
  {
    short: 'RMI / IRI',
    full: 'Republic of the Marshall Islands / International Registries — Marine Notices',
    category: 'flag_state',
    flagCC: 'mh',
    url: 'https://www.register-iri.com/',
  },
  {
    short: 'BMA',
    full: 'Bahamas Maritime Authority — Marine Notices',
    category: 'flag_state',
    flagCC: 'bs',
    url: 'https://www.bahamasmaritime.com/',
  },
  {
    short: 'France',
    full: 'France — Code des transports, Cinquième Partie (Maritime). Articles L5*/R5*/D5* covering ship identification, registration, liability, autonomous vessels, seafarer rights, port operations, and maritime enforcement (French-language source).',
    category: 'flag_state',
    flagCC: 'fr',
    url: 'https://www.legifrance.gouv.fr/codes/texte_lc/LEGITEXT000023086525',
  },
  {
    short: 'BG Verkehr',
    full: 'Germany — BG Verkehr Dienststelle Schifffahrt: ISM Rundschreiben, SOLAS interpretations, MLC implementation, STCW, SchSV, Ballast Water (German-language source).',
    category: 'flag_state',
    flagCC: 'de',
    url: 'https://www.deutsche-flagge.de/',
  },
  {
    short: 'DGMM',
    full: 'Spain — Dirección General de la Marina Mercante: Reales Decretos, Instrucciones de Servicio, BOE consolidations covering inspection/certification, manning, training, vessel registration (Spanish-language source).',
    category: 'flag_state',
    flagCC: 'es',
    url: 'https://www.transportes.gob.es/marina-mercante',
  },
  {
    short: 'Capitanerie / MIT',
    full: 'Italy — Guardia Costiera (Capitanerie di Porto) Circolari Serie Generale + sample ordinanze, plus Ministero MIT lavoro-marittimo decreti and STCW transposition (Italian-language source).',
    category: 'flag_state',
    flagCC: 'it',
    url: 'https://www.guardiacostiera.gov.it/',
  },

  // ── U.S. federal (statute, regulation, USCG guidance) ────────────────
  {
    short: '33 CFR',
    full: 'Code of Federal Regulations, Title 33 — Navigation and Navigable Waters',
    category: 'us_federal',
    url: 'https://www.ecfr.gov/current/title-33',
  },
  {
    short: '46 CFR',
    full: 'Code of Federal Regulations, Title 46 — Shipping',
    category: 'us_federal',
    url: 'https://www.ecfr.gov/current/title-46',
  },
  {
    short: '49 CFR',
    full: 'Code of Federal Regulations, Title 49 — Transportation',
    category: 'us_federal',
    url: 'https://www.ecfr.gov/current/title-49',
  },
  {
    short: '46 USC',
    full: 'United States Code, Title 46 — Shipping (Subtitle II — Vessels and Seamen)',
    category: 'us_federal',
    url: 'https://uscode.house.gov/browse/prelim@title46&edition=prelim',
  },
  {
    short: 'NVIC',
    full: 'USCG Navigation and Vessel Inspection Circulars',
    category: 'us_federal',
    url: 'https://www.dco.uscg.mil/Our-Organization/NVIC/',
  },
  {
    short: 'NMC',
    full: 'National Maritime Center policy letters and inspection checklists',
    category: 'us_federal',
    url: 'https://www.dco.uscg.mil/national_maritime_center/',
  },
  {
    short: 'USCG MSM',
    full: 'USCG Marine Safety Manual (CIM 16000.X series)',
    category: 'us_federal',
    url: 'https://www.dco.uscg.mil/Our-Organization/Assistant-Commandant-for-Prevention-Policy-CG-5P/Inspections-Compliance-CG-5PC-/Office-of-Investigations-Casualty-Analysis/Marine-Safety-Manual/',
  },
  {
    short: 'USCG Bulletins',
    full: 'USCG MSIBs (Marine Safety Information Bulletins), GovDelivery alerts, ALCOAST notices',
    category: 'us_federal',
    url: 'https://www.dco.uscg.mil/Our-Organization/NVIC/MSIB/',
  },

  // ── Reference & emergency ────────────────────────────────────────────
  {
    short: 'OCIMF SIRE 2.0',
    full: 'OCIMF — SIRE 2.0 program documents, Information Papers, TMSA fast facts, and operational guidance (publicly-downloadable layer only; full Question Library beyond Part 1, ISGOTT 6th, MEG-4, and similar member-only publications require an OCIMF subscription)',
    category: 'reference',
    url: 'https://www.ocimf.org/programmes/sire-2-0',
  },
  {
    short: 'ERG',
    full: 'Emergency Response Guidebook (PHMSA)',
    category: 'reference',
    url: 'https://www.phmsa.dot.gov/hazmat/erg/emergency-response-guidebook-erg',
  },
  {
    short: 'WHO IHR',
    full: 'WHO International Health Regulations (2005, with 2014/2022/2024 amendments)',
    category: 'reference',
    url: 'https://www.who.int/health-topics/international-health-regulations',
  },
]

const CATEGORY_LABELS: Record<CorpusSource['category'], string> = {
  international: 'International conventions & references',
  us_federal: 'U.S. federal',
  flag_state: 'Non-U.S. flag-state regulators',
  reference: 'Reference & emergency',
}

const CATEGORY_ORDER: CorpusSource['category'][] = ['international', 'us_federal', 'flag_state', 'reference']

// ── Chip ─────────────────────────────────────────────────────────────────────

function CorpusChip({ source }: { source: CorpusSource }) {
  const className = `
    inline-flex items-center gap-1.5
    px-2.5 py-1 rounded-md
    bg-[#0a0e1a] border border-[#2dd4bf]/25
    font-mono text-xs text-[#f0ece4]/90
    hover:border-[#2dd4bf]/60 hover:bg-[#111827]
    transition-colors duration-150
    whitespace-nowrap
  `.replace(/\s+/g, ' ').trim()

  // Sprint D6.26 — render a small flag SVG inside flag_state chips so
  // each non-US regulator carries its country flag inline. /brand/flags/
  // SVGs are designed for a 28x20 box, so we scale down to 16x12 here.
  const content = (
    <span title={source.full} className="inline-flex items-center gap-1.5">
      {source.flagCC && (
        <span className="inline-block w-4 h-3 overflow-hidden rounded-[2px]
          border border-white/15 flex-shrink-0 bg-[#0f1525]">
          <img
            src={`/brand/flags/${source.flagCC}.svg`}
            alt=""
            aria-hidden="true"
            width={16}
            height={12}
            loading="lazy"
            className="block w-full h-full object-cover"
          />
        </span>
      )}
      <span>{source.short}</span>
    </span>
  )

  if (source.url) {
    return (
      <a
        href={source.url}
        target="_blank"
        rel="noopener noreferrer"
        className={className}
        aria-label={`${source.full} (opens in new tab)`}
      >
        {content}
      </a>
    )
  }
  return <span className={className}>{content}</span>
}

// ── Categorized mode ────────────────────────────────────────────────────────

interface Props {
  mode?: 'categorized' | 'inline'
  className?: string
  /** Optional eyebrow heading above the chip groups. */
  heading?: string
  /** Subhead under the heading. */
  subhead?: string
}

function CategorizedView({ heading, subhead, className }: Pick<Props, 'heading' | 'subhead' | 'className'>) {
  const grouped = CATEGORY_ORDER.map((cat) => ({
    category: cat,
    label: CATEGORY_LABELS[cat],
    sources: CORPUS.filter((s) => s.category === cat),
  })).filter((g) => g.sources.length > 0)

  return (
    <div className={className}>
      {(heading || subhead) && (
        <div className="text-center mb-6">
          {heading && (
            <h2 className="font-display text-2xl md:text-3xl font-bold text-[#f0ece4] mb-2 tracking-wide">
              {heading}
            </h2>
          )}
          {subhead && (
            <p className="font-mono text-sm text-[#6b7594] max-w-xl mx-auto leading-relaxed">
              {subhead}
            </p>
          )}
        </div>
      )}
      <div className="flex flex-col gap-5 max-w-3xl mx-auto">
        {grouped.map(({ category, label, sources }) => (
          <div key={category}>
            <p className="font-mono text-[10px] uppercase tracking-widest text-[#6b7594] mb-2.5
              flex items-center gap-2">
              {/* Sprint D6.26 — US flag inline beside the "U.S. federal"
                  heading mirrors the per-chip flags in the flag_state
                  section, so the country signal is consistent across both. */}
              {category === 'us_federal' && (
                <span className="inline-block w-4 h-3 overflow-hidden rounded-[2px]
                  border border-white/15 flex-shrink-0 bg-[#0f1525]">
                  <img
                    src="/brand/flags/us.svg"
                    alt=""
                    aria-hidden="true"
                    width={16}
                    height={12}
                    loading="lazy"
                    className="block w-full h-full object-cover"
                  />
                </span>
              )}
              <span>{label}</span>
            </p>
            <div className="flex flex-wrap gap-1.5">
              {sources.map((s) => (
                <CorpusChip key={s.short} source={s} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Inline mode ─────────────────────────────────────────────────────────────

/**
 * Returns the corpus as a comma-separated prose string. Used inside
 * other paragraphs where chips would be too heavy.
 */
export function corpusInlineString(): string {
  return (
    'the IMO conventions (SOLAS, MARPOL, IMDG, COLREGs, STCW, ISM, '
    + 'plus HSC/IGC/IBC/CSS/Load Lines and IACS class standards), '
    + 'U.S. CFR 33/46/49 + 46 USC + USCG guidance, '
    + 'and flag-state regulations from the UK, Australia, Singapore, '
    + 'Hong Kong, Norway, Liberia, Marshall Islands, and Bahamas, '
    + 'plus ERG and WHO IHR'
  )
}

function InlineView({ className }: Pick<Props, 'className'>) {
  return <span className={className}>{corpusInlineString()}</span>
}

// ── Main component ──────────────────────────────────────────────────────────

export function CorpusBadges({
  mode = 'categorized',
  className,
  heading,
  subhead,
}: Props) {
  if (mode === 'inline') {
    return <InlineView className={className} />
  }
  return <CategorizedView heading={heading} subhead={subhead} className={className} />
}
