"""Bounded OpenAPI document loading.

Trust boundary: input documents are untrusted data. This loader enforces the
spec's hard limits (size, depth, node count, local refs only, no custom YAML
tags/anchors) before any structural analysis happens. It never fetches external
URLs. PyYAML is pinned to safe_load; psycopg-style adapters stay out of here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import yaml

MAX_BYTES = 1_048_576          # 1 MiB
MAX_DEPTH = 32                 # JSON/YAML nesting depth
MAX_NODES = 20_000             # total visited nodes
MAX_REF_RESOLUTIONS = 10_000   # local $ref lookups per document


class ParseLimitError(ValueError):
    """Raised when a document exceeds a bounded limit (never a compatibility verdict)."""


class UnsupportedConstructError(ValueError):
    """Raised when a construct is outside the supported OpenAPI subset.

    Callers convert this into an UNKNOWN/UNSUPPORTED finding, never into PASS.
    """


@dataclass
class _Budget:
    nodes: int = 0
    ref_resolutions: int = 0

    def count_node(self) -> None:
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise ParseLimitError("document exceeds max node budget (20,000)")

    def count_ref(self) -> None:
        self.ref_resolutions += 1
        if self.ref_resolutions > MAX_REF_RESOLUTIONS:
            raise ParseLimitError("document exceeds max $ref resolution budget (10,000)")


def _walk_count(value: Any, depth: int, budget: _Budget) -> None:
    if depth > MAX_DEPTH:
        raise ParseLimitError(f"document nesting exceeds max depth ({MAX_DEPTH})")
    budget.count_node()
    if isinstance(value, dict):
        for v in value.values():
            _walk_count(v, depth + 1, budget)
    elif isinstance(value, list):
        for item in value:
            _walk_count(item, depth + 1, budget)


class _NoAliasSafeLoader(yaml.SafeLoader):
    """SafeLoader subclass that rejects anchors/aliases outright.

    yaml.safe_load alone permits YAML anchors and aliases, which enables alias
    amplification (small source, huge object graph). Anchors arrive as an
    `anchor=` property on the next event; aliases as AliasEvent. Both are
    refused before any node is constructed.
    """

    def compose_node(self, parent: Any, index: Any) -> Any:
        from yaml.events import AliasEvent
        if self.check_event(AliasEvent):
            raise UnsupportedConstructError("YAML aliases are not supported")
        event = self.peek_event()
        if getattr(event, "anchor", None) is not None:
            raise UnsupportedConstructError("YAML anchors are not supported")
        return super().compose_node(parent, index)


def load_document(text: str, fmt: str) -> dict[str, Any]:
    """Parse an OpenAPI document from JSON or YAML text within hard bounds.

    fmt: 'json' or 'yaml'. Returns the parsed mapping (NOT the analysis result).
    Raises ParseLimitError / UnsupportedConstructError / ValueError on abuse.
    """
    if not isinstance(text, str):
        raise ValueError("document must be a string")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ParseLimitError(f"document exceeds max size ({MAX_BYTES} bytes)")
    if fmt == "json":
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON document: {exc.msg} at line {exc.lineno}") from exc
    elif fmt == "yaml":
        try:
            doc = yaml.load(text, Loader=_NoAliasSafeLoader)
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid YAML document: {exc}") from exc
    else:
        raise ValueError(f"unsupported format: {fmt!r}")
    if not isinstance(doc, dict):
        raise ValueError("document root must be an object/mapping")
    budget = _Budget()
    _walk_count(doc, 0, budget)
    return doc


SUPPORTED_VERSION_PREFIXES = ("3.0.", "3.1.")


def validate_openapi_version(doc: dict[str, Any]) -> str:
    """Return the openapi version string after checking it is 3.0.x/3.1.x."""
    version = doc.get("openapi")
    if not isinstance(version, str) or not any(
        version.startswith(p) for p in SUPPORTED_VERSION_PREFIXES
    ):
        raise UnsupportedConstructError(
            f"openapi field must be 3.0.x or 3.1.x, got {version!r}"
        )
    return version


def json_pointer_escape(token: str) -> str:
    """RFC 6901 escaping: '~' -> '~0', '/' -> '~1'."""
    return token.replace("~", "~0").replace("/", "~1")


def json_pointer_join(*tokens: str) -> str:
    return "/" + "/".join(json_pointer_escape(t) for t in tokens)
