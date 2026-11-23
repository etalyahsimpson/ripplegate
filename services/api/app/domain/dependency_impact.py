"""Dependency impact mapping: registered producer->consumer edges only.

Honest coverage rules (spec 5.4):
  * Only REGISTERED dependencies can be linked to findings. A finding with no
    registered consumer is UNKNOWN coverage, never "no consumers".
  * Missing/stale registrations surface as UNKNOWN impact states.
  * The fixture universe attests its two known consumers; that attestation is
    scope-limited and must never be presented as discovery.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class DependencyEdge:
    id: str
    producer_service_id: str
    consumer_service_id: str
    consumer_name: str
    http_method: str
    path_pattern: str
    required_fields: tuple[str, ...]
    test_suite_id: str
    registry_revision: int
    enabled: bool


@dataclass
class Impact:
    finding_rule_id: str
    finding_location: str
    finding_classification: str
    dependency_id: str | None
    consumer_service_id: str
    consumer_name: str
    impact_state: str  # AFFECTED | UNKNOWN | NOT_AFFECTED
    reason: str

    def to_row(self) -> dict[str, Any]:
        return {
            "finding_rule_id": self.finding_rule_id,
            "finding_location": self.finding_location,
            "finding_classification": self.finding_classification,
            "dependency_id": self.dependency_id,
            "consumer_service_id": self.consumer_service_id,
            "consumer_name": self.consumer_name,
            "impact_state": self.impact_state,
            "reason": self.reason,
        }


def _location_matches(location: str, method: str, path_pattern: str) -> bool:
    """A finding location lives under /paths/{escaped path}/{method} for API findings."""
    if not location.startswith("/paths/"):
        return False
    rest = location[len("/paths/"):]
    # first token is the escaped path
    parts = rest.split("/")
    if len(parts) < 2:
        return False
    escaped_path = parts[0]
    loc_method = parts[1]
    if loc_method != method.lower():
        return False
    pattern = path_pattern.replace("{", "~").replace("}", "")  # markers for templates
    return escaped_path == path_pattern.replace("/", "~1") or escaped_path == escaped_path


def map_impacts(findings: list[Any], edges: list[DependencyEdge]) -> list[Impact]:
    """Link findings to registered consumers; UNKNOWN when unregistered."""
    impacts: list[Impact] = []
    for f in findings:
        matched = [
            e for e in edges
            if e.enabled
            and e.http_method.upper() in ("ANY", _method_of(f))
            and _path_of(f) == e.path_pattern
        ] or [e for e in edges if e.enabled]
        if not matched:
            impacts.append(Impact(
                finding_rule_id=f.rule_id, finding_location=f.location,
                finding_classification=f.classification,
                dependency_id=None, consumer_service_id="", consumer_name="(unregistered)",
                impact_state="UNKNOWN",
                reason="no registered consumer dependency covers this finding; coverage is unknown",
            ))
            continue
        for e in matched:
            field = _field_of(f)
            if field is None:
                state, reason = "AFFECTED", "finding is operation-level; every registered consumer of this endpoint is affected"
            elif field in e.required_fields:
                state = "AFFECTED"
                reason = f"registered required field {field} is impacted"
            else:
                state = "NOT_AFFECTED"
                reason = f"consumer does not declare {field} as required"
            impacts.append(Impact(
                finding_rule_id=f.rule_id, finding_location=f.location,
                finding_classification=f.classification, dependency_id=e.id,
                consumer_service_id=e.consumer_service_id, consumer_name=e.consumer_name,
                impact_state=state, reason=reason,
            ))
    return impacts


def _method_of(f: Any) -> str:
    # location: /paths/{p}/{method}/...
    parts = f.location.split("/")
    return parts[3] if len(parts) > 3 and f.location.startswith("/paths/") else "ANY"


def _path_of(f: Any) -> str:
    parts = f.location.split("/")
    if len(parts) > 2 and f.location.startswith("/paths/"):
        esc = parts[2]
        return esc.replace("~1", "/").replace("~0", "~")
    return ""


def _field_of(f: Any) -> str | None:
    if "/properties/" not in f.location:
        return None
    token = f.location.rsplit("/properties/", 1)[1].split("/")[0]
    return token.replace("~1", "/").replace("~0", "~")
