"""Worker idempotency: duplicate pipeline execution (spec 13 matrix row 11)."""
from __future__ import annotations

import json

import pytest


@pytest.fixture()
def pipeline_app(app):
    yield app


def _create_run(client, token, seeded, key, cand="fixture-candidate-breaking-v2"):
    r = client.post("/api/v1/analyses",
                    headers={"Authorization": f"Bearer {token}",
                             "Idempotency-Key": key},
                    json={"project_id": seeded["project_id"],
                          "producer_service_id": seeded["services"]["orders-api"],
                          "base_contract_id": seeded["contracts"]["fixture-base-v1"],
                          "candidate_contract_id": seeded["contracts"][cand],
                          "migration_artifact_id": None,
                          "policy_version": 1,
                          "registry_revision": 1})
    assert r.status_code == 202, r.text
    return r.json()["id"]


def test_replayed_pipeline_run_does_not_duplicate_findings(client, admin_token, seeded_ids, app):
    run_id = _create_run(client, admin_token, seeded_ids, "demo-idem-replay-001")
    store = app.state.store
    before_findings = store.list_findings(run_id, size=500)["items"]
    before_tests = store.list_test_executions(run_id)
    before_assessment = store.get_assessment(run_id)

    from app.worker.pipeline import run_pipeline
    result = run_pipeline(run_id, app.state)
    assert result["already_final"] is True or result["state"] == "COMPLETED"

    after_findings = store.list_findings(run_id, size=500)["items"]
    after_tests = store.list_test_executions(run_id)
    after_assessment = store.get_assessment(run_id)
    assert len(after_findings) == len(before_findings)
    assert len(after_tests) == len(before_tests)
    assert after_assessment == before_assessment


def test_error_run_records_error_assessment(client, admin_token, seeded_ids, app):
    # force an error: register a run whose contracts vanish from the artifact store
    run_id = _create_run(client, admin_token, seeded_ids, "demo-error-run-002")
    store = app.state.store
    run = store.get_run(run_id)
    assert run["state"] == "COMPLETED"  # healthy baseline

    # create a run pointing at a missing digest
    contracts = {c["id"]: c for c in store.list_contracts(run["project_id"])}
    base = contracts[seeded_ids["contracts"]["fixture-base-v1"]]
    run_key = store.compute_run_key(run["project_id"], "ghost", "ghost2", 1,
                                    "0" * 64, "1" * 64, None, 1)
    ghost_id, _ = store.create_run(
        project_id=run["project_id"], run_key=run_key, idempotency_key=None,
        base_identity="ghost", candidate_identity="ghost2",
        base_digest="0" * 64, candidate_digest="1" * 64, migration_digest=None,
        policy_id=run["policy_id"], policy_version=1, registry_revision=1,
        source_type="FIXTURE", base_sha=None, candidate_sha=None, requested_by=None)
    from app.worker.pipeline import run_pipeline
    result = run_pipeline(ghost_id, app.state)
    assert result["state"] == "ERROR"
    assessment = store.get_assessment(ghost_id)
    assert assessment["outcome"] == "ERROR"
    detail = store.get_run(ghost_id)
    assert detail["state"] == "ERROR"


def test_terminal_run_state_is_immutable(client, admin_token, seeded_ids, app):
    run_id = _create_run(client, admin_token, seeded_ids, "demo-terminal-003")
    store = app.state.store
    from app.domain.release_policy import InvalidTransition
    with pytest.raises(Exception):
        store.set_run_state(run_id, "QUEUED")  # COMPLETED -> QUEUED forbidden


def test_celery_style_duplicate_delivery_is_safe(client, admin_token, seeded_ids, app):
    run_id = _create_run(client, admin_token, seeded_ids, "demo-dup-delivery-004")
    store = app.state.store
    run = store.get_run(run_id)
    # a second create_run with the same key returns the same row (dedup)
    run_key = store.compute_run_key(run["project_id"], run["base_identity"],
                                    run["candidate_identity"], run["policy_version"],
                                    run["base_digest"], run["candidate_digest"], None,
                                    run["registry_revision"])
    run_id_2, created = store.create_run(
        project_id=run["project_id"], run_key=run_key, idempotency_key=None,
        base_identity=run["base_identity"], candidate_identity=run["candidate_identity"],
        base_digest=run["base_digest"], candidate_digest=run["candidate_digest"],
        migration_digest=None, policy_id=run["policy_id"],
        policy_version=run["policy_version"], registry_revision=run["registry_revision"],
        source_type=run["source_type"], base_sha=None, candidate_sha=None,
        requested_by=None)
    assert not created and run_id_2 == run_id
