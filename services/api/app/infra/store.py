"""psycopg-backed transactional store.

Single database adapter boundary: every SQL statement RippleGate executes
against its OWN database lives here (analysis inputs never execute untrusted
SQL). psycopg is deliberately confined to infra/ and parsing/ per the
technology lock.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg import sql as pgsql

from app.config import Settings


class StoreError(Exception):
    pass


VALID_ROLES = ("admin", "maintainer", "reviewer", "viewer")
_PERMISSIONS = {
    "register": ("admin", "maintainer"),
    "analyze": ("admin", "maintainer"),
    "policy": ("admin",),
    "review": ("admin", "maintainer", "reviewer"),
    "view": ("admin", "maintainer", "reviewer", "viewer"),
}


def can(role: str, action: str) -> bool:
    return role in _PERMISSIONS.get(action, ())


class Store:
    """Postgres is authoritative for runs/findings/verdicts; Redis never is."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._conn: psycopg.Connection | None = None

    # ------------------------------------------------------------ lifecycle
    def connect(self) -> None:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(self.settings.database_url, autocommit=False)

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()

    @contextmanager
    def tx(self) -> Iterator[psycopg.Connection]:
        self.connect()
        assert self._conn is not None
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    @contextmanager
    def readonly(self) -> Iterator[psycopg.Connection]:
        self.connect()
        assert self._conn is not None
        try:
            yield self._conn
        finally:
            self._conn.rollback()

    # ---------------------------------------------------------- migrations
    def apply_migrations(self, migration_dir: str) -> list[str]:
        """Apply explicit versioned SQL files with a schema_migrations ledger."""
        import pathlib
        applied: list[str] = []
        files = sorted(pathlib.Path(migration_dir).glob("*.sql"))
        with self.tx() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS schema_migrations (
                       version TEXT PRIMARY KEY,
                       applied_at TIMESTAMPTZ NOT NULL DEFAULT (now() AT TIME ZONE 'UTC'),
                       digest CHAR(64) NOT NULL
                   )"""
            )
        for f in files:
            digest = hashlib.sha256(f.read_bytes()).hexdigest()
            with self.readonly() as conn:
                row = conn.execute(
                    "SELECT digest FROM schema_migrations WHERE version=%s", (f.name,)
                ).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise StoreError(
                        f"migration {f.name} digest changed after being applied; refusing"
                    )
                continue
            text = f.read_text()
            with self.tx() as conn:
                conn.execute(text)
                conn.execute(
                    "INSERT INTO schema_migrations (version, digest) VALUES (%s, %s)",
                    (f.name, digest),
                )
            applied.append(f.name)
        return applied

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _uuid() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _now() -> str:
        import datetime as dt
        return dt.datetime.now(dt.timezone.utc).isoformat()

    def _fetchone(self, conn: psycopg.Connection, query: pgsql.Composable,
                  params: tuple) -> tuple | None:
        return conn.execute(query, params).fetchone()

    # ------------------------------------------------------------ identity
    def role_for(self, user_id: str, organization_id: str) -> str | None:
        with self.readonly() as conn:
            row = conn.execute(
                "SELECT role FROM memberships WHERE user_id=%s AND organization_id=%s",
                (user_id, organization_id),
            ).fetchone()
        return row[0] if row else None

    def user_orgs(self, user_id: str) -> list[dict[str, Any]]:
        with self.readonly() as conn:
            rows = conn.execute(
                """SELECT o.id, o.name, o.slug, o.synthetic, m.role
                   FROM organizations o JOIN memberships m ON m.organization_id = o.id
                   WHERE m.user_id=%s ORDER BY o.slug""",
                (user_id,),
            ).fetchall()
        return [
            {"id": str(r[0]), "name": r[1], "slug": r[2], "synthetic": r[3], "role": r[4]}
            for r in rows
        ]

    # ------------------------------------------------------------- projects
    def list_projects(self, user_id: str, page: int = 1, size: int = 20) -> dict[str, Any]:
        offset = (page - 1) * size
        with self.readonly() as conn:
            total = conn.execute(
                """SELECT count(*) FROM projects p
                   JOIN memberships m ON m.organization_id = p.organization_id
                   WHERE m.user_id=%s""",
                (user_id,),
            ).fetchone()[0]
            rows = conn.execute(
                """SELECT p.id, p.owner, p.repository, p.display_name, p.status,
                          p.organization_id, p.created_at
                   FROM projects p
                   JOIN memberships m ON m.organization_id = p.organization_id
                   WHERE m.user_id=%s ORDER BY p.created_at DESC LIMIT %s OFFSET %s""",
                (user_id, size, offset),
            ).fetchall()
        return {
            "total": total, "page": page, "size": size,
            "items": [
                {"id": str(r[0]), "owner": r[1], "repository": r[2],
                 "display_name": r[3], "status": r[4],
                 "organization_id": str(r[5]), "created_at": r[6].isoformat()}
                for r in rows
            ],
        }

    def project_role(self, user_id: str, project_id: str) -> str | None:
        with self.readonly() as conn:
            row = conn.execute(
                """SELECT m.role FROM projects p
                   JOIN memberships m ON m.organization_id = p.organization_id
                   WHERE p.id=%s AND m.user_id=%s""",
                (project_id, user_id),
            ).fetchone()
        return row[0] if row else None

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self.readonly() as conn:
            row = conn.execute(
                """SELECT id, organization_id, github_repo_id, owner, repository,
                          display_name, status, created_at
                   FROM projects WHERE id=%s""",
                (project_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": str(row[0]), "organization_id": str(row[1]), "github_repo_id": row[2],
            "owner": row[3], "repository": row[4], "display_name": row[5],
            "status": row[6], "created_at": row[7].isoformat(),
        }

    def create_project(self, organization_id: str, owner: str, repository: str,
                       display_name: str, allowed_contract_paths: list[str],
                       user_id: str) -> str:
        pid = self._uuid()
        try:
            with self.tx() as conn:
                conn.execute(
                    """INSERT INTO projects (id, organization_id, owner, repository, display_name)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (pid, organization_id, owner, repository, display_name),
                )
                conn.execute(
                    """INSERT INTO integrations (id, project_id, allowed_paths, permissions, enabled)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (self._uuid(), pid, json.dumps(allowed_contract_paths),
                     json.dumps({"mode": "fixture", "pull_requests": "read"}), True),
                )
                self._audit(conn, pid, user_id, "project.created", "project", pid,
                            {"owner": owner, "repository": repository})
        except psycopg.errors.UniqueViolation as exc:
            raise StoreError(f"project {owner}/{repository} already exists in this organization") from exc
        return pid

    # ------------------------------------------------------------- services
    def list_services(self, project_id: str) -> list[dict[str, Any]]:
        with self.readonly() as conn:
            rows = conn.execute(
                """SELECT id, name, kind, owner_label, created_at
                   FROM services WHERE project_id=%s ORDER BY kind, name""",
                (project_id,),
            ).fetchall()
        return [
            {"id": str(r[0]), "name": r[1], "kind": r[2], "owner_label": r[3],
             "created_at": r[4].isoformat()} for r in rows
        ]

    def create_service(self, project_id: str, name: str, kind: str,
                       owner_label: str, user_id: str) -> str:
        sid = self._uuid()
        try:
            with self.tx() as conn:
                conn.execute(
                    """INSERT INTO services (id, project_id, name, kind, owner_label)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (sid, project_id, name, kind, owner_label),
                )
                self._audit(conn, project_id, user_id, "service.created", "service", sid,
                            {"name": name, "kind": kind})
        except psycopg.errors.UniqueViolation as exc:
            raise StoreError(f"service {name} already exists in this project") from exc
        return sid

    # --------------------------------------------------------- dependencies
    def list_dependencies(self, project_id: str) -> list[dict[str, Any]]:
        with self.readonly() as conn:
            rows = conn.execute(
                """SELECT d.id, d.producer_service_id, d.consumer_service_id,
                          d.http_method, d.path_pattern, d.required_fields, d.version_range,
                          d.test_suite_id, d.registry_revision, d.enabled,
                          ps.name, cs.name
                   FROM consumer_dependencies d
                   JOIN services ps ON ps.id = d.producer_service_id
                   JOIN services cs ON cs.id = d.consumer_service_id
                   WHERE d.project_id=%s ORDER BY ps.name, cs.name""",
                (project_id,),
            ).fetchall()
        return [
            {"id": str(r[0]), "producer_service_id": str(r[1]),
             "consumer_service_id": str(r[2]), "http_method": r[3],
             "path_pattern": r[4], "required_fields": r[5], "version_range": r[6],
             "test_suite_id": r[7], "registry_revision": r[8], "enabled": r[9],
             "producer_name": r[10], "consumer_name": r[11]}
            for r in rows
        ]

    def create_dependency(self, project_id: str, producer_service_id: str,
                          consumer_service_id: str, http_method: str, path_pattern: str,
                          required_fields: list[str], version_range: str,
                          test_suite_id: str, registry_revision: int,
                          user_id: str) -> str:
        dep_id = self._uuid()
        with self.tx() as conn:
            # both services must belong to the same project (cross-project FK guard)
            bad = conn.execute(
                """SELECT count(*) FROM services WHERE id IN (%s,%s)
                   AND project_id <> %s""",
                (producer_service_id, consumer_service_id, project_id),
            ).fetchone()
            if bad[0]:
                raise StoreError("producer/consumer service not in this project")
            try:
                conn.execute(
                    """INSERT INTO consumer_dependencies
                       (id, project_id, producer_service_id, consumer_service_id, http_method,
                        path_pattern, required_fields, version_range, test_suite_id,
                        evidence_source, registry_revision)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'OWNER_REGISTERED',%s)""",
                    (dep_id, project_id, producer_service_id, consumer_service_id,
                     http_method, path_pattern, json.dumps(required_fields),
                     version_range, test_suite_id, registry_revision),
                )
            except psycopg.errors.UniqueViolation as exc:
                raise StoreError(
                    "identical dependency registration already exists for this revision"
                ) from exc
            self._audit(conn, project_id, user_id, "dependency.registered",
                        "consumer_dependency", dep_id,
                        {"consumer": consumer_service_id, "suite": test_suite_id})
        return dep_id

    # ------------------------------------------------------------- policies
    def get_policy(self, project_id: str, version: int) -> dict[str, Any] | None:
        with self.readonly() as conn:
            row = conn.execute(
                "SELECT id, version, block_rules, mandatory_suites, unknown_strategy "
                "FROM policies WHERE project_id=%s AND version=%s",
                (project_id, version),
            ).fetchone()
        if row is None:
            return None
        return {"id": str(row[0]), "version": row[1], "block_rules": row[2],
                "mandatory_suites": row[3], "unknown_strategy": row[4]}

    def create_policy(self, project_id: str, version: int, block_rules: list[str],
                      mandatory_suites: list[str], unknown_strategy: str,
                      user_id: str) -> str:
        pol_id = self._uuid()
        try:
            with self.tx() as conn:
                conn.execute(
                    """INSERT INTO policies (id, project_id, version, block_rules,
                                             mandatory_suites, unknown_strategy)
                       VALUES (%s,%s,%s,%s,%s,%s)""",
                    (pol_id, project_id, version, json.dumps(block_rules),
                     json.dumps(mandatory_suites), unknown_strategy),
                )
                self._audit(conn, project_id, user_id, "policy.created", "policy", pol_id,
                            {"version": version})
        except psycopg.errors.UniqueViolation as exc:
            raise StoreError(f"policy version {version} already exists for this project") from exc
        return pol_id

    # ----------------------------------------------------------- contracts
    def register_contract(self, project_id: str, service_id: str, source_type: str,
                          commit_sha: str | None, fixture_id: str | None, spec_digest: str,
                          openapi_version: str, fmt: str, storage_key: str,
                          user_id: str) -> str | None:
        """Returns contract id, or None when the same immutable version exists."""
        cid = self._uuid()
        try:
            with self.tx() as conn:
                conn.execute(
                    """INSERT INTO contract_versions
                       (id, project_id, service_id, source_type, commit_sha, fixture_id,
                        spec_digest, openapi_version, format, storage_key)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (cid, project_id, service_id, source_type, commit_sha, fixture_id,
                     spec_digest, openapi_version, fmt, storage_key),
                )
                self._audit(conn, project_id, user_id, "contract.registered",
                            "contract_version", cid,
                            {"digest": spec_digest[:16], "source_type": source_type})
        except psycopg.errors.UniqueViolation:
            return None
        return cid

    def list_contracts(self, project_id: str, service_id: str | None = None) -> list[dict[str, Any]]:
        query = """SELECT cv.id, cv.service_id, cv.source_type, cv.commit_sha, cv.fixture_id,
                          cv.spec_digest, cv.openapi_version, cv.format, cv.storage_key,
                          cv.created_at, s.name
                   FROM contract_versions cv JOIN services s ON s.id = cv.service_id
                   WHERE cv.project_id=%s"""
        params: list[Any] = [project_id]
        if service_id:
            query += " AND cv.service_id=%s"
            params.append(service_id)
        query += " ORDER BY cv.created_at DESC"
        with self.readonly() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [
            {"id": str(r[0]), "service_id": str(r[1]), "source_type": r[2],
             "commit_sha": r[3], "fixture_id": r[4], "spec_digest": r[5],
             "openapi_version": r[6], "format": r[7], "storage_key": r[8],
             "created_at": r[9].isoformat(), "service_name": r[10]}
            for r in rows
        ]

    # ---------------------------------------------------------- run identity
    @staticmethod
    def compute_run_key(project_id: str, base_identity: str, candidate_identity: str,
                        policy_version: int, base_digest: str, candidate_digest: str,
                        migration_digest: str | None, registry_revision: int) -> str:
        payload = json.dumps({
            "project_id": project_id, "base": base_identity, "candidate": candidate_identity,
            "policy_version": policy_version, "base_digest": base_digest,
            "candidate_digest": candidate_digest,
            "migration_digest": migration_digest, "registry_revision": registry_revision,
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def create_run(self, *, project_id: str, run_key: str, idempotency_key: str | None,
                   base_identity: str, candidate_identity: str, base_digest: str,
                   candidate_digest: str, migration_digest: str | None,
                   policy_id: str, policy_version: int, registry_revision: int,
                   source_type: str, base_sha: str | None, candidate_sha: str | None,
                   requested_by: str | None) -> tuple[str, bool]:
        """Idempotent insert; returns (run_id, created). Relies on UNIQUE(run_key)."""
        rid = self._uuid()
        with self.tx() as conn:
            existing = conn.execute(
                "SELECT id, idempotency_key FROM analysis_runs WHERE run_key=%s",
                (run_key,),
            ).fetchone()
            if existing is not None:
                return str(existing[0]), False
            conn.execute(
                """INSERT INTO analysis_runs
                   (id, project_id, run_key, idempotency_key, base_identity,
                    candidate_identity, base_digest, candidate_digest, migration_digest,
                    policy_id, policy_version, registry_revision, source_type,
                    base_sha, candidate_sha, state, requested_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'QUEUED',%s)""",
                (rid, project_id, run_key, idempotency_key, base_identity,
                 candidate_identity, base_digest, candidate_digest, migration_digest,
                 policy_id, policy_version, registry_revision, source_type,
                 base_sha, candidate_sha, requested_by),
            )
        return rid, True

    def idempotency_lookup(self, user_id: str, project_id: str, key: str) -> dict[str, Any] | None:
        with self.readonly() as conn:
            row = conn.execute(
                """SELECT id, run_key, project_id, requested_by FROM analysis_runs
                   WHERE idempotency_key=%s ORDER BY created_at DESC LIMIT 1""",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return {"id": str(row[0]), "run_key": row[1], "project_id": str(row[2]),
                "requested_by": str(row[3]) if row[3] else None}

    def set_run_state(self, run_id: str, new_state: str) -> None:
        from app.domain import release_policy
        with self.tx() as conn:
            row = conn.execute("SELECT state FROM analysis_runs WHERE id=%s",
                               (run_id,)).fetchone()
            if row is None:
                raise StoreError("run not found")
            try:
                release_policy.validate_transition(row[0], new_state)
            except release_policy.InvalidTransition as exc:
                raise StoreError(str(exc)) from exc
            if new_state in ("COMPLETED", "ERROR", "CANCELLED"):
                conn.execute(
                    "UPDATE analysis_runs SET state=%s, finished_at=%s WHERE id=%s",
                    (new_state, self._now(), run_id))
            else:
                conn.execute("UPDATE analysis_runs SET state=%s WHERE id=%s",
                             (new_state, run_id))

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.readonly() as conn:
            row = conn.execute(
                """SELECT id, project_id, run_key, idempotency_key, source_type,
                          base_sha, candidate_sha, base_identity, candidate_identity,
                          base_digest, candidate_digest, migration_digest,
                          policy_id, policy_version, registry_revision, state,
                          requested_by, created_at, finished_at
                   FROM analysis_runs WHERE id=%s""",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        keys = ("id", "project_id", "run_key", "idempotency_key", "source_type",
                "base_sha", "candidate_sha", "base_identity", "candidate_identity",
                "base_digest", "candidate_digest", "migration_digest", "policy_id",
                "policy_version", "registry_revision", "state", "requested_by",
                "created_at", "finished_at")
        out = {}
        for i, k in enumerate(keys):
            v = row[i]
            if k in ("id", "project_id", "policy_id", "requested_by") and v is not None:
                v = str(v)
            if k in ("created_at", "finished_at") and v is not None:
                v = v.isoformat()
            out[k] = v
        return out

    def list_runs(self, user_id: str, project_id: str | None, page: int = 1,
                  size: int = 20) -> dict[str, Any]:
        base_query = """FROM analysis_runs ar JOIN projects p ON p.id = ar.project_id
                        JOIN memberships m ON m.organization_id = p.organization_id
                        WHERE m.user_id=%s"""
        params: list[Any] = [user_id]
        if project_id:
            base_query += " AND ar.project_id=%s"
            params.append(project_id)
        with self.readonly() as conn:
            total = conn.execute(f"SELECT count(*) {base_query}", tuple(params)).fetchone()[0]
            rows = conn.execute(
                f"""SELECT ar.id, ar.project_id, ar.source_type, ar.base_identity,
                           ar.candidate_identity, ar.state, ar.policy_version,
                           ar.created_at, ar.finished_at
                    {base_query}
                    ORDER BY ar.created_at DESC LIMIT %s OFFSET %s""",
                tuple(params) + (size, (page - 1) * size),
            ).fetchall()
        items = []
        for r in rows:
            assessment = None
            with self.readonly() as conn:
                arow = conn.execute(
                    "SELECT outcome FROM release_assessments WHERE run_id=%s", (str(r[0]),)
                ).fetchone()
            if arow:
                assessment = arow[0]
            items.append({
                "id": str(r[0]), "project_id": str(r[1]), "source_type": r[2],
                "base_identity": r[3], "candidate_identity": r[4], "state": r[5],
                "policy_version": r[6], "created_at": r[7].isoformat(),
                "finished_at": r[8].isoformat() if r[8] else None,
                "assessment": assessment,
            })
        return {"total": total, "page": page, "size": size, "items": items}

    # -------------------------------------------------------------- findings
    def insert_findings(self, run_id: str, finding_rows: list[dict[str, Any]]) -> list[str]:
        ids: list[str] = []
        with self.tx() as conn:
            # idempotent: a re-delivered job must not duplicate findings
            existing = conn.execute(
                "SELECT count(*) FROM findings WHERE run_id=%s", (run_id,)
            ).fetchone()[0]
            if existing:
                return conn.execute(
                    "SELECT id FROM findings WHERE run_id=%s ORDER BY created_at", (run_id,)
                ).fetchall() and [str(r[0]) for r in conn.execute(
                    "SELECT id FROM findings WHERE run_id=%s ORDER BY created_at", (run_id,)
                ).fetchall()]
            for row in finding_rows:
                fid = self._uuid()
                conn.execute(
                    """INSERT INTO findings
                       (id, run_id, rule_id, rule_version, surface, location, before_value,
                        after_value, classification, severity, reason, verification_state,
                        evidence_refs, confidence_basis)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (fid, run_id, row["rule_id"], row["rule_version"], row["surface"],
                     row["location"], json.dumps(row["before_value"]),
                     json.dumps(row["after_value"]), row["classification"], row["severity"],
                     row["reason"], row["verification_state"],
                     json.dumps(row["evidence_refs"]), row["confidence_basis"]),
                )
                ids.append(fid)
        return ids

    def list_findings(self, run_id: str, classification: str | None = None,
                      page: int = 1, size: int = 50) -> dict[str, Any]:
        where = "WHERE run_id=%s"
        params: list[Any] = [run_id]
        if classification:
            where += " AND classification=%s"
            params.append(classification)
        with self.readonly() as conn:
            total = conn.execute(
                f"SELECT count(*) FROM findings {where}", tuple(params)
            ).fetchone()[0]
            rows = conn.execute(
                f"""SELECT id, rule_id, rule_version, surface, location, before_value,
                           after_value, classification, severity, reason, verification_state,
                           evidence_refs, confidence_basis
                    FROM findings {where} ORDER BY severity_rank(classification), rule_id
                    LIMIT %s OFFSET %s""".replace("severity_rank(classification)",
                        "CASE classification WHEN 'BREAKING' THEN 0 WHEN 'POTENTIALLY_BREAKING' THEN 1 WHEN 'UNKNOWN' THEN 2 WHEN 'ADDITIVE' THEN 3 ELSE 4 END"),
                tuple(params) + (size, (page - 1) * size),
            ).fetchall()
        items = [{
            "id": str(r[0]), "rule_id": r[1], "rule_version": r[2], "surface": r[3],
            "location": r[4], "before_value": r[5], "after_value": r[6],
            "classification": r[7], "severity": r[8], "reason": r[9],
            "verification_state": r[10], "evidence_refs": r[11],
            "confidence_basis": r[12],
        } for r in rows]
        return {"total": total, "page": page, "size": size, "items": items}

    def update_finding_verification(self, finding_id: str, verification_state: str,
                                    evidence_refs: list[dict[str, Any]] | None = None) -> None:
        with self.tx() as conn:
            if evidence_refs is not None:
                conn.execute(
                    "UPDATE findings SET verification_state=%s, evidence_refs=%s WHERE id=%s",
                    (verification_state, json.dumps(evidence_refs), finding_id))
            else:
                conn.execute(
                    "UPDATE findings SET verification_state=%s WHERE id=%s",
                    (verification_state, finding_id))

    # --------------------------------------------------------------- impacts
    def insert_impacts(self, run_id: str, impact_rows: list[dict[str, Any]],
                       finding_location_to_id: dict[str, str]) -> None:
        with self.tx() as conn:
            existing = conn.execute(
                "SELECT count(*) FROM impacts WHERE run_id=%s", (run_id,)
            ).fetchone()[0]
            if existing:
                return
            for row in impact_rows:
                finding_id = finding_location_to_id.get(
                    (row["finding_rule_id"], row["finding_location"]))
                if finding_id is None:
                    continue
                conn.execute(
                    """INSERT INTO impacts
                       (id, run_id, finding_id, consumer_dependency_id, consumer_service_id,
                        impact_state, reason)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (self._uuid(), run_id, finding_id, row["dependency_id"],
                     row["consumer_service_id"], row["impact_state"], row["reason"]),
                )

    def list_impacts(self, run_id: str) -> list[dict[str, Any]]:
        with self.readonly() as conn:
            rows = conn.execute(
                """SELECT i.impact_state, i.reason, i.consumer_service_id, f.rule_id,
                          f.location, f.classification, s.name, i.consumer_dependency_id
                   FROM impacts i JOIN findings f ON f.id = i.finding_id
                   LEFT JOIN services s ON s.id = i.consumer_service_id
                   WHERE i.run_id=%s""",
                (run_id,),
            ).fetchall()
        return [{
            "impact_state": r[0], "reason": r[1],
            "consumer_service_id": str(r[2]) if r[2] else None,
            "finding_rule_id": r[3], "finding_location": r[4],
            "finding_classification": r[5], "consumer_name": r[6],
            "dependency_id": str(r[7]) if r[7] else None,
        } for r in rows]

    # ------------------------------------------------------- test executions
    def insert_test_execution(self, run_id: str, suite_id: str, fixture_digest: str,
                              image_ref: str, status: str, duration_ms: int | None,
                              exit_code: int | None, artifact_id: str | None) -> str | None:
        te_id = self._uuid()
        try:
            with self.tx() as conn:
                conn.execute(
                    """INSERT INTO test_executions
                       (id, run_id, suite_id, fixture_digest, image_ref, status,
                        duration_ms, exit_code, artifact_id, finished_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (te_id, run_id, suite_id, fixture_digest, image_ref, status,
                     duration_ms, exit_code, artifact_id, self._now()),
                )
        except psycopg.errors.UniqueViolation:
            with self.readonly() as conn:
                row = conn.execute(
                    "SELECT id FROM test_executions WHERE run_id=%s AND suite_id=%s "
                    "AND fixture_digest=%s",
                    (run_id, suite_id, fixture_digest),
                ).fetchone()
            return str(row[0]) if row else None
        return te_id

    def list_test_executions(self, run_id: str) -> list[dict[str, Any]]:
        with self.readonly() as conn:
            rows = conn.execute(
                """SELECT id, suite_id, fixture_digest, image_ref, status, duration_ms,
                          exit_code, artifact_id, created_at, finished_at
                   FROM test_executions WHERE run_id=%s ORDER BY suite_id""",
                (run_id,),
            ).fetchall()
        return [{
            "id": str(r[0]), "suite_id": r[1], "fixture_digest": r[2], "image_ref": r[3],
            "status": r[4], "duration_ms": r[5], "exit_code": r[6],
            "artifact_id": str(r[7]) if r[7] else None,
            "created_at": r[8].isoformat(), "finished_at": r[9].isoformat() if r[9] else None,
        } for r in rows]

    # ------------------------------------------------------------ assessment
    def upsert_assessment(self, run_id: str, policy_version: int, outcome: str,
                          blocking_reasons: list[str], unknowns: list[str],
                          evidence_digest: str) -> None:
        with self.tx() as conn:
            row = conn.execute(
                "SELECT id FROM release_assessments WHERE run_id=%s", (run_id,)
            ).fetchone()
            if row is not None:
                raise StoreError("assessment is immutable once final")
            conn.execute(
                """INSERT INTO release_assessments
                   (id, run_id, policy_version, outcome, blocking_reasons, unknowns,
                    evidence_digest)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (self._uuid(), run_id, policy_version, outcome,
                 json.dumps(blocking_reasons), json.dumps(unknowns), evidence_digest),
            )

    def get_assessment(self, run_id: str) -> dict[str, Any] | None:
        with self.readonly() as conn:
            row = conn.execute(
                """SELECT outcome, blocking_reasons, unknowns, evidence_digest,
                          policy_version, created_at
                   FROM release_assessments WHERE run_id=%s""",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return {"outcome": row[0], "blocking_reasons": row[1], "unknowns": row[2],
                "evidence_digest": row[3], "policy_version": row[4],
                "created_at": row[5].isoformat()}

    # ------------------------------------------------------------- artifacts
    def insert_artifact(self, run_id: str, kind: str, relative_key: str, sha256_hex: str,
                        byte_size: int, visibility: str = "project") -> str:
        aid = self._uuid()
        with self.tx() as conn:
            conn.execute(
                """INSERT INTO artifacts (id, run_id, kind, relative_key, sha256, byte_size,
                                          visibility)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (aid, run_id, kind, relative_key, sha256_hex, byte_size, visibility),
            )
        return aid

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        with self.readonly() as conn:
            row = conn.execute(
                "SELECT id, run_id, kind, relative_key, sha256, byte_size, visibility "
                "FROM artifacts WHERE id=%s",
                (artifact_id,),
            ).fetchone()
        if row is None:
            return None
        return {"id": str(row[0]), "run_id": str(row[1]), "kind": row[2],
                "relative_key": row[3], "sha256": row[4], "byte_size": row[5],
                "visibility": row[6]}

    # ------------------------------------------------------------- webhooks
    def webhook_seen(self, delivery_id: str) -> bool:
        with self.readonly() as conn:
            row = conn.execute(
                "SELECT 1 FROM webhook_deliveries WHERE delivery_id=%s", (delivery_id,)
            ).fetchone()
        return row is not None

    def record_webhook(self, delivery_id: str, github_event: str, repo_id: int,
                       body_digest: str, status: str, analysis_run_id: str | None) -> None:
        with self.tx() as conn:
            conn.execute(
                """INSERT INTO webhook_deliveries
                   (id, delivery_id, github_event, repo_id, body_digest, status,
                    analysis_run_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (self._uuid(), delivery_id, github_event, repo_id, body_digest, status,
                 analysis_run_id),
            )

    # ---------------------------------------------------------------- audit
    def _audit(self, conn: psycopg.Connection, project_id: str, actor_id: str | None,
               action: str, resource_type: str, resource_id: str | None,
               summary: dict[str, Any]) -> None:
        conn.execute(
            """INSERT INTO audit_events
               (id, project_id, actor_id, action, resource_type, resource_id, summary)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (self._uuid(), project_id, actor_id, action, resource_type, resource_id,
             json.dumps(summary)),
        )

    def list_audit(self, project_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.readonly() as conn:
            rows = conn.execute(
                """SELECT action, resource_type, resource_id, summary, occurred_at, actor_id
                   FROM audit_events WHERE project_id=%s
                   ORDER BY occurred_at DESC LIMIT %s""",
                (project_id, limit),
            ).fetchall()
        return [{
            "action": r[0], "resource_type": r[1],
            "resource_id": str(r[2]) if r[2] else None, "summary": r[3],
            "occurred_at": r[4].isoformat(),
            "actor_id": str(r[5]) if r[5] else None,
        } for r in rows]
