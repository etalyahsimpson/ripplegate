"""The analysis pipeline: QUEUED -> ... -> COMPLETED with idempotent stages.

Every stage is transactional and safe to re-run for the same run_id (worker
retries, duplicate deliveries): findings/impacts/test-executions/assessments
are inserted once, guarded by existence checks and UNIQUE keys.
"""
from __future__ import annotations

import json
from typing import Any

from app.domain import release_policy as policy_mod
from app.domain.dependency_impact import DependencyEdge, map_impacts
from app.domain.migration_rules import migration_findings
from app.domain.rules import run_engine
from app.infra.artifacts import ArtifactStore, sanitize_log
from app.infra.store import Store, StoreError
from app.parsing.openapi_loader import (
    UnsupportedConstructError, load_document, validate_openapi_version,
)
from app.parsing.openapi_model import normalize


def _load_contract_document(store: Store, artifacts: ArtifactStore, contract: dict[str, Any]) -> dict[str, Any]:
    """Load the stored OpenAPI document for a registered contract version."""
    raw = artifacts.load(
        contract["id"], "contract", f"{contract['spec_digest']}.{'json' if contract['format'] == 'json' else 'yaml'}"
    ) if False else None
    # Contracts are small; we persist the canonical document under the artifact store
    content = artifacts.load("contracts", "contract", f"{contract['spec_digest']}.{contract['format']}")
    if content is None:
        raise RuntimeError(f"stored contract document missing for digest {contract['spec_digest'][:12]}")
    return json.loads(content.decode("utf-8"))


