"""2026-09-28 — messages.model_used aliases: explicit keys, then the model family.

The D6.73 failure: a model ID missing from _MODEL_ALIAS was stored as NULL.
"""
from app.routers.chat import _model_alias


def test_explicit_keys():
    assert _model_alias("claude-haiku-4-5-20251001") == "haiku"
    assert _model_alias("claude-sonnet-5-5") == "sonnet"
    assert _model_alias("claude-sonnet-5") == "sonnet"
    assert _model_alias("claude-opus-5-5") == "opus"
    assert _model_alias("fallback:gpt-4o") == "fallback_gpt4o"


def test_unlisted_versions_fall_back_to_their_family():
    assert _model_alias("claude-haiku-5-5") == "haiku"
    assert _model_alias("claude-sonnet-6") == "sonnet"
    assert _model_alias("claude-opus-6") == "opus"


def test_unknown_and_empty_stay_none():
    assert _model_alias("gpt-4o") is None
    assert _model_alias("") is None
    assert _model_alias(None) is None
