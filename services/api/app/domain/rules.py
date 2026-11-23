"""The single authoritative compatibility rule engine (versioned rule IDs).

Design invariants (spec 5.2):
  * Request-side and response-side compatibility are DIRECTIONAL. A new
    optional response field is ADDITIVE for typical consumers but can still
    break strict ones; the executed consumer test is the tie-breaker.
  * Ambiguous rules resolve to POTENTIALLY_BREAKING or UNKNOWN, never PASS.
  * Rule versions change only through a new version string; findings persist
    the rule_version they were produced under.

Frontends render these typed results; they never re-classify.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.parsing.openapi_loader import UnsupportedConstructError, json_pointer_escape
from app.parsing.openapi_model import NormalizedDocument, Operation, SchemaNode
from .findings import Finding

RULE_SET_VERSION = "1.0.0"


def _ptr(path: str, method: str, *rest: str) -> str:
    return f"/paths/{json_pointer_escape(path)}/{method}" + ("/" + "/".join(rest) if rest else "")


def _types_label(node: SchemaNode) -> str:
    base = "|".join(node.types) if node.types else "(untyped)"
    return base + ("|null" if node.nullable else "")


def _types_compatible(before: SchemaNode, after: SchemaNode) -> tuple[bool, str]:
    """Return (compatible, reason). Compatible means every value the old
    contract could emit is still acceptable/derivable under the new one."""
    if not before.types and not after.types:
        return True, "both untyped"
    if not after.types:
        return False, "candidate schema dropped its type declaration"
    if set(before.types) == set(after.types):
        if before.nullable and not after.nullable:
            return False, "field no longer nullable"
        return True, "same primitive type"
    # integer values are representable as JSON numbers: integer -> number is widening
    if before.types == ("integer",) and after.types == ("number",):
        return True, "integer widened to number"
    return False, f"type changed from {_types_label(before)} to {_types_label(after)}"


@dataclass
class RuleEngineResult:
    findings: list[Finding]
    unsupported: list[dict[str, str]]  # location/construct/detail


def _op_key(op: Operation) -> tuple[str, str]:
    return (op.path, op.method)


def _enum_removed(before: SchemaNode, after: SchemaNode) -> list[Any]:
    if before.enum is None:
        return []
    if after.enum is None:
        return list(before.enum)  # enum dropped entirely: all prior values at risk
    return [v for v in before.enum if v not in after.enum]


class CompatibilityRuleEngine:
    """Deterministic, versioned, side-effect free."""

    rule_set_version = RULE_SET_VERSION

    def diff(self, before: NormalizedDocument, after: NormalizedDocument) -> RuleEngineResult:
        findings: list[Finding] = []
        unsupported: list[dict[str, str]] = [
            {"location": u.location, "construct": u.construct, "detail": u.detail}
            for u in before.unsupported + after.unsupported
        ]

        before_ops = {_op_key(op): op for op in before.operations}
        after_ops = {_op_key(op): op for op in after.operations}

        # ---------------------------------------------------- removed endpoints
        for (path, method), op in sorted(before_ops.items()):
            if (path, method) not in after_ops:
                findings.append(Finding(
                    rule_id="API-PATH-REMOVED", rule_version=self.rule_set_version,
                    surface="HTTP_OPERATION", location=_ptr(path, method),
                    before_value={"operationId": "present"},
                    after_value=None,
                    classification="BREAKING", severity="critical",
                    reason=f"operation {method.upper()} {path} exists in the base contract "
                           "but is absent from the candidate",
                ))

        for (path, method), after_op in sorted(after_ops.items()):
            before_op = before_ops.get((path, method))
            if before_op is None:
                continue
            findings.extend(self._diff_operation(path, method, before_op, after_op))
        return RuleEngineResult(findings=findings, unsupported=unsupported)

    # -------------------------------------------------------------- operation
    def _diff_operation(self, path: str, method: str,
                        before: Operation, after: Operation) -> list[Finding]:
        out: list[Finding] = []
        out.extend(self._diff_parameters(path, method, before, after))

        if before.request_schema or after.request_schema:
            out.extend(self._diff_request_schema(path, method, before.request_schema, after.request_schema))

        for status in sorted(set(before.response_schemas) | set(after.response_schemas)):
            out.extend(self._diff_response_schema(path, method, status,
                        before.response_schemas.get(status), after.response_schemas.get(status)))
        return out

    # ------------------------------------------------------------- parameters
    def _diff_parameters(self, path: str, method: str,
                         before: Operation, after: Operation) -> list[Finding]:
        out: list[Finding] = []
        before_params = {(p.location, p.name): p for p in before.parameters}
        after_params = {(p.location, p.name): p for p in after.parameters}
        for key, p in sorted(before_params.items()):
            if key not in after_params:
                out.append(Finding(
                    rule_id="API-PARAM-REMOVED", rule_version=self.rule_set_version,
                    surface="REQUEST", location=_ptr(path, method, "parameters", key[1]),
                    before_value={"in": p.location, "required": p.required},
                    after_value=None, classification="BREAKING", severity="high",
                    reason=f"{p.location} parameter {key[1]} was removed",
                ))
            else:
                after_p = after_params[key]
                if not p.required and after_p.required:
                    out.append(Finding(
                        rule_id="API-REQ-REQUIRED-ADDED", rule_version=self.rule_set_version,
                        surface="REQUEST", location=_ptr(path, method, "parameters", key[1]),
                        before_value={"required": False},
                        after_value={"required": True},
                        classification="BREAKING", severity="high",
                        reason=f"previously optional {p.location} parameter {key[1]} is now required",
                    ))
        return out

    # --------------------------------------------------------- request body
    def _diff_request_schema(self, path: str, method: str,
                             before: SchemaNode | None, after: SchemaNode | None) -> list[Finding]:
        if before is None and after is None:
            return []
        if before is None:
            # request body appeared where none existed: breaking if required properties exist
            if after is not None and after.required:
                return [Finding(
                    rule_id="API-REQ-REQUIRED-ADDED", rule_version=self.rule_set_version,
                    surface="REQUEST", location=_ptr(path, method, "requestBody"),
                    before_value=None, after_value={"required": list(after.required)},
                    classification="BREAKING", severity="high",
                    reason="candidate adds a request body with required properties",
                )]
            return []
        if after is None:
            return [Finding(
                rule_id="API-REQUEST-REMOVED", rule_version=self.rule_set_version,
                surface="REQUEST", location=_ptr(path, method, "requestBody"),
                before_value={"present": True}, after_value=None,
                classification="INFORMATIONAL", severity="info",
                reason="request body removed; existing senders of the body typically still pass",
            )]
        out: list[Finding] = []
        out.extend(self._diff_object(path, method, "REQUEST", before, after, direction="request"))
        return out

    # -------------------------------------------------------- response body
    def _diff_response_schema(self, path: str, method: str, status: str,
                              before: SchemaNode | None, after: SchemaNode | None) -> list[Finding]:
        if before is None and after is None:
            return []
        if before is None or after is None:
            return [Finding(
                rule_id="API-STATUS-CHANGED", rule_version=self.rule_set_version,
                surface="HTTP_OPERATION",
                location=_ptr(path, method, "responses", status),
                before_value={"schema": "present" if before else "absent"},
                after_value={"schema": "present" if after else "absent"},
                classification="POTENTIALLY_BREAKING", severity="medium",
                reason=f"response schema for status {status} was "
                       f"{'added' if before is None else 'removed'}; clients keyed on the other shape may fail",
            )]
        out = self._diff_object(path, method, "RESPONSE", before, after, direction="response",
                                status=status)
        return out

    # ----------------------------------------------------- object-level diff
    def _diff_object(self, path: str, method: str, surface: str,
                     before: SchemaNode, after: SchemaNode, direction: str,
                     status: str = "") -> list[Finding]:
        out: list[Finding] = []
        ptr = _ptr(path, method, "requestBody") if direction == "request" else \
            _ptr(path, method, "responses", status, "content", "application~1json", "schema")

        for name in sorted(set(before.required)):
            if name not in after.properties and name not in set(after.required):
                out.append(self._required_removed_finding(ptr, name, before, after, direction))
        for name, sub in sorted(after.properties.items()):
            b = before.properties.get(name)
            if b is None:
                out.append(self._new_property_finding(
                    ptr, name, sub, direction, required=name in set(after.required)))
                continue
            out.extend(self._diff_property(ptr, name, b, sub, direction))

        # newly required (was optional or absent)
        for name in sorted(set(after.required)):
            if name not in set(before.required) and name in before.properties:
                if direction == "request":
                    out.append(Finding(
                        rule_id="API-REQ-REQUIRED-ADDED", rule_version=self.rule_set_version,
                        surface=surface, location=f"{ptr}/properties/{json_pointer_escape(name)}",
                        before_value={"required": False}, after_value={"required": True},
                        classification="BREAKING", severity="high",
                        reason=f"request property {name} became required; existing callers omit it",
                    ))
                else:
                    out.append(Finding(
                        rule_id="API-RESP-REQUIRED-ADDED", rule_version=self.rule_set_version,
                        surface=surface, location=f"{ptr}/properties/{json_pointer_escape(name)}",
                        before_value={"required": False}, after_value={"required": True},
                        classification="ADDITIVE", severity="low",
                        reason=(f"response property {name} became required; producers now guarantee "
                                "it, which adds data rather than removing it (strict-validator caveat applies)"),
                    ))
        return out

    def _required_removed_finding(self, ptr: str, name: str,
                                   before: SchemaNode, after: SchemaNode,
                                   direction: str) -> Finding:
        if direction == "response":
            return Finding(
                rule_id="API-RESP-REQUIRED-REMOVED", rule_version=self.rule_set_version,
                surface="RESPONSE", location=f"{ptr}/properties/{json_pointer_escape(name)}",
                before_value={"required": True, "type": _types_label(before.properties[name])},
                after_value={"present": False},
                classification="BREAKING", severity="critical",
                reason=f"required response field {name} removed from the candidate; consumers "
                       "that read it will see absent/undefined data",
            )
        return Finding(
            rule_id="API-REQ-REQUIRED-REMOVED", rule_version=self.rule_set_version,
            surface="REQUEST", location=f"{ptr}/properties/{json_pointer_escape(name)}",
            before_value={"required": True}, after_value={"present": False},
            classification="INFORMATIONAL", severity="low",
            reason=f"required request field {name} removed; senders that still send it are "
                   "usually tolerated (servers ignore unknown fields), flagged informational",
        )

    def _new_property_finding(self, ptr: str, name: str, sub: SchemaNode,
                              direction: str, required: bool = False) -> Finding:
        if direction == "response":
            # A new response property (required or not) is data the producer now
            # emits. Typical consumers ignore unknown members; only strict
            # response validators reject them, hence ADDITIVE with a caveat.
            return Finding(
                rule_id="API-RESP-OPTIONAL-ADDED", rule_version=self.rule_set_version,
                surface="RESPONSE",
                location=f"{ptr}/properties/{json_pointer_escape(name)}",
                before_value=None,
                after_value={"type": _types_label(sub), "nullable": sub.nullable,
                             "required": required},
                classification="ADDITIVE", severity="low",
                reason=(f"new response property {name} added; additive for typical consumers "
                        "but strict response validators may reject unknown members"),
            )
        # Request direction: a new REQUIRED input property breaks existing
        # callers; a new optional one is additive.
        return Finding(
            rule_id="API-REQ-REQUIRED-ADDED" if required else "API-REQUEST-NEW-OPTIONAL",
            rule_version=self.rule_set_version,
            surface="REQUEST",
            location=f"{ptr}/properties/{json_pointer_escape(name)}",
            before_value=None,
            after_value={"type": _types_label(sub), "required": required},
            classification="BREAKING" if required else "ADDITIVE",
            severity="high" if required else "low",
            reason=(f"new required request property {name}; existing callers omit it"
                    if required
                    else f"new optional request property {name} accepted; additive under supported rules"),
        )

    def _diff_property(self, ptr: str, name: str,
                       before: SchemaNode, after: SchemaNode,
                       direction: str) -> list[Finding]:
        out: list[Finding] = []
        loc = f"{ptr}/properties/{json_pointer_escape(name)}"
        compatible, why = _types_compatible(before, after)
        if not compatible:
            out.append(Finding(
                rule_id="API-RESP-TYPE-CHANGED" if direction == "response" else "API-REQ-TYPE-CHANGED",
                rule_version=self.rule_set_version,
                surface="RESPONSE" if direction == "response" else "REQUEST",
                location=loc,
                before_value={"type": _types_label(before)},
                after_value={"type": _types_label(after)},
                classification="BREAKING" if direction == "response" else "POTENTIALLY_BREAKING",
                severity="critical" if direction == "response" else "medium",
                reason=f"field type change: {why}",
            ))
        removed = _enum_removed(before, after)
        if before.enum is not None and after.enum is not None:
            if removed and direction == "request":
                out.append(Finding(
                    rule_id="API-REQ-ENUM-REMOVED", rule_version=self.rule_set_version,
                    surface="REQUEST", location=loc,
                    before_value={"enum": list(before.enum)}, after_value={"enum": list(after.enum)},
                    classification="BREAKING", severity="high",
                    reason=f"previously accepted request values no longer allowed: {removed}",
                ))
            elif removed and direction == "response":
                out.append(Finding(
                    rule_id="API-RESP-ENUM-REMOVED", rule_version=self.rule_set_version,
                    surface="RESPONSE", location=loc,
                    before_value={"enum": list(before.enum)}, after_value={"enum": list(after.enum)},
                    classification="BREAKING", severity="high",
                    reason=f"response enum values removed: {removed}",
                ))
            expanded = [v for v in after.enum if v not in before.enum]
            if expanded and direction == "response":
                out.append(Finding(
                    rule_id="API-RESP-ENUM-EXPANDED", rule_version=self.rule_set_version,
                    surface="RESPONSE", location=loc,
                    before_value={"enum": list(before.enum)}, after_value={"enum": list(after.enum)},
                    classification="POTENTIALLY_BREAKING", severity="medium",
                    reason=f"new possible response values {expanded} may violate strict consumer validation",
                ))
        # nullable tightened on response
        if direction == "response" and before.nullable and not after.nullable and compatible:
            if before.types == after.types or set(before.types) == set(after.types):
                out.append(Finding(
                    rule_id="API-RESP-TYPE-CHANGED", rule_version=self.rule_set_version,
                    surface="RESPONSE", location=loc,
                    before_value={"type": _types_label(before)},
                    after_value={"type": _types_label(after)},
                    classification="POTENTIALLY_BREAKING", severity="medium",
                    reason="field can no longer be null; consumers handling null will observe errors",
                ))
        return out


def run_engine(before: NormalizedDocument, after: NormalizedDocument) -> RuleEngineResult:
    return CompatibilityRuleEngine().diff(before, after)
