# RAG Architecture Audit

**Date:** 2026-04-20
**Context:** Post-baseline eval (92.9% A or A− on 28-question regression set). Fresh perspective review.
**Scope:** Full retrieval → synthesis → verification pipeline. Recommends structural changes ranked by ROI.

---

## 1. Current architecture — flow diagram

```
user query
   │
   ▼
┌─────────────────────────────────────────────────────────┐
│  (1) ROUTER — Claude Haiku, 10-token output             │
│  Classifies 1/2/3 complexity → picks Haiku/Sonnet/Opus  │
└─────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────┐
│  (2) RETRIEVER — packages/rag/rag/retriever.py          │
│  (a) Embed query once (text-embedding-3-small, 1536d)   │
│  (b) Identifier regex scan (UN1219, NVIC 04-08, etc.)   │
│  (c) Per-source-group vector search (pgvector HNSW),    │
│      each group gets 6-12 candidates (CFR: 12, else: 6) │
│  (d) Broad keyword trigram search via GIN index         │
│  (e) Merge: identifier hits (+0.05), keyword (+0.02)    │
│  (f) Source affinity boost (+0.20 per matched group)    │
│  (g) Vessel profile boost (+0.05 per text-match term)   │
│  (h) Sort by combined _score, return top 8              │
└─────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────┐
│  (3) CONTEXT BUILDER — packages/rag/rag/context.py      │
│  Concatenates top chunks up to 6K token budget,         │
│  builds [SOURCE: ...] blocks for the system prompt.     │
│  Dedupes citations by section_number.                   │
└─────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────┐
│  (4) SYNTHESIS — Claude Sonnet 4.6 (default)            │
│  Reads system prompt (100+ line instruction) +          │
│  vessel context + retrieved chunks + conversation       │
│  history. Max 2048 output tokens.                       │
└─────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────┐
│  (5) CITATION VERIFICATION — packages/rag/rag/engine.py │
│  Regex-extracts citations from answer; verifies each    │
│  against DB. Unverified → regenerate with feedback      │
│  ("don't cite X, it doesn't exist"). Strip any still-   │
│  unverified cites. Log failures to citation_errors.     │
└─────────────────────────────────────────────────────────┘
   │
   ▼
ChatResponse { answer, cited_regulations, model_used, tokens... }
```

**Strengths:**
- Hybrid retrieval (vector + trigram + identifier) handles varied query styles.
- Source-diversified fetch prevents large sources (CFR ~33K chunks) from swamping small ones (COLREGs ~102).
- Citation-verification + regeneration is an effective hallucination safety net (seen in baseline: 6 queries triggered regen, all landed clean).
- Router-selects model by complexity: cost-efficient without compromising on hard queries.

