export interface CitedRegulation {
  source: string
  section_number: string
  section_title: string
}

// Sprint D6.48 Phase 2 — yellow-card payload returned alongside an
// assistant message when the corpus genuinely missed and a web search
// fallback found a verified verbatim quote on a trusted regulator
// domain. Frontend renders this as a visually-distinct card so users
// never confuse it with an authoritative corpus answer.
export interface WebFallbackCard {
  fallback_id: string
  source_url: string
  source_domain: string
  quote: string
  summary: string
  confidence: number  // 1-5
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
