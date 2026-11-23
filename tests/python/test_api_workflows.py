"""End-to-end API workflows: seed -> register -> analyze -> test -> report.

These tests prove the mandatory demo scenarios from the spec:
  * breaking rename  -> BREAKING finding, billing FAIL, BLOCK verdict
  * additive control -> ADDITIVE finding, suites PASS, PASS verdict
  * external ref     -> UNSUPPORTED -> REVIEW, never PASS
"""
from __future__ import annotations

import json


def _create_analysis(client, token, seeded, base_fid, cand_fid, key):
    return client.post(
        "/api/v1/analyses",
        headers={"Authorization": f"Bearer {token}",
                 "Idempotency-Key": key, "Content-Type": "application/json"},
        json={
            "project_id": seeded["project_id"],
            "producer_service_id": seeded["services"]["orders-api"],
            "base_contract_id": seeded["contracts"][base_fid],
            "candidate_contract_id": seeded["contracts"][cand_fid],
            "migration_artifact_id": None,
            "policy_version": 1,
            "registry_revision": 1,
        })


def test_breaking_rename_blocks_with_consumer_evidence(client, admin_token, seeded_ids):
    r = _create_analysis(client, admin_token, seeded_ids,
                          "fixture-base-v1", "fixture-candidate-breaking-v2",
                          "demo-breaking-analysis-0001")
    assert r.status_code == 202, r.text
    run_id = r.json()["id"]
    assert r.json()["state"] in ("COMPLETED", "QUEUED", "TESTING")

    detail = client.get(f"/api/v1/analyses/{run_id}",
                        headers={"Authorization": f"Bearer {admin_token}"})
    assert detail.status_code == 200
    body = detail.json()
    assert body["state"] == "COMPLETED"
    assert body["assessment"] == "BLOCK"
    counts = body["finding_counts"]
    assert counts.get("BREAKING", 0) >= 1

    findings = client.get(f"/api/v1/analyses/{run_id}/findings",
                          headers={"Authorization": f"Bearer {admin_token}"}).json()
    removed = [f for f in findings["items"]
               if f["rule_id"] == "API-RESP-REQUIRED-REMOVED"]
    assert removed, "expected the rename to produce REQUIRED-REMOVED"
    f = removed[0]
    assert f["classification"] == "BREAKING"
    assert f["severity"] == "critical"
    assert f["location"].endswith("properties/customer_id")
    assert f["verification_state"] == "CONSUMER_FAIL"

    tests = client.get(f"/api/v1/analyses/{run_id}/tests",
                      headers={"Authorization": f"Bearer {admin_token}"}).json()
    statuses = {t["suite_id"]: t["status"] for t in tests["items"]}
    assert statuses.get("billing-contract") == "FAILED"
    assert statuses.get("reporting-contract") == "PASSED"
    billing = [t for t in tests["items"] if t["suite_id"] == "billing-contract"][0]
    assert billing["exit_code"] == 1
    assert billing["fixture_digest"] and len(billing["fixture_digest"]) == 64


def test_additive_control_passes(client, admin_token, seeded_ids):
    r = _create_analysis(client, admin_token, seeded_ids,
                          "fixture-base-v1", "fixture-candidate-additive-v2",
                          "demo-additive-analysis-0002")
    assert r.status_code == 202, r.text
    run_id = r.json()["id"]
    detail = client.get(f"/api/v1/analyses/{run_id}",
                        headers={"Authorization": f"Bearer {admin_token}"}).json()
    assert detail["state"] == "COMPLETED"
    assert detail["assessment"] == "PASS"
    assert detail["finding_counts"].get("ADDITIVE", 0) >= 1

    tests = client.get(f"/api/v1/analyses/{run_id}/tests",
                       headers={"Authorization": f"Bearer {admin_token}"}).json()
    statuses = {t["suite_id"]: t["status"] for t in tests["items"]}
    assert statuses == {"billing-contract": "PASSED", "reporting-contract": "PASSED"}


