// Finds the maritime citations in an answer's text. ChatMessage.tsx turns
// each hit into a CitationChip, inline and in the footer.
//
// 2026-09-29 — moved here from ChatMessage.tsx so parseMessage.test.mjs
// can run it with plain node (no React). It replaces the pilot-era
// parseContent(), which nothing imported.

// ── Inline citation patterns ───────────────────────────────────────────────────
//
// Sprint D6.87 — expanded from CFR-only to all maritime citation
// patterns the model actually writes. Before D6.87, only `\d+ CFR ...`
// strings rendered as inline chips; everything else (SOLAS Ch.VI Reg.2,
// IMDG Ch.7.4, MSC.1/Circ.1440, NVIC 10-97, STCW Code A-II/3, ISM 1.2.3,
// 46 USC 7101) stayed as plain text. Blake's 2026-05-11 VGM screenshot
// made the problem visible: the answer cited SOLAS Reg.2, para.6 ten
// times and rendered zero chips for it.
//
// Each pattern is paired with a `sourceHint` so a click on a chip the
// DB doesn't know about still produces a sensible source attribution.
// The DB citation_map (passed via `citations`) still wins on exact
// section_number match — sourceHint is only the fallback.

interface CitationPattern {
  re: RegExp
  /** Source for the chip lookup. String for static sources; function
   *  for dynamic sources where the captured groups determine which DB
   *  source contains the row (e.g. CFR Title number selects
   *  cfr_33/cfr_46/cfr_49). */
  sourceHint: string | ((m: RegExpExecArray) => string)
  /** Extract the canonical section_number from the regex match. */
  toSection: (m: RegExpExecArray) => string
  /** Chip text, when it says more than the section (a CFR paragraph).
   *  Defaults to the section. */
  toLabel?: (m: RegExpExecArray) => string
}

export interface CitationHit {
  index: number
  length: number
  sectionNumber: string
  label: string
  sourceHint: string
}

// A CFR paragraph designation: (b), (1), (ii), (A).
const CFR_PARAGRAPH = String.raw`\((?:[a-z]{1,5}|\d{1,3}|[A-Z])\)`
// 46 CFR 140.410 / 46 CFR 91.60-10 / 33 CFR 153, then any paragraphs
// written straight after it: (b), (b)(1)(ii), (c)–(d).
// Groups: 1 Title, 2 section, 3 paragraphs.
const CFR_CITATION =
  String.raw`(\d+)\s+CFR\s+(\d+(?:\.\d+(?:-\d+)?)?)` +
  `((?:${CFR_PARAGRAPH})+(?:[–-](?:${CFR_PARAGRAPH})+)?)?`
const CFR_CHIP = {
  sourceHint: (m: RegExpExecArray) => `cfr_${m[1]}`,
  toSection: (m: RegExpExecArray) => `${m[1]} CFR ${m[2]}`,
  toLabel: (m: RegExpExecArray) => `${m[1]} CFR ${m[2]}${m[3] ?? ''}`,
}

