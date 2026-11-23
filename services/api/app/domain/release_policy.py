"""Deterministic release policy and run state machine (spec 5.5).

Outcome calculus, fail-closed:
  BLOCK   when a mandatory controlled consumer suite reproducibly fails, or a
          configured hard breaking rule is violated.
  REVIEW  when an unknown/unsupported finding, incomplete dependency coverage,
          or a policy-relevant POTENTIALLY_BREAKING finding remains.
  PASS    only when all declared mandatory suites pass, no configured blocking
          rule fires, and coverage prerequisites hold.
  ERROR   when analysis could not complete; never a compatibility verdict.

The optional AI summary generator has READ-ONLY access to this input and can
never mutate the outcome. Humans remain the release authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

RUN_STATES = (
    "QUEUED", "PARSING", "DIFFED", "IMPACT_MAPPED", "TESTING",
    "ASSESSED", "COMPLETED", "ERROR", "CANCELLED",
)
_STATE_ORDER = {name: i for i, name in enumerate(
    ["QUEUED", "PARSING", "DIFFED", "IMPACT_MAPPED", "TESTING", "ASSESSED", "COMPLETED"])}

OUTCOMES = ("BLOCK", "REVIEW", "PASS", "ERROR")


class InvalidTransition(ValueError):
    pass


def validate_transition(current: str, target: str) -> None:
    if current == target:
        return
    terminal = {"COMPLETED", "ERROR", "CANCELLED"}
    if current in terminal:
        raise InvalidTransition(f"run is {current}; terminal states are immutable")
    if target in ("ERROR", "CANCELLED"):
        return  # allowed from any non-terminal state
    if _STATE_ORDER.get(target, -1) <= _STATE_ORDER.get(current, -1):
        raise InvalidTransition(f"cannot move from {current} backwards/sideways to {target}")


@dataclass
class PolicySnapshot:
    version: int
    block_rules: tuple[str, ...]
    mandatory_suites: tuple[str, ...]
    unknown_strategy: str  # REVIEW | BLOCK


@dataclass
class PolicyInput:
    findings: list[Any]
    impacts: list[Any]
    test_executions: list[Any]  # dicts with suite_id/status
    policy: PolicySnapshot
    coverage_complete: bool = True
    coverage_unknown_consumers: bool = False
    infrastructure_error: bool = False
    unsupported_constructs: list[dict[str, str]] = field(default_factory=list)


@dataclass
class PolicyDecision:
    outcome: str
    blocking_reasons: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)


def evaluate_policy(inp: PolicyInput) -> PolicyDecision:
    if inp.infrastructure_error:
        return PolicyDecision(outcome="ERROR",
                               blocking_reasons=[],
                               unknowns=["analysis infrastructure error; no compatibility verdict is possible"])

    block_reasons: list[str] = []
    unknowns: list[str] = []

    # 1. executed consumer evidence: mandatory suites
    executed = {t["suite_id"]: t for t in inp.test_executions}
    for suite in inp.policy.mandatory_suites:
        te = executed.get(suite)
        if te is None:
            block_reasons.append(f"mandatory suite {suite} produced no execution record")
        elif te["status"] == "FAILED":
            block_reasons.append(f"mandatory consumer suite {suite} FAILED (executed assertion)")
        elif te["status"] == "TIMED_OUT":
            block_reasons.append(f"mandatory consumer suite {suite} TIMED_OUT (no verdict)")
        elif te["status"] == "INFRA_ERROR":
            block_reasons.append(f"mandatory consumer suite {suite} INFRA_ERROR (fail closed)")
        elif te["status"] == "NOT_RUN":
            block_reasons.append(f"mandatory consumer suite {suite} was NOT_RUN")

    # 2. configured hard rules
    fired = {f.rule_id for f in inp.findings if f.classification == "BREAKING"}
    for rule in inp.policy.block_rules:
        if rule in fired:
            block_reasons.append(f"configured blocking rule {rule} fired")

    # 3. unknown / unsupported
    for f in inp.findings:
        if f.classification == "UNKNOWN":
            unknowns.append(f"finding {f.rule_id} at {f.location} is UNKNOWN")
    for u in inp.unsupported_constructs:
        unknowns.append(f"unsupported construct at {u.get('location')}: {u.get('detail')}")
    if not inp.coverage_complete:
        unknowns.append("dependency coverage is incomplete for the analyzed surface")
    if inp.coverage_unknown_consumers:
        unknowns.append("consumer coverage attestation is missing or out of scope")

    # 4. potentially breaking findings
    pb = [f for f in inp.findings if f.classification == "POTENTIALLY_BREAKING"]
    for f in pb:
        unknowns.append(
            f"potentially breaking finding {f.rule_id} at {f.location} requires review")

    if block_reasons:
        return PolicyDecision(outcome="BLOCK", blocking_reasons=block_reasons, unknowns=unknowns)

    # fail closed on unknowns unless strategy is REVIEW (which still yields REVIEW, never PASS)
    if unknowns:
        if inp.policy.unknown_strategy == "BLOCK":
            return PolicyDecision(outcome="BLOCK", blocking_reasons=unknowns, unknowns=[])
        return PolicyDecision(outcome="REVIEW", blocking_reasons=[], unknowns=unknowns)

    # PASS requires every mandatory suite to have PASSED
    all_passed = all(
        executed.get(s, {}).get("status") == "PASSED" for s in inp.policy.mandatory_suites
    ) if inp.policy.mandatory_suites else True
    if not all_passed:
        return PolicyDecision(
            outcome="REVIEW",
            unknowns=["mandatory suites have not all completed with PASSED"])
    return PolicyDecision(outcome="PASS")


def compute_evidence_digest(run_id: str, finding_rows: list[dict[str, Any]],
                            test_rows: list[dict[str, Any]],
                            outcome: str) -> str:
    """SHA-256 over canonical evidence so the assessment is recomputable/auditable."""
    import hashlib
    import json
    payload = json.dumps({
        "run_id": run_id,
        "findings": sorted(
            ({"rule_id": f["rule_id"], "location": f["location"],
              "classification": f["classification"]} for f in finding_rows),
            key=lambda x: (x["rule_id"], x["location"])),
        "tests": sorted(
            ({"suite_id": t["suite_id"], "status": t["status"]} for t in test_rows),
            key=lambda x: x["suite_id"]),
        "outcome": outcome,
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
