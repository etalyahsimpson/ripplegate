"""Summary draft: deterministic template, no provider mutation (spec 13 row 16)."""
from __future__ import annotations

import json


def _make_run(client, admin_token, seeded, key):
    r = client.post("/api/v1/analyses",
                    headers={"Authorization": f"Bearer {admin_token}",
                             "Idempotency-Key": key},
                    json={"project_id": seeded["project_id"],
                          "producer_service_id": seeded["services"]["orders-api"],
                          "base_contract_id": seeded["contracts"]["fixture-base-v1"],
                          "candidate_contract_id": seeded["contracts"]["fixture-candidate-breaking-v2"],
                          "migration_artifact_id": None,
                          "policy_version": 1, "registry_revision": 1})
    assert r.status_code == 202, r.text
    return r.json()["id"]


def test_template_mode_used_without_provider_credentials(client, admin_token, seeded_ids, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    run_id = _make_run(client, admin_token, seeded_ids, "demo-ai-summary-0001")
    r = client.post(f"/api/v1/analyses/{run_id}/summary-draft",
                    headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "deterministic_template"
    assert body["provider"] is None
    assert "BLOCK" in body["draft"]


def test_draft_cannot_mutate_verdict(client, admin_token, seeded_ids, monkeypatch):
    run_id = _make_run(client, admin_token, seeded_ids, "demo-ai-summary-0002")
    before = client.get(f"/api/v1/analyses/{run_id}",
                        headers={"Authorization": f"Bearer {admin_token}"}).json()
    client.post(f"/api/v1/analyses/{run_id}/summary-draft",
                headers={"Authorization": f"Bearer {admin_token}"})
    after = client.get(f"/api/v1/analyses/{run_id}",
                       headers={"Authorization": f"Bearer {admin_token}"}).json()
    assert before["assessment"] == after["assessment"] == "BLOCK"
    assert before["finding_counts"] == after["finding_counts"]


def test_unavailable_provider_returns_503_not_fake_success(client, admin_token, seeded_ids, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "configured-but-unreachable-key")
    import app.reporting.summary_draft as sd
    run_id = _make_run(client, admin_token, seeded_ids, "demo-ai-summary-0003")

    class Boom(Exception):
        pass

    monkeypatch.setattr(sd, "_call_provider", lambda *a, **k: (_ for _ in ()).throw(
        sd.ProviderUnavailable("provider down")))
    r = client.post(f"/api/v1/analyses/{run_id}/summary-draft",
                    headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 503
    assert "not reachable" in r.json()["error"]["message"]


def test_incomplete_run_rejects_draft(client, admin_token, seeded_ids):
    r = client.post("/api/v1/analyses/00000000-0000-4000-8000-000000000001/summary-draft",
                    headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 404
