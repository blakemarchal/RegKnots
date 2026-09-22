"""2026-09-22 (U5) — the API routers' structured-output schemas.

The first tests in apps/api. Run from apps/api:
    uv run --extra dev python -m pytest tests -q
"""
import importlib

import pytest

SCHEMAS = [
    ("app.routers.me", "_RENEWAL_SCHEMA"),
    ("app.routers.me", "_CAREER_SCHEMA"),
    ("app.routers.me", "_VESSEL_ANALYSIS_SCHEMA"),
    ("app.routers.me", "_PSC_PREP_SCHEMA"),
    ("app.routers.me", "_CHANGELOG_SCHEMA"),
    ("app.routers.me", "_AUDIT_READINESS_SCHEMA"),
    ("app.routers.study", "_QUIZ_SCHEMA"),
    ("app.routers.study", "_GUIDE_SCHEMA"),
    ("app.routers.checklists", "_PSC_SCHEMA"),
    ("app.routers.credentials", "_CREDENTIAL_SCHEMA"),
    ("app.routers.documents", "_EXTRACTION_SCHEMA"),
]


def _walk(schema):
    yield schema
    for v in schema.get("properties", {}).values():
        yield from _walk(v)
    if "items" in schema:
        yield from _walk(schema["items"])
    for v in schema.get("anyOf", []):
        yield from _walk(v)


@pytest.mark.parametrize("module,name", SCHEMAS)
def test_schema_objects_are_closed(module, name):
    schema = getattr(importlib.import_module(module), name)
    assert schema["type"] == "object"
    for node in _walk(schema):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False
            assert set(node["required"]) <= set(node["properties"])
        for banned in ("minimum", "maximum", "minLength", "maxLength", "multipleOf"):
            assert banned not in node


def test_me_schemas_cover_every_key_the_consumers_read():
    """A key the consumer reads but the schema omits would silently be None forever."""
    me = importlib.import_module("app.routers.me")
    expected = {
        "_RENEWAL_SCHEMA": {"overall_status", "narrative", "requirements", "suggested_actions", "citations"},
        "_CAREER_SCHEMA": {"current_credentials", "cap_eligible_now", "within_reach", "narrative", "citations"},
        "_VESSEL_ANALYSIS_SCHEMA": {"narrative", "applicable_regulations", "inspection_focus", "required_certificates", "citations"},
        "_PSC_PREP_SCHEMA": {"narrative", "focus_areas", "common_deficiencies", "documents_to_have_ready", "citations"},
        "_CHANGELOG_SCHEMA": {"narrative", "items"},
        "_AUDIT_READINESS_SCHEMA": {"score_percent", "score_label", "narrative", "findings"},
    }
    for name, keys in expected.items():
        assert set(getattr(me, name)["properties"]) == keys, name


def _union_count(schema):
    return sum(1 for node in _walk(schema) if "anyOf" in node or isinstance(node.get("type"), list))


@pytest.mark.parametrize("module,name", SCHEMAS)
def test_schema_union_count_under_api_limit(module, name):
    """The API rejects schemas with too many union-typed parameters (20 in the
    first documents schema -> HTTP 400 'exponential compilation', caught by the
    2026-09-22 live validation). Keep every schema well under that."""
    schema = getattr(importlib.import_module(module), name)
    assert _union_count(schema) <= 8, f"{name}: {_union_count(schema)} union-typed params"


def test_documents_flatten_restores_null_and_string_contract():
    docs = importlib.import_module("app.routers.documents")
    out = docs._flatten_extraction({
        "vessel_name": "  ",
        "subchapter": "I",
        "route_limitations": ["Not more than 20 nm from a harbor of safe refuge"],
        "conditions_of_operation": [],
        "cargo_types": [],
        "other_fields": [],
    })
    assert out["vessel_name"] is None
    assert out["subchapter"] == "I"
    assert out["route_limitations"] == "Not more than 20 nm from a harbor of safe refuge"
    assert out["conditions_of_operation"] is None
    assert out["cargo_types"] == []          # cargo_types keeps its list contract
    multi = docs._flatten_extraction({"conditions_of_operation": ["a", "b"], "other_fields": []})
    assert multi["conditions_of_operation"] == ["a", "b"]


def test_documents_flatten_folds_other_fields_without_overwriting():
    docs = importlib.import_module("app.routers.documents")
    out = docs._flatten_extraction({
        "vessel_name": "MAERSK KINLOSS",
        "gross_tonnage": 74642,
        "other_fields": [
            {"name": "Port of Registry", "value": "New York"},
            {"name": "vessel name", "value": "SHOULD NOT OVERWRITE"},
            {"name": "  ", "value": "dropped"},
        ],
    })
    assert out == {
        "vessel_name": "MAERSK KINLOSS",
        "gross_tonnage": 74642,
        "port_of_registry": "New York",
    }
