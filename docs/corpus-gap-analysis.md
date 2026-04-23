# RegKnot — Corpus Gap Analysis

**Purpose:** authoritative, ranked inventory of maritime regulatory content we don't yet ingest, with estimated costs and user-value signals to drive ingest-sprint sequencing.

**Last updated:** 2026-04-22 (post-Karynn test session + Sprint D4 sailor-speak scaffolding)

**Current corpus:** 15 sources, ~42K chunks (see `docs/PROJECT_STATE.md`).

---

## Priority tiers

- **P0 — User surfaced a hedge today (2026-04-22).** Karynn's real test session produced bad answers directly attributable to these gaps. Highest ROI.
- **P1 — Advertised / on-deck.** Already on the roadmap or implicitly promised by our marketing. Ship to meet expectations.
- **P2 — Referenced-but-missing.** Our existing corpus explicitly references these standards; users who follow citations hit dead ends.
- **P3 — Strategic international coverage.** Valuable for specific vessel segments (international voyage, fishing, Arctic, etc.) but not weight-bearing on current pilot base.
- **P4 — Not worth ingesting.** Listed for completeness so we don't re-evaluate them every quarter.

## Cost dimensions (apply to every item below)

- **Source** — where does the content come from; any licensing blockers
- **Format** — PDF / HTML / structured XML / scanned (OCR needed)
- **Chunks (est.)** — rough post-chunker count using our 512-token, 50-overlap settings
- **One-time cost** — embedding cost at `text-embedding-3-small` ($0.00002/1K tokens) + dev time in sessions
- **Maintenance** — cadence of updates we'd need to track
- **User-value signal** — strong / medium / weak, derived from: hedge frequency, pilot request rate, marketing claim leverage
- **Implementation risk** — low / medium / high (based on scanned-vs-structured, licensing, OCR reliability)

---

## P0 — User surfaced today

### P0.1 — BMP5 / MSCHOA / UKMTO industry guidance (maritime security)
- **Why:** Karynn's HRA transit (Gulf of Aden → Pakistan) and HRA guidelines questions both hedged. No content in corpus.
- **Source:** BMP5 is free-download PDF from ICS Shipping + industry bodies; MSCHOA/UKMTO advisories are free on their sites.
- **Format:** PDF (BMP5 ~80 pages); MSCHOA advisories are HTML bulletins.
- **Chunks (est.):** BMP5 ~350 chunks; MSCHOA archive ~200 chunks if we take the last 2 years.
- **One-time cost:** ~$0.15 embedding + 1 session (ingest adapter, chunker tuning for the handbook style).
- **Maintenance:** BMP5 revises every 2-3 years (BMP6 is rumored for late 2026). MSCHOA advisories are event-driven.
- **User value:** **Strong.** International-voyage vessels (most containerships, tankers) need this. Without it, we decline to answer one of the most operationally critical question classes.
- **Risk:** Low. BMP5 is well-structured. MSCHOA is noisy but filterable like we did with GovDelivery.
- **Recommendation:** **Ingest BMP5 first.** Defer MSCHOA live-feed to a Cowork task (roadmap §5) — it's bulletin-shaped and fits that pattern.

### P0.2 — 46 USC (United States Code, maritime)
- **Why:** Karynn's slop chest, foreign articles discharge, ship's store, and crew wage questions all hedged because they're governed by 46 USC Chapters 111-113, not 46 CFR. We have CFR but not USC.
- **Source:** Public via uscode.house.gov. XML, HTML, plain text, PDF — all clean.
- **Format:** Structured HTML/XML via GovInfo bulk data.
- **Chunks (est.):** 46 USC Subtitle II (Shipping) is roughly 450 sections. ~4,000 chunks at our chunker settings.
- **One-time cost:** ~$0.50 embedding + 1.5 sessions (adapter, entity extraction for §-level structure, NMC policy cross-references).
- **Maintenance:** Revisions are legislative (bills passed into law). Quarterly check at most.
- **User value:** **Strong.** Seamen's law is a recurring pilot question category. Covers articles, discharge, vessel documentation, wages, Jones Act basics.
- **Risk:** Low. Same shape as CFR.
- **Recommendation:** Ingest 46 USC Subtitle II. High leverage, cheap, unblocks Karynn's entire "crew/labor/seamen" question cluster.