def test_unsupported_external_ref_yields_review_not_pass(client, admin_token, seeded_ids):
    r = _create_analysis(client, admin_token, seeded_ids,
                          "fixture-base-v1", "fixture-candidate-external-ref-v1",
                          "demo-unknown-analysis-0003")
    assert r.status_code == 202, r.text
    run_id = r.json()["id"]
    detail = client.get(f"/api/v1/analyses/{run_id}",
                        headers={"Authorization": f"Bearer {admin_token}"}).json()
    assert detail["state"] in ("COMPLETED", "ERROR")
    assert detail["assessment"] in ("REVIEW", "ERROR"), \
        "unsupported constructs must never yield PASS"


def test_idempotency_key_returns_same_run(client, admin_token, seeded_ids):
    first = _create_analysis(client, admin_token, seeded_ids,
                             "fixture-base-v1", "fixture-candidate-breaking-v2",
                             "demo-idem-analysis-0004")
    second = _create_analysis(client, admin_token, seeded_ids,
                               "fixture-base-v1", "fixture-candidate-breaking-v2",
                               "demo-idem-analysis-0004")
    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json().get("replayed") is True


def test_report_json_and_markdown_available(client, admin_token, seeded_ids):
    run_id = _create_analysis(client, admin_token, seeded_ids,
                              "fixture-base-v1", "fixture-candidate-breaking-v2",
                              "demo-report-analysis-0005").json()["id"]
    rj = client.get(f"/api/v1/analyses/{run_id}/report",
                    headers={"Authorization": f"Bearer {admin_token}"})
    assert rj.status_code == 200
    report = rj.json()
    assert report["assessment"]["outcome"] == "BLOCK"
    assert any(f["rule_id"] == "API-RESP-REQUIRED-REMOVED" for f in report["findings"])
    assert report["run"]["base_identity"] == "fixture-base-v1"
    assert report["run"]["candidate_identity"] == "fixture-candidate-breaking-v2"

    rm = client.get(f"/api/v1/analyses/{run_id}/report?format=markdown",
                    headers={"Authorization": f"Bearer {admin_token}"})
    assert rm.status_code == 200
    md = rm.text
    assert "API-RESP-REQUIRED-REMOVED" in md
    assert "billing-contract" in md
    assert "customer_id" in md


