-- RippleGate migration 002: evidence store (analysis runs, findings, impacts,
-- test executions, artifacts, release assessments, webhook deliveries, audit).

BEGIN;

CREATE TABLE IF NOT EXISTS analysis_runs (
    id               UUID PRIMARY KEY,
    project_id       UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    base_sha         CHAR(40),
    candidate_sha    CHAR(40),
    source_type      TEXT NOT NULL DEFAULT 'FIXTURE' CHECK (source_type IN ('GITHUB_COMMIT','FIXTURE')),
    base_identity    TEXT NOT NULL,
    candidate_identity TEXT NOT NULL,
    base_digest      CHAR(64) NOT NULL,
    candidate_digest CHAR(64) NOT NULL,
    migration_digest CHAR(64),
    policy_id        UUID NOT NULL REFERENCES policies(id),
    policy_version   INT NOT NULL,
    registry_revision INT NOT NULL,
    run_key          CHAR(64) NOT NULL UNIQUE,
    idempotency_key  TEXT,
    state            TEXT NOT NULL DEFAULT 'QUEUED' CHECK (state IN
                        ('QUEUED','PARSING','DIFFED','IMPACT_MAPPED','TESTING','ASSESSED','COMPLETED','ERROR','CANCELLED')),
    requested_by     UUID,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT (now() AT TIME ZONE 'UTC'),
    finished_at      TIMESTAMPTZ,
    CHECK (source_type = 'FIXTURE' OR (base_sha ~ '^[0-9a-f]{40}$' AND candidate_sha ~ '^[0-9a-f]{40}$')),
    CHECK (state = 'COMPLETED' OR state = 'ERROR' OR state = 'CANCELLED' OR finished_at IS NULL)
);
CREATE INDEX IF NOT EXISTS runs_project_created_idx ON analysis_runs(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS runs_idempotency_idx ON analysis_runs(idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS findings (
    id                 UUID PRIMARY KEY,
    run_id             UUID NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    rule_id            TEXT NOT NULL,
    rule_version       TEXT NOT NULL,
    surface            TEXT NOT NULL CHECK (surface IN ('REQUEST','RESPONSE','HTTP_OPERATION','DB_MIGRATION')),
    location           TEXT NOT NULL,
    before_value       JSONB,
    after_value        JSONB,
    classification     TEXT NOT NULL CHECK (classification IN
                           ('BREAKING','POTENTIALLY_BREAKING','ADDITIVE','INFORMATIONAL','UNKNOWN')),
    severity           TEXT NOT NULL CHECK (severity IN ('critical','high','medium','low','info')),
    reason             TEXT NOT NULL,
    verification_state TEXT NOT NULL DEFAULT 'STATIC_ONLY' CHECK (verification_state IN
                           ('STATIC_ONLY','CONSUMER_PASS','CONSUMER_FAIL','EXECUTION_ERROR','NOT_TESTED')),
    evidence_refs      JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence_basis   TEXT NOT NULL DEFAULT 'STRUCTURAL_STATIC',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')
);
CREATE INDEX IF NOT EXISTS findings_run_class_idx ON findings(run_id, classification);

CREATE TABLE IF NOT EXISTS impacts (
    id                      UUID PRIMARY KEY,
    run_id                  UUID NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    finding_id              UUID NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
    consumer_dependency_id  UUID REFERENCES consumer_dependencies(id) ON DELETE SET NULL,
    consumer_service_id     UUID NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    impact_state            TEXT NOT NULL CHECK (impact_state IN ('AFFECTED','UNKNOWN','NOT_AFFECTED')),
    reason                  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS impacts_run_idx ON impacts(run_id);

CREATE TABLE IF NOT EXISTS test_executions (
    id             UUID PRIMARY KEY,
    run_id         UUID NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    suite_id       TEXT NOT NULL,
    fixture_digest CHAR(64) NOT NULL,
    image_ref      TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('PASSED','FAILED','TIMED_OUT','INFRA_ERROR','NOT_RUN')),
    duration_ms    INT CHECK (duration_ms IS NULL OR duration_ms >= 0),
    exit_code      INT,
    artifact_id    UUID,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT (now() AT TIME ZONE 'UTC'),
    finished_at    TIMESTAMPTZ,
    UNIQUE (run_id, suite_id, fixture_digest)
);
CREATE INDEX IF NOT EXISTS test_exec_run_suite_idx ON test_executions(run_id, suite_id);

CREATE TABLE IF NOT EXISTS artifacts (
    id          UUID PRIMARY KEY,
    run_id      UUID NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('consumer_log','report_json','report_markdown','migration_sql','summary_draft')),
    relative_key TEXT NOT NULL,
    sha256      CHAR(64) NOT NULL,
    byte_size   INT NOT NULL CHECK (byte_size >= 0),
    visibility  TEXT NOT NULL DEFAULT 'project' CHECK (visibility IN ('public','project','private')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT (now() AT TIME ZONE 'UTC'),
    UNIQUE (run_id, kind, relative_key)
);

CREATE TABLE IF NOT EXISTS release_assessments (
    id                UUID PRIMARY KEY,
    run_id            UUID NOT NULL UNIQUE REFERENCES analysis_runs(id) ON DELETE CASCADE,
    policy_version    INT NOT NULL,
    outcome           TEXT NOT NULL CHECK (outcome IN ('BLOCK','REVIEW','PASS','ERROR')),
    blocking_reasons  JSONB NOT NULL DEFAULT '[]'::jsonb,
    unknowns          JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_digest   CHAR(64) NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')
);

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id              UUID PRIMARY KEY,
    delivery_id     TEXT NOT NULL UNIQUE,
    github_event    TEXT NOT NULL,
    repo_id         BIGINT NOT NULL,
    body_digest     CHAR(64) NOT NULL,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT (now() AT TIME ZONE 'UTC'),
    status          TEXT NOT NULL CHECK (status IN ('ACCEPTED','DUPLICATE','REJECTED')),
    analysis_run_id UUID REFERENCES analysis_runs(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id            UUID PRIMARY KEY,
    project_id    UUID REFERENCES projects(id) ON DELETE CASCADE,
    actor_id      UUID,
    action        TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id   UUID,
    summary       JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')
);
CREATE INDEX IF NOT EXISTS audit_project_time_idx ON audit_events(project_id, occurred_at DESC);

-- schema_migrations ledger is created by the migration runner itself; each
-- applied file records (version, digest) transactionally with its own changes.

COMMIT;
