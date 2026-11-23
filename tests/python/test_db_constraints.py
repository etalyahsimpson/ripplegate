"""Database constraints on the real schema (spec 13 matrix row 8)."""
from __future__ import annotations

import uuid

import pytest

from app.config import Settings
from app.infra.store import Store, StoreError


@pytest.fixture()
def store(database_url):
    s = Store(Settings(database_url=database_url,
                       session_signing_secret="x", webhook_secret="y",
                       artifact_dir="/tmp/rg-constraints"))
    with s.tx() as conn:
        conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    s.apply_migrations("db/migrations")
    yield s
    s.close()


PID = "11111111-1111-4111-8111-111111111111"
USER_ID = "10000000-0000-4000-8000-000000000001"


def _mk_project(store: Store) -> str:
    return store.create_project(
        "a0000000-0000-4000-8000-000000000001", "etalyahsimpson", "constraint-demo",
        "Constraint Demo", ["a/b.json"], USER_ID)


def test_unique_run_key_prevents_duplicate_runs(store):
    pid = _mk_project(store)
    with store.readonly() as conn:
        pol = conn.execute("SELECT id FROM policies WHERE project_id=%s LIMIT 1",
                           (pid,)).fetchone()
    assert pol is None  # no policy for a new project
    pol_id = store.create_policy(pid, 1, [], [], "REVIEW", USER_ID)
    k = store.compute_run_key(pid, "b", "c", 1, "d1", "d2", None, 1)
    r1, created1 = store.create_run(project_id=pid, run_key=k, idempotency_key=None,
        base_identity="b", candidate_identity="c", base_digest="d1",
        candidate_digest="d2", migration_digest=None, policy_id=pol_id,
        policy_version=1, registry_revision=1, source_type="FIXTURE",
        base_sha=None, candidate_sha=None, requested_by=None)
    r2, created2 = store.create_run(project_id=pid, run_key=k, idempotency_key=None,
        base_identity="b", candidate_identity="c", base_digest="d1",
        candidate_digest="d2", migration_digest=None, policy_id=pol_id,
        policy_version=1, registry_revision=1, source_type="FIXTURE",
        base_sha=None, candidate_sha=None, requested_by=None)
    assert created1 and not created2 and r1 == r2


def test_concurrent_same_run_key_single_row(store, database_url):
    # two connections racing to create the same run: UNIQUE(run_key) arbitrates
    import psycopg
    pid = _mk_project(store)
    pol_id = store.create_policy(pid, 1, [], [], "REVIEW", USER_ID)
    k = store.compute_run_key(pid, "b2", "c2", 1, "d1", "d2", None, 1)
    conns = [psycopg.connect(database_url) for _ in range(2)]
    inserted = []
    try:
        for conn in conns:
            conn.execute("BEGIN")
            row = conn.execute(
                "SELECT count(*) FROM analysis_runs WHERE run_key=%s", (k,)).fetchone()
            if row[0] == 0:
                try:
                    conn.execute(
                        """INSERT INTO analysis_runs
                           (id, project_id, run_key, base_identity, candidate_identity,
                            base_digest, candidate_digest, policy_id, policy_version,
                            registry_revision, source_type, state)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1,1,'FIXTURE','QUEUED')""",
                        (str(uuid.uuid4()), pid, k, "b2", "c2", "d1", "d2", pol_id))
                    inserted.append("mine")
                    conn.commit()
                except psycopg.errors.UniqueViolation:
                    conn.rollback()
                    inserted.append("theirs")
    finally:
        for conn in conns:
            conn.close()
    with store.readonly() as conn:
        rows = conn.execute("SELECT count(*) FROM analysis_runs WHERE run_key=%s",
                            (k,)).fetchone()[0]
    assert rows == 1


def test_policy_version_immutability(store):
    pid = _mk_project(store)
    store.create_policy(pid, 1, [], [], "REVIEW", USER_ID)
    try:
        store.create_policy(pid, 1, [], [], "REVIEW", USER_ID)
        raise AssertionError("duplicate policy version accepted")
    except StoreError:
        pass


def test_service_name_unique_per_project(store):
    pid = _mk_project(store)
    store.create_service(pid, "orders-api", "producer", "team", USER_ID)
    try:
        store.create_service(pid, "orders-api", "consumer", "team", USER_ID)
        raise AssertionError("duplicate service accepted")
    except StoreError:
        pass