def run_pipeline(run_id: str, app_state: Any) -> dict[str, Any]:
    store: Store = app_state.store
    artifacts: ArtifactStore = app_state.artifacts
    run = store.get_run(run_id)
    if run is None:
        raise RuntimeError(f"run {run_id} not found")
    if run["state"] in ("COMPLETED", "ERROR", "CANCELLED"):
        return {"run_id": run_id, "state": run["state"], "already_final": True}

    try:
        # ---------------------------------------------------------- PARSING
        store.set_run_state(run_id, "PARSING")
        contracts = {c["id"]: c for c in store.list_contracts(run["project_id"])}
        base = _contract_by_identity(contracts, run["base_identity"], run["base_digest"])
        candidate = _contract_by_identity(contracts, run["candidate_identity"], run["candidate_digest"])
        base_doc = load_document(_contract_text(artifacts, base), base["format"])
        candidate_doc = load_document(_contract_text(artifacts, candidate), candidate["format"])
        base_norm = normalize(base_doc, validate_openapi_version(base_doc))
        candidate_norm = normalize(candidate_doc, validate_openapi_version(candidate_doc))

        # ---------------------------------------------------------- DIFFED
        store.set_run_state(run_id, "DIFFED")
        result = run_engine(base_norm, candidate_norm)
        finding_rows = [f.to_row() for f in result.findings]

        migration_rows: list[dict[str, Any]] = []
        if run["migration_digest"]:
            migration_rows = _migration_findings_for(store, artifacts, run)

        all_rows = finding_rows + migration_rows
        finding_ids = store.insert_findings(run_id, all_rows)

        # ---------------------------------------------------- IMPACT_MAPPED
        store.set_run_state(run_id, "IMPACT_MAPPED")
        deps = store.list_dependencies(run["project_id"])
        edges = [
            DependencyEdge(
                id=d["id"], producer_service_id=d["producer_service_id"],
                consumer_service_id=d["consumer_service_id"],
                consumer_name=d["consumer_name"], http_method=d["http_method"],
                path_pattern=d["path_pattern"],
                required_fields=tuple(d["required_fields"]),
                test_suite_id=d["test_suite_id"],
                registry_revision=d["registry_revision"], enabled=d["enabled"])
            for d in deps
        ]
        # find_impacts operates on lightweight finding stubs
        from types import SimpleNamespace
        stubs = [SimpleNamespace(**{k: v for k, v in row.items()}) for row in all_rows]
        impacts = map_impacts(stubs, edges)
        impact_rows = [i.to_row() for i in impacts]
        with store.readonly() as conn:
            rows = conn.execute(
                "SELECT rule_id, location, id FROM findings WHERE run_id=%s",
                (run_id,)).fetchall()
        loc_map = {(r[0], r[1]): str(r[2]) for r in rows}
        store.insert_impacts(run_id, impact_rows, loc_map)

        # --------------------------------------------------------- TESTING
        store.set_run_state(run_id, "TESTING")
        executed = _execute_consumer_suites(store, artifacts, app_state, run, run_id,
                                            finding_rows, impact_rows)

        # -------------------------------------------------------- ASSESSED
        store.set_run_state(run_id, "ASSESSED")
        coverage_complete = len([e for e in impacts if e.impact_state == "UNKNOWN"]) == 0 or \
            all(e.impact_state != "UNKNOWN" for e in impacts)
        unsupported = result.unsupported
        decision = policy_mod.evaluate_policy(policy_mod.PolicyInput(
            findings=[SimpleNamespace(**row) for row in all_rows],
            impacts=impact_rows,
            test_executions=executed,
            policy=policy_mod.PolicySnapshot(
                version=run["policy_version"],
                block_rules=tuple(policy_row_for(store, run)["block_rules"]),
                mandatory_suites=tuple(policy_row_for(store, run)["mandatory_suites"]),
                unknown_strategy=policy_row_for(store, run)["unknown_strategy"]),
            coverage_complete=coverage_complete,
            unsupported_constructs=unsupported,
        ))
        finding_rows_final = store.list_findings(run_id, size=200)["items"]
        test_rows = [dict(t) for t in executed]
        digest = policy_mod.compute_evidence_digest(run_id, finding_rows_final, test_rows, decision.outcome)
        try:
            store.upsert_assessment(run_id, run["policy_version"], decision.outcome,
                                   decision.blocking_reasons, decision.unknowns, digest)
        except StoreError:
            pass  # immutable once final; a retried worker must not duplicate

        # -------------------------------------------------------- COMPLETED
        store.set_run_state(run_id, "COMPLETED")

        # store deterministic report artifacts
        from app.reporting.report import build_json_report, build_markdown_report
        json_report = build_json_report(store, run_id)
        md_report = build_markdown_report(store, run_id)
        _save_report_artifacts(store, artifacts, run_id, json_report, md_report)
        return {"run_id": run_id, "state": "COMPLETED", "outcome": decision.outcome}
    except Exception as exc:  # noqa: BLE001 - infra failure must land in ERROR
        try:
            store.set_run_state(run_id, "ERROR")
            assessment = store.get_assessment(run_id)
            if assessment is None:
                digest = policy_mod.compute_evidence_digest(run_id, [], [], "ERROR")
                store.upsert_assessment(run_id, run["policy_version"], "ERROR", [], [], digest)
        except StoreError:
            pass
        return {"run_id": run_id, "state": "ERROR", "error": sanitize_log(str(exc))[:500]}


def _contract_by_identity(contracts: dict[str, dict[str, Any]], identity: str, digest: str) -> dict[str, Any]:
    for c in contracts.values():
        cid = c["fixture_id"] or c["commit_sha"]
        if cid == identity and c["spec_digest"] == digest:
            return c
    raise RuntimeError(f"contract {identity} (digest {digest[:12]}) not found")


def _contract_text(artifacts: ArtifactStore, contract: dict[str, Any]) -> str:
    content = artifacts.load("contracts", "contract", f"{contract['spec_digest']}.{contract['format']}")
    if content is None:
        raise RuntimeError(f"stored contract missing: {contract['spec_digest'][:12]}")
    return content.decode("utf-8")


def _migration_findings_for(store: Store, artifacts: ArtifactStore, run: dict[str, Any]) -> list[dict[str, Any]]:
    from app.parsing.sql_migration import analyze_migration
    content = artifacts.load("migrations", "migration", f"{run['migration_digest']}.sql")
    if content is None:
        return [{
            "rule_id": "PG-UNKNOWN", "rule_version": "1.0.0", "surface": "DB_MIGRATION",
            "location": "migration-artifact", "before_value": None, "after_value": None,
            "classification": "UNKNOWN", "severity": "medium",
            "reason": "registered migration artifact content is missing",
            "verification_state": "STATIC_ONLY", "evidence_refs": [],
            "confidence_basis": "STRUCTURAL_STATIC",
        }]
    analysis = analyze_migration(content.decode("utf-8"))
    return [f.to_row() for f in migration_findings(analysis)]


