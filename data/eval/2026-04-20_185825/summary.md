# RAG Eval Baseline — 2026-04-20_185825

**Total runs:** 28
**Grade distribution:** A: 21, A-: 4, B: 1, F: 2
**A or A−:** 89.3%
**B or better:** 92.9%

**LLM spend:** 197,643 input + 19,690 output tokens across 28 runs

## Failures (C + F)

### V2 / F1  — F
**Query:** What are the regulations for SCBA packs on my vessel?
**Reason:** Unverified citation(s) present: ['29 CFR 1910.134']
**Citations (8):**
  1. [stcw] STCW Code A-V/1-1 — Mandatory minimum requirements for the training and qualifications of masters, o
  2. [cfr_46] 46 CFR 117.175 — Survival craft equipment
  3. [cfr_46] 46 CFR 180.175 — Survival craft equipment
  4. [solas] SOLAS Ch.II — Chapter II-2: Construction – Fire protection, fire detection and fire extinction
  5. [nvic] NVIC 05-86 §19 — Voluntary Standards for U.S. Uninspected Commercial Fishing Vessels — A respirat
**Unverified citations:** ['29 CFR 1910.134']

### V5 / F5  — F
**Query:** Do I need a fixed CO2 system on my vessel?
**Reason:** Expected source not cited; no wrong-Subchapter either (retrieval whiff)
**Citations (8):**
  1. [cfr_46] 46 CFR 95.05-10 — Fixed fire extinguishing systems
  2. [nvic] NVIC 06-72 §4 — Guide to Fixed Fire-Fighting Equipment Aboard Merchant Vessels — Revisions. It i
  3. [cfr_46] 46 CFR 169.564 — Fixed extinguishing system, general
  4. [cfr_46] 46 CFR 167.45-1 — Steam, carbon dioxide, Halon 1301, and clean agent fire extinguishing systems
  5. [cfr_46] 46 CFR 167.45-45 — Carbon dioxide fire extinguishing system requirements

## B-grade contaminations

### V5 / F1
**Query:** What are the regulations for SCBA packs on my vessel?
**Wrong-Subchapter cites in top-2:** ['46 CFR 117\\.', '46 CFR 180\\.']

## A / A− roll-up

- [A ] V1 / C1: `What do I need to submit for my MMC renewal?`
- [A ] V1 / C2: `Can I use Navy sea service toward my MMC?`
- [A ] V1 / C3: `What medical standards apply if I have type 2 diabetes?`
- [A-] V1 / E1: `What are the rescue boat tiller requirements on my vessel?`
- [A-] V1 / F1: `What are the regulations for SCBA packs on my vessel?`
- [A ] V1 / F2: `How many firefighter's outfits does my vessel require?`
- [A ] V1 / F5: `Do I need a fixed CO2 system on my vessel?`
- [A ] V1 / F7: `Has there been any recent safety alert on fire extinguishers?`
- [A ] V1 / N1: `Crossing situation right-of-way if I'm overtaking another vessel?`
- [A ] V1 / P3: `What port restrictions apply at Elizabeth River bridges in Norfolk?`
- [A ] V1 / V1q: `What are the ballast water requirements for my vessel?`
- [A ] V1 / X1: `What is today's date and the most recent bulletin you've seen?`
- [A ] V1 / X4: `Is NFPA 1981 required on my vessel?`
- [A-] V2 / F2: `How many firefighter's outfits does my vessel require?`
- [A ] V2 / V3q: `What's in my Oil Record Book entries?`
- [A ] V3 / C1: `What do I need to submit for my MMC renewal?`
- [A ] V3 / C2: `Can I use Navy sea service toward my MMC?`
- [A ] V3 / C3: `What medical standards apply if I have type 2 diabetes?`
- [A ] V3 / C4: `How do I get a ROUPV endorsement?`
- [A ] V3 / F7: `Has there been any recent safety alert on fire extinguishers?`
- [A ] V5 / C1: `What do I need to submit for my MMC renewal?`
- [A ] V5 / C3: `What medical standards apply if I have type 2 diabetes?`
- [A-] V5 / E1: `What are the rescue boat tiller requirements on my vessel?`
- [A ] V5 / N1: `Crossing situation right-of-way if I'm overtaking another vessel?`
- [A ] V5 / P1: `Are there any port conditions or MSIBs active on the Lower Mississippi?`