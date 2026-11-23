# Evidence index

| Requirement | Implementation path | Test/command | Observed evidence | Status |
|---|---|---|---|---|
| FR-01 bounded OpenAPI parsing | services/api/app/parsing/openapi_loader.py | pytest tests/python/test_openapi_parsing.py | 145 tests passed locally (see TESTING.md) | VERIFIED_LOCAL |
| FR-01b 3.0/3.1 dialects | openapi_model.py | test_openapi_dialects.py | passed | VERIFIED_LOCAL |
| FR-02 rule engine | app/domain/rules.py | test_compatibility_rules.py | passed | VERIFIED_LOCAL |
| FR-02b unknowns fail closed | rules.py + release_policy.py | test_unknown_and_bounds.py | passed | VERIFIED_LOCAL |
| FR-03 SQL migration risk | app/parsing/sql_migration.py | test_sql_migrations.py | passed | VERIFIED_LOCAL |
| FR-04 dependency graph | app/domain/dependency_impact.py | test_dependency_impact.py | passed | VERIFIED_LOCAL |
| FR-05 release policy | app/domain/release_policy.py | test_release_policy.py | passed | VERIFIED_LOCAL |
| DB constraints | db/migrations/*.sql | test_db_constraints.py | passed | VERIFIED_LOCAL |
| Authorization | app/auth/session.py | test_auth_boundaries.py | passed | VERIFIED_LOCAL |
| Webhook security | app/main.py github_webhook | test_github_webhooks.py | passed | VERIFIED_LOCAL |
| Worker idempotency | app/worker/pipeline.py | test_worker_idempotency.py | passed | VERIFIED_LOCAL |
| Runner controls | services/runner/* | test_runner_allowlist.py | passed | VERIFIED_LOCAL |
| Real JS consumers | examples/* | direct node runs | billing exit 1 breaking / exit 0 additive; reporting exit 0 both | VERIFIED_LOCAL |
| End-to-end workflows | app/worker/pipeline.py | test_api_workflows.py (14 tests) | breaking→BLOCK, additive→PASS, external-ref→REVIEW | VERIFIED_LOCAL |
| GitHub reporting honesty | app/infra/github.py | test_github_reporting.py | passed | VERIFIED_LOCAL |
| AI non-authority | app/reporting/summary_draft.py | test_summary_draft.py | passed | VERIFIED_LOCAL |
| Web UI | apps/web/src | npm run build | build succeeded | VERIFIED_LOCAL |
| PR checks on GitHub | .github/workflows/ci.yml | push + controlled PRs | NOT YET OBSERVED (pending push) | PENDING |
| Clean-clone Docker | docker-compose.yml | scripts/verify-clean-clone.sh | Docker absent in this sandbox; script degrades honestly | UNVERIFIED_DOCKER_ABSENT |
| FR-07 optional AI provider | summary_draft.py | test_summary_draft.py | template mode verified; provider opt-in unconfigured | OPTIONAL_UNCONFIGURED |