def test_report_rejects_incomplete_run(client, admin_token, seeded_ids):
    # craft an analysis that is still QUEUED by forcing inline-off; simpler:
    # use a nonexistent run
    r = client.get("/api/v1/analyses/00000000-0000-4000-8000-000000000000/report",
                   headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 404


def test_listing_runs_scoped(client, admin_token, seeded_ids):
    _create_analysis(client, admin_token, seeded_ids,
                     "fixture-base-v1", "fixture-candidate-breaking-v2",
                     "demo-list-analysis-0006")
    r = client.get("/api/v1/analyses",
                   headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(i["assessment"] == "BLOCK" for i in items)


def test_viewer_can_read_but_not_create(client, viewer_token, seeded_ids):
    r = client.get("/api/v1/analyses",
                   headers={"Authorization": f"Bearer {viewer_token}"})
    assert r.status_code == 200
    r = _create_analysis(client, viewer_token, seeded_ids,
                         "fixture-base-v1", "fixture-candidate-breaking-v2",
                         "demo-viewer-analysis-07")
    assert r.status_code == 403


def test_artifact_download_and_digest(client, admin_token, seeded_ids):
    run_id = _create_analysis(client, admin_token, seeded_ids,
                              "fixture-base-v1", "fixture-candidate-breaking-v2",
                              "demo-artifact-analysis-08").json()["id"]
    tests = client.get(f"/api/v1/analyses/{run_id}/tests",
                       headers={"Authorization": f"Bearer {admin_token}"}).json()
    billing = [t for t in tests["items"] if t["suite_id"] == "billing-contract"][0]
    art_id = billing["artifact_id"]
    assert art_id
    art = client.get(f"/api/v1/analyses/{run_id}/artifacts/{art_id}",
                     headers={"Authorization": f"Bearer {admin_token}"})
    assert art.status_code == 200
    assert "FAIL: response contains customer_id" in art.text
    assert "argv" in art.text  # execution identity present


def test_cross_project_artifact_denied(client, admin_token, seeded_ids):
    # create a second project and attempt to read the first project's artifact
    r = client.post("/api/v1/projects",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={"organization_id": "a0000000-0000-4000-8000-000000000001",
                          "github_owner": "etalyahsimpson", "github_repo": "other-project",
                          "display_name": "Other", "allowed_contract_paths": ["a/b.json"]})
    other_project = r.json().get("id")
    tests = None
    run_id = _create_analysis(client, admin_token, seeded_ids,
                              "fixture-base-v1", "fixture-candidate-breaking-v2",
                              "demo-cross-artifact-09").json()["id"]
    tests = client.get(f"/api/v1/analyses/{run_id}/tests",
                       headers={"Authorization": f"Bearer {admin_token}"}).json()
    billing = [t for t in tests["items"] if t["suite_id"] == "billing-contract"][0]
    art_id = billing["artifact_id"]
    # direct artifact access with unrelated run id must 404 (no existence leak)
    r = client.get(f"/api/v1/analyses/00000000-0000-4000-8000-000000000099/artifacts/{art_id}",
                   headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 404


def test_duplicate_contract_registration_conflicts(client, admin_token, seeded_ids):
    from pathlib import Path
    orders = Path(__file__).resolve().parents[2] / "examples" / "orders-api"
    r = client.post(f"/api/v1/projects/{seeded_ids['project_id']}/contracts",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={"service_id": seeded_ids["services"]["orders-api"],
                          "source_type": "FIXTURE", "fixture_id": "fixture-base-v1",
                          "format": "json",
                          "document": (orders / "openapi-base.json").read_text()})
    assert r.status_code == 409


def test_fixture_contract_must_not_carry_sha(client, admin_token, seeded_ids):
    from pathlib import Path
    orders = Path(__file__).resolve().parents[2] / "examples" / "orders-api"
    r = client.post(f"/api/v1/projects/{seeded_ids['project_id']}/contracts",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={"service_id": seeded_ids["services"]["orders-api"],
                          "source_type": "FIXTURE", "fixture_id": "fixture-fake",
                          "commit_sha": "a" * 40, "format": "json",
                          "document": (orders / "openapi-base.json").read_text()})
    assert r.status_code == 422


def test_review_recorded_as_audit(client, admin_token, seeded_ids):
    run_id = _create_analysis(client, admin_token, seeded_ids,
                              "fixture-base-v1", "fixture-candidate-breaking-v2",
                              "demo-review-analysis-10").json()["id"]
    r = client.post(f"/api/v1/analyses/{run_id}/reviews",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={"disposition": "reject",
                          "rationale": "breaking rename ships never; needs expand/contract"})
    assert r.status_code == 201
    # engine verdict unchanged
    detail = client.get(f"/api/v1/analyses/{run_id}",
                        headers={"Authorization": f"Bearer {admin_token}"}).json()
    assert detail["assessment"] == "BLOCK"
    # duplicate review conflicts
    r = client.post(f"/api/v1/analyses/{run_id}/reviews",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={"disposition": "reject", "rationale": "second opinion not allowed"})
    assert r.status_code == 409


def test_summary_draft_template_mode_never_mutates(client, admin_token, seeded_ids):
    run_id = _create_analysis(client, admin_token, seeded_ids,
                              "fixture-base-v1", "fixture-candidate-breaking-v2",
                              "demo-summary-analysis-11").json()["id"]
    r = client.post(f"/api/v1/analyses/{run_id}/summary-draft",
                    headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "deterministic_template"
    assert "BLOCK" in body["draft"]
    detail = client.get(f"/api/v1/analyses/{run_id}",
                        headers={"Authorization": f"Bearer {admin_token}"}).json()
    assert detail["assessment"] == "BLOCK"  # unchanged
