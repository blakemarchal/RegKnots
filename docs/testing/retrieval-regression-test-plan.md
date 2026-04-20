# RegKnot Retrieval Regression Test Plan

**Audience:** Blake + Karynn + pilot captains.
**Purpose:** Generate real-world feedback data on answer quality. Populate the regression test set so every future retrieval change can be graded against known-good expectations.

**How to use:**
1. Pick a vessel setup from §1 (or add a new one matching your vessel).
2. Work through the questions in §2 relevant to that vessel type.
3. For each answer, record: which sources it cited, whether you judge it A / B / C / F, what was wrong or missing.
4. Send results back in any format (text, sheet, screenshots) — even 10 graded answers is valuable.

Grading scale (calibrated off the Cassandra audit):
- **A** — direct, correctly cited, vessel-specific, nothing notable missing.
- **A−** — correct answer, minor omissions or slightly wordy, no credibility issues.
- **B** — right domain, cited something applicable, missed a material element.
- **C** — plausible but cited wrong Subchapter / wrong vessel-type regulation. This is the category we are currently hitting too often.
- **F** — hallucinated facts, wrong citations, would mislead a captain.

---

## §1 — Vessel setups

Pick one before testing. Each setup matches a real-world profile we should handle well.

### V1 — Large international containership
- Name: MAERSK Tennessee (or any 50K+ GT name)
- Type: Containership
- GT: 74,642
- Route: International
- Cargo: Containers
- Expected strong subchapters: 46 CFR Subchapter I (Parts 90–105), SOLAS Ch. II / II-2 / III / IV / V, ISM Code, STCW.
- Cassandra's profile.

### V2 — Tanker, U.S. coastal
- Name: any US-flag petroleum tanker
- Type: Tanker
- GT: ~30,000
- Route: Coastal
- Cargo: Petroleum / Oil
- Expected strong subchapters: 46 CFR Subchapter D (Parts 30–39), 33 CFR Part 154–156 (facilities/transfer), OPA 90, MARPOL Annex I.

### V3 — Subchapter T small passenger vessel
- Name: e.g. "Island Explorer"
- Type: Passenger Vessel
- GT: 65
- Route: Inland
- Subchapter: T
- Cargo: Passengers
- Certificate Type: COI
- Expected strong subchapters: 46 CFR Subchapter T (Parts 175–187), NVIC 04-08 (medical), NMC policy letters on passenger-vessel credentialing.

### V4 — Subchapter K passenger, Great Lakes / inland
- Name: e.g. "Harbor Queen"
- Type: Passenger Vessel
- GT: 180
- Route: Inland + coastal
- Subchapter: K
- Expected strong subchapters: 46 CFR Subchapter K (Parts 114–122), SOLAS if international legs.

### V5 — Subchapter M towing vessel
- Name: e.g. "Mississippi Hauler"
- Type: Towing / Tugboat
- GT: 198
- Route: Inland (rivers + intercoastal)
- Expected strong subchapters: 46 CFR Subchapter M (Parts 140–144), Subchapter C (uninspected vessels if under 26 GT — not this one).

### V6 — Fishing vessel
- Name: any U.S. commercial fisher
- Type: Fish Processing
- GT: 95
- Route: Coastal
- Cargo: None / Not Applicable (self-catch)
- Expected strong subchapters: 46 CFR Part 28 (Commercial Fishing Industry), NVIC guidance on CFIVSA.

### V7 — OSV, Gulf of Mexico
- Name: any OSV
- Type: OSV / Offshore Support
- GT: 850
- Route: Coastal (GOM)
- Cargo: General cargo / Hazardous Materials (muds, chemicals)
- Expected strong subchapters: 46 CFR Subchapter L (Parts 125–139), NVIC 01-10 OSV guidance.

### V8 — Ferry (small, inland)
- Name: any small ferry
- Type: Ferry
- GT: 85
- Route: Inland (harbor transit)
- Subchapter: T
- Expected strong subchapters: 46 CFR Subchapter T; ferry-specific operational guidance where applicable.

### V9 — Research vessel
- Name: UNOLS fleet or similar
- Type: Research Vessel
- GT: 3,200
- Route: International
- Expected strong subchapters: 46 CFR Subchapter U (Parts 188–195). **This is the only vessel type where Part 195 is the right answer.**

