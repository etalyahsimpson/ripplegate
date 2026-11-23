"""Normalized OpenAPI model: the bounded subset RippleGate reasons about.

The normalizer converts parsed JSON/YAML documents into a small typed
structure so the rule engine never touches raw untrusted dicts. Unsupported
constructs surface as UnsupportedConstruct entries with exact locations;
they are never silently flattened or guessed to be compatible.

Supported subset (spec 5.1):
  paths, get/post/put/patch/delete, path/query/header parameters, requestBody
  JSON schema, responses JSON schema, object schemas, properties, required,
  primitive types, items arrays, nullable (3.0), type-list null union (3.1),
  enum, descriptions, local #/components/schemas/... references.

Everything else (oneOf/anyOf/allOf/discriminator/additionalProperties as a
schema, external refs, callbacks, non-local refs) is UNSUPPORTED.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .openapi_loader import (
    ParseLimitError,
    UnsupportedConstructError,
    json_pointer_escape,
)

HTTP_OPERATIONS = ("get", "post", "put", "patch", "delete")
MAX_REF_DEPTH = 32

Primitive = str | int | float | bool | None


@dataclass
class UnsupportedConstruct:
    location: str
    construct: str
    detail: str


@dataclass
class SchemaNode:
    """A bounded JSON-schema-ish node after $ref resolution.

    nullable is normalized: OpenAPI 3.0 'nullable: true' and OpenAPI 3.1
    'type: [T, "null"]' both map to nullable=True so dialects compare by
    semantics, not spelling. types holds the non-null type names.
    """

    types: tuple[str, ...] = ()
    nullable: bool = False
    enum: tuple[Any, ...] | None = None
    items: "SchemaNode | None" = None
    properties: dict[str, "SchemaNode"] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    description: str | None = None
    ref_name: str | None = None  # preserved reference identity for findings


@dataclass
class Parameter:
    name: str
    location: str  # path / query / header
    required: bool
    schema: SchemaNode


@dataclass
class Operation:
    method: str
    path: str
    parameters: list[Parameter]
    request_schema: SchemaNode | None
    response_schemas: dict[str, SchemaNode]  # status code -> schema


@dataclass
class NormalizedDocument:
    openapi_version: str
    operations: list[Operation]
    unsupported: list[UnsupportedConstruct]


class _Normalizer:
    def __init__(self, doc: dict[str, Any], version: str) -> None:
        self.doc = doc
        self.version = version
        self.major_minor = ".".join(version.split(".")[:2])  # '3.0' or '3.1'
        self.schemas = self._components_schemas()
        self.unsupported: list[UnsupportedConstruct] = []
        self._resolving: set[str] = set()

    def _components_schemas(self) -> dict[str, Any]:
        comps = self.doc.get("components")
        if comps is None:
            return {}
        if not isinstance(comps, dict):
            raise UnsupportedConstructError("components must be an object")
        schemas = comps.get("schemas")
        if schemas is None:
            return {}
        if not isinstance(schemas, dict):
            raise UnsupportedConstructError("components.schemas must be an object")
        return schemas

    # ------------------------------------------------------------------ refs
    def _resolve_ref(self, ref: Any, ptr: str, depth: int = 0) -> SchemaNode:
        if depth > MAX_REF_DEPTH:
            raise UnsupportedConstructError(f"reference chain too deep at {ptr}")
        if not isinstance(ref, str):
            raise UnsupportedConstructError(f"$ref must be a string at {ptr}")
        if not ref.startswith("#/components/schemas/"):
            if ref.startswith("#"):
                raise UnsupportedConstructError(
                    f"unsupported local $ref target (only #/components/schemas/...) at {ptr}: {ref}"
                )
            raise UnsupportedConstructError(
                f"external/non-local $ref refused at {ptr}: {ref[:120]}"
            )
        name = ref.split("/")[-1]
        if name in self._resolving:
            raise UnsupportedConstructError(f"circular $ref detected at {ptr} ({name})")
        target = self.schemas.get(name)
        if target is None:
            raise UnsupportedConstructError(f"$ref target missing at {ptr}: {ref}")
        self._resolving.add(name)
        try:
            return self._schema(target, ptr, depth + 1, ref_name=name)
        finally:
            self._resolving.discard(name)

    # ---------------------------------------------------------------- schema
    def _schema(self, node: Any, ptr: str, depth: int = 0, ref_name: str | None = None) -> SchemaNode:
        if node is None:
            return SchemaNode()
        if not isinstance(node, dict):
            raise UnsupportedConstructError(f"schema must be an object at {ptr}")
        if len(node) == 1 and "$ref" in node:
            return self._resolve_ref(node["$ref"], ptr, depth)

        out = SchemaNode(ref_name=ref_name)
        unrecognized = set(node) - {
            "type", "nullable", "enum", "items", "properties", "required",
            "description", "$ref", "format", "title",
        }
        # 'format'/'title' carry no compatibility decision weight in the subset;
        # they are tolerated and dropped. Everything else is unsupported.
        if unrecognized:
            self.unsupported.append(
                UnsupportedConstruct(
                    location=ptr,
                    construct=sorted(unrecognized)[0],
                    detail=f"unsupported schema keyword(s) {sorted(unrecognized)} at {ptr}",
                )
            )
            raise UnsupportedConstructError(
                f"unsupported schema keyword(s) {sorted(unrecognized)} at {ptr}"
            )

        raw_type = node.get("type")
        if isinstance(raw_type, str):
            out.types = (raw_type,)
            if raw_type != "object" and raw_type not in _PRIMITIVE_TYPES and raw_type != "array":
                # unknown type name: stay honest rather than guess
                raise UnsupportedConstructError(
                    f"unsupported schema type {raw_type!r} at {ptr}"
                )
        elif isinstance(raw_type, list):
            if self.major_minor == "3.1":
                normalized = []
                for t in raw_type:
                    if not isinstance(t, str):
                        raise UnsupportedConstructError(f"non-string type entry at {ptr}")
                    if t == "null":
                        continue
                    normalized.append(t)
                out.types = tuple(normalized)
                out.nullable = "null" in raw_type
            else:
                raise UnsupportedConstructError(
                    f"array-valued 'type' is only valid in OpenAPI 3.1; found at {ptr}"
                )

        nullable_flag = node.get("nullable")
        if self.major_minor == "3.0" and nullable_flag is True:
            out.nullable = True
        elif self.major_minor == "3.1" and nullable_flag is not None:
            raise UnsupportedConstructError(
                f"'nullable' is not a 3.1 keyword (use type:[T,'null']) at {ptr}"
            )

        if "enum" in node:
            enum = node["enum"]
            if not isinstance(enum, list):
                raise UnsupportedConstructError(f"enum must be an array at {ptr}")
            out.enum = tuple(enum)

        if "items" in node:
            out.items = self._schema(node["items"], f"{ptr}/items", depth + 1)

        if "properties" in node:
            props = node["properties"]
            if not isinstance(props, dict):
                raise UnsupportedConstructError(f"properties must be an object at {ptr}")
            for key, sub in props.items():
                out.properties[key] = self._schema(
                    sub, f"{ptr}/properties/{json_pointer_escape(key)}", depth + 1
                )

        if "required" in node:
            req = node["required"]
            if not isinstance(req, list) or not all(isinstance(r, str) for r in req):
                raise UnsupportedConstructError(f"required must be an array of strings at {ptr}")
            out.required = tuple(req)

        if isinstance(node.get("description"), str):
            out.description = node["description"]
        return out

    # ----------------------------------------------------------- parameters
    def _parameter(self, p: Any, ptr: str) -> Parameter:
        if not isinstance(p, dict):
            raise UnsupportedConstructError(f"parameter must be an object at {ptr}")
        name = p.get("name")
        loc = p.get("in")
        if not isinstance(name, str) or loc not in ("path", "query", "header"):
            raise UnsupportedConstructError(f"invalid parameter name/in at {ptr}")
        required = bool(p.get("required", loc == "path"))
        schema = self._schema(p.get("schema"), f"{ptr}/schema")
        return Parameter(name=name, location=loc, required=required, schema=schema)

    # ------------------------------------------------------------ operations
    def _operation(self, method: str, path: str, op: dict[str, Any]) -> Operation:
        ptr = f"/paths/{json_pointer_escape(path)}/{method}"
        unsupported_keys = set(op) - {"parameters", "requestBody", "responses", "operationId",
                                     "summary", "description", "tags", "deprecated"}
        if unsupported_keys:
            raise UnsupportedConstructError(
                f"unsupported operation keyword(s) {sorted(unsupported_keys)} at {ptr}"
            )
        parameters: list[Parameter] = []
        for i, p in enumerate(op.get("parameters", []) or []):
            parameters.append(self._parameter(p, f"{ptr}/parameters/{i}"))
        request_schema = None
        rb = op.get("requestBody")
        if isinstance(rb, dict):
            content = rb.get("content", {})
            if not isinstance(content, dict) or "application/json" not in content:
                raise UnsupportedConstructError(
                    f"requestBody requires application/json content at {ptr}"
                )
            media = content["application/json"]
            if not isinstance(media, dict) or "schema" not in media:
                raise UnsupportedConstructError(f"missing schema in requestBody at {ptr}")
            request_schema = self._schema(media["schema"], f"{ptr}/requestBody/content/application~1json/schema")
        elif rb is not None:
            raise UnsupportedConstructError(f"requestBody must be an object at {ptr}")

        responses = op.get("responses", {})
        if not isinstance(responses, dict):
            raise UnsupportedConstructError(f"responses must be an object at {ptr}")
        response_schemas: dict[str, SchemaNode] = {}
        for status, resp in responses.items():
            if not isinstance(status, str) or not (status.isdigit() or status == "default"):
                raise UnsupportedConstructError(f"invalid response status {status!r} at {ptr}")
            rptr = f"{ptr}/responses/{status}"
            if not isinstance(resp, dict):
                raise UnsupportedConstructError(f"response must be an object at {rptr}")
            content = resp.get("content")
            if content is None:
                continue  # a response with no content has no schema to compare
            if not isinstance(content, dict) or "application/json" not in content:
                raise UnsupportedConstructError(
                    f"only application/json response content is supported at {rptr}"
                )
            media = content["application/json"]
            if not isinstance(media, dict) or "schema" not in media:
                raise UnsupportedConstructError(f"missing schema in response at {rptr}")
            response_schemas[status] = self._schema(
                media["schema"], f"{rptr}/content/application~1json/schema"
            )
        return Operation(method=method, path=path, parameters=parameters,
                         request_schema=request_schema, response_schemas=response_schemas)

    # --------------------------------------------------------------- document
    def normalize(self) -> NormalizedDocument:
        paths = self.doc.get("paths")
        if not isinstance(paths, dict):
            raise UnsupportedConstructError("paths must be an object")
        operations: list[Operation] = []
        for path, item in paths.items():
            if not isinstance(path, str) or not isinstance(item, dict):
                raise UnsupportedConstructError("path item must be an object")
            for method in HTTP_OPERATIONS:
                if method in item:
                    operations.append(self._operation(method, path, item[method]))
        return NormalizedDocument(
            openapi_version=self.version, operations=operations, unsupported=self.unsupported
        )


_PRIMITIVE_TYPES = {"string", "integer", "number", "boolean"}


def normalize(doc: dict[str, Any], version: str) -> NormalizedDocument:
    return _Normalizer(doc, version).normalize()
