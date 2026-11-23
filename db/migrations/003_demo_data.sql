-- RippleGate migration 003: synthetic demo seed (FIXTURE-sourced identities only).
-- Every row here is explicitly synthetic: demo-platform organization, three
-- example services, one policy version, and the two registered dependency edges.
-- IMPORTANT: no fixture row stores a fake 40-hex git SHA; fixtures use
-- source_type=FIXTURE + fixture_id (e.g. fixture-base-v1) per spec 6.1.

BEGIN;

INSERT INTO organizations (id, name, slug, synthetic) VALUES
    ('a0000000-0000-4000-8000-000000000001', 'Demo Platform (synthetic)', 'demo-platform', TRUE)
ON CONFLICT (slug) DO NOTHING;

INSERT INTO memberships (id, organization_id, user_id, role) VALUES
    ('b0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000001', 'admin'),
    ('b0000000-0000-4000-8000-000000000002', 'a0000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000002', 'viewer')
ON CONFLICT (organization_id, user_id) DO NOTHING;

INSERT INTO projects (id, organization_id, owner, repository, display_name) VALUES
    ('11111111-1111-4111-8111-111111111111', 'a0000000-0000-4000-8000-000000000001',
     'etalyahsimpson', 'demo-orders', 'Demo Orders API (synthetic)')
ON CONFLICT (organization_id, owner, repository) DO NOTHING;

INSERT INTO integrations (id, project_id, allowed_paths, permissions, enabled) VALUES
    ('c0000000-0000-4000-8000-000000000001', '11111111-1111-4111-8111-111111111111',
     '["examples/orders-api/openapi-base.json","examples/orders-api/openapi-candidate.json"]'::jsonb,
     '{"mode":"fixture","pull_requests":"read"}'::jsonb, TRUE)
ON CONFLICT (project_id) DO NOTHING;

INSERT INTO services (id, project_id, name, kind, owner_label) VALUES
    ('22222222-2222-4222-8222-222222222222', '11111111-1111-4111-8111-111111111111', 'orders-api', 'producer', 'orders-team'),
    ('33333333-3333-4333-8333-333333333333', '11111111-1111-4111-8111-111111111111', 'billing-service', 'consumer', 'billing-team'),
    ('44444444-4444-4444-8444-444444444444', '11111111-1111-4111-8111-111111111111', 'reporting-service', 'consumer', 'data-team')
ON CONFLICT (project_id, name) DO NOTHING;

-- contract_versions rows are inserted by scripts/bootstrap.sh via the API (digests
-- are computed from actual file contents, so no digest is hardcoded here).

INSERT INTO policies (id, project_id, version, block_rules, mandatory_suites, unknown_strategy) VALUES
    ('d0000000-0000-4000-8000-000000000001', '11111111-1111-4111-8111-111111111111', 1,
     '["API-PATH-REMOVED","API-REQ-REQUIRED-ADDED","API-REQ-ENUM-REMOVED","API-RESP-REQUIRED-REMOVED","API-RESP-TYPE-CHANGED"]'::jsonb,
     '["billing-contract","reporting-contract"]'::jsonb,
     'REVIEW')
ON CONFLICT (project_id, version) DO NOTHING;

INSERT INTO consumer_dependencies
    (id, project_id, producer_service_id, consumer_service_id, http_method, path_pattern,
     required_fields, version_range, test_suite_id, evidence_source, registry_revision) VALUES
    ('e0000000-0000-4000-8000-000000000001', '11111111-1111-4111-8111-111111111111',
     '22222222-2222-4222-8222-222222222222', '33333333-3333-4333-8333-333333333333',
     'GET', '/orders/{id}',
     '["customer_id","total_cents"]'::jsonb, '^1\\.0', 'billing-contract', 'OWNER_REGISTERED', 1),
    ('e0000000-0000-4000-8000-000000000002', '11111111-1111-4111-8111-111111111111',
     '22222222-2222-4222-8222-222222222222', '44444444-4444-4444-8444-444444444444',
     'GET', '/orders/{id}',
     '["total_cents"]'::jsonb, '^1\\.0', 'reporting-contract', 'OWNER_REGISTERED', 1)
ON CONFLICT (project_id, producer_service_id, consumer_service_id, http_method, path_pattern, registry_revision) DO NOTHING;

COMMIT;