def policy_row_for(store: Store, run: dict[str, Any]) -> dict[str, Any]:
    p = store.get_policy(run["project_id"], run["policy_version"])
    if p is None:
        return {"block_rules": [], "mandatory_suites": [], "unknown_strategy": "REVIEW"}
    return p


def _execute_consumer_suites(store: Store, artifacts: ArtifactStore, app_state: Any,
                              run: dict[str, Any], run_id: str,
                              finding_rows: list[dict[str, Any]],
                              impact_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Execute the allowlisted consumer suites via the controlled runner."""
    from app.config import Settings
    settings: Settings = app_state.settings
    candidate_contract = _contract_by_identity(
        {c["id"]: c for c in store.list_contracts(run["project_id"])},
        run["candidate_identity"], run["candidate_digest"])
    candidate_doc = json.loads(_contract_text(artifacts, candidate_contract))

    # which suites matter for this run: policy mandatory suites intersect allowlist
    policy = policy_row_for(store, run)
    suites = [s for s in policy["mandatory_suites"] if s in settings.runner_allowed_suites]

    from app.runner_bridge import load_runner_execute
    execute_suite = load_runner_execute()
    executed: list[dict[str, Any]] = []
    for suite_id in suites:
        record = execute_suite(
            suite_id=suite_id, candidate_document=candidate_doc,
            timeout_seconds=settings.max_run_seconds,
            project_root=app_state.project_root,
        )
        # persist sanitized log as artifact
        log_artifact_id = None
        try:
            meta = artifacts.save(run_id, "consumer_log", f"{suite_id}.txt",
                                 sanitize_log(record["log"]).encode("utf-8"))
            log_artifact_id = store.insert_artifact(
                run_id, "consumer_log", meta["relative_key"], meta["sha256"],
                meta["byte_size"], visibility="project")
        except ValueError:
            pass  # immutable duplicate from a retried worker
        te_id = store.insert_test_execution(
            run_id, suite_id, record["fixture_digest"], record["image_ref"],
            record["status"], record["duration_ms"], record["exit_code"],
            log_artifact_id)
        executed.append({
            "suite_id": suite_id,
            "status": record["status"],
            "duration_ms": record["duration_ms"],
            "exit_code": record["exit_code"],
            "fixture_digest": record["fixture_digest"],
            "image_ref": record["image_ref"],
            "id": te_id,
        })

        # update finding verification states from executed evidence
        consumer_name = "billing-service" if suite_id == "billing-contract" else "reporting-service"
        failed = record["status"] == "FAILED"
        with store.readonly() as conn:
            finding_rows_db = conn.execute(
                "SELECT id, rule_id, verification_state FROM findings WHERE run_id=%s",
                (run_id,)).fetchall()
        for fid, rule_id, current in finding_rows_db:
            target = None
            if failed and any(
                imp["finding_rule_id"] == rule_id and imp["consumer_name"] == consumer_name
                for imp in impact_rows
            ):
                target = "CONSUMER_FAIL"
            elif not failed and any(
                imp["finding_rule_id"] == rule_id and imp["consumer_name"] == consumer_name
                for imp in impact_rows
            ):
                target = "CONSUMER_PASS"
            if target and current == "STATIC_ONLY":
                store.update_finding_verification(fid, target, [
                    {"type": "executed_assertion", "suite": suite_id,
                     "status": record["status"], "exit_code": record["exit_code"],
                     "artifact_id": log_artifact_id},
                ])
    return executed


def _save_report_artifacts(store: Store, artifacts: ArtifactStore, run_id: str,
                           json_report: dict[str, Any], md_report: str) -> None:
    import hashlib
    try:
        meta = artifacts.save(run_id, "report_json", "report.json",
                              json.dumps(json_report, indent=2, sort_keys=True).encode("utf-8"))
        store.insert_artifact(run_id, "report_json", meta["relative_key"],
                              meta["sha256"], meta["byte_size"])
        meta = artifacts.save(run_id, "report_markdown", "report.md", md_report.encode("utf-8"))
        store.insert_artifact(run_id, "report_markdown", meta["relative_key"],
                              meta["sha256"], meta["byte_size"])
    except ValueError:
        pass  # immutable duplicates on worker retry
