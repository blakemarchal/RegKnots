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


class ChatResponse(BaseModel):
    answer: str
    conversation_id: UUID
    cited_regulations: list[CitedRegulation]
    model_used: str
    input_tokens: int
    output_tokens: int
    unverified_citations: list[str] = []
