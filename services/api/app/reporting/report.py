"""Deterministic JSON and Markdown release reports built from stored evidence."""
from __future__ import annotations

import json
from typing import Any

from app.infra.store import Store


def build_json_report(store: Store, run_id: str) -> dict[str, Any]:
    run = store.get_run(run_id)
    if run is None:
        raise ValueError("run not found")
    findings = store.list_findings(run_id, size=500)["items"]
    tests = store.list_test_executions(run_id)
    impacts = store.list_impacts(run_id)
    assessment = store.get_assessment(run_id)
    project = store.get_project(run["project_id"])
    return {
        "report_version": "1.0.0",
        "generated_at": run["finished_at"] or run["created_at"],
        "run": {
            "id": run["id"],
            "project": f"{project['owner']}/{project['repository']}" if project else None,
            "source_type": run["source_type"],
            "base_identity": run["base_identity"],
            "candidate_identity": run["candidate_identity"],
            "base_digest": run["base_digest"],
            "candidate_digest": run["candidate_digest"],
            "policy_version": run["policy_version"],
            "registry_revision": run["registry_revision"],
            "run_key": run["run_key"],
        },
        "findings": [{
            "rule_id": f["rule_id"], "rule_version": f["rule_version"],
            "surface": f["surface"], "location": f["location"],
            "before": f["before_value"], "after": f["after_value"],
            "classification": f["classification"], "severity": f["severity"],
            "reason": f["reason"], "verification_state": f["verification_state"],
        } for f in findings],
        "impacts": impacts,
        "tests": [{
            "suite_id": t["suite_id"], "status": t["status"],
            "duration_ms": t["duration_ms"], "exit_code": t["exit_code"],
            "fixture_digest": t["fixture_digest"], "image_ref": t["image_ref"],
        } for t in tests],
        "assessment": assessment,
        "provenance": "RippleGate deterministic rule engine; synthetic demo fixtures only",
    }


def build_markdown_report(store: Store, run_id: str) -> str:
    data = build_json_report(store, run_id)
    run = data["run"]
    assessment = data["assessment"] or {}
    lines: list[str] = []
    lines.append("# RippleGate Release Impact Report")
    lines.append("")
    lines.append(f"- Run: `{run['id']}`")
    lines.append(f"- Project: `{run['project']}`")
    src = "GitHub commit" if run["source_type"] == "GITHUB_COMMIT" else "fixture fingerprint"
    lines.append(f"- Inputs: base `{run['base_identity']}`, candidate `{run['candidate_identity']}` ({src})")
    lines.append(f"- Policy version: {run['policy_version']}; registry revision: {run['registry_revision']}")
    lines.append(f"- Outcome: **{assessment.get('outcome', 'PENDING')}**")
    lines.append("")
    if assessment.get("blocking_reasons"):
        lines.append("## Blocking reasons")
        for r in assessment["blocking_reasons"]:
            lines.append(f"- {r}")
        lines.append("")
    if assessment.get("unknowns"):
        lines.append("## Unknowns (fail closed)")
        for u in assessment["unknowns"]:
            lines.append(f"- {u}")
        lines.append("")
    lines.append("## Findings")
    if data["findings"]:
        lines.append("| Rule | Classification | Severity | Location | Verification |")
        lines.append("|---|---|---|---|---|")
        for f in data["findings"]:
            loc = f["location"].replace("|", "\\|")
            lines.append(
                f"| {f['rule_id']} | {f['classification']} | {f['severity']} | "
                f"`{loc}` | {f['verification_state']} |")
    else:
        lines.append("_No findings recorded._")
    lines.append("")
    lines.append("## Executed consumer evidence")
    if data["tests"]:
        lines.append("| Suite | Status | Exit | Duration (ms) | Fixture digest |")
        lines.append("|---|---|---|---|---|")
        for t in data["tests"]:
            lines.append(
                f"| {t['suite_id']} | {t['status']} | {t['exit_code']} | "
                f"{t['duration_ms']} | `{t['fixture_digest'][:16]}…` |")
    else:
        lines.append("_No consumer suite execution recorded._")
    lines.append("")
    lines.append("## Affected registered consumers")
    consumer_hits = [i for i in data["impacts"] if i["impact_state"] == "AFFECTED"]
    if consumer_hits:
        for i in consumer_hits:
            lines.append(f"- **{i['consumer_name']}** via {i['finding_rule_id']}: {i['reason']}")
    else:
        lines.append("_No registered consumer impacted (coverage caveat applies)._")
    lines.append("")
    lines.append("---")
    lines.append("Evidence is deterministic and immutable; the optional AI draft "
                 "summarizes it but never alters it. Human release authority is final.")
    lines.append(f"_Evidence digest: `{assessment.get('evidence_digest', 'n/a')}`_")
    return "\n".join(lines)
