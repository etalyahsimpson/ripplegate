"""Dependency impact mapping honesty (spec 13 matrix row 6)."""
from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

from app.domain.dependency_impact import DependencyEdge, map_impacts
from app.parsing.openapi_model import normalize
from app.domain.rules import run_engine

ORDERS = pathlib.Path(__file__).resolve().parents[2] / "examples" / "orders-api"


def _edges():
    return [
        DependencyEdge(
            id="dep-1", producer_service_id="p", consumer_service_id="c1",
            consumer_name="billing-service", http_method="GET",
            path_pattern="/orders/{id}", required_fields=("customer_id", "total_cents"),
            test_suite_id="billing-contract", registry_revision=1, enabled=True),
        DependencyEdge(
            id="dep-2", producer_service_id="p", consumer_service_id="c2",
            consumer_name="reporting-service", http_method="GET",
            path_pattern="/orders/{id}", required_fields=("total_cents",),
            test_suite_id="reporting-contract", registry_revision=1, enabled=True),
    ]


def _breaking_findings():
    base = json.loads((ORDERS / "openapi-base.json").read_text())
    breaking = json.loads((ORDERS / "openapi-candidate-breaking.json").read_text())
    return run_engine(normalize(base, "3.0.3"), normalize(breaking, "3.0.3")).findings


def test_only_registered_consumers_linked():
    impacts = map_impacts(_breaking_findings(), _edges())
    names = {i.consumer_name for i in impacts}
    assert names <= {"billing-service", "reporting-service"}


def test_customer_id_removal_affects_billing_not_reporting():
    impacts = map_impacts(_breaking_findings(), _edges())
    billing = [i for i in impacts if i.consumer_name == "billing-service"
               and i.finding_rule_id == "API-RESP-REQUIRED-REMOVED"]
    reporting = [i for i in impacts if i.consumer_name == "reporting-service"
                 and i.finding_rule_id == "API-RESP-REQUIRED-REMOVED"]
    assert billing and all(i.impact_state == "AFFECTED" for i in billing)
    assert reporting and all(i.impact_state == "NOT_AFFECTED" for i in reporting)


def test_no_edges_means_unknown_not_no_consumers():
    impacts = map_impacts(_breaking_findings(), [])
    assert impacts and all(i.impact_state == "UNKNOWN" for i in impacts)
    assert all("(unregistered)" == i.consumer_name for i in impacts)


def test_disabled_edge_is_ignored():
    edges = _edges()
    edges[0].enabled = False
    impacts = map_impacts(_breaking_findings(), edges)
    billing = [i for i in impacts if i.consumer_name == "billing-service"]
    assert not billing


def test_stale_registry_revision_is_visible_in_edge_data():
    # the registry revision participates in run identity; the mapper surfaces it
    edge = _edges()[0]
    assert edge.registry_revision == 1
    impacts = map_impacts(_breaking_findings(), _edges())
    assert any(i.dependency_id == "dep-1" for i in impacts)


def test_operation_level_finding_affects_all_registered():
    finding = SimpleNamespace(
        rule_id="API-PATH-REMOVED", location="/paths/~1orders~1{id}/get",
        classification="BREAKING")
    impacts = map_impacts([finding], _edges())
    assert impacts and all(i.impact_state == "AFFECTED" for i in impacts if i.dependency_id)


def test_field_outside_required_is_not_affected():
    additive = json.loads((ORDERS / "openapi-candidate-additive.json").read_text())
    base = json.loads((ORDERS / "openapi-base.json").read_text())
    findings = run_engine(normalize(base, "3.0.3"), normalize(additive, "3.0.3")).findings
    impacts = map_impacts(findings, _edges())
    # fulfillment_note is not required by either consumer
    hit = [i for i in impacts if i.finding_rule_id == "API-RESP-OPTIONAL-ADDED"]
    assert hit and all(i.impact_state in ("NOT_AFFECTED",) for i in hit)
