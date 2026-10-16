"""2026-10-16 — the OpenAI fallback after GPT-4o: message translation and the
reasoning-model request parameters (rag/fallback.py)."""
from rag import fallback as F


def test_text_and_image_blocks_translate():
    system = [{"type": "text", "text": "You are RegKnot.", "cache_control": {"type": "ephemeral"}}]
    messages = [
        {"role": "user", "content": "First question"},
        {"role": "assistant", "content": "First answer"},
        {"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBOR"}},
            {"type": "text", "text": "What is this placard?"},
        ]},
    ]
    out = F.to_openai_messages(system, messages)
    assert out[0] == {"role": "system", "content": "You are RegKnot."}
    assert out[1] == {"role": "user", "content": "First question"}
    assert out[3]["content"] == [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBOR"}},
        {"type": "text", "text": "What is this placard?"},
    ]
    # text-only block lists collapse to a string
    assert F.to_openai_messages("s", [{"role": "user", "content": [{"type": "text", "text": "a"},
                                                                   {"type": "text", "text": "b"}]}])[1] == \
        {"role": "user", "content": "a\n\nb"}


def test_request_parameters_by_model():
    assert F.request_kwargs("gpt-4o", "low", 2048) == {"max_tokens": 2048}
    assert F.request_kwargs("gpt-6-luna", "low", 2048) == {"max_completion_tokens": 2048 + 8192,
                                                           "reasoning_effort": "low"}
    assert F.request_kwargs("gpt-6-luna", "none", 2048) == {"max_completion_tokens": 2048,
                                                            "reasoning_effort": "none"}


def test_default_is_not_a_retiring_model():
    assert not F.FALLBACK_MODEL.startswith(("gpt-4o", "gpt-4.1"))
    assert F.FALLBACK_MODEL_ID == f"fallback:{F.FALLBACK_MODEL}"
