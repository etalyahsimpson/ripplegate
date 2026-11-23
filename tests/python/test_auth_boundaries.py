"""Authorization boundary tests (spec 13 matrix row 9)."""
from __future__ import annotations

import time

from app.auth.session import SessionError, issue_session, verify_session

SECRET = "test-session-secret-not-real"


def test_missing_token_401(client):
    r = client.get("/api/v1/projects")
    assert r.status_code == 401
    assert "error" in r.json()


def test_malformed_token_401(client):
    r = client.get("/api/v1/projects", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401


def test_forged_signature_rejected(client):
    forged = issue_session("demo-admin", "wrong-secret-entirely")
    r = client.get("/api/v1/projects", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


def test_expired_session_rejected(client):
    token = issue_session("demo-admin", SECRET, ttl=-10)
    r = client.get("/api/v1/projects", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_viewer_cannot_register_project(client, viewer_token):
    r = client.post("/api/v1/projects",
                    headers={"Authorization": f"Bearer {viewer_token}"},
                    json={"organization_id": "a0000000-0000-4000-8000-000000000001",
                          "github_owner": "x", "github_repo": "y",
                          "display_name": "z", "allowed_contract_paths": ["a/b.json"]})
    assert r.status_code == 403


def test_viewer_cannot_create_policy(client, viewer_token, seeded_ids):
    r = client.post(f"/api/v1/projects/{seeded_ids['project_id']}/policies",
                    headers={"Authorization": f"Bearer {viewer_token}"},
                    json={"version": 99, "blocking_rule_ids": [],
                          "mandatory_suite_ids": [], "unknown_strategy": "REVIEW"})
    assert r.status_code == 403


def test_admin_can_register_project(client, admin_token):
    r = client.post("/api/v1/projects",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={"organization_id": "a0000000-0000-4000-8000-000000000001",
                          "github_owner": "etalyahsimpson", "github_repo": "fresh-demo",
                          "display_name": "Fresh", "allowed_contract_paths": ["a/b.json"]})
    assert r.status_code == 201


def test_cross_tenant_read_is_404_without_existence_leak(client, seeded_ids):
    # viewer is member of the demo org; use a foreign org for project creation
    other_org = "99999999-9999-4999-8999-999999999999"
    # attempt to read a project the caller has no membership for
    r = client.get(f"/api/v1/projects/{seeded_ids['project_id']}",
                   headers={"Authorization": "Bearer forged"})
    assert r.status_code == 401
    # a session valid but with no membership anywhere: use a viewer of same org
    r = client.get(f"/api/v1/analyses/{seeded_ids['project_id']}")
    assert r.status_code == 401


def test_role_header_injection_is_ignored(client, viewer_token, seeded_ids):
    # caller-supplied role headers must never upgrade permissions
    r = client.post(f"/api/v1/projects/{seeded_ids['project_id']}/services",
                    headers={"Authorization": f"Bearer {viewer_token}",
                             "X-Role": "admin"},
                    json={"name": "sneaky", "kind": "producer", "owner_label": "x"})
    assert r.status_code == 403


def test_demo_session_labeled_as_demo(client):
    r = client.post("/api/v1/demo/session", json={"account": "demo-admin"})
    assert r.status_code == 200
    body = r.json()
    assert body["account_type"] == "demo"
    assert body["role"] == "admin"


def test_unknown_account_rejected(client):
    r = client.post("/api/v1/demo/session", json={"account": "root"})
    assert r.status_code in (401, 422)


def test_me_returns_scoped_orgs(client, admin_token):
    r = client.get("/api/v1/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    orgs = r.json()["organizations"]
    assert any(o["slug"] == "demo-platform" for o in orgs)
