# Data model

Migrations `db/migrations/001_core.sql`, `002_evidence.sql`, `003_demo_data.sql` with a `schema_migrations(version, digest)` ledger; idempotent, order-checked (digest mismatch refuses).

Tables: organizations, memberships, projects, integrations, services, contract_versions (UNIQUE expression index on project/service/source/COALESCE(commit_sha,'')/COALESCE(fixture_id,'')/digest; fixtures may never carry a git sha - CHECK), consumer_dependencies (producer≠consumer), policies (UNIQUE(project,version), immutable), analysis_runs (run_key CHAR(64) UNIQUE; source_type CHECK with 40-hex sha requirement for GITHUB_COMMIT), findings, impacts, test_executions (UNIQUE run/suite/fixture), artifacts, release_assessments (UNIQUE run, immutable once final), webhook_deliveries (delivery_id UNIQUE), audit_events (append-only).

Seed domain (`003_demo_data.sql`): demo-platform org (synthetic=true), orders-api producer, billing/reporting consumers, policy v1, two registered edges with allowlisted suite ids. Contract rows are inserted via the API at bootstrap so digests derive from actual file content.

Run identity: run_key = sha256(project + base identity + candidate identity + policy version + digests + registry revision) (`app/infra/store.py:compute_run_key`). New commit → new identity; old evidence immutable.
