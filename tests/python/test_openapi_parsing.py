"""OpenAPI JSON/YAML safe-parsing gate (spec 13 matrix row 1)."""
from __future__ import annotations

import json
import pathlib

import pytest

from app.parsing.openapi_loader import (
    MAX_BYTES, ParseLimitError, UnsupportedConstructError, load_document,
    validate_openapi_version,
)

ORDERS = pathlib.Path(__file__).resolve().parents[2] / "examples" / "orders-api"


def test_same_semantics_from_json_and_yaml():
    base_json = json.loads((ORDERS / "openapi-base.json").read_text())
    base_yaml = load_document((ORDERS / "openapi-base.yaml").read_text(), "yaml")
    assert base_json == base_yaml


def test_reject_yaml_anchors_and_aliases():
    yaml_with_alias = """
openapi: 3.0.3
info: &info
  title: Demo
  version: 1.0.0
paths: {}
also: *info
"""
    with pytest.raises(UnsupportedConstructError):
        load_document(yaml_with_alias, "yaml")


def test_reject_size_bomb():
    big = '{"k": "' + "x" * 1_100_000 + '"}'
    assert len(big.encode()) > MAX_BYTES
    with pytest.raises(ParseLimitError):
        load_document(big, "json")




def test_reject_wide_node_bomb():
    # 30,000 sibling keys: node budget exceeded while staying under 1 MiB
    wide = "{" + ",".join(f'"k{i}":1' for i in range(30_000)) + "}"
    assert len(wide.encode()) < MAX_BYTES
    with pytest.raises(ParseLimitError):
        load_document(wide, "json")


def test_reject_deep_nesting():
    nested = '{"a":' * 40 + "1" + "}" * 40
    with pytest.raises(ParseLimitError):
        load_document(nested, "json")


def test_reject_external_ref_at_load_time_is_parser_level():
    # external refs are refused during normalization, not silently fetched
    doc = json.loads((ORDERS / "openapi-candidate-external-ref.json").read_text())
    from app.parsing.openapi_model import normalize
    with pytest.raises(UnsupportedConstructError):
        normalize(doc, validate_openapi_version(doc))


def test_invalid_json_error_is_precise():
    with pytest.raises(ValueError) as excinfo:
        load_document("{oops", "json")
    assert "line" in str(excinfo.value) or "invalid JSON" in str(excinfo.value)


def test_root_must_be_object():
    with pytest.raises(ValueError):
        load_document("[1,2,3]", "json")


def test_bad_format_name_rejected():
    with pytest.raises(ValueError):
        load_document("{}", "xml")


def test_unsupported_openapi_version():
    with pytest.raises(UnsupportedConstructError):
        validate_openapi_version({"openapi": "2.0"})
