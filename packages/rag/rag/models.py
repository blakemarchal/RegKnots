"""Pydantic models for the RAG chat engine."""

from uuid import UUID

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class CitedRegulation(BaseModel):
    source: str
    section_number: str
    section_title: str


class RouteDecision(BaseModel):
    score: int   # 1, 2, or 3
    model: str   # Anthropic model ID


class ChatRequest(BaseModel):
    query: str
    conversation_id: UUID | None = None
    vessel_id: UUID | None = None


class WebFallbackCard(BaseModel):
    """Yellow-card payload returned alongside a hedge when a web search
    fallback succeeded. Sprint D6.48 Phase 2."""
    fallback_id: str        # web_fallback_responses.id, used for thumbs feedback
    source_url: str
    source_domain: str
    quote: str              # verbatim, verified to exist in source
    summary: str            # Claude's plain-English explanation
    confidence: int         # 1-5, gated to >= 4 before surfacing


class ChatResponse(BaseModel):
    answer: str
    conversation_id: UUID
    cited_regulations: list[CitedRegulation]
    model_used: str
    input_tokens: int
    output_tokens: int
    unverified_citations: list[str] = []
    vessel_update: dict | None = None
    regenerated: bool = False
    # Sprint D6.48 Phase 2 — populated only when retrieval missed AND
    # the hedge classifier matched AND web fallback found a verified
    # quote on a trusted domain. Frontend renders as a yellow card.
    web_fallback: WebFallbackCard | None = None
