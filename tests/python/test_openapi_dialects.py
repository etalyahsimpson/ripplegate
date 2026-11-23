"""OpenAPI 3.0 vs 3.1 dialect semantics (spec 13 matrix row 2)."""
from __future__ import annotations

import pytest

from app.parsing.openapi_loader import UnsupportedConstructError
from app.parsing.openapi_model import normalize


def _doc(version: str, schema: dict) -> dict:
    return {
        "openapi": version,
        "info": {"title": "t", "version": "1"},
        "paths": {"/x/": {"get": {"responses": {"200": {
            "description": "ok",
            "content": {"application/json": {"schema": schema}},
        }}}}},
    }


def test_30_nullable_maps_to_normalized_nullability():
    doc = _doc("3.0.3", {"type": "object", "properties": {"a": {"type": "string", "nullable": True}}})
    norm = normalize(doc, "3.0.3")
    prop = norm.operations[0].response_schemas["200"].properties["a"]
    assert prop.nullable is True
    assert prop.types == ("string",)


def test_31_type_union_maps_to_same_normalized_nullability():
    doc = _doc("3.1.0", {"type": "object", "properties": {"a": {"type": ["string", "null"]}}})
    norm = normalize(doc, "3.1.0")
    prop = norm.operations[0].response_schemas["200"].properties["a"]
    assert prop.nullable is True
    assert prop.types == ("string",)


def test_30_and_31_nullable_are_equivalent_after_normalization():
    d30 = normalize(_doc("3.0.3", {"type": "object", "properties": {"a": {"type": "string", "nullable": True}}}), "3.0.3")
    d31 = normalize(_doc("3.1.0", {"type": "object", "properties": {"a": {"type": ["string", "null"]}}}), "3.1.0")
    p30 = d30.operations[0].response_schemas["200"].properties["a"]
    p31 = d31.operations[0].response_schemas["200"].properties["a"]
    assert (p30.types, p30.nullable) == (p31.types, p31.nullable)


def test_array_type_only_in_31():
    with pytest.raises(UnsupportedConstructError):
        normalize(_doc("3.0.3", {"type": "object", "properties": {"a": {"type": ["string"]}}}), "3.0.3")


def test_nullable_keyword_rejected_in_31():
    with pytest.raises(UnsupportedConstructError):
        normalize(_doc("3.1.0", {"type": "object", "properties": {"a": {"type": "string", "nullable": True}}}), "3.1.0")


def test_unsupported_union_one_of_is_unknown_not_compatible():
    with pytest.raises(UnsupportedConstructError):
        normalize(_doc("3.1.0", {"oneOf": [{"type": "string"}, {"type": "integer"}]}), "3.1.0")


def test_circular_ref_detected():
    doc = _doc("3.0.3", {"$ref": "#/components/schemas/Node"})
    doc["components"] = {"schemas": {"Node": {"type": "object", "properties": {"next": {"$ref": "#/components/schemas/Node"}}}}}
    with pytest.raises(UnsupportedConstructError, match="circular"):
        normalize(doc, "3.0.3")