### P0.3 — WHO International Health Regulations / Ship Sanitation Control Certificate
- **Why:** Karynn asked about the "derat" / sanitary inspection certificate. SSCC is governed by WHO IHR 2005 Annex 3. We don't have WHO content.
- **Source:** WHO's IHR 2005 is free PDF. Annex 3 is <10 pages.
- **Format:** PDF, structured.
- **Chunks (est.):** 200 chunks for full IHR 2005; ~40 if we take just Annex 3 + ship-relevant articles.
- **One-time cost:** ~$0.05 embedding + 0.5 session (small scope).
- **Maintenance:** IHR updates rarely (last major revision 2005; COVID-era amendments 2022). Annual check sufficient.
- **User value:** **Medium.** Appears in pilot questions but not super frequently.
- **Risk:** Low.
- **Recommendation:** Ingest with P0.2 in the same sprint — tiny incremental cost.

### P0.4 — USCG PSC inspection + enforcement procedures
- **Why:** Karynn's "penalties if PSC inspector asks for VGM but I'm missing some" question hedged. Our corpus has USCG bulletins and NVICs but not the PSC ops manual or civil penalty guidance.
- **Source:** USCG Marine Safety Manual (MSM) Vol. I-V — public PDF on dco.uscg.mil. Also CG-CVC PSC guidance.
- **Format:** PDF, mostly narrative but with structured checklists.
- **Chunks (est.):** MSM is ~2,000 pages across 5 volumes. Full ingest would be ~15,000 chunks. Selective ingest (Vol. II — Vessel Inspections, Vol. IV — Technical, PSC chapters) ~5,000 chunks.
- **One-time cost:** ~$0.75 embedding + 2 sessions (PDF extraction for volumes, section identifier parsing, OCR check on any scanned segments).
- **Maintenance:** MSM gets Change Notices periodically. Quarterly review.
- **User value:** **Strong.** PSC prep is a flagship use case for pilots. Highly leverageable in marketing ("know what the inspector wants before they board").
- **Risk:** Medium. Large document set; internal structure is heterogeneous across volumes.
- **Recommendation:** Scope a "PSC-adjacent chapters only" initial ingest (~1,500 chunks) rather than full MSM. Expand if user signal warrants.

**P0 total:** ~3-4 sessions, ~$1.45 in embedding cost, unlocks 4 of Karynn's 5 corpus-gap hedges from today. Strong ROI.

---

## P1 — Advertised / on-deck

### P1.1 — IMDG Code (International Maritime Dangerous Goods)
- **Why:** On roadmap. Containership and tanker pilots expect this to work. Currently we fall back to 49 CFR (US domestic HM rules) when IMDG is the right answer for international voyages.
- **Source:** IMO. Copyright-restricted (like SOLAS/STCW/ISM). Available by IMO subscription. Pilots typically have paper copies onboard.
- **Format:** Published as a 2-volume set (Vol. 1 provisions + Vol. 2 dangerous goods list). Structured PDF.
- **Chunks (est.):** ~6,000 chunks (Volume 1 provisions ~2,500; Volume 2 DG list ~3,500).
- **One-time cost:** ~$1.00 embedding + 2 sessions (IMO copyright compliance review like we did for SOLAS; chunking strategy for the DG list which is tabular).
- **Maintenance:** IMDG has biennial amendments (like SOLAS supplements). Same supplement-source pattern.
- **User value:** **Strong** for international operators. Medium for domestic-only.
- **Risk:** Low (structurally similar to SOLAS). IMO licensing is established precedent from our SOLAS ingest.
- **Recommendation:** Ship after P0 batch. Natural pair with MARPOL.

### P1.2 — MARPOL (International Convention for the Prevention of Pollution from Ships)
- **Why:** On roadmap. Current environmental queries hit 33 CFR 151 (US implementation) but miss international MARPOL. Annex-level queries about oil, chemicals, sewage, garbage, air emissions hedge when the user frames the question internationally.
- **Source:** IMO. Copyright-restricted. 6 annexes + protocols.
- **Format:** Structured PDF.
- **Chunks (est.):** ~1,800 chunks across 6 annexes.
- **One-time cost:** ~$0.30 embedding + 1.5 sessions.
- **Maintenance:** MSC/MEPC resolution amendments (like SOLAS supplement pattern).
- **User value:** **Strong.** Environmental compliance is a top-3 pilot question category.
- **Risk:** Low.
- **Recommendation:** Pair with IMDG in a single "IMO completeness sprint."

