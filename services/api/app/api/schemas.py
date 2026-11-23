"""Typed request/response schemas (spec 7.3) shared by routes and tests."""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_SUITES = ("billing-contract", "reporting-contract")


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
    details: dict[str, Any] | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class SessionCreate(BaseModel):
    account: Literal["demo-admin", "demo-viewer"]


class SessionRead(BaseModel):
    token: str
    account: str
    user_id: str
    role: str
    account_type: Literal["demo"]
    expires_in: int


class ProjectCreate(BaseModel):
    organization_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    github_owner: str = Field(min_length=1, max_length=100)
    github_repo: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=120)
    allowed_contract_paths: list[str] = Field(min_length=1, max_length=20)

    @field_validator("allowed_contract_paths")
    @classmethod
    def paths_look_safe(cls, v: list[str]) -> list[str]:
        for p in v:
            if not re.match(r"^[\w./-]{1,200}$", p) or ".." in p:
                raise ValueError(f"invalid contract path: {p!r}")
        return v


class ProjectRead(BaseModel):
    id: str
    organization_id: str
    owner: str
    repository: str
    display_name: str
    status: str
    created_at: str


class ServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["producer", "consumer"]
    owner_label: str = Field(min_length=1, max_length=100)


class ServiceRead(BaseModel):
    id: str
    name: str
    kind: str
    owner_label: str
    created_at: str


class ContractRegister(BaseModel):
    service_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    source_type: Literal["GITHUB_COMMIT", "FIXTURE"]
    commit_sha: str | None = None
    fixture_id: str | None = None
    format: Literal["json", "yaml"]
    document: str = Field(min_length=2, max_length=1_048_576)

    @model_validator(mode="after")
    def source_constraints(self) -> "ContractRegister":
        if self.source_type == "GITHUB_COMMIT":
            if not self.commit_sha or not SHA_RE.match(self.commit_sha):
                raise ValueError("GITHUB_COMMIT requires a 40-hex lowercase commit_sha")
            if self.fixture_id is not None:
                raise ValueError("fixture_id must be null for GITHUB_COMMIT")
        else:
            if not self.fixture_id or len(self.fixture_id) > 100:
                raise ValueError("FIXTURE requires a fixture_id (1..100 chars)")
            if self.commit_sha is not None:
                raise ValueError("fixture sources must never carry a git sha")
        return self


class ContractRead(BaseModel):
    id: str
    service_id: str
    service_name: str
    source_type: str
    commit_sha: str | None
    fixture_id: str | None
    spec_digest: str
    openapi_version: str
    format: str
    storage_key: str
    created_at: str


class DependencyCreate(BaseModel):
    producer_service_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    consumer_service_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    http_method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path_pattern: str = Field(min_length=1, max_length=200)
    required_response_fields: list[str] = Field(default_factory=list, max_length=50)
    contract_version_range: str = Field(default=">=1.0", max_length=100)
    test_suite_id: Literal["billing-contract", "reporting-contract"]
    evidence_source: Literal["OWNER_REGISTERED"] = "OWNER_REGISTERED"


class PolicyCreate(BaseModel):
    version: int = Field(ge=1)
    blocking_rule_ids: list[str] = Field(default_factory=list)
    mandatory_suite_ids: list[str] = Field(default_factory=list)
    unknown_strategy: Literal["REVIEW", "BLOCK"] = "REVIEW"

    @field_validator("mandatory_suite_ids")
    @classmethod
    def suites_allowlisted(cls, v: list[str]) -> list[str]:
        for s in v:
            if s not in ALLOWED_SUITES:
                raise ValueError(f"suite {s!r} is not in the controlled allowlist")
        return v


class AnalysisCreate(BaseModel):
    project_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    producer_service_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    base_contract_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    candidate_contract_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    migration_artifact_id: str | None = None
    policy_version: int = Field(ge=1)
    registry_revision: int = Field(ge=0)


class FindingRead(BaseModel):
    id: str
    rule_id: str
    rule_version: str
    surface: str
    location: str
    before_value: Any
    after_value: Any
    classification: str
    severity: str
    reason: str
    verification_state: str
    evidence_refs: list[dict[str, Any]]
    confidence_basis: str


class AssessmentRead(BaseModel):
    outcome: Literal["BLOCK", "REVIEW", "PASS", "ERROR"]
    blocking_reasons: list[str]
    unknowns: list[str]
    evidence_digest: str
    evaluated_policy_version: int


class AnalysisRead(BaseModel):
    id: str
    project_id: str
    source_type: str
    base_identity: str
    candidate_identity: str
    state: str
    policy_version: int
    created_at: str
    finished_at: str | None
    finding_counts: dict[str, int]
    assessment: str | None
    report_href: str | None


class TestExecutionRead(BaseModel):
    id: str
    suite_id: str
    fixture_digest: str
    image_ref: str
    status: str
    duration_ms: int | None
    exit_code: int | None
    artifact_id: str | None
    created_at: str
    finished_at: str | None


class ReviewCreate(BaseModel):
    disposition: Literal["approve", "reject", "needs_followup"]
    rationale: str = Field(min_length=10, max_length=2000)


class ReviewRead(BaseModel):
    disposition: str
    rationale: str
    reviewer_user_id: str
    occurred_at: str
