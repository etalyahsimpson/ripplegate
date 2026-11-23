"""Shared test fixtures: a real user-mode PostgreSQL cluster per session.

The cluster is created once (initdb via /tmp/pguser binaries when present, or
an already-running server) and each test gets an isolated database. Tests run
against the REAL schema migrations, never mocks.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import uuid

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
API_SRC = REPO_ROOT / "services" / "api"
sys.path.insert(0, str(API_SRC))

os.environ.setdefault("SESSION_SIGNING_SECRET", "test-session-secret-not-real")
os.environ.setdefault("WEBHOOK_SECRET", "test-webhook-secret-not-real")
os.environ.setdefault("ARTIFACT_DIR", tempfile.mkdtemp(prefix="rg-artifacts-"))
os.environ.setdefault("WORKER_INLINE", "true")
os.environ.setdefault("DEMO_MODE", "true")

PG_BIN = os.environ.get("RG_PG_BIN", "/tmp/pguser/bin")
PG_PORT = int(os.environ.get("RG_PG_PORT", "55433"))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Cluster:
    def __init__(self, port: int) -> None:
        self.port = port
        self.data_dir = tempfile.mkdtemp(prefix="rg-pgdata-")
        self.log = tempfile.NamedTemporaryFile(prefix="rg-pg-", suffix=".log", delete=False).name

    def start(self) -> None:
        initdb = os.path.join(PG_BIN, "initdb")
        pg_ctl = os.path.join(PG_BIN, "pg_ctl")
        subprocess.run([initdb, "-D", self.data_dir, "-U", "ripple", "--auth=trust",
                        "--encoding=UTF8"], check=True, capture_output=True)
        subprocess.run([pg_ctl, "-D", self.data_dir,
                        "-o", f"-p {self.port} -k /tmp -c listen_addresses=127.0.0.1",
                        "-l", self.log, "start"], check=True, capture_output=True)

    def stop(self) -> None:
        try:
            subprocess.run([os.path.join(PG_BIN, "pg_ctl"), "-D", self.data_dir, "stop", "-m", "fast"],
                           capture_output=True, timeout=30)
        except subprocess.SubprocessError:
            pass
        shutil.rmtree(self.data_dir, ignore_errors=True)


def _running_server_available() -> bool:
    try:
        import psycopg
        conn = psycopg.connect(f"host=127.0.0.1 port=55432 user=ripplegate dbname=ripplegate",
                               connect_timeout=2)
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def database_url() -> str:
    """Provide a real Postgres URL; manage a user-mode cluster when needed."""
    if os.environ.get("RG_DATABASE_URL"):
        yield os.environ["RG_DATABASE_URL"]
        return
    if _running_server_available():
        yield "host=127.0.0.1 port=55432 user=ripplegate dbname=ripplegate"
        return
    if not os.path.exists(os.path.join(PG_BIN, "postgres")):
        pytest.skip("no PostgreSQL server available on this host")
    cluster = _Cluster(_free_port())
    try:
        cluster.start()
    except subprocess.CalledProcessError:
        pytest.skip("failed to start local PostgreSQL cluster")
    import psycopg
    with psycopg.connect(f"host=127.0.0.1 port={cluster.port} user=ripple dbname=postgres",
                         autocommit=True) as conn:
        conn.execute("CREATE DATABASE ripplegate_test")
    yield f"host=127.0.0.1 port={cluster.port} user=ripple dbname=ripplegate_test"
    cluster.stop()


@pytest.fixture()
def app(database_url):
    """A fresh FastAPI app on a fresh, migrated database per test."""
    from app.config import Settings
    from app.infra.artifacts import ArtifactStore
    from app.infra.store import Store
    from app.main import create_app

    settings = Settings(
        database_url=database_url,
        session_signing_secret="test-session-secret-not-real",
        webhook_secret="test-webhook-secret-not-real",
        artifact_dir=os.environ["ARTIFACT_DIR"],
        worker_inline=True,
        demo_mode=True,
    )
    store = Store(settings)
    artifacts = ArtifactStore(settings)
    # fresh schema per test: drop & recreate
    with store.tx() as conn:
        conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    store.apply_migrations(str(REPO_ROOT / "db" / "migrations"))

    application = create_app(settings=settings, store=store, artifacts=artifacts)
    application.state.project_root = str(REPO_ROOT)
    # persist contract documents through the artifact store the same way the
    # API's register-contract route does (digest comes from canonical JSON)
    import json
    orders = REPO_ROOT / "examples" / "orders-api"
    for name in ("openapi-base.json", "openapi-candidate-breaking.json",
                 "openapi-candidate-additive.json", "openapi-candidate-external-ref.json"):
        raw = (orders / name).read_text()
        digest = hashlib.sha256(
            json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        try:
            artifacts.save("contracts", "contract", f"{digest}.json", raw.encode("utf-8"))
        except ValueError:
            pass  # already present
    yield application
    store.close()



@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture()
def admin_token(client):
    r = client.post("/api/v1/demo/session", json={"account": "demo-admin"})
    assert r.status_code == 200
    return r.json()["token"]


@pytest.fixture()
def viewer_token(client):
    r = client.post("/api/v1/demo/session", json={"account": "demo-viewer"})
    assert r.status_code == 200
    return r.json()["token"]


@pytest.fixture()
def seeded_ids(client, admin_token):
    """Register the full synthetic demo domain through the real API."""
    r = client.post("/api/v1/projects",
                     headers={"Authorization": f"Bearer {admin_token}"},
                     json={"organization_id": "a0000000-0000-4000-8000-000000000001",
                           "github_owner": "etalyahsimpson", "github_repo": "demo-orders",
                           "display_name": "Demo Orders API",
                           "allowed_contract_paths": ["examples/orders-api/openapi-base.json"]})
    assert r.status_code in (201, 409), r.text
    project_id = r.json().get("id") or _existing_project(client, admin_token)

    services = {}
    for name, kind, sid in (("orders-api", "producer", "22222222-2222-4222-8222-222222222222"),
                            ("billing-service", "consumer", "33333333-3333-4333-8333-333333333333"),
                            ("reporting-service", "consumer", "44444444-4444-4444-8444-444444444444")):
        r = client.post(f"/api/v1/projects/{project_id}/services",
                        headers={"Authorization": f"Bearer {admin_token}"},
                        json={"name": name, "kind": kind, "owner_label": f"{name}-team"})
        if r.status_code == 201:
            services[name] = r.json()["id"]
    if not services:
        listing = client.get(f"/api/v1/projects/{project_id}/services",
                             headers={"Authorization": f"Bearer {admin_token}"}).json()
        services = {s["name"]: s["id"] for s in listing["items"]}

    # contracts
    contracts = {}
    orders = REPO_ROOT / "examples" / "orders-api"
    for fixture_id, fname in (("fixture-base-v1", "openapi-base.json"),
                              ("fixture-candidate-breaking-v2", "openapi-candidate-breaking.json"),
                              ("fixture-candidate-additive-v2", "openapi-candidate-additive.json"),
                              ("fixture-candidate-external-ref-v1", "openapi-candidate-external-ref.json")):
        r = client.post(f"/api/v1/projects/{project_id}/contracts",
                        headers={"Authorization": f"Bearer {admin_token}"},
                        json={"service_id": services["orders-api"],
                              "source_type": "FIXTURE", "fixture_id": fixture_id,
                              "format": "json", "document": (orders / fname).read_text()})
        assert r.status_code in (201, 409), r.text
        contracts[fixture_id] = r.json().get("id")
    if contracts.get(None):
        listing = client.get(f"/api/v1/projects/{project_id}/contracts",
                             headers={"Authorization": f"Bearer {admin_token}"}).json()
        for c in listing["items"]:
            contracts[c["fixture_id"]] = c["id"]

    # dependencies
    for consumer, suite in (("billing-service", "billing-contract"),
                            ("reporting-service", "reporting-contract")):
        r = client.post(f"/api/v1/projects/{project_id}/dependencies",
                        headers={"Authorization": f"Bearer {admin_token}"},
                        json={"producer_service_id": services["orders-api"],
                              "consumer_service_id": services[consumer],
                              "http_method": "GET", "path_pattern": "/orders/{id}",
                              "required_response_fields": (
                                  ["customer_id", "total_cents"] if "billing" in consumer
                                  else ["total_cents"]),
                              "contract_version_range": "^1.0",
                              "test_suite_id": suite,
                              "evidence_source": "OWNER_REGISTERED"})
        assert r.status_code in (201, 409), r.text
    return {"project_id": project_id, "services": services, "contracts": contracts}


def _existing_project(client, admin_token) -> str:
    r = client.get("/api/v1/projects", headers={"Authorization": f"Bearer {admin_token}"})
    for item in r.json()["items"]:
        if item["repository"] == "demo-orders":
            return item["id"]
    raise AssertionError("project disappeared")