**Observed weaknesses (from baseline):**
- Embedding cannot distinguish mirrored-text regulations (same fireman's-outfit text in 6+ CFR Parts).
- Source affinity is query-keyword-based, not vessel-context-based.
- Synthesis LLM tries to cite OSHA 29 CFR 1910 (not in corpus); regeneration catches it but wastes tokens.
- System prompt enumerates CFR/SOLAS/COLREGs/STCW/ISM/NVIC/ERG but **not** NMC policy/checklist or uscg_bulletin — stale, doesn't tell the model what's available.
- Top-8 chunk selection is pure similarity + shallow boosts. No cross-encoder stage to re-rank near-ties.

---

## 2. Stage-by-stage analysis

### 2.1 Router

**What we do:** one Haiku call per query classifies complexity 1-3, picks Haiku/Sonnet/Opus.

**What works:** cheap (~$0.0003 per classification). Covers ~95% of queries with Sonnet, reserving Opus for complex synthesis.

**Open question:** is router adding latency proportional to its value? Every query pays +400-600ms for the classifier. For single-regulation lookups the router correctly picks Haiku, but we could skip the router entirely for a handful of known-cheap query types (identifier-only lookups) and go straight to Haiku without paying for a classifier call. Marginal win, probably not worth doing.

**Verdict:** keep as-is. Not a priority.

### 2.2 Retrieval — the core quality lever

This is where 90% of the quality variance lives. Breaking it down:

#### 2.2.1 Embedding — `text-embedding-3-small` (1536d)

**Why this choice:** cheap (~$0.00002 / 1K tokens), reasonable quality, plays well with pgvector.

**Cost-per-query:** negligible (< $0.0001).

**Alternatives:**
| Model | Dim | Pros | Cons |
|---|---|---|---|
| `text-embedding-3-small` (current) | 1536 | Cheap, OpenAI-reliable | Generic, trained on general web |
| `text-embedding-3-large` | 3072 | ~10% better on domain benchmarks | 4× storage, 3× ingestion re-cost |
| Voyage `voyage-3-large` | 1024 | State-of-art on legal/technical | Added vendor dependency |
| Cohere `embed-english-v3.0` | 1024 | Strong legal-domain performance | Added vendor, no maritime-specific eval |
| Fine-tuned maritime model | ? | Would solve mirror-text problem | Months of work, ongoing cost |

**Verdict:** embedding model is NOT the bottleneck. Upgrading to `text-embedding-3-large` would help maybe +2-5% on mirror-text cases, but the structural issue (same text in different Parts) doesn't go away. Not worth a re-ingest right now.

#### 2.2.2 Hybrid search — vector + trigram + identifier

**What works really well:** identifier regex. A query mentioning "NVIC 04-08" or "UN1219" or "Rule 15" reliably pulls the right chunk. Zero hallucination cost.

**What works OK:** trigram + broad keyword. Picks up "chlorine gas" for ERG Guide 124 when vector similarity alone might not.

**What could be better:** the keyword tier's frequency cap (200) suppresses common words, but doesn't help with "fireman's outfit" which appears in 6+ Parts. All hit above the cap. Retrieval pulls ALL of them ranked by similarity — the wrong-vessel-type ones score identically to the right-vessel-type ones.

**Root cause:** none of the three tiers (vector, trigram, identifier) has access to vessel-type context. Source affinity boosts are keyword-based, not vessel-based.

#### 2.2.3 Source-diversified fetch (per-group top-N)

**Why we do it:** small sources (COLREGs 102 chunks, ISM 63, ERG 762) would get obliterated by CFR (33K chunks) if we did a single top-20 pull. Diversification guarantees representation.

**Hidden cost:** for a query that's clearly CFR-only (e.g. "46 CFR 10.227 renewal requirements"), we still spend a query per group — 8 concurrent SELECTs when 1 would do. Latency-wise it's fine (all parallel), but we also force 6 COLREGs and 6 ERG candidates into the pool even when they're not useful.

**Alternative:** classifier-gated retrieval. One Haiku call at query time classifies intent (credentialing / port ops / navigation / env / COLREGs / ...) → retrieval goes only against the relevant source groups. Would eliminate noise from irrelevant groups AND allow per-vertical tuning of retrieval parameters.

**Trade-off:** adds ~500ms latency per query. Feasible but not obviously a win over the current approach. Worth testing via eval.

**Verdict:** keep diversified fetch, but classifier-gated is worth prototyping.

#### 2.2.4 Re-ranking — soft boosts

**What we do:** after retrieval, apply three additive scores on top of cosine similarity:
- Vessel-profile text-match boost (+0.05 per matched term in full_text)
- Source affinity boost (+0.20 per matched query-keyword group)
- Hybrid keyword boost (+0.02 for broad-keyword matches)

Then sort.

**What works:** source affinity boost works well on queries that mention the source explicitly ("per SOLAS Chapter II-2...").

**What doesn't:** vessel-profile boost is +0.05 per term. The term has to literally appear in chunk full_text. "Containership" probably DOES appear in Subchapter I chunks. But a chunk that says "The master shall ensure" is just as likely to score well — the vessel-profile boost is giving a small nudge, not a structural filter.

**The missing piece:** no vessel-type × CFR-Part applicability filter. This is what the Cassandra audit surfaced as the #1 issue.

**Proposed re-ranking stage (new):**
```
For each candidate:
  1. Compute base similarity score.
  2. If candidate is a CFR chunk AND vessel context is set:
     - If chunk's Part is in vessel's applicable_parts → no change
     - If chunk's Part is explicitly inapplicable → drop (filter), not penalize
     - If unknown mapping → small penalty (-0.05)
  3. Apply existing source-affinity + vessel-profile boosts.
  4. Sort.
```

Building the vessel_type → applicable_cfr_parts mapping is the work. Once it's there, this stage is ~20 lines of Python.

### 2.3 Context builder

**What we do:** concat top chunks up to 6K tokens, drop any chunk that would exceed.

**Question worth asking:** why 6K? Sonnet's input window is 200K. We could pass 15-20 full chunks if we wanted.

**Real constraint:** not token budget; it's the LLM's ability to focus. Passing 20 chunks of near-identical Subchapter mirror text might confuse the synthesizer worse than passing the 5 best. Classic "more retrieval ≠ better synthesis" curve.

**Verdict:** 6K is a reasonable Schelling point. Not a priority.

### 2.4 Synthesis

**Model:** Sonnet 4.6 by default. Router can upgrade to Opus 4.6 for complex queries.

**System prompt (packages/rag/rag/prompts.py):** 100+ lines. Enumerates knowledge base sources, cite-format rules, copyright policy, vessel-context handling, progressive vessel profiling (VESSEL_UPDATE block), coverage language.

**Observed issues from baseline:**

1. **System prompt doesn't list NMC policy / checklist / uscg_bulletin sources.** These were added after the prompt was written and never merged in. The synthesis LLM doesn't know these are available. Could explain why MSIB-related queries sometimes don't lead with bulletin citations — LLM doesn't expect them to be available.

2. **System prompt pushes model toward coverage claims.** The "COVERAGE" clause says "never claim that you lack access to specific rules." This is well-intentioned (prevents wishy-washy "I don't have that") but may be driving OSHA hallucinations: the model thinks it MUST cite something, so it invents 29 CFR 1910.

3. **No explicit no-OSHA clause.** Add: "Do not cite 29 CFR Part 1910 (OSHA) — those regulations are not in your knowledge base. Maritime workplaces are covered by 46 CFR Subchapter V (Marine Occupational Safety) instead."

4. **No confidence scoring.** Synthesis output is prose. Would be better to have structured output: `{answer: "...", citations: [{section_number, confidence}], caveats: [...]}`. Weak citations could be stripped or flagged.

### 2.5 Citation verification + regeneration

**What we do:** after synthesis, regex-extract every `(46 CFR X.Y)` / `(NVIC ...)` / `(SOLAS ...)` citation in the answer. Verify against DB. If any are unverified, regenerate with explicit "don't cite X" feedback. Strip remaining unverified.

**What works:** this is the one piece of the pipeline that directly prevents hallucination from reaching users. Baseline showed 6+ queries triggered regeneration; all landed clean.

**Cost:** doubles the Sonnet call on affected queries. At 6/28 = 21% of queries, this is a real latency + token tax.

**Preventive alternative:** if the system prompt pre-empted OSHA hallucination (no-OSHA clause above), regeneration rate drops ~to zero. Much cheaper.

**Verdict:** keep as the safety net, but fix the prompt so it rarely fires.

---

## 3. Top structural improvements — ranked by expected lift

### Priority 1 — Vessel-type × CFR-Subchapter applicability filter

**What it fixes:** the 3 A− contamination cases in the baseline + the V5/F5 towing-CO2-cited-fishing error. Probably lifts 3-4 grade points on the test set.

**Mechanism:** post-retrieval filter that drops chunks from inapplicable CFR Parts when vessel context is set.

**Risk:** if the applicable-Parts table has a gap, we lose legitimate hits. Mitigated by defaulting to "include with small penalty" for unmapped Parts, not "exclude."

**Effort:** 1 focused session — table + filter function + regression eval.

**Expected post-filter baseline:** ~95-97% A or A−.

### Priority 2 — System prompt refresh (pure prompt engineering)

**What it fixes:** OSHA hallucinations (eliminates regeneration cost on those queries), stale source enumeration (surfaces NMC + uscg_bulletin to the model).

**Changes:**
1. Add uscg_bulletin + nmc_policy + nmc_checklist to the KNOWLEDGE BASE SOURCES list with cite format.
2. Add an explicit "do not cite 29 CFR Part 1910 (OSHA)" clause.
3. Soften the "COVERAGE" language — "If a regulation isn't in the retrieved context, say so briefly and invite follow-up" (instead of "never claim that you lack access").

**Risk:** near-zero. Prompt changes are reversible in seconds.

**Effort:** 30 minutes including eval re-run.

### Priority 3 — Structured citation output (small architecture change)

**What it fixes:** today's answer is prose with citations embedded. Weak citations are indistinguishable from strong ones until post-hoc verification. Structured output lets us surface confidence to the user ("this one I'm 95% sure about; this one is referenced but I'd verify directly").

**Mechanism:** change synthesis to request JSON output: `{"answer_text": ..., "citations": [{source, section_number, confidence, relevance}], "caveats": [...]}`. Render the prose but gate low-confidence citations.

**Risk:** moderate. Requires change in both prompt and frontend rendering. Could break existing citation-capture regex flow.

**Effort:** 2-3 sessions.

**Expected win:** user trust + better regression data (we can grade per-citation confidence calibration).

### Priority 4 — Classifier-gated retrieval (experimental)

**What it fixes:** potentially reduces noise in the retrieval pool for focused queries (e.g., a pure "credential" query wouldn't waste 6 COLREGs + 6 ERG candidates in the pool).

**Mechanism:** one Haiku call at query time classifies intent → retrieval runs only against relevant groups.

**Risk:** the classifier gets it wrong and we miss cross-domain context (e.g., a query that mentions port security AND credentialing that needs both NMC and bulletin).

**Effort:** 1 session + eval A/B.

**Expected win:** uncertain. Worth prototyping but not betting on.

### Priority 5 — Cross-encoder re-ranker

**What it fixes:** the "ranks 20 near-identical candidates by cosine" problem. A cross-encoder (Cohere rerank, Voyage rerank) would look at query + candidate pairs and produce a more discriminating score — good at pulling the most relevant mirror out of near-identical candidates.

**Mechanism:** top-20 from diversified retrieval → cross-encoder rerank → top-8.

**Risk:** added vendor dependency + ~500ms latency + per-query cost (~$0.001).

**Effort:** 1-2 sessions.

**Expected win:** modest. Much of the mirror-text problem is already solved by the Subchapter filter (Priority 1). Rerank might help the remaining cases but it's solving a problem that's already mostly addressed upstream.

**Verdict:** defer until we have data showing mirror-text contamination AFTER the Subchapter filter lands. Likely not needed.

### Priority 6 — Structured metadata on chunks (longer-term)

**What it unlocks:** today's "chunk is just a text blob" approach means every filter has to be done at retrieval time via regex on section_number. If chunks had first-class metadata (`vessel_applicability: ["containership", "tanker"]`, `topic: "fire_equipment"`, `authority_level: "binding_regulation" | "interpretive_guidance"`), filtering becomes indexed + fast.

**Mechanism:** migration to add columns + a one-time enrichment pass over the corpus (probably LLM-assisted classification, then cached).

**Risk:** touches every ingest source adapter. Needs coordination.

**Effort:** 4-6 sessions.

**Expected win:** significant for edge cases and new source types, but most of the day-1 benefit comes from Priority 1 without needing this. Defer.

---

## 4. Recommended sprint order

Conservative, risk-reducing, evidence-gated order:

**Sprint C1 (this week):** Priority 2 — system prompt refresh. Single commit, eval re-run. Baseline check after.

**Sprint C2 (next):** Priority 1 — vessel-type × Subchapter filter. Eval re-run. Expect **~95%+ A or A−**. If we don't hit it, diagnose and iterate before moving on.

**Sprint C3 (after C2 locks in):** Priority 3 — structured citation output. Optional depending on C1+C2 results.

**Deferred:** Priority 4 (classifier-gated), 5 (cross-encoder), 6 (metadata). Only pursue if post-C2 baseline reveals specific failure modes they'd address.

**Total effort to hit 95%+ A-or-A− target: 1.5 sessions.** C1 is ~30 min; C2 is ~1 focused session.

---

## 5. Architectural questions worth revisiting later

These are not urgent but are worth queueing:

- **Is 512-token chunking the right size for maritime regulations?** A CFR section can be 50 tokens or 2000 tokens; fixed-size chunking doesn't match the natural boundary. Semantic chunking (chunk at section/subsection boundaries) could be more principled.

- **Should retrieval return spans, not chunks?** Some queries need a specific paragraph within a 512-token chunk. Cross-encoder rerank can surface the best chunk; span extraction would find the best ~50 tokens within it. Possibly overkill.

- **Cross-source answer coherence.** When an answer needs to cite SOLAS + CFR 46 + NMC policy together (e.g., medical certificate renewal spans all three), our retrieval may not balance the pool correctly. Worth evaluating as we build more cross-domain test questions.

- **Conversation history.** Today we pass the last ~10 turns. Long credential-renewal dialogs could exceed context. A compression/summarization pass on older turns is eventually needed.

- **User feedback integration.** Today the only signal is citation_errors (hallucinations caught). We should capture user thumbs-up/down + "this answer was wrong because..." so the test set grows organically from production usage.

---

## 6. The bottom line

The RAG pipeline is **fundamentally sound**. Baseline numbers (92.9% A or A−) reflect that. The Cassandra single-point Q1 error was a real issue but it's not representative — the majority of the system is working.

The path to A− at worst is **two small structural changes** (Priorities 1 and 2), plus disciplined regression evaluation on every change. Not a rewrite, not new retrieval infrastructure, not new embedding models.

**What shifts the conversation about quality:** not "more data" or "better model" — but vessel-aware retrieval + sharper synthesis prompt.

## Appendix — baseline reference

- Eval run: `2026-04-20_183711`
- 28 runs across 5 vessel profiles (V1 containership, V2 tanker, V3 Subchapter-T passenger, V5 Subchapter-M towing, V7 OSV)
- Grade distribution: 23 A, 3 A− (Subchapter-mirror contamination), 2 F (1 regex-false-F, 1 real wrong-Subchapter)
- Hallucination rate (caught by regen): 6+ queries / 28 = ~21%. Nearly all targeting 29 CFR 1910 OSHA.
- Synthesis + regen cost: 191K input tokens + 22K output = ~$0.35 total

See `data/eval/2026-04-20_183711/summary.md` for the full graded list.
