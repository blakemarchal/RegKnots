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
  category: 'international' | 'us_federal' | 'reference'
  url?: string
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
  international: 'International conventions',
  us_federal: 'U.S. federal',
  reference: 'Reference & emergency',
}

const CATEGORY_ORDER: CorpusSource['category'][] = ['international', 'us_federal', 'reference']

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

  const content = (
    <span title={source.full}>
      {source.short}
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
            <p className="font-mono text-[10px] uppercase tracking-widest text-[#6b7594] mb-2.5">
              {label}
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
 *
 * Example:
 *   "U.S. CFR 33/46/49 + 46 USC, the IMO conventions (SOLAS, MARPOL,
 *   IMDG, COLREGs, STCW, ISM), USCG circulars and bulletins, NMC, ERG,
 *   and WHO IHR"
 */
export function corpusInlineString(): string {
  return (
    'U.S. CFR 33/46/49 + 46 USC, the IMO conventions (SOLAS, MARPOL, '
    + 'IMDG, COLREGs, STCW, ISM), USCG circulars and bulletins, NMC, '
    + 'ERG, and WHO IHR'
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
