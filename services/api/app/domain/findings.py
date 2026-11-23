"""Finding dataclasses shared by the rule engine, impact mapper and policy."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SURFACES = ("REQUEST", "RESPONSE", "HTTP_OPERATION", "DB_MIGRATION")
CLASSIFICATIONS = ("BREAKING", "POTENTIALLY_BREAKING", "ADDITIVE", "INFORMATIONAL", "UNKNOWN")
VERIFICATION_STATES = (
    "STATIC_ONLY", "CONSUMER_PASS", "CONSUMER_FAIL", "EXECUTION_ERROR", "NOT_TESTED",
)
SEVERITIES = ("critical", "high", "medium", "low", "info")


@dataclass
class Finding:
    rule_id: str
    rule_version: str
    surface: str
    location: str
    before_value: Any
    after_value: Any
    classification: str
    severity: str
    reason: str
    verification_state: str = "STATIC_ONLY"
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    confidence_basis: str = "STRUCTURAL_STATIC"

    def to_row(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "surface": self.surface,
            "location": self.location,
            "before_value": self.before_value,
            "after_value": self.after_value,
            "classification": self.classification,
            "severity": self.severity,
            "reason": self.reason,
            "verification_state": self.verification_state,
            "evidence_refs": self.evidence_refs,
            "confidence_basis": self.confidence_basis,
        }