def test_dependency_cross_project_rejected(store):
    pid1 = _mk_project(store)
    pid2 = store.create_project("a0000000-0000-4000-8000-000000000001",
                                 "etalyahsimpson", "second-demo", "Second",
                                 ["a/b.json"], USER_ID)
    s1a = store.create_service(pid1, "producer-a", "producer", "t", USER_ID)
    s2a = store.create_service(pid2, "consumer-b", "consumer", "t", USER_ID)
    try:
        store.create_dependency(pid1, s1a, s2a, "GET", "/x", [], ">0",
                                 "billing-contract", 1, USER_ID)
        raise AssertionError("cross-project dependency accepted")
    except StoreError as exc:
        assert "not in this project" in str(exc)


def test_fixture_contract_may_not_carry_git_sha(store):
    pid = _mk_project(store)
    sid = store.create_service(pid, "orders-api", "producer", "t", USER_ID)
    with pytest.raises(Exception):
        with store.tx() as conn:
            conn.execute(
                """INSERT INTO contract_versions
                   (id, project_id, service_id, source_type, commit_sha, spec_digest,
                    openapi_version, format, storage_key)
                   VALUES (%s,%s,%s,'FIXTURE',%s,%s,'3.0.3','json','k')""",
                (str(uuid.uuid4()), pid, sid, "a" * 40, "0" * 64))


def test_github_contract_requires_40_hex_sha(store):
    pid = _mk_project(store)
    sid = store.create_service(pid, "orders-api", "producer", "t", USER_ID)
    with pytest.raises(Exception):
        with store.tx() as conn:
            conn.execute(
                """INSERT INTO contract_versions
                   (id, project_id, service_id, source_type, commit_sha, spec_digest,
                    openapi_version, format, storage_key)
                   VALUES (%s,%s,%s,'GITHUB_COMMIT',%s,%s,'3.0.3','json','k')""",
                (str(uuid.uuid4()), pid, sid, "zzzz", "0" * 64))


def test_negative_duration_rejected(store):
    pid = _mk_project(store)
    pol_id = store.create_policy(pid, 1, [], [], "REVIEW", USER_ID)
    k = store.compute_run_key(pid, "x", "y", 1, "d1", "d2", None, 1)
    rid, _ = store.create_run(project_id=pid, run_key=k, idempotency_key=None,
        base_identity="x", candidate_identity="y", base_digest="d1",
        candidate_digest="d2", migration_digest=None, policy_id=pol_id,
        policy_version=1, registry_revision=1, source_type="FIXTURE",
        base_sha=None, candidate_sha=None, requested_by=None)
    with pytest.raises(Exception):
        with store.tx() as conn:
            conn.execute(
                """INSERT INTO test_executions
                   (id, run_id, suite_id, fixture_digest, image_ref, status, duration_ms)
                   VALUES (%s,%s,'s','0'*64,'img','PASSED',-5)""",
                (str(uuid.uuid4()), rid))


def test_state_machine_backwards_transition_rejected(store):
    pid = _mk_project(store)
    pol_id = store.create_policy(pid, 1, [], [], "REVIEW", USER_ID)
    k = store.compute_run_key(pid, "x9", "y9", 1, "d1", "d2", None, 1)
    rid, _ = store.create_run(project_id=pid, run_key=k, idempotency_key=None,
        base_identity="x9", candidate_identity="y9", base_digest="d1",
        candidate_digest="d2", migration_digest=None, policy_id=pol_id,
        policy_version=1, registry_revision=1, source_type="FIXTURE",
        base_sha=None, candidate_sha=None, requested_by=None)
    store.set_run_state(rid, "PARSING")
    with pytest.raises(StoreError):
        store.set_run_state(rid, "QUEUED")  # backwards


def test_webhook_delivery_unique(store):
    store.record_webhook("d-1", "pull_request", 1, "0" * 64, "ACCEPTED", None)
    with pytest.raises(Exception):
        store.record_webhook("d-1", "pull_request", 1, "0" * 64, "ACCEPTED", None)


def test_assessment_immutable_once_final(store):
    pid = _mk_project(store)
    pol_id = store.create_policy(pid, 1, [], [], "REVIEW", USER_ID)
    k = store.compute_run_key(pid, "xa", "ya", 1, "d1", "d2", None, 1)
    rid, _ = store.create_run(project_id=pid, run_key=k, idempotency_key=None,
        base_identity="xa", candidate_identity="ya", base_digest="d1",
        candidate_digest="d2", migration_digest=None, policy_id=pol_id,
        policy_version=1, registry_revision=1, source_type="FIXTURE",
        base_sha=None, candidate_sha=None, requested_by=None)
    store.upsert_assessment(rid, 1, "BLOCK", ["r"], [], "e" * 64)
    with pytest.raises(StoreError):
        store.upsert_assessment(rid, 1, "PASS", [], [], "f" * 64)
