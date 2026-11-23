"""Release policy outcomes (spec 13 matrix row 7)."""
from __future__ import annotations

from types import SimpleNamespace

from app.domain.release_policy import (
    PolicyInput, PolicySnapshot, compute_evidence_digest, evaluate_policy,
    validate_transition, InvalidTransition,
)


def _finding(rule_id="API-RESP-REQUIRED-REMOVED", classification="BREAKING"):
    return SimpleNamespace(rule_id=rule_id, classification=classification,
                           location="/paths/x", surface="RESPONSE")


def _policy():
    return PolicySnapshot(version=1,
                          block_rules=("API-RESP-REQUIRED-REMOVED",),
                          mandatory_suites=("billing-contract", "reporting-contract"),
                          unknown_strategy="REVIEW")


def test_mandatory_consumer_failure_blocks():
    decision = evaluate_policy(PolicyInput(
        findings=[], impacts=[],
        test_executions=[{"suite_id": "billing-contract", "status": "FAILED"},
                         {"suite_id": "reporting-contract", "status": "PASSED"}],
        policy=_policy()))
    assert decision.outcome == "BLOCK"
    assert any("billing-contract" in r for r in decision.blocking_reasons)


def test_configured_hard_rule_blocks():
    decision = evaluate_policy(PolicyInput(
        findings=[_finding()], impacts=[],
        test_executions=[{"suite_id": "billing-contract", "status": "PASSED"},
                         {"suite_id": "reporting-contract", "status": "PASSED"}],
        policy=_policy()))
    assert decision.outcome == "BLOCK"


def test_unknown_yields_review_never_pass():
    decision = evaluate_policy(PolicyInput(
        findings=[_finding(rule_id="API-REF-UNSUPPORTED", classification="UNKNOWN")],
        impacts=[], test_executions=[
            {"suite_id": "billing-contract", "status": "PASSED"},
            {"suite_id": "reporting-contract", "status": "PASSED"}],
        policy=_policy()))
    assert decision.outcome == "REVIEW"
    assert decision.unknowns


def test_infrastructure_error_is_error_not_pass():
    decision = evaluate_policy(PolicyInput(
        findings=[], impacts=[], test_executions=[], policy=_policy(),
        infrastructure_error=True))
    assert decision.outcome == "ERROR"


def test_missing_mandatory_suite_blocks():
    decision = evaluate_policy(PolicyInput(
        findings=[], impacts=[], test_executions=[], policy=_policy()))
    assert decision.outcome == "BLOCK"
    assert any("no execution record" in r for r in decision.blocking_reasons)


def test_timed_out_mandatory_suite_fails_closed():
    decision = evaluate_policy(PolicyInput(
        findings=[], impacts=[],
        test_executions=[{"suite_id": "billing-contract", "status": "TIMED_OUT"},
                         {"suite_id": "reporting-contract", "status": "PASSED"}],
        policy=_policy()))
    assert decision.outcome == "BLOCK"


def test_infra_error_mandatory_suite_fails_closed():
    decision = evaluate_policy(PolicyInput(
        findings=[], impacts=[],
        test_executions=[{"suite_id": "billing-contract", "status": "INFRA_ERROR"},
                         {"suite_id": "reporting-contract", "status": "PASSED"}],
        policy=_policy()))
    assert decision.outcome == "BLOCK"


def test_all_pass_and_no_blockers_yields_pass():
    decision = evaluate_policy(PolicyInput(
        findings=[_finding(classification="ADDITIVE")], impacts=[],
        test_executions=[{"suite_id": "billing-contract", "status": "PASSED"},
                         {"suite_id": "reporting-contract", "status": "PASSED"}],
        policy=_policy()))
    assert decision.outcome == "PASS"


def test_potentially_breaking_yields_review():
    decision = evaluate_policy(PolicyInput(
        findings=[_finding(rule_id="API-RESP-ENUM-EXPANDED",
                           classification="POTENTIALLY_BREAKING")],
        impacts=[],
        test_executions=[{"suite_id": "billing-contract", "status": "PASSED"},
                         {"suite_id": "reporting-contract", "status": "PASSED"}],
        policy=_policy()))
    assert decision.outcome == "REVIEW"


def test_incomplete_coverage_yields_review():
    decision = evaluate_policy(PolicyInput(
        findings=[], impacts=[],
        test_executions=[{"suite_id": "billing-contract", "status": "PASSED"},
                         {"suite_id": "reporting-contract", "status": "PASSED"}],
        policy=_policy(), coverage_complete=False))
    assert decision.outcome == "REVIEW"


def test_unsupported_construct_yields_review():
    decision = evaluate_policy(PolicyInput(
        findings=[], impacts=[],
        test_executions=[{"suite_id": "billing-contract", "status": "PASSED"},
                         {"suite_id": "reporting-contract", "status": "PASSED"}],
        policy=_policy(),
        unsupported_constructs=[{"location": "/paths/x", "construct": "oneOf",
                                 "detail": "unsupported"}]))
    assert decision.outcome == "REVIEW"


def test_unknown_strategy_block_escalates():
    policy = PolicySnapshot(version=1, block_rules=(), mandatory_suites=(),
                            unknown_strategy="BLOCK")
    decision = evaluate_policy(PolicyInput(
        findings=[_finding(classification="UNKNOWN")], impacts=[],
        test_executions=[], policy=policy))
    assert decision.outcome == "BLOCK"


def test_evidence_digest_is_deterministic_and_sensitive():
    rows = [{"rule_id": "R", "location": "/x", "classification": "BREAKING"}]
    d1 = compute_evidence_digest("run", rows, [{"suite_id": "s", "status": "PASSED"}], "PASS")
    d2 = compute_evidence_digest("run", rows, [{"suite_id": "s", "status": "PASSED"}], "PASS")
    d3 = compute_evidence_digest("run", rows, [{"suite_id": "s", "status": "FAILED"}], "BLOCK")
    assert d1 == d2 and len(d1) == 64 and d1 != d3


def test_state_machine_transitions():
    validate_transition("QUEUED", "PARSING")
    validate_transition("PARSING", "COMPLETED")
    validate_transition("TESTING", "ERROR")
    for bad in (("PARSING", "QUEUED"), ("COMPLETED", "PARSING"), ("ERROR", "COMPLETED")):
        try:
            validate_transition(*bad)
            raise AssertionError(f"allowed {bad}")
        except InvalidTransition:
            pass


def test_duplicate_execution_status_flavors_distinguish():
    for status in ("FAILED", "TIMED_OUT", "INFRA_ERROR", "NOT_RUN"):
        decision = evaluate_policy(PolicyInput(
            findings=[], impacts=[],
            test_executions=[{"suite_id": "billing-contract", "status": status},
                             {"suite_id": "reporting-contract", "status": "PASSED"}],
            policy=_policy()))
        assert decision.outcome == "BLOCK", status