### P1.3 — Forms — CG-719 series + NMC applications (served, not ingested)
- **Why:** On roadmap §3a. These are the forms mariners download from NMC. Currently they're in `data/raw/nmc/` but not served as a Forms tab product.
- **Source:** NMC (already downloaded locally).
- **Format:** PDF, AcroForm in most cases.
- **Chunks (est.):** Not a RAG ingest — this is a product feature, not a corpus expansion. Out of scope for this doc but listed for completeness.
- **Recommendation:** Separate product sprint; don't fold into corpus work.

---

## P2 — Referenced-but-missing

### P2.1 — NFPA standards (1981 SCBA, 1971 firefighter PPE, 10 fire extinguishers, others)
- **Why:** 46 CFR 95 + SOLAS Ch.II-2 reference NFPA standards by incorporation. User asks "do I need NFPA 1981 on board" → our eval's X4 question hedges because we don't have NFPA content.
- **Source:** NFPA. **Copyright-restricted** and **paid** (NFPA charges individual-access and institutional licensing). Significant blocker.
- **Format:** PDF, structured.
- **Chunks (est.):** NFPA 1981 alone is ~60 pages → ~300 chunks. Full maritime-relevant NFPA set (1971, 1981, 10, 13, 25, 72) is ~2,000 chunks.
- **One-time cost:** **Licensing cost first** — NFPA institutional licenses run $800-2,000/year depending on scope. Embedding cost trivial once content is in hand.
- **Maintenance:** NFPA revises on 3-5 year cycles.
- **User value:** **Medium.** Users rarely ask NFPA directly; they ask about the equipment the standard specifies. We can often answer via the CFR-referenced-NFPA path without the standard text.
- **Risk:** High — licensing is the blocker, not the tech.
- **Recommendation:** **Defer.** The CFR incorporation-by-reference language we already have explains what's required ("an SCBA conforming to NFPA 1981 or equivalent"). Pilots generally have the NFPA standard themselves if they need spec details. Revisit if user signal shows this is a recurring complaint.

### P2.2 — IEEE Std 45 (shipboard electrical engineering)
- **Why:** 46 CFR Subchapter J references it. Engineering-heavy queries may surface it.
- **Source:** IEEE. Paid license (~$200 individual).
- **User value:** **Weak.** Engineers onboard have this standard. Low query frequency.
- **Recommendation:** **Decline.** Not worth licensing cost.

### P2.3 — ABS Rules (American Bureau of Shipping)
- **Why:** Classification society rules. Referenced in CFR for specific vessel types.
- **Source:** ABS. Free PDF download with registration.
- **User value:** **Medium** for specific vessel segments (passenger, tanker).
- **Recommendation:** Consider as a P3 extension — free source, mid-value.

---

## P3 — Strategic international coverage

### P3.1 — International Ship and Port Facility Security Code (ISPS)
- **Source:** IMO. Copyright-restricted.
- **Chunks (est.):** ~500 chunks.
- **One-time cost:** ~$0.10 embedding + 1 session.
- **User value:** **Strong** for international-voyage vessels. Pairs with BMP5 (P0.1) — security coverage would be complete with both.
- **Recommendation:** Ship alongside IMDG/MARPOL in a security/environmental international sprint.

### P3.2 — International Convention on Load Lines (LL 1966/88)
- **Chunks (est.):** ~200 chunks.
- **User value:** **Medium.** Technical, draft survey, freeboard.
- **Recommendation:** Low priority.

### P3.3 — International Convention on Tonnage Measurement (ITC 1969)
- **Chunks (est.):** ~100 chunks.
- **User value:** **Low.** Tonnage is usually a one-time vessel characteristic, not recurring compliance.
- **Recommendation:** Defer.

