"""Immutable allowlisted suite->fixture mapping (spec 10.1).

Users can NEVER submit arbitrary commands, images, URLs or suite ids. The
suite id must be in this pinned table AND in the runtime RUNNER_ALLOWED_SUITES.
Each entry fixes the exact script, its digest, the image identity and the
argument vector. No 'latest' tags anywhere.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any

# digest is filled at build time by scripts/bootstrap.sh into runner_manifest.json
MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "runner_manifest.json")

_FALLBACK_IMAGE = "node:22-bookworm-slim"  # pinned major-slim base used by compose build


@dataclass(frozen=True)
class AllowedSuite:
    suite_id: str
    script_relpath: str          # relative to repo root
    consumer_dir: str            # examples/<service>
    image_ref: str               # pinned image identity (digest or explicit tag)
    node_version: str


ALLOWED_SUITES: dict[str, AllowedSuite] = {
    "billing-contract": AllowedSuite(
        suite_id="billing-contract",
        script_relpath="examples/billing-service/contract.test.js",
        consumer_dir="examples/billing-service",
        image_ref=_FALLBACK_IMAGE,
        node_version="22",
    ),
    "reporting-contract": AllowedSuite(
        suite_id="reporting-contract",
        script_relpath="examples/reporting-service/contract.test.js",
        consumer_dir="examples/reporting-service",
        image_ref=_FALLBACK_IMAGE,
        node_version="22",
    ),
}


class RunnerAllowlistError(ValueError):
    pass


def resolve_suite(suite_id: str) -> AllowedSuite:
    if suite_id not in ALLOWED_SUITES:
        raise RunnerAllowlistError(f"suite {suite_id!r} is not in the pinned allowlist")
    return ALLOWED_SUITES[suite_id]


def load_manifest() -> dict[str, Any]:
    if os.path.exists(MANIFEST_PATH):
        import json
        with open(MANIFEST_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def fixture_digest_for(candidate_document: dict[str, Any]) -> str:
    """Stable digest over the exact candidate contract content handed to the suite."""
    import json as _json
    payload = _json.dumps(candidate_document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
