# Security model

## Assets and entry points
- Analysis evidence (runs/findings/assessments) in Postgres; consumer logs as sanitized artifacts; the demo session mechanism; the GitHub webhook intake.

## Controls (each has a test)
| Risk | Control | Test |
|---|---|---|
| Spoofed webhook | raw-byte HMAC-SHA256, constant-time compare, repo allowlist, event allowlist | `tests/python/test_github_webhooks.py` |
| Replay/duplicate delivery | unique delivery_id + run_key; idempotent pipeline | `test_worker_idempotency.py`, `test_db_constraints.py` |
| Cross-tenant leak | membership scoping on every route; 404 without existence leak | `test_auth_boundaries.py` |
| Malicious contracts | bounded size/depth/nodes; no anchors/aliases; local refs only; cycle detection | `test_openapi_parsing.py`, `test_unknown_and_bounds.py` |
| Unsafe migration SQL | text-only tokenizer, never executed; unknown for unsupported DDL | `test_sql_migrations.py` |
| Runner injection | pinned allowlist, fixed argv, no user commands/images; timeout/infra distinct statuses | `test_runner_allowlist.py` |
| Credential disclosure | log redaction, no `.env` tracked, tokens never in bodies | `test_runner_allowlist.py::test_runner_log_sanitizer_redacts_secrets` |
| Unsafe verdict | fail closed: unknown→REVIEW, infra error→ERROR; AI draft read-only | `test_release_policy.py`, `test_summary_draft.py` |

## Residual risks (honest)
- The trusted local/CI launcher can start Docker one-shot containers; Docker daemon access is privileged by definition. The API/web/worker containers never mount the Docker socket, and the launcher runs only in operator/CI context.
- Demo sessions are development identities, not production SSO.
- The SQL parser covers a bounded subset; unsupported constructs are reported UNKNOWN, never "safe".
- This is a controlled portfolio reference system, not a certified security appliance.
