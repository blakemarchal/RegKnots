export interface CitedRegulation {
  source: string
  section_number: string
  section_title: string
}

// Sprint D6.48 Phase 2 — yellow-card payload returned alongside an
// assistant message when the corpus genuinely missed and a web search
// fallback found a usable source. Frontend renders this as a visually-
// distinct card so users never confuse it with an authoritative
// corpus answer.
//
// Sprint D6.58 Slice 1 + Slice 3 — `surface_tier` distinguishes:
//   'verified'  — confidence 4-5, quote verified verbatim against
//                 the source. RegKnots-authored answer, "Verified
//                 web result" badge.
//   'consensus' — Slice 3 Big-3 ensemble found ≥2/3 cross-LLM
//                 agreement on the answer but no single citation
//                 we'd vouch for. Badge: "AI consensus — verify
//                 yourself." Premium signal but explicitly NOT a
//                 RegKnots verified citation.
//   'reference' — single-LLM (or single-provider) result with
//                 confidence 2-3 OR quote unverifiable. Surfaces
//                 the source URL with an "External reference"
//                 badge. Lower endorsement floor → useful pointer
//                 without RegKnot vouching for content.
export interface WebFallbackCard {
  fallback_id: string
  source_url: string
  source_domain: string
  quote: string
  summary: string
  confidence: number  // 1-5
  surface_tier?: 'verified' | 'consensus' | 'reference'
}

// Sprint D6.84 — confidence tier router metadata.
// Surfaced to the frontend ONLY when CONFIDENCE_TIERS_MODE=live on
// the backend. In 'off' / 'shadow' modes, this stays null and the
// chat UI renders today's behavior unchanged.
//
//   tier 1 = ✓ RegKnot Verified         (corpus citation)
//   tier 2 = ⚓ Industry Standard       (settled maritime knowledge,
//                                        anchor footnote, no claimed citation)
//   tier 3 = 🌐 Relaxed Web             (web fallback with disclaimer +
//                                        confidence score)
//   tier 4 = ⚠ Best-effort              (explicit hedge / "needs a Captain")
export interface TierMetadata {
  tier: 1 | 2 | 3 | 4
  label: 'verified' | 'industry_standard' | 'relaxed_web' | 'best_effort'
  reason: string
  classifier_verdict?: 'yes' | 'no' | 'uncertain' | null
  self_consistency_pass?: boolean | null
  web_confidence?: number | null
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations: CitedRegulation[]
  web_fallback?: WebFallbackCard | null
  tier_metadata?: TierMetadata | null
  // Sprint D6.85 Fix C — user-cancelled assistant message marker.
  // Renders distinctly (italic + "Stopped" hint) and the content
  // includes the partial text that was streamed before the abort.
  cancelled?: boolean
}

export interface ApiResponse {
  answer: string
  conversation_id: string
  cited_regulations: CitedRegulation[]
  model_used: string
  input_tokens: number
  output_tokens: number
  web_fallback?: WebFallbackCard | null
  tier_metadata?: TierMetadata | null
}
