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
    # D6.58 prelude — score=0 means OFF-TOPIC. Engine short-circuits
    # before retrieval / fallback / ensemble. Scores 1/2/3 are the
    # original maritime complexity tiers.
    score: int   # 0 (off-topic), 1, 2, or 3
    model: str   # Anthropic model ID; "" when score=0
    is_off_topic: bool = False


class ChatRequest(BaseModel):
    query: str
    conversation_id: UUID | None = None
    vessel_id: UUID | None = None


class WebFallbackCard(BaseModel):
    """Yellow-card payload returned alongside a hedge when a web search
    fallback succeeded.

    Sprint D6.58 (Slice 1) — `surface_tier` distinguishes two
    presentations:

      'verified' — confidence 4-5 + quote verified in source. UI shows
                   "Verified web result" badge; the answer is presented
                   as a RegKnots-authored statement anchored on the
                   verbatim quote.
      'reference' — confidence 2-3 OR quote unverifiable. UI shows
                    "External reference — please verify" badge; the
                    surface is a link-with-context, NOT a RegKnots
                    statement of fact. The user is invited to click
                    through and check the source themselves.
    """
    fallback_id: str        # web_fallback_responses.id, used for thumbs feedback
    source_url: str
    source_domain: str
    quote: str              # verbatim if surface_tier='verified'; may be empty for 'reference'
    summary: str            # Claude's plain-English explanation
    confidence: int         # 1-5
    surface_tier: str = "verified"  # 'verified' | 'reference'


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
