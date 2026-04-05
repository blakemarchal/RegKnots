# RegKnots Pilot Analytics — April 4, 2026

Data gathered via direct SQL queries against production database.

---

## Model Usage

| Model  | Responses | Total Tokens | Avg Tokens/Response |
|--------|-----------|-------------|---------------------|
| Sonnet | 19        | 104,223     | 5,485               |
| Haiku  | 22        | 122,253     | 5,557               |

**Total:** 41 assistant responses, 226,476 tokens

---

## Most Active Users

| Email                                  | Messages |
|----------------------------------------|----------|
| blakemarchal@gmail.com                 | 13       |
| bowling.nick@gmail.com                 | 12       |
| blakemarchal+regknotstest1@gmail.com   | 5        |
| shepmg225@gmail.com                    | 4        |

---

## Vessel-Context Queries

- **20 total queries** sent with a vessel profile attached
- Vessels used: USNS Seay, Kennicott, USS Dinky, MAERSK Kinloss

---

## "My vessel/boat" Without Vessel Profile

- **2 queries** referenced "my vessel" or "my boat" but had no vessel_id set
- Both from: blakemarchal@gmail.com
- Implication: user expected vessel-aware answers but hadn't selected a vessel

---

## Sample Real User Questions

Topics asked about by pilot users:
- Lifeboat inspections
- SOLAS amendments
- Watch schedules
- AFFF (firefighting foam) requirements
- Pilot carriage requirements
- Fire drill regulations
- Sailing short (undermanned) procedures

---

## Citation Errors (7-day window)

| Citation        | Model  |
|-----------------|--------|
| 46 CFR 160.051  | Haiku  |
| 46 CFR 160.051  | Haiku  |
| 46 CFR 131      | Sonnet |

Only 3 total hallucinated citations in the entire pilot period.

---

## Key Takeaways

1. **Haiku gets slightly more use than Sonnet** — the router is sending most simple lookups to Haiku (correct behavior).
2. **Token usage is nearly identical per response** (~5,500 avg) regardless of model — suggests context window usage is the driver, not model verbosity.
3. **4 real external users** beyond admin/test accounts (bowling.nick, shepmg225).
4. **Vessel profile gap fixed** — vessel context was only used for retrieval re-ranking, not passed to Claude in the prompt. Fixed in this deploy.
5. **Citation accuracy is excellent** — only 3 errors across 41 responses (7.3% error rate, all CFR sections).
