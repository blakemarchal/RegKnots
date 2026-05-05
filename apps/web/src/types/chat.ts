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

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations: CitedRegulation[]
  web_fallback?: WebFallbackCard | null
}

export interface ApiResponse {
  answer: string
  conversation_id: string
  cited_regulations: CitedRegulation[]
  model_used: string
  input_tokens: number
  output_tokens: number
  web_fallback?: WebFallbackCard | null
}
