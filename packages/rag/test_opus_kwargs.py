"""2026-09-22 — Opus 5.5 call-shape helpers (engine._opus_kwargs / _text_of).

Opus 5.5 always thinks and opens every response with a `thinking` block,
so the engine (a) sends an explicit effort + larger cap for Opus only and
(b) reads answer text by block type, never by position.
"""
from types import SimpleNamespace

from rag.engine import _MAX_TOKENS, _OPUS_MAX_TOKENS, _is_opus, _opus_kwargs, _text_of


def test_is_opus():
    assert _is_opus("claude-opus-5-5")
    assert _is_opus("claude-opus-4-8")
    assert not _is_opus("claude-sonnet-5")
    assert not _is_opus("claude-haiku-4-5-20251001")
    assert not _is_opus("")
    assert not _is_opus(None)


def test_opus_kwargs_sets_cap_and_effort_for_opus_only():
    kw = _opus_kwargs("claude-opus-5-5", "medium")
    assert kw == {"max_tokens": _OPUS_MAX_TOKENS, "output_config": {"effort": "medium"}}
    # Haiku 4.5 rejects output_config — it must never be sent for non-Opus models.
    assert _opus_kwargs("claude-haiku-4-5-20251001", "high") == {"max_tokens": _MAX_TOKENS}
    assert _opus_kwargs("claude-sonnet-5", "high") == {"max_tokens": _MAX_TOKENS}
    assert _opus_kwargs("fallback:gpt-4o", "high") == {"max_tokens": _MAX_TOKENS}


def _resp(*blocks):
    return SimpleNamespace(content=list(blocks))


def test_text_of_skips_leading_thinking_block():
    resp = _resp(
        SimpleNamespace(type="thinking", thinking=""),
        SimpleNamespace(type="text", text="Rule 13 applies."),
    )
    assert _text_of(resp) == "Rule 13 applies."


def test_text_of_joins_text_blocks_and_tolerates_none():
    resp = _resp(
        SimpleNamespace(type="text", text="A"),
        SimpleNamespace(type="thinking", thinking=""),
        SimpleNamespace(type="text", text="B"),
    )
    assert _text_of(resp) == "AB"
    assert _text_of(_resp(SimpleNamespace(type="thinking", thinking=""))) == ""
    assert _text_of(_resp()) == ""
