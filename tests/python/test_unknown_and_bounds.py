"""Negative/unknown paths never report compatible (spec 13 matrix row 4)."""
from __future__ import annotations

import json

import pytest

from app.parsing.openapi_loader import (
    ParseLimitError, UnsupportedConstructError, load_document,
    validate_openapi_version,
)
from app.parsing.openapi_model import normalize
from app.domain.rules import run_engine


def _wrap(schema: dict) -> dict:
    return {
        "openapi": "3.0.3", "info": {"title": "t", "version": "1"},
        "paths": {"/x/": {"get": {"responses": {"200": {"description": "ok",
            "content": {"application/json": {"schema": schema}}}}}}},
    }


def test_external_ref_is_refused():
    doc = _wrap({"$ref": "https://schemas.demo.invalid/order.yaml"})
    with pytest.raises(UnsupportedConstructError, match="external"):
        normalize(doc, validate_openapi_version(doc))


def test_non_components_local_ref_is_refused():
    doc = _wrap({"$ref": "#/paths"})
    with pytest.raises(UnsupportedConstructError, match="local"):
        normalize(doc, validate_openapi_version(doc))


def test_oneof_is_unsupported():
    with pytest.raises(UnsupportedConstructError):
        normalize(_wrap({"oneOf": [{"type": "string"}, {"type": "object"}]}), "3.0.3")


def test_anyof_is_unsupported():
    with pytest.raises(UnsupportedConstructError):
        normalize(_wrap({"anyOf": [{"type": "string"}]}), "3.0.3")


def test_allof_is_unsupported():
    with pytest.raises(UnsupportedConstructError):
        normalize(_wrap({"allOf": [{"type": "object"}]}), "3.0.3")


def test_discriminator_is_unsupported():
    with pytest.raises(UnsupportedConstructError):
        normalize(_wrap({"type": "object", "discriminator": {"propertyName": "t"}}), "3.0.3")


def test_additional_properties_schema_is_unsupported():
    with pytest.raises(UnsupportedConstructError):
        normalize(_wrap({"type": "object", "additionalProperties": {"type": "string"}}), "3.0.3")


def test_invalid_json_never_compatible():
    with pytest.raises(ValueError):
        load_document("{not json", "json")


def test_oversized_document_rejected():
    with pytest.raises(ParseLimitError):
        load_document('{"k": "' + "x" * 1_100_000 + '"}', "json")


def test_circular_components_ref_refused():
    doc = _wrap({"$ref": "#/components/schemas/A"})
    doc["components"] = {"schemas": {"A": {"type": "object", "properties": {
        "b": {"$ref": "#/components/schemas/A"}}}}}
    with pytest.raises(UnsupportedConstructError, match="circular"):
        normalize(doc, "3.0.3")


def test_removed_and_added_cancel_out_is_reported_not_hidden():
    # rename shows BOTH removal (breaking) and addition (additive)
    from pathlib import Path
    orders = Path(__file__).resolve().parents[2] / "examples" / "orders-api"
    base = json.loads((orders / "openapi-base.json").read_text())
    breaking = json.loads((orders / "openapi-candidate-breaking.json").read_text())
    res = run_engine(normalize(base, "3.0.3"), normalize(breaking, "3.0.3"))
    rules = {f.rule_id for f in res.findings}
    assert "API-RESP-REQUIRED-REMOVED" in rules
    assert "API-RESP-OPTIONAL-ADDED" in rules


def test_missing_ref_target_is_explicit():
    doc = _wrap({"$ref": "#/components/schemas/Missing"})
    doc["components"] = {"schemas": {"Other": {"type": "object"}}}
    with pytest.raises(UnsupportedConstructError, match="missing"):
        normalize(doc, "3.0.3")