const CITATION_PATTERNS: CitationPattern[] = [
  // 2026-09-27 — the fleet's own documents in workspace chats:
  // [Company: TSMS Manual §4.2 Emergency Drills]. The sheet resolves the
  // label inside the chat's workspace (GET /workspaces/{id}/documents/citation).
  {
    re: /\[Company:\s*([^\]§]+?)\s*§\s*([^\]]+?)\s*\]/g,
    sourceHint: 'company',
    toSection: m => `Company: ${m[1].trim()} §${m[2].trim()}`,
  },
  // 46 CFR 91.60-10 / (33 CFR 153) / 49 CFR 172.101
  //
  // Sprint D6.90 — sourceHint is now Title-aware. The regulations.cfr_*
  // sources are split by Title (cfr_33 / cfr_46 / cfr_49); the regex
  // captures the Title in group 1, and the lookup must route to the
  // matching source. Pre-D6.90 this emitted the literal string `cfr`,
  // which doesn't exist as a source, so every CFR chip click 404'd
  // (4 misses for "46 CFR 91.60-10" in the last 6 hours of citation_lookups
  // telemetry — same row resolves cleanly when source=cfr_46).
  //
  // 2026-09-29 — the chip label keeps the paragraph the answer cited
  // ("46 CFR 140.410(b)") and the chip still opens 46 CFR 140.410.
  // Parentheses go into the chip only as a pair around the whole citation:
  // the first entry below. Its match starts at the "(", one character
  // before the bare match inside it, so scanCitations keeps it.
  // The old single pattern had an optional "(" and an optional ")", so in
  // "(46 CFR 140.410(b))" the "(" went into the chip and the ")" never
  // matched: the answer read "[46 CFR 140.410](b))".
  { re: new RegExp(String.raw`\(${CFR_CITATION}\)`, 'g'), ...CFR_CHIP },
  { re: new RegExp(CFR_CITATION, 'g'), ...CFR_CHIP },
  // 46 USC 7101 / 46 USC 11102
  //
  // Sprint D6.97 Track A patch — sourceHint Title-aware (parity with the
  // D6.90 CFR fix above). The regulations.usc_* sources are split by Title
  // (currently usc_46 is the only Title in corpus), so the hardcoded
  // literal `usc` doesn't exist as a source row. Pre-patch the chip
  // resolved only via the references-fallback path in regulations.py,
  // which prepends "Full text isn't in our corpus directly" — confusing
  // UX since the section IS in corpus. Telemetry (citation_lookups, last
  // 4h): source=usc rows hit references-fallback; source=usc_46 rows hit
  // the exact-match path. Same chip, two outcomes. This unifies on the
  // exact-match path.
  {
    re: /\b(\d+)\s+USC\s+(\d+)\b/g,
    sourceHint: m => `usc_${m[1]}`,
    toSection: m => `${m[1]} USC ${m[2]}`,
  },
  // Sprint D6.91 — SOLAS regulation/sub-paragraph citation chips.
  //
  // The pre-D6.91 pattern was overfitted to "SOLAS Ch.II-2 Reg.10"
  // (no-space, no-comma, abbreviated-only form). Kenan's 2026-05-13
  // answer cited the same SOLAS section in three other valid forms
  // and got zero chips:
  //   "SOLAS Ch. II-2, Reg. 9.4.1.1.5"   (comma separator)
  //   "SOLAS Chapter II-2, Regulation 9" (full-word forms)
  //   "SOLAS II-2/9.4.1.1.5.3"           (slash form, no Ch. prefix)
  //
  // New regex handles all four:
  //   - Optional "Ch" / "Ch." / "Chapter" prefix
  //   - Separator can be whitespace, comma+space, or slash
  //   - Optional "Reg" / "Reg." / "Regulation" prefix
  //   - Reg number can be arbitrarily deep (Reg.9.4.1.1.5.3) — the
  //     suffix-strip fallback in regulations.py D6.88 Phase 2 resolves
  //     deep refs to their parent row at click time.
  //
  // "Part X" form (e.g. SOLAS Ch.VI Part A) handled as a separate
  // entry below so the digit-vs-Part branches don't pollute one regex.
  {
    re: /\bSOLAS\s+(?:Ch(?:apter)?\.?\s*)?([IVX]+(?:-\d+)?)(?:\s*[,/]\s*|\s+)(?:Reg(?:ulation)?\.?\s*)?(\d+(?:\.\d+)*)/g,
    sourceHint: 'solas',
    toSection: m => `SOLAS Ch.${m[1]} Reg.${m[2]}`,
  },
  // SOLAS Ch.VI Part A / SOLAS Chapter II-2, Part D / SOLAS II-2/Part D
  {
    re: /\bSOLAS\s+(?:Ch(?:apter)?\.?\s*)?([IVX]+(?:-\d+)?)(?:\s*[,/]\s*|\s+)Part\s+([A-Z])\b/g,
    sourceHint: 'solas',
    toSection: m => `SOLAS Ch.${m[1]} Part ${m[2]}`,
  },
  // IMDG Ch.7.4 / IMDG Chapter 7.4 / IMDG 7.3 / IMDG 7.3.1
  {
    re: /\bIMDG\s+(?:Ch\.?|Chapter)?\s*(\d+(?:\.\d+)*)\b/g,
    sourceHint: 'imdg',
    toSection: m => `IMDG ${m[1]}`,
  },
  // MSC.1/Circ.1440 / MSC.520(106) / MSC.97(73)
  {
    re: /\bMSC\.(\d+(?:\(\d+\)|\/Circ\.\d+)?)/g,
    sourceHint: 'imo_supplement',
    toSection: m => `MSC.${m[1]}`,
  },
  // NVIC 10-97 / NVIC 10-97 §5 / NVIC 01-20
  // 2026-09-27 — enclosures and changes as the corpus names them:
  // NVIC 06-72 Encl.1 / NVIC 04-03 Encl.3 §12 / NVIC 04-08 Ch-2 §3, and
  // "NVIC 06-72, Enclosure (1)". A bare "NVIC 06-72" is the circular's opening.
  {
    re: /\bNVIC\s+(\d{2}-\d{2})(?:\s+Ch-(\d+))?(?:,?\s+Encl(?:osure)?\.?\s*(?:\((\d{1,2})\)|(\d{1,2})))?(?:\s+§\s*(\d+))?(?!\w)/g,
    sourceHint: 'nvic',
    toSection: m => {
      const encl = m[3] || m[4]
      return `NVIC ${m[1]}${m[2] ? ` Ch-${m[2]}` : ''}${encl ? ` Encl.${encl}` : ''}${m[5] ? ` §${m[5]}` : ''}`
    },
  },
  // STCW Code A-II/3 / STCW Code B-I/2 / STCW Reg.II/1
  // The STCW corpus stores Convention regulations under the canonical
  // form 'STCW Ch.<chapter> Reg.<chapter>/<number>' (e.g.,
  // 'STCW Ch.II Reg.II/1'). The model commonly writes the abbreviated
  // 'STCW Reg.II/1'; we expand the abbreviation into the canonical
  // section_number here so chip clicks resolve. The chapter is the
  // Roman-numeral portion before the '/'.
  {
    re: /\bSTCW\s+(?:(Code\s+[AB])-([IVX]+\/\d+)|Reg\.?\s*([IVX]+\/\d+))/g,
    sourceHint: 'stcw',
    toSection: m => {
      if (m[1]) return `STCW ${m[1]}-${m[2]}`  // STCW Code A-II/3
      const chapter = m[3].split('/')[0]      // 'II/1' -> 'II'
      return `STCW Ch.${chapter} Reg.${m[3]}` // -> STCW Ch.II Reg.II/1
    },
  },
  // ISM Code 1.2.3 / ISM 1.2 / ISM Code 5
  {
    re: /\bISM(?:\s+Code)?\s+(\d+(?:\.\d+)*)/g,
    sourceHint: 'ism',
    toSection: m => `ISM ${m[1]}`,
  },

  // Sprint D6.88 Phase 2 follow-up — patterns Blake reported missing
  // from the 2026-05-11 evening QA pass. Adds coverage for the
  // sources that have the largest chunk counts behind no patterns:
  //
  //   marpol         571 chunks  | uscg_msm   3048 chunks
  //   marpol_amend   316 chunks  | erg         762 chunks
  //   colregs        102 chunks  | mca_msn     649 chunks
  //   amsa_mo        680 chunks  | mca_mgn     228 chunks
  //   who_ihr        163 chunks  | nmc_policy  209 chunks
  //   iacs_ur       2981 chunks  | imo_*        ~1300 chunks total
  //
  // Ordered by specificity (most specific first) so general
  // patterns don't swallow more specific ones; scanCitations
  // dedups overlapping spans by document position.

  // MARPOL Annex I/II/III/IV/V/VI with optional Reg/Ch/App suffix.
  // The model writes a mix of full-word and abbreviated forms:
  //   "MARPOL Annex VI Regulation 14.1"
  //   "MARPOL Annex VI Reg.14.1"
  //   "MARPOL Annex II Appendix VII"  /  "App.VII"
  //   "MARPOL Annex I Chapter 1"  /  "Ch.1"
  //   "MARPOL Annex VI Appendix III Part II"  (sub-appendix part)
  // Captures the full citation including the optional "Part N"
  // trailing reference, so the chip text matches what the model
  // wrote. Backend lookup normalizes full-word -> abbreviated form
  // (Appendix -> App., Chapter -> Ch., Regulation -> Reg.) when the
  // exact-match lookup misses.
  {
    re: /\bMARPOL\s+Annex\s+([IVX]+)(?:\s+(Reg(?:ulation|\.?)\s*\d+[A-Z]?(?:\.\d+)*|Ch(?:apter|\.?)\s*\d+|App(?:endix|\.?)\s*[IVX]+(?:\s+Part\s+[IVX]+)?))?/g,
    sourceHint: 'marpol',
    toSection: m =>
      m[2]
        ? `MARPOL Annex ${m[1]} ${m[2].replace(/\s+/g, ' ')}`
        : `MARPOL Annex ${m[1]}`,
  },
  // MARPOL Amendments MEPC.NNN(MM)
  {
    re: /\bMARPOL\s+Amendments\s+MEPC\.\d+\(\d+\)/g,
    sourceHint: 'marpol_amend',
    toSection: m => m[0].replace(/\s+/g, ' '),
  },

  // USCG Marine Safety Manual — "USCG MSM 16000.71 Ch.6", "USCG MSM 16000.74 Ch.1"
  {
    re: /\bUSCG\s+MSM\s+\d{5}(?:\.\d+[A-Z]?)?\s+Ch\.\d+(?:\(\w+\))?/g,
    sourceHint: 'uscg_msm',
    toSection: m => m[0].replace(/\s+/g, ' '),
  },

  // COLREGS Rule N — also accepts the lowercase 'COLREGs' spelling.
  // Standalone "Rule 5" is intentionally NOT matched — too ambiguous
  // without surrounding COLREGS context. Mariners or the model use
  // the explicit prefix for citation-grade references.
  {
    re: /\bCOLREGS?\s+Rule\s+(\d+)/gi,
    sourceHint: 'colregs',
    toSection: m => `COLREGS Rule ${m[1]}`,
  },

  // ERG — "ERG Guide 128", "ERG ID 1203", "ERG Yellow 3253-3267"
  {
    re: /\bERG\s+(?:Guide|ID|Yellow|Green|Blue|Orange|Table|CBRN)\s+[\w-]+/g,
    sourceHint: 'erg',
    toSection: m => m[0].replace(/\s+/g, ' '),
  },

  // WHO IHR — "WHO IHR Article 20", "WHO IHR Annex 3"
  {
    re: /\bWHO\s+IHR\s+(?:Article|Annex)\s+(?:\d+|[IVX]+)/g,
    sourceHint: 'who_ihr',
    toSection: m => m[0].replace(/\s+/g, ' '),
  },

  // UK MCA MGN — "MGN 71 (M+F)", "MGN 50 (M)", "MGN 71"
  {
    re: /\bMGN\s+\d+(?:\s+\([MF+]+\))?/g,
    sourceHint: 'mca_mgn',
    toSection: m => m[0].replace(/\s+/g, ' '),
  },

  // UK MCA MSN — "MSN 1676 Amendment 4", "MSN 1747"
  {
    re: /\bMSN\s+\d+(?:\s+Amendment\s+\d+)?/g,
    sourceHint: 'mca_msn',
    toSection: m => m[0].replace(/\s+/g, ' '),
  },

  // AMSA Marine Order — "Marine Order 25", "Marine Order 11"
  {
    re: /\bMarine\s+Order\s+\d+/g,
    sourceHint: 'amsa_mo',
    toSection: m => m[0].replace(/\s+/g, ' '),
  },

  // NMC Policy Letters — "CG-MMC PL 01-18", "CG-OES PL 01-16", "NMC PL 04-03"
  {
    re: /\b(?:CG-(?:MMC|OES)|NMC)\s+PL\s+\d{2}-\d{2}/g,
    sourceHint: 'nmc_policy',
    toSection: m => m[0].replace(/\s+/g, ' '),
  },

  // 2026-09-30 — the inland / Coast Guard sources.
  // CG-CVC policy letters (and the older CG-543 / CG-MOC / CG-PCV series),
  // with a change or enclosure: "CG-CVC PL 21-03", "CG-CVC Policy Letter
  // 23-05 CH-1", "CG-MOC PL 99-002". PL 15-03 is stored with the NMC
  // letters; the lookup tries nmc_policy when uscg_cvc has no such row.
  {
    re: /\b(CG-(?:CVC|543|MOC|PCV|3PCV))\s+(?:PL|Policy\s+Letter)\s+(\d{2}-\d{2,3})(?:\s+(CH-\d+|Encl\.\d+))?/g,
    sourceHint: 'uscg_cvc',
    toSection: m => `${m[1]} PL ${m[2]}${m[3] ? ` ${m[3]}` : ''}`,
  },
  // CG-CVC work instructions and forms — "CVC-WI-013", "CG-CVC-WI-038",
  // "CVC-FM-840K", "5P-WI-002"
  {
    re: /\b(?:CG-)?(CVC-(?:WI|FM)-\d{3}[A-Z]?|5P-WI-\d{3})\b/g,
    sourceHint: 'uscg_cvc',
    toSection: m => m[1],
  },
  // USCG Marine Safety Alerts — "USCG SA 15-26", "Safety Alert 20-25 CH-1"
  {
    re: /\b(?:USCG\s+SA|(?:USCG\s+)?(?:Marine\s+)?Safety\s+Alert)\s+(?:No\.\s*)?(\d{1,2}-\d{2})(?:\s+CH-?(\d+))?\b/g,
    sourceHint: 'uscg_safety_alert',
    toSection: m => `USCG SA ${m[1]}${m[2] ? ` CH-${m[2]}` : ''}`,
  },
  // Findings of Concern from casualty investigations — "USCG FOC 006-26",
  // "Finding of Concern 006-26"
  {
    re: /\b(?:USCG\s+FOC|Finding\s+of\s+Concern)\s+(?:No\.\s*)?(\d{3}-\d{2})\b/g,
    sourceHint: 'uscg_safety_alert',
    toSection: m => `USCG FOC ${m[1]}`,
  },
  // NMC credential checklists and towing officer assessment records —
  // "MCP-FM-NMC5-28", "TOAR Western Rivers"
  {
    re: /\bMCP-FM-NMC5-(\d{2,3})\b/g,
    sourceHint: 'nmc_checklist',
    toSection: m => `MCP-FM-NMC5-${m[1]}`,
  },
  {
    re: /\bTOAR\s+(Ocean and Near Coastal|Great Lakes and Inland|Western Rivers|Limited)\b/g,
    sourceHint: 'nmc_checklist',
    toSection: m => `TOAR ${m[1]}`,
  },
  // TVNCOE Subchapter M FAQs — "Sub M FAQ Part 138", "Subchapter M FAQ
  // Parts 1, 2 and 15", "Sub M FAQ General"
  {
    re: /\bSub(?:chapter)?\s+M\s+FAQs?\s+(Parts?\s+\d+(?:(?:\s*,\s*|\s+and\s+)\d+)*|General|Preamble)\b/g,
    sourceHint: 'uscg_towing',
    toSection: m => `Sub M FAQ ${m[1].replace(/\s+/g, ' ')}`,
  },
  // Merchant Mariner Medical Manual — "COMDTINST M16721.48 Ch.12",
  // "COMDTINST M16721.48, Chapter 7"
  {
    re: /\bCOMDTINST\s+M16721\.48(?:,?\s+Ch(?:apter\s*|\.\s*)(\d+))?/g,
    sourceHint: 'uscg_msm',
    toSection: m => `COMDTINST M16721.48${m[1] ? ` Ch.${m[1]}` : ''}`,
  },
  // EPA 2013 Vessel General Permit — "EPA 2013 VGP 2.2.3", "VGP Part 5.1",
  // "2013 VGP Appendix A". A year after VGP is not a part number.
  {
    re: /\b(?:EPA\s+)?(?:2013\s+)?VGP\s+(?:Part\s+)?(?!20\d\d\b)(\d+(?:\.\d+){0,3}|App(?:endix\s*|\.\s*)[A-Z])\b/g,
    sourceHint: 'epa_vgp',
    toSection: m => `EPA 2013 VGP ${m[1].replace(/^App(?:endix\s*|\.\s*)/, 'App.')}`,
  },

  // IMO Specialty Codes — HSC, IGC, IBC, BWM, Polar, IGF, CSS, IAMSAR
  // The Codes use MSC.XXX(YY) resolution refs or Ch.X.Y sections.
  // Capture the full identifier the model writes; rely on the
  // suffix-stripping backend fallback for sub-paragraph lookups.
  {
    re: /\bIMO\s+(HSC|IGC|IBC|BWM|Polar|IGF|CSS|IAMSAR)\s+Code\s+(?:MSC\.\d+\(\d+\)|MEPC\.\d+\(\d+\)|[A-Z]\.\d+\(\d+\))?\s*(?:Ch\.\d+(?:\.\d+)*)?/g,
    sourceHint: 'imo_codes',
    toSection: m => m[0].trim().replace(/\s+/g, ' '),
  },

  // IACS Unified Requirements — "IACS UR M74", "IACS UR S25"
  {
    re: /\bIACS\s+UR\s+[A-Z]\d+(?:\.\d+)?/g,
    sourceHint: 'iacs_ur',
    toSection: m => m[0].replace(/\s+/g, ' '),
  },

  // Sprint D6.93 — class society rules. Two corpora live behind the
  // LR- prefix (LR-CO-001 Code for Lifting Appliances and LR-RU-001
  // Rules for Classification of Ships), so the sourceHint switches on
  // the captured doc family. ABS Marine Vessel Rules use a single
  // citation shape covering Pt.N (digit or "5C1"/"5D"/etc. variants
  // plus the "Notices"/"Notations" pseudo-parts) optionally followed
  // by Ch.X Sec.Y.

  // LR-CO-001 / LR-RU-001 — "LR-CO-001 Ch.10 Sec.2", "LR-RU-001 Ch.5",
  // "LR-CO-001 GenReg Sec.4", "LR-CO-001 Notice1 Sec.1", and (D6.93
  // follow-up after LR-RU-001 ingest landed in per-Part folders)
  // "LR-RU-001 Pt.6 Ch.2 Sec.3". The Part segment is optional so
  // both LR-CO-001 (flat, no Part) and LR-RU-001 (Part-bearing)
  // citations chip cleanly.
  {
    re: /\bLR-(CO|RU)-(\d{3})\s+(?:Pt\.\w+\s+)?(?:Ch\.\w+|GenReg|Notice\d+)(?:\s+Sec\.\d+)?/g,
    sourceHint: m => m[1] === 'CO' ? 'lr_lifting_code' : 'lr_rules',
    toSection: m => m[0].replace(/\s+/g, ' '),
  },

  // ABS Marine Vessel Rules — "ABS MVR Pt.4 Ch.2 Sec.1",
  // "ABS MVR Pt.5C1 Ch.3 Sec.2", "ABS MVR Pt.Notices",
  // "ABS MVR Pt.Notations". Part is alphanumeric to cover the 5A/5B/
  // 5C-1/5C-2/5D variants ABS uses for Vessel Types.
  {
    re: /\bABS\s+MVR\s+Pt\.\w+(?:\s+Ch\.\d+(?:\s+Sec\.\d+)?)?/g,
    sourceHint: 'abs_mvr',
    toSection: m => m[0].replace(/\s+/g, ' '),
  },
]