### P3.4 — Polar Code
- **Source:** IMO. Free download of the Code text; related SOLAS amendments we already have in supplement.
- **Chunks (est.):** ~250 chunks.
- **User value:** **Low currently** (pilot base doesn't operate Arctic). High if we target Arctic operators.
- **Recommendation:** Wait for demand signal.

### P3.5 — Ballast Water Management Convention (BWMC 2004)
- **Why:** We cover 33 CFR 151 (US implementation) but not the international convention directly.
- **Chunks (est.):** ~200 chunks.
- **User value:** **Medium.** International-voyage vessels frequently hit BWM compliance questions.
- **Recommendation:** Pair with MARPOL in the international-environmental sprint.

### P3.6 — IAMSAR Manual (Search and Rescue)
- **Source:** IMO/ICAO joint publication.
- **Chunks (est.):** ~3,000 chunks (3-volume manual).
- **User value:** **Low.** Onboard SAR responsibilities are mostly covered by SOLAS Ch.V Reg.33. IAMSAR is reference material for coast guards, not pilots.
- **Recommendation:** Decline.

### P3.7 — CFR Title 50 (NOAA fisheries)
- **Why:** On roadmap §3d. Would matter if we target commercial fishing vessels.
- **Chunks (est.):** ~20,000 chunks.
- **One-time cost:** ~$3.00 embedding + 2 sessions.
- **Maintenance:** Weekly eCFR republishes (like CFR 33/46/49).
- **User value:** **Zero** for current pilot segments. **High** for a commercial fishing segment.
- **Recommendation:** Hold until fishing becomes a target segment.

### P3.8 — STCW Manila Amendments (beyond what our current STCW + 2025 supplement covers)
- **Why:** We have STCW 2017 + Jan 2025 supplement. Manila Amendments (2010) predate our consolidated edition and are folded in.
- **Recommendation:** No action; already covered.

### P3.9 — OPA 90 / 33 USC Chapter 40 (Oil Pollution Act)
- **Why:** We have 33 CFR 151 which implements OPA 90. The statute itself has occasional query surface.
- **Source:** Public via uscode.house.gov.
- **Chunks (est.):** ~300 chunks.
- **User value:** **Low.** Usually the CFR answer suffices.
- **Recommendation:** Fold into P0.2 (46 USC) if we're already ingesting USC — trivial incremental cost.

### P3.10 — Jones Act / 46 USC 55102 (cabotage)
- **Why:** Covered automatically if we ingest 46 USC (P0.2). No separate action needed.

---

## P4 — Not worth ingesting

- **Country-specific port arrival documents** — India, Pakistan, Brazil, etc. Each country's requirements are published by their respective port authorities; not maritime-industry-standard. RegKnot should direct users to their local agent.
- **Port-specific pilotage rules** — thousands of ports worldwide. Not scalable.
- **Flag-state-specific interpretations** — Marshall Islands, Panama, Liberia administer their own regs. Out of scope.
- **Company-specific SMS / OMS documents** — proprietary, per-vessel.
- **IHO ENC chart specifications** — too niche; pilots don't compliance-query chart specs.
- **US Coast Guard Auxiliary Operations Policy** — for Auxiliary members, not commercial mariners.

---

## Recommended sequencing

**Sprint D6a — P0 batch (4 sessions total):**
1. **D6a.1:** 46 USC Subtitle II ingest (P0.2) — biggest unlock, cheapest ingest, zero licensing. Fold in OPA 90 (P3.9) in the same pass.
2. **D6a.2:** BMP5 + ISPS ingest (P0.1 + P3.1) — pair these since they're both security-domain.
3. **D6a.3:** PSC chapters from USCG Marine Safety Manual (P0.4) — scoped to PSC-relevant volumes.
4. **D6a.4:** WHO IHR / SSCC (P0.3) — small, tag on.

**Sprint D6b — P1 IMO completeness (3 sessions):**
5. **D6b.1:** IMDG Code (P1.1).
6. **D6b.2:** MARPOL (P1.2).
7. **D6b.3:** BWMC + Load Lines (P3.5 + P3.2) in the same pass — shared IMO ingest pattern.

**Total to P0 + P1:** ~7 sessions of ingest work. ~$3 in embedding cost. No licensing blockers.

**Estimated hedge-rate reduction from Karynn's profile:** P0 alone addresses 4 of her 5 corpus-gap hedges. Expected hedge rate on her exact questions post-P0: near zero, ignoring retrieval issues.

---

## Monitoring

After each ingest sprint, re-run:
- Full eval (regulatory-register + naturalistic + sailor-speak subsets)
- `retrieval_misses` query filtered to post-sprint timestamp
- A/B the pilot hedge rate before/after

If post-ingest hedge rate on the targeted domain doesn't drop by at least half, the retrieval layer has a separate problem and another enrichment pass is needed before declaring the ingest "done."
