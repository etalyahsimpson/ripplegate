"""Runner allowlist and execution controls (spec 13 matrix row 12)."""
from __future__ import annotations

import json
import os
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

from app.runner_bridge import load_runner_execute  # noqa: E402

execute_suite = load_runner_execute()

from services.runner.allowlist import RunnerAllowlistError, resolve_suite  # noqa: E402


CANDIDATE_ADDITIVE = json.loads(
    (REPO_ROOT / "examples" / "orders-api" / "openapi-candidate-additive.json").read_text())
CANDIDATE_BREAKING = json.loads(
    (REPO_ROOT / "examples" / "orders-api" / "openapi-candidate-breaking.json").read_text())


def test_unknown_suite_rejected():
    with pytest.raises(RunnerAllowlistError):
        resolve_suite("attacker-suite")


def test_allowlisted_suites_are_pinned():
    for suite in ("billing-contract", "reporting-contract"):
        allowed = resolve_suite(suite)
        assert allowed.script_relpath.endswith("contract.test.js")
        assert "latest" not in allowed.image_ref


def test_billing_breaks_on_breaking_candidate():
    record = execute_suite(suite_id="billing-contract",
                           candidate_document=CANDIDATE_BREAKING,
                           timeout_seconds=60,
                           project_root=str(REPO_ROOT))
    assert record["status"] == "FAILED"
    assert record["exit_code"] == 1
    assert "FAIL: response contains customer_id" in record["log"]
    assert len(record["fixture_digest"]) == 64


def test_billing_passes_on_additive_candidate():
    record = execute_suite(suite_id="billing-contract",
                           candidate_document=CANDIDATE_ADDITIVE,
                           timeout_seconds=60,
                           project_root=str(REPO_ROOT))
    assert record["status"] == "PASSED"
    assert record["exit_code"] == 0


def test_reporting_passes_on_both_candidates():
    for cand in (CANDIDATE_ADDITIVE, CANDIDATE_BREAKING):
        record = execute_suite(suite_id="reporting-contract",
                               candidate_document=cand,
                               timeout_seconds=60,
                               project_root=str(REPO_ROOT))
        assert record["status"] == "PASSED", record["log"][:200]


def test_timeout_is_a_distinct_status():
    # a suite that never finishes: emulate with timeout 0 (immediately expired)
    record = execute_suite(suite_id="billing-contract",
                           candidate_document=CANDIDATE_ADDITIVE,
                           timeout_seconds=0,
                           project_root=str(REPO_ROOT))
    assert record["status"] in ("TIMED_OUT", "INFRA_ERROR")


def test_execution_log_contains_fixed_argv_identity():
    record = execute_suite(suite_id="billing-contract",
                           candidate_document=CANDIDATE_ADDITIVE,
                           timeout_seconds=60,
                           project_root=str(REPO_ROOT))
    assert "argv (fixed allowlist vector)" in record["log"]


def test_no_docker_socket_mounted_in_api_container_definitions():
    compose = (REPO_ROOT / "docker-compose.yml")
    if compose.exists():
        text = compose.read_text()
        api_service = text.split("services:")[1]
        assert "/var/run/docker.sock" not in api_service, \
            "api/web containers must never mount the Docker socket"


def test_runner_log_sanitizer_redacts_secrets():
    sys.path.insert(0, str(REPO_ROOT / "services" / "runner"))
    from sanitize import sanitize_log
    dirty = ("token=abc123DEF456ghi789JKL\n"
             "contact: somebody@example.com\n"
             "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig\n"
             "aws key AKIAIOSFODNN7EXAMPLE")
    clean = sanitize_log(dirty)
    assert "abc123DEF456" not in clean
    assert "example.com" not in clean
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in clean
    assert "AKIAIOSFODNN7EXAMPLE" not in clean


def test_image_ref_records_execution_profile_honestly():
    record = execute_suite(suite_id="reporting-contract",
                           candidate_document=CANDIDATE_ADDITIVE,
                           timeout_seconds=60,
                           project_root=str(REPO_ROOT))
    # either a pinned container image or an explicit local-node marker, never 'latest'
    assert record["image_ref"] and "latest" not in record["image_ref"]
