"""Demo sessions: HMAC-signed, expiring, membership-checked (spec 7.1).

This is an OFFLINE development identity mechanism. Demo accounts are allowlisted
here; the signed token only proves "this caller selected one of the demo
accounts", and every request still re-checks the persisted membership. It is
explicitly NOT production SSO and must not be described as such.

Roles are read ONLY from the membership row, never from a header or query.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid

from typing import Any

TOKEN_TTL_SECONDS = 12 * 3600

DEMO_ACCOUNTS: dict[str, dict[str, Any]] = {
    "demo-admin": {
        "user_id": "10000000-0000-4000-8000-000000000001",
        "display_name": "Demo Admin",
        "role": "admin",
        "account_type": "demo",
    },
    "demo-viewer": {
        "user_id": "10000000-0000-4000-8000-000000000002",
        "display_name": "Demo Viewer",
        "role": "viewer",
        "account_type": "demo",
    },
}


class SessionError(Exception):
    pass


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def issue_session(account: str, secret: str, ttl: int = TOKEN_TTL_SECONDS) -> str:
    if account not in DEMO_ACCOUNTS:
        raise SessionError("unknown demo account")
    body = {
        "account": account,
        "user_id": DEMO_ACCOUNTS[account]["user_id"],
        "role": DEMO_ACCOUNTS[account]["role"],
        "account_type": "demo",
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl,
        "jti": str(uuid.uuid4()),
    }
    payload = _b64url(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    sig = _b64url(hmac.new(secret.encode("utf-8"), payload.encode("ascii"),
                           hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_session(token: str, secret: str) -> dict[str, Any]:
    """Verify signature (constant-time) and expiry; return claims or raise."""
    if not isinstance(token, str) or token.count(".") != 1:
        raise SessionError("malformed session token")
    payload, sig = token.split(".")
    expected = _b64url(hmac.new(secret.encode("utf-8"), payload.encode("ascii"),
                                hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise SessionError("invalid session signature")
    try:
        body = json.loads(_b64url_decode(payload))
    except (ValueError, json.JSONDecodeError) as exc:
        raise SessionError("malformed session payload") from exc
    if not isinstance(body, dict) or body.get("account_type") != "demo":
        raise SessionError("unexpected token type")
    if int(body.get("exp", 0)) < time.time():
        raise SessionError("expired session token")
    if body.get("account") not in DEMO_ACCOUNTS:
        raise SessionError("unknown demo account")
    return body
