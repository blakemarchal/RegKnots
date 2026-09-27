"""2026-09-27 — the model-led grounding edits (under test) still apply to the
shipped system prompt. If a prompt change moves their target text, the
comparison harness would fail mid-run; this catches it in CI."""
import pytest

from rag.prompts import MODEL_LED_GROUNDING, SYSTEM_PROMPT, apply_prompt_edits, assemble_system_prompt


def test_every_edit_target_occurs_once_in_the_assembled_prompt():
    for precision in (False, True):
        full = assemble_system_prompt(precision_mode=precision)
        edited = apply_prompt_edits(full, MODEL_LED_GROUNDING)
        assert "Base answers ONLY on the provided regulation context" not in edited
        assert "not in the excerpts retrieved here" in edited
        assert "IS the set of sources you may cite" not in edited


def test_safety_rules_survive_the_edits():
    edited = apply_prompt_edits(SYSTEM_PROMPT, MODEL_LED_GROUNDING)
    for kept in ("NEVER ASSERT NON-EXISTENCE", "NO HALLUCINATED RECOMMENDATIONS", "UN number"):
        assert kept in edited


def test_a_missing_target_is_an_error():
    with pytest.raises(ValueError, match="found 0 times"):
        apply_prompt_edits("unrelated text", MODEL_LED_GROUNDING)


def test_assembly_applies_model_led_except_in_precision_mode():
    led = assemble_system_prompt(model_led=True)
    assert "not in the excerpts retrieved here" in led
    assert "Base answers ONLY on the provided regulation context" not in led
    strict = assemble_system_prompt(model_led=True, precision_mode=True)
    assert "Base answers ONLY on the provided regulation context" in strict
    assert assemble_system_prompt() == assemble_system_prompt(model_led=False)


def test_engine_and_config_carry_the_flag():
    import inspect

    import rag.engine as E
    for fn in (E.chat, E.chat_with_progress):
        assert "model_led_grounding_enabled" in inspect.signature(fn).parameters
