# RippleGate - engineering agent guidance

RippleGate is an evidence-led API compatibility and release-impact analysis product:
OpenAPI diffs, bounded PostgreSQL migration risk review, registered consumer
dependencies, controlled consumer test execution and deterministic release policy.

## Technology lock (closed world)

Only these are allowed in tracked source. Do not add anything else without an ADR.

- Python 3.12: FastAPI, Pydantic, Celery, psycopg (DB adapter, confined to `services/api/app/infra/` and `services/api/app/parsing/`), PyYAML (safe load only, same confinement), pytest, uvicorn, httpx (test transport), stdlib.
- TypeScript/Next.js App Router + React, Tailwind CSS, TanStack Query, React Hook Form, Zod, Playwright; Node.js 22 LTS (CI) / 24 compatible.
- JavaScript: Node/Express consumer fixtures + Jest only (`examples/`).
- SQL: PostgreSQL 16 migrations in `db/migrations/`; Redis 7 as queue only.
- Bash for `scripts/`; Docker/Compose + GitHub Actions for runtime/CI.

Forbidden examples: Go, Rust, Java, C#, Django, Flask, SQLAlchemy, Prisma, MongoDB,
Kafka, Kubernetes, Terraform, any new chart/graph SDK, any new test framework. See
`scripts/verify-technology-lock.sh` for the enforced audit.

## File ownership

- `services/api/app/parsing/` - bounded OpenAPI JSON/YAML loader + SQL migration tokenizer (no execution of untrusted SQL).
- `services/api/app/domain/` - the ONLY compatibility rule engine (versioned rule IDs), dependency impact mapping, release policy, run-state machine. Frontend never re-classifies.
- `services/api/app/infra/` - psycopg transactional store, artifact store, GitHub REST adapter.
- `services/api/app/auth/` - demo sessions (HMAC-signed, expiring, membership-checked).
- `services/worker/` - Celery task pipeline `QUEUED -> PARSING -> DIFFED -> IMPACT_MAPPED -> TESTING -> ASSESSED -> COMPLETED` (+ `ERROR`/`CANCELLED`), idempotent by run_key.
- `services/runner/` - allowlisted fixture execution: fixed argv arrays, bounded timeouts, log redaction. NEVER arbitrary user commands/images.
- `apps/web/src/` - Next.js UI; all data via typed API client; no fabricated analytics.
- `db/migrations/` - explicit versioned SQL with `schema_migrations` ledger; applied in order.

## Architecture invariants

1. PostgreSQL is authoritative for runs, findings, verdicts. Redis is queue transport only.
2. Evidence ladder kept separate: structural change -> rule classification -> registered consumer impact -> executed test outcome.
3. `UNKNOWN`, `UNSUPPORTED`, runner failure and missing dependency coverage are first-class results, never rendered as PASS.
4. Policy outcomes: `BLOCK` / `REVIEW` / `PASS` / `ERROR`; fail closed on unknowns and infrastructure errors.
5. Immutable analysis identity: run_key = sha256(project + base identity + candidate identity + policy version + digests + registry revision). Re-analysis means a new run; old evidence stays immutable.
6. Webhooks: raw-byte HMAC-SHA256 validation before parse; delivery-ID dedup; repo allowlist.
7. Runner boundary: the API/web containers never mount the Docker socket. The trusted launcher runs pinned fixture suites only.

## Commands

From repo root (see docs/DEPLOYMENT.md for the full path):

- `pytest services/api/tests tests/python` - unit, API, auth, webhook, policy, DB tests.
- `npm --prefix apps/web ci && npm --prefix apps/web run build` - web typecheck + build.
- `npm --prefix examples/billing-service ci && npm --prefix examples/billing-service test` (and reporting-service) - consumer contract suites.
- `bash scripts/verify-technology-lock.sh` and `bash scripts/verify-links.sh` - repo audits.
- `docker compose up --build -d` then `bash scripts/bootstrap.sh`, `bash scripts/demo-breaking.sh`, `bash scripts/demo-compatible.sh` - full local demo.
- `bash scripts/verify-clean-clone.sh` - clean-clone smoke.

## Test gates (do not weaken)

All pytest + Jest + tsc + next build + Playwright suites must pass. Expected-negative
fixtures (billing failure on breaking candidate) are asserted as *correctly detected*
failures, never skipped. CI is `.github/workflows/ci.yml`; the run on the final
pushed SHA is the only release-green signal.

## Secrets

No token, key or `.env` file is ever committed. `.env.example` holds harmless
placeholders only. Sessions and webhooks verify with HMAC from runtime env
variables. Report anything that looks like a credential; never log it.

## Honesty rules

- Synthetic demo data is labeled synthetic (`demo-platform`, `source_type=FIXTURE` fingerprints, not fake git SHAs).
- Statuses `CONFIGURATION_REQUIRED` / `APP_MODE_UNCONFIGURED` / `PUBLIC_DEPLOYMENT_NOT_VERIFIED` are legitimate, expected labels; do not paper over them.