### V10 — Liftboat
- Name: any Liftboat
- Type: OSV / Offshore Support (or Other)
- GT: 250
- Route: Coastal
- Expected strong subchapters: 46 CFR Subchapter L partial, Liftboat Policy Letter (in corpus), industry guidance.

---

## §2 — Test question bank

Pick the row matching your vessel setup and work through the questions. Many questions apply to multiple setups — grade them under each setup you use.

### Fire safety & emergency equipment

| # | Question | Strong for | Expected citation |
|---|---|---|---|
| F1 | What are the regulations for SCBA packs on my vessel? | V1, V2, V5 | V1: 46 CFR 96.35-10; V2: 46 CFR 35.30-20; V5: 46 CFR 142.226; SOLAS II-2/10 on int'l |
| F2 | How many firefighter's outfits does my vessel require? | V1, V2 | V1: 46 CFR 96.35-10 (min 2); SOLAS II-2/10.10.2 (min 2 cargo, more for pax) |
| F3 | What stowage requirements apply to my fireman's outfits? | V1, V2 | V1: 46 CFR 96.35-15 stowage; similar for V2 |
| F4 | What fire detection is required in engine room? | V1, V3 | V1: 46 CFR 95.05-1; V3: 46 CFR 181 Subpart 4 |
| F5 | Do I need fixed CO2 system on my vessel? | V1, V5 | V1: 46 CFR 95.15; V5: 46 CFR 144.240 |
| F6 | What are the requirements for SCBA low-air alarms? | All | Honest limit expected (NFPA 1981 reference; not in corpus today) |
| F7 | Has there been any recent safety alert on fire extinguishers? | All | ACN 013/18 Kidde recall, ACN 002/22 rec-vessel fire protection |
| F8 | What's the drill frequency for fire on my vessel? | All | SOLAS III/19 (pax/cargo int'l); 46 CFR 97.13-13 (cargo U.S.) |

### Credentialing — MMC & endorsements

| # | Question | Strong for | Expected citation |
|---|---|---|---|
| C1 | What do I need to submit for my MMC renewal? | All | NMC Application Acceptance Checklist; MCP-FM-NMC5-01 |
| C2 | Can I use Navy sea service toward my MMC? | All | CG-CVC 15-03; Crediting Military Sea Service |
| C3 | What medical standards apply if I have [diabetes / hypertension / hearing loss]? | All | NVIC 04-08 Ch-2 (medical & physical evaluation) |
| C4 | How do I get a ROUPV endorsement? | V3, V5, V8 | CG-MMC PL 01-16 Restricted Operator of UPV |
| C5 | What does Polar Code training require? | V1 (if polar) | CG-OES PL 01-16 Polar Code Training |
| C6 | STCW endorsement process for [rating/officer]? | All | STCW Convention + NMC policy letters |
| C7 | Can my credential be renewed if my medical cert expired? | All | NVIC 04-08, 46 CFR 10.227/10.302 |
| C8 | What's the liftboat operator credential policy? | V10 | Liftboat Policy Letter (Signed 2015-04-06) |
| C9 | Raise of grade requirements from [Master 500 GRT] to [Master 1600 GRT]? | All | 46 CFR 11.462; NMC process docs |

### Port conditions & MSIBs (depends on current corpus)

| # | Question | Strong for | Expected citation |
|---|---|---|---|
| P1 | Are there any port conditions or MSIBs active on the Lower Mississippi? | All | MSIB Vol XXI-XXV Issues (river conditions) |
| P2 | What's the current policy on Mardi Gras safety zones? | V5 (inland) | MSIB Vol XXV Issue 013 |
| P3 | What port restrictions apply at Elizabeth River Norfolk Southern bridge? | V1, V5 (if Mid-Atl) | SEC VA MSIB series 168-22, 201-23, 641-23 |
| P4 | Any safety advisories about the Sabine River or Gulf region? | V2, V7 | GOM MSIBs and LNM notices |
| P5 | What's the latest MARSEC level for [major port]? | V1 | Operational advisories (if recent) |

### Operational equipment

| # | Question | Strong for | Expected citation |
|---|---|---|---|
| E1 | Rescue boat tiller requirements? | V1, V5 | 46 CFR 160.156-7(14); SOLAS LSA Code Ch.V |
| E2 | Life raft servicing intervals? | V1, V3, V5 | SOLAS III/20.8; 46 CFR 199.180 |
| E3 | AIS Class A requirements for my vessel? | V1, V2 | 33 CFR 164.46; SOLAS V/19.2.4 |
| E4 | Bridge navigation equipment I must carry? | V1, V2, V5 | SOLAS V/19; 33 CFR 164 |
| E5 | What lights do I show at anchor in restricted visibility? | All | COLREGs Rules 30, 35 |

