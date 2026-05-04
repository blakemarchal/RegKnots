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
// Sprint D6.58 Slice 1 — `surface_tier` distinguishes:
//   'verified'  — confidence 4-5, quote verified verbatim. Card
//                 reads as a RegKnots-authored answer with a
//                 "Verified web result" badge.
//   'reference' — confidence 2-3 OR quote unverifiable. Card reads
//                 "We found this — verify yourself" with the source
//                 URL prominent and an "External reference" badge.
//                 Lower endorsement floor → more useful answers
//                 reach the user without RegKnot vouching for them.
export interface WebFallbackCard {
  fallback_id: string
  source_url: string
  source_domain: string
  quote: string
  summary: string
  confidence: number  // 1-5
  surface_tier?: 'verified' | 'reference'
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
