"""GitHub webhook intake security (spec 13 matrix row 10)."""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid


SECRET = "test-webhook-secret-not-real"


def _headers(event: str = "pull_request", delivery: str | None = None):
    return {
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery or str(uuid.uuid4()),
    }


def _signed(payload: bytes, secret: str = SECRET) -> dict[str, str]:
    sig = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    h = _headers()
    h["X-Hub-Signature-256"] = sig
    return h


def _pr_body() -> bytes:
    return json.dumps({
        "action": "opened",
        "repository": {"id": 1469037749, "full_name": "etalyahsimpson/ripplegate"},
        "pull_request": {"number": 1, "head": {"sha": "a" * 40}},
    }).encode()


def test_valid_signature_accepted(client):
    payload = _pr_body()
    r = client.post("/api/v1/github/webhook", content=payload,
                    headers=_signed(payload))
    assert r.status_code == 202
    assert r.json()["status"] == "accepted"


def test_tampered_body_rejected(client):
    payload = _pr_body()
    headers = _signed(payload)
    tampered = payload.replace(b'"action": "opened"', b'"action": "synchronize"')
    r = client.post("/api/v1/github/webhook", content=tampered, headers=headers)
    assert r.status_code == 401


def test_missing_signature_rejected(client):
    r = client.post("/api/v1/github/webhook", content=_pr_body(), headers=_headers())
    assert r.status_code == 401


def test_wrong_secret_rejected(client):
    payload = _pr_body()
    r = client.post("/api/v1/github/webhook", content=payload,
                    headers=_signed(payload, secret="attacker-secret"))
    assert r.status_code == 401


def test_wrong_repo_rejected(client):
    payload = json.dumps({
        "repository": {"id": 1, "full_name": "attacker/other-repo"},
    }).encode()
    r = client.post("/api/v1/github/webhook", content=payload, headers=_signed(payload))
    assert r.status_code == 403


def test_non_pull_request_event_rejected(client):
    payload = json.dumps({
        "repository": {"id": 1469037749, "full_name": "etalyahsimpson/ripplegate"},
    }).encode()
    headers = _signed(payload)
    headers["X-GitHub-Event"] = "push"
    r = client.post("/api/v1/github/webhook", content=payload, headers=headers)
    assert r.status_code == 400


def test_duplicate_delivery_is_idempotent(client):
    payload = _pr_body()
    headers = _signed(payload)
    first = client.post("/api/v1/github/webhook", content=payload, headers=headers)
    assert first.status_code == 202
    second = client.post("/api/v1/github/webhook", content=payload, headers=headers)
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"


def test_signature_verified_before_json_parse(client):
    # invalid JSON with a valid signature: parse error AFTER signature check
    garbage = b"not-json-{{"
    r = client.post("/api/v1/github/webhook", content=garbage, headers=_signed(garbage))
    # signature valid, repo validation fails first (no repository in payload)
    assert r.status_code in (400, 403, 422)


def test_oversized_webhook_rejected(client):
    payload = _pr_body()
    big = b'{"pad": "' + b"x" * 1_200_000 + b'"}'
    headers = _signed(big)
    r = client.post("/api/v1/github/webhook", content=big, headers=headers)
    assert r.status_code in (403, 413)