### Environmental

| # | Question | Strong for | Expected citation |
|---|---|---|---|
| V1 | What are the ballast water requirements for my vessel? | V1 (int'l) | 33 CFR 151 Subpart D; VGP/IGP; BWM Convention |
| V2 | Do I need an ODMCS on my vessel? | V2 | 33 CFR 155.370; MARPOL Annex I |
| V3 | What's in my Oil Record Book entries? | V2 | 33 CFR 151.25; MARPOL Annex I Reg 17 |
| V4 | Garbage disposal record requirements? | All int'l | 33 CFR 151.55; MARPOL Annex V |

### Navigation / COLREGs / inland rules

| # | Question | Strong for | Expected citation |
|---|---|---|---|
| N1 | Crossing situation right-of-way if I'm overtaking another vessel? | All | COLREGs Rules 13, 15 |
| N2 | Sound signals required in narrow channel? | V5 (rivers) | COLREGs Rule 9 + 34; Inland Rules |
| N3 | What waterway rules apply at [specific waterway mile marker]? | V5 | 33 CFR 207, LNM, MSIB |
| N4 | Speed restrictions in my area? | All | 33 CFR 165 Subchapter A; LNM |

### Hazmat / cargo

| # | Question | Strong for | Expected citation |
|---|---|---|---|
| H1 | IMDG Code requirements for my container cargo? | V1 | SOLAS VII; 49 CFR 176 |
| H2 | Hazmat cargo documentation I need onboard? | V1, V2 | 49 CFR 176; IMDG Code |
| H3 | ERG response guidance for UN1219 (isopropanol)? | All if hazmat | ERG Guide 127 |
| H4 | ERG response for [specific UN/NA number]? | All | ERG Guide + Table lookup |

### Edge-case sanity checks (these SHOULD expose limits)

| # | Question | What we're looking for |
|---|---|---|
| X1 | What's today's date and most recent bulletin you've seen? | Should be honest about the 3-year bulletin backfill cutoff, not claim knowledge of yesterday's bulletins |
| X2 | What's the difference between NVIC 04-08 and 46 CFR 10.301? | Should distinguish interpretive guidance from binding regulation |
| X3 | Cite the specific paragraph of SOLAS II-2 that requires SCBA on cargo ships over 500 GT. | Should pull the exact cite; no hallucinated numbers |
| X4 | Is NFPA 1981 required on my vessel? | Honest limit expected — not in our corpus today |
| X5 | What happens if you don't know the answer? | Should gracefully admit unknown, not fabricate |

---

## §3 — Feedback capture template

Copy-paste for each question. Easier with a spreadsheet but this works:

```
Question: (one of the F1/C1/P1/... codes above or free-form)
Vessel setup used: (V1 / V2 / etc.)
Grade: (A / A− / B / C / F)
Cited sources: (paste the citation list from the answer)
Expected source (if known): (from the tables above)
What was wrong or missing: (free text — be specific)
Would a captain on this vessel trust this answer? (yes / no / with caveats)
```

Blake will compile these into `data/eval/real_queries.jsonl` and wire them into the regression test runner.

---

## §4 — What I'll do with the results

1. Every graded question becomes a **persistent regression test** — runs against retriever + synthesizer after every ingest or retriever change.
2. Any C or F grade triggers a diagnostic run of `scripts/debug_retrieval.py` to show exactly which chunks the retriever pulled.
3. Patterns across C/F answers reveal either (a) retrieval quality gaps (the Subchapter mirror-text issue for Cassandra's Q1) or (b) corpus gaps (NFPA 1981, etc.) or (c) synthesis prompt issues.
4. Regression pass rate becomes the headline quality metric — "92% A/A− on our test set" is a real number that can go in marketing.

## §5 — Honest target

Once the vessel-type × Subchapter filter lands and we've regressed against 30+ real questions:

- **A or A−: target 80%** of questions with vessel context.
- **B or better: target 95%**.
- **C or F: zero tolerance** on questions in-domain to our corpus. Any C/F becomes a sprint blocker.

Until we have that filter + that regression set, the quality floor is lower than any of us are comfortable with. That's the honest answer to "can we guarantee A- at worst?"
