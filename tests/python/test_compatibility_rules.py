"""Compatibility rule directionality (spec 13 matrix row 3)."""
from __future__ import annotations

import json
import pathlib

from app.parsing.openapi_model import normalize
from app.domain.rules import run_engine

ORDERS = pathlib.Path(__file__).resolve().parents[2] / "examples" / "orders-api"


def _norm(name: str):
    doc = json.loads((ORDERS / name).read_text())
    return normalize(doc, doc["openapi"])


def _findings(before_name: str, after_name: str):
    return run_engine(_norm(before_name), _norm(after_name)).findings


def test_path_removal_is_breaking():
    base = {
        "openapi": "3.0.3", "info": {"title": "t", "version": "1"},
        "paths": {
            "/a/": {"get": {"responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {"type": "object"}}}}}}},
            "/b/": {"get": {"responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {"type": "object"}}}}}}},
        },
    }
    removed = json.loads(json.dumps(base))
    del removed["paths"]["/b/"]
    fs = run_engine(normalize(base, "3.0.3"), normalize(removed, "3.0.3")).findings
    assert any(f.rule_id == "API-PATH-REMOVED" and f.classification == "BREAKING"
               for f in fs)


def test_required_request_field_added_is_breaking():
    doc = {
        "openapi": "3.0.3",
        "info": {"title": "t", "version": "1"},
        "paths": {"/o/": {"post": {
            "requestBody": {"content": {"application/json": {"schema": {
                "type": "object", "properties": {"a": {"type": "string"}}}}}},
            "responses": {"200": {"description": "ok"}}}}},
    }
    candidate = json.loads(json.dumps(doc))
    candidate["paths"]["/o/"]["post"]["requestBody"]["content"]["application/json"]["schema"]["required"] = ["a"]
    fs = run_engine(normalize(doc, "3.0.3"), normalize(candidate, "3.0.3")).findings
    assert any(f.rule_id == "API-REQ-REQUIRED-ADDED" and f.classification == "BREAKING" for f in fs)


def test_optional_response_addition_is_additive():
    fs = _findings("openapi-base.json", "openapi-candidate-additive.json")
    assert fs and all(f.rule_id == "API-RESP-OPTIONAL-ADDED" and f.classification == "ADDITIVE"
                      for f in fs)


def test_rename_produces_required_removed_breaking():
    fs = _findings("openapi-base.json", "openapi-candidate-breaking.json")
    removed = [f for f in fs if f.rule_id == "API-RESP-REQUIRED-REMOVED"]
    assert removed and removed[0].classification == "BREAKING"
    assert removed[0].severity == "critical"
    assert "customer_id" in removed[0].location


def test_enum_expansion_is_potentially_breaking():
    doc = {
        "openapi": "3.0.3",
        "info": {"title": "t", "version": "1"},
        "paths": {"/e/": {"get": {"responses": {"200": {"description": "ok",
            "content": {"application/json": {"schema": {
                "type": "object", "properties": {"s": {"type": "string", "enum": ["a", "b"]}}}}}}}}}},
    }
    cand = json.loads(json.dumps(doc))
    cand["paths"]["/e/"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["properties"]["s"]["enum"] = ["a", "b", "c"]
    fs = run_engine(normalize(doc, "3.0.3"), normalize(cand, "3.0.3")).findings
    assert any(f.rule_id == "API-RESP-ENUM-EXPANDED" and f.classification == "POTENTIALLY_BREAKING" for f in fs)


def test_request_enum_narrowing_is_breaking():
    doc = {
        "openapi": "3.0.3", "info": {"title": "t", "version": "1"},
        "paths": {"/e/": {"post": {
            "requestBody": {"content": {"application/json": {"schema": {
                "type": "object", "properties": {"s": {"type": "string", "enum": ["a", "b", "c"]}}}}}},
            "responses": {"200": {"description": "ok"}}}}},
    }
    cand = json.loads(json.dumps(doc))
    cand["paths"]["/e/"]["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"]["s"]["enum"] = ["a", "b"]
    fs = run_engine(normalize(doc, "3.0.3"), normalize(cand, "3.0.3")).findings
    assert any(f.rule_id == "API-REQ-ENUM-REMOVED" and f.classification == "BREAKING" for f in fs)


def test_response_type_change_is_breaking():
    doc = {
        "openapi": "3.0.3", "info": {"title": "t", "version": "1"},
        "paths": {"/t/": {"get": {"responses": {"200": {"description": "ok",
            "content": {"application/json": {"schema": {
                "type": "object", "properties": {"n": {"type": "integer"}}}}}}}}}},
    }
    cand = json.loads(json.dumps(doc))
    cand["paths"]["/t/"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["properties"]["n"]["type"] = "string"
    fs = run_engine(normalize(doc, "3.0.3"), normalize(cand, "3.0.3")).findings
    hit = [f for f in fs if f.rule_id == "API-RESP-TYPE-CHANGED"]
    assert hit and hit[0].classification == "BREAKING"


def test_integer_widened_to_number_is_not_breaking():
    doc = {
        "openapi": "3.0.3", "info": {"title": "t", "version": "1"},
        "paths": {"/t/": {"get": {"responses": {"200": {"description": "ok",
            "content": {"application/json": {"schema": {
                "type": "object", "properties": {"n": {"type": "integer"}}}}}}}}}},
    }
    cand = json.loads(json.dumps(doc))
    cand["paths"]["/t/"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["properties"]["n"]["type"] = "number"
    fs = run_engine(normalize(doc, "3.0.3"), normalize(cand, "3.0.3")).findings
    assert not any(f.rule_id == "API-RESP-TYPE-CHANGED" for f in fs)


def test_no_change_no_findings():
    fs = _findings("openapi-base.json", "openapi-base.json")
    assert fs == []


def test_rules_have_versions_and_surfaces():
    fs = _findings("openapi-base.json", "openapi-candidate-breaking.json")
    for f in fs:
        assert f.rule_version == "1.0.0"
        assert f.surface in ("REQUEST", "RESPONSE", "HTTP_OPERATION", "DB_MIGRATION")
        assert f.severity in ("critical", "high", "medium", "low", "info")
        assert f.verification_state == "STATIC_ONLY"
