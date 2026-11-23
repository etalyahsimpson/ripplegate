# Limitations (read before trusting results)

- OpenAPI subset only: paths, the 5 methods, path/query/header params, JSON bodies/responses, object schemas, primitives, items, enum, nullable (3.0) / type-union (3.1), local #/components/schemas refs. Everything else (oneOf/anyOf/allOf/discriminator/additionalProperties-as-schema/external refs/callbacks) is reported UNKNOWN/UNSUPPORTED - never flattened, never "compatible".
- SQL migration parser covers DROP/RENAME/SET NOT NULL/ADD COLUMN/CREATE INDEX forms; DO blocks, functions and dynamic SQL are PG-UNKNOWN.
- Only REGISTERED consumers are mapped; absence of an edge is unknown coverage, not proof of no consumers.
- Consumer execution is limited to the two pinned allowlisted suites; this is a controlled fixture system, not an arbitrary-code sandbox.
- Demo sessions are development identities. GitHub App Checks mode is APP_MODE_UNCONFIGURED without installation credentials; webhook intake is validated but automated GitHub-sourced analysis requires the configured integration.
- Public cloud deployment: PUBLIC_DEPLOYMENT_NOT_VERIFIED (no authorized host in this environment).
- AI summary is an optional rewording of immutable evidence; deterministic templates always work provider-free.
