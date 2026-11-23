-- RippleGate migration 001: core registry (organizations, memberships, projects,
-- integrations, services, contract versions, consumer dependencies, policies).
-- All UUIDs are application-generated (gen_random_uuid() fallback allowed).
-- TIMESTAMPTZ UTC only. Explicit CHECK constraints for every enum-ish column.

BEGIN;

CREATE TABLE IF NOT EXISTS organizations (
    id           UUID PRIMARY KEY,
    name         TEXT NOT NULL,
    slug         TEXT NOT NULL UNIQUE,
    synthetic    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')
);
COMMENT ON TABLE organizations IS 'Demo organizations carry synthetic=true; no real customer data.';

CREATE TABLE IF NOT EXISTS memberships (
    id              UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('admin','maintainer','reviewer','viewer')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT (now() AT TIME ZONE 'UTC'),
    UNIQUE (organization_id, user_id)
);

CREATE TABLE IF NOT EXISTS projects (
    id              UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    github_repo_id  BIGINT,
    owner           TEXT NOT NULL CHECK (owner <> '' AND length(owner) <= 100),
    repository      TEXT NOT NULL CHECK (repository <> '' AND length(repository) <= 100),
    display_name    TEXT NOT NULL CHECK (display_name <> '' AND length(display_name) <= 120),
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT (now() AT TIME ZONE 'UTC'),
    UNIQUE (organization_id, owner, repository)
);
CREATE INDEX IF NOT EXISTS projects_org_idx ON projects(organization_id);

CREATE TABLE IF NOT EXISTS integrations (
    id              UUID PRIMARY KEY,
    project_id      UUID NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
    installation_id BIGINT,
    allowed_paths   JSONB NOT NULL DEFAULT '[]'::jsonb,
    permissions     JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled         BOOLEAN NOT NULL DEFAULT FALSE
);
-- allowed_paths is a bounded manifest (<=20 entries) validated by the application.

CREATE TABLE IF NOT EXISTS services (
    id          UUID PRIMARY KEY,
    project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name        TEXT NOT NULL CHECK (name <> '' AND length(name) <= 100),
    kind        TEXT NOT NULL CHECK (kind IN ('producer','consumer')),
    owner_label TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT (now() AT TIME ZONE 'UTC'),
    UNIQUE (project_id, name)
);

CREATE TABLE IF NOT EXISTS contract_versions (
    id              UUID PRIMARY KEY,
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    service_id      UUID NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    source_type     TEXT NOT NULL DEFAULT 'FIXTURE' CHECK (source_type IN ('GITHUB_COMMIT','FIXTURE')),
    commit_sha      CHAR(40),
    fixture_id      TEXT,
    spec_digest     CHAR(64) NOT NULL,
    openapi_version TEXT NOT NULL,
    format          TEXT NOT NULL CHECK (format IN ('json','yaml')),
    storage_key     TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')
);
-- unique immutable contract identity (expression index: functions in UNIQUE
-- constraints need to be immutable; COALESCE is stable, so use an equivalent
-- unique index on the COALESCE expression instead)
CREATE UNIQUE INDEX IF NOT EXISTS contract_versions_identity_idx
    ON contract_versions (
        project_id, service_id, source_type,
        COALESCE(commit_sha, ''), COALESCE(fixture_id, ''), spec_digest
    );
ALTER TABLE contract_versions DROP CONSTRAINT IF EXISTS contract_versions_identity_ck;
ALTER TABLE contract_versions ADD CONSTRAINT contract_versions_identity_ck CHECK (
    (source_type = 'GITHUB_COMMIT' AND commit_sha IS NOT NULL AND commit_sha ~ '^[0-9a-f]{40}$'
        AND fixture_id IS NULL)
    OR (source_type = 'FIXTURE' AND fixture_id IS NOT NULL AND commit_sha IS NULL)
);

CREATE TABLE IF NOT EXISTS consumer_dependencies (
    id                   UUID PRIMARY KEY,
    project_id          UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    producer_service_id UUID NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    consumer_service_id UUID NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    http_method         TEXT NOT NULL,
    path_pattern        TEXT NOT NULL,
    required_fields     JSONB NOT NULL DEFAULT '[]'::jsonb,
    version_range      TEXT NOT NULL DEFAULT '>0',
    test_suite_id       TEXT NOT NULL,
    evidence_source     TEXT NOT NULL DEFAULT 'OWNER_REGISTERED' CHECK (evidence_source IN ('OWNER_REGISTERED')),
    registry_revision   INT NOT NULL CHECK (registry_revision >= 0),
    enabled             BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT (now() AT TIME ZONE 'UTC'),
    CHECK (producer_service_id <> consumer_service_id),
    UNIQUE (project_id, producer_service_id, consumer_service_id, http_method, path_pattern, registry_revision)
);
CREATE INDEX IF NOT EXISTS dep_producer_idx ON consumer_dependencies(producer_service_id, http_method, path_pattern);

CREATE TABLE IF NOT EXISTS policies (
    id                UUID PRIMARY KEY,
    project_id        UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version           INT NOT NULL CHECK (version >= 1),
    block_rules       JSONB NOT NULL,
    mandatory_suites  JSONB NOT NULL,
    unknown_strategy  TEXT NOT NULL CHECK (unknown_strategy IN ('REVIEW','BLOCK')),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT (now() AT TIME ZONE 'UTC'),
    UNIQUE (project_id, version)
);
-- Policies are immutable versioned rows; a new configuration is always a new version.

COMMIT;
