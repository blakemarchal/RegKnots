export interface CitedRegulation {
  source: string
  section_number: string
  section_title: string
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations: CitedRegulation[]
}

export interface ApiResponse {
  answer: string
  conversation_id: string
  cited_regulations: CitedRegulation[]
  model_used: string
  input_tokens: number
  output_tokens: number
}