/** Scan a string for all maritime citations across every pattern.
 *  Returns matches in document order, deduplicated by span. */
export function scanCitations(text: string): CitationHit[] {
  const found: CitationHit[] = []
  for (const p of CITATION_PATTERNS) {
    p.re.lastIndex = 0
    let m: RegExpExecArray | null
    while ((m = p.re.exec(text)) !== null) {
      // Sprint D6.90 — sourceHint can be a function (CFR Title-aware
      // routing) or a static string. Resolve at match time.
      const resolvedSource =
        typeof p.sourceHint === 'function' ? p.sourceHint(m) : p.sourceHint
      const sectionNumber = p.toSection(m)
      found.push({
        index: m.index,
        length: m[0].length,
        sectionNumber,
        label: p.toLabel ? p.toLabel(m) : sectionNumber,
        sourceHint: resolvedSource,
      })
    }
  }
  // Sort by position; collapse overlapping spans (keep earliest).
  found.sort((a, b) => a.index - b.index || b.length - a.length)
  const merged: typeof found = []
  let cursor = 0
  for (const hit of found) {
    if (hit.index < cursor) continue
    merged.push(hit)
    cursor = hit.index + hit.length
  }
  return merged
}

/** Extract a deduplicated, ordered list of citations from the full
 *  rendered message text. Used by the footer to mirror what's inline.
 *  Sprint D6.87 — previously the footer rendered message.citations
 *  directly (the DB-verified parent corpus entries), which often
 *  didn't match what the model actually wrote inline. Now both
 *  surfaces share the same source of truth: the answer text itself. */
export function extractFooterCitations(
  text: string,
  citationMap: Map<string, { source: string; title: string }>,
): Array<{ sectionNumber: string; source: string; title: string }> {
  const seen = new Set<string>()
  const result: Array<{ sectionNumber: string; source: string; title: string }> = []
  for (const hit of scanCitations(text)) {
    if (seen.has(hit.sectionNumber)) continue
    seen.add(hit.sectionNumber)
    const info = citationMap.get(hit.sectionNumber)
    result.push({
      sectionNumber: hit.sectionNumber,
      source: info?.source ?? hit.sourceHint,
      title: info?.title ?? '',
    })
  }
  return result
}
