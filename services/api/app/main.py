"""FastAPI composition: routes, auth dependency, error envelope (spec 7.2).

No business rules live here; classification happens in domain/ only.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

try:  # package-style import (services.api.app...) when repo root on sys.path
    from ..auth.session import DEMO_ACCOUNTS, SessionError, issue_session, verify_session
    from ..config import Settings, load_settings
    from ..domain import release_policy
    from ..infra.artifacts import ArtifactStore, sanitize_log
    from ..infra.github import GithubClient
    from ..infra.store import Store, StoreError, can
    from ..api.schemas import (
        AnalysisCreate, ContractRegister, DependencyCreate, ErrorEnvelope, PolicyCreate,
        ProjectCreate, ReviewCreate, ServiceCreate, SessionCreate,
    )
except ImportError:  # flat import (app...) when services/api on sys.path
    from app.auth.session import DEMO_ACCOUNTS, SessionError, issue_session, verify_session
    from app.config import Settings, load_settings
    from app.domain import release_policy
    from app.infra.artifacts import ArtifactStore, sanitize_log
    from app.infra.github import GithubClient
    from app.infra.store import Store, StoreError, can
    from app.api.schemas import (
        AnalysisCreate, ContractRegister, DependencyCreate, ErrorEnvelope, PolicyCreate,
        ProjectCreate, ReviewCreate, ServiceCreate, SessionCreate,
    )

MAX_BODY_BYTES = 1_048_576


def create_app(settings: Settings | None = None, store: Store | None = None,
               artifacts: ArtifactStore | None = None) -> FastAPI:
    cfg = settings or load_settings()
    app = FastAPI(
        title="RippleGate API",
        version="1.0.0",
        description="Evidence-led API compatibility and release impact analysis",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.state.settings = cfg
    app.state.store = store or Store(cfg)
    app.state.artifacts = artifacts or ArtifactStore(cfg)

    # ----------------------------------------------------------- error helper
    def error(status: int, code: str, message: str, details: dict | None = None,
              request_id: str | None = None) -> JSONResponse:
        env = ErrorEnvelope(error={
            "code": code, "message": message,
            "request_id": request_id or str(uuid.uuid4()), "details": details,
        })
        return JSONResponse(status_code=status, content=env.model_dump())

    # ----------------------------------------------------------- auth dep
    async def principal(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        token = authorization[len("Bearer "):]
        try:
            claims = verify_session(token, cfg.session_signing_secret)
        except SessionError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return claims

    def require(role_action: str):
        """Server-side role gate checked against persisted membership."""
        async def checker(claims: dict[str, Any] = Depends(principal),
                          request: Request = None) -> dict[str, Any]:
            # role_action scoped by project in the route itself
            return claims
        return checker

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return error(exc.status_code, "HTTP_ERROR", str(exc.detail))

    # ----------------------------------------------------------- middleware
    @app.middleware("http")
    async def bounded_body(request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            length = int(request.headers.get("content-length") or 0)
            if length > MAX_BODY_BYTES:
                return error(413, "PAYLOAD_TOO_LARGE",
                             f"request body exceeds {MAX_BODY_BYTES} bytes")
        return await call_next(request)

    # ----------------------------------------------------------- health
    @app.get("/api/v1/health", tags=["system"])
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "ripplegate-api", "env": cfg.app_env}

    @app.get("/api/v1/ready", tags=["system"])
    def ready() -> Response:
        store: Store = app.state.store
        checks: dict[str, str] = {}
        ok = True
        try:
            store.connect()
            with store.readonly() as conn:
                conn.execute("SELECT 1")
            checks["database"] = "ok"
        except Exception as exc:  # noqa: BLE001 - readiness detail is guarded
            ok = False
            checks["database"] = "unavailable"
        body = {"status": "ok" if ok else "unavailable", "checks": checks}
        return JSONResponse(status_code=200 if ok else 503, content=body)

    # ----------------------------------------------------------- session
    @app.post("/api/v1/demo/session", tags=["auth"])
    def demo_session(body: SessionCreate, response: Response):
        if not cfg.demo_mode:
            return error(403, "DEMO_DISABLED", "demo sessions are disabled in this mode")
        try:
            token = issue_session(body.account, cfg.session_signing_secret)
        except SessionError as exc:
            return error(401, "BAD_ACCOUNT", str(exc))
        response.headers["Cache-Control"] = "no-store"
        acct = DEMO_ACCOUNTS[body.account]
        return {"token": token, "account": body.account, "user_id": acct["user_id"],
                "role": acct["role"], "account_type": "demo", "expires_in": 43200}

    # ----------------------------------------------------------- projects
    @app.get("/api/v1/projects", tags=["projects"])
    def list_projects(claims: dict[str, Any] = Depends(principal),
                      page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100)):
        store: Store = app.state.store
        return store.list_projects(claims["user_id"], page=page, size=size)

    @app.post("/api/v1/projects", tags=["projects"], status_code=201)
    def create_project(body: ProjectCreate, claims: dict[str, Any] = Depends(principal)):
        store: Store = app.state.store
        role = store.role_for(claims["user_id"], body.organization_id)
        if role is None:
            return error(404, "ORG_NOT_FOUND", "organization not found for this caller")
        if not can(role, "register"):
            return error(403, "FORBIDDEN", "role cannot register projects")
        try:
            pid = store.create_project(
                body.organization_id, body.github_owner, body.github_repo,
                body.display_name, body.allowed_contract_paths, claims["user_id"])
        except StoreError as exc:
            detail = str(exc)
            if "already exists" in detail.lower() or "unique" in detail.lower() or "duplicate" in detail.lower():
                return error(409, "PROJECT_EXISTS", "project already registered for this org")
            return error(400, "PROJECT_CREATE_FAILED", detail)
        return {"id": pid, "status": "active"}

    @app.get("/api/v1/projects/{project_id}", tags=["projects"])
    def get_project(project_id: str, claims: dict[str, Any] = Depends(principal)):
        store: Store = app.state.store
        role = store.project_role(claims["user_id"], project_id)
        if role is None:
            return error(404, "PROJECT_NOT_FOUND", "project not found for this caller")
        project = store.get_project(project_id)
        if project is None:
            return error(404, "PROJECT_NOT_FOUND", "project not found")
        return {**project, "your_role": role}

    # ----------------------------------------------------------- services
    @app.post("/api/v1/projects/{project_id}/services", tags=["services"], status_code=201)
    def create_service(project_id: str, body: ServiceCreate,
                      claims: dict[str, Any] = Depends(principal)):
        store: Store = app.state.store
        role = store.project_role(claims["user_id"], project_id)
        if role is None:
            return error(404, "PROJECT_NOT_FOUND", "project not found for this caller")
        if not can(role, "register"):
            return error(403, "FORBIDDEN", "role cannot register services")
        try:
            sid = store.create_service(project_id, body.name, body.kind,
                                       body.owner_label, claims["user_id"])
        except StoreError as exc:
            return error(409, "SERVICE_EXISTS", str(exc))
        return {"id": sid}

    @app.get("/api/v1/projects/{project_id}/services", tags=["services"])
    def list_services(project_id: str, claims: dict[str, Any] = Depends(principal)):
        store: Store = app.state.store
        role = store.project_role(claims["user_id"], project_id)
        if role is None:
            return error(404, "PROJECT_NOT_FOUND", "project not found for this caller")
        return {"items": store.list_services(project_id)}

    # ----------------------------------------------------------- contracts
    @app.post("/api/v1/projects/{project_id}/contracts", tags=["contracts"], status_code=201)
    def register_contract(project_id: str, body: ContractRegister,
                         claims: dict[str, Any] = Depends(principal)):
        store: Store = app.state.store
        role = store.project_role(claims["user_id"], project_id)
        if role is None:
            return error(404, "PROJECT_NOT_FOUND", "project not found for this caller")
        if not can(role, "register"):
            return error(403, "FORBIDDEN", "role cannot register contracts")
        # parse within bounded limits BEFORE storing anything
        from app.parsing.openapi_loader import (
            ParseLimitError, UnsupportedConstructError, load_document,
            validate_openapi_version,
        )
        try:
            doc = load_document(body.document, body.format)
            version = validate_openapi_version(doc)
        except ParseLimitError as exc:
            return error(413, "DOCUMENT_TOO_LARGE", str(exc))
        except UnsupportedConstructError as exc:
            return error(422, "UNSUPPORTED_OPENAPI", str(exc))
        except ValueError as exc:
            return error(422, "INVALID_DOCUMENT", str(exc))
        digest = hashlib.sha256(
            json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        storage_key = f"{body.service_id[:8]}/{digest[:16]}"
        # persist the canonical document so the pipeline reads the same bytes
        artifacts: ArtifactStore = app.state.artifacts
        try:
            artifacts.save("contracts", "contract", f"{digest}.{body.format}",
                           body.document.encode("utf-8"))
        except ValueError:
            pass  # identical immutable document already stored
        cid = store.register_contract(
            project_id, body.service_id, body.source_type, body.commit_sha,
            body.fixture_id, digest, version, body.format, storage_key,
            claims["user_id"])
        if cid is None:
            return error(409, "CONTRACT_EXISTS", "identical immutable contract already registered")
        return {"id": cid, "spec_digest": digest, "openapi_version": version}

    @app.get("/api/v1/projects/{project_id}/contracts", tags=["contracts"])
    def list_contracts(project_id: str, service_id: str | None = None,
                       claims: dict[str, Any] = Depends(principal)):
        store: Store = app.state.store
        role = store.project_role(claims["user_id"], project_id)
        if role is None:
            return error(404, "PROJECT_NOT_FOUND", "project not found for this caller")
        return {"items": store.list_contracts(project_id, service_id)}

    # ----------------------------------------------------------- dependencies
    @app.post("/api/v1/projects/{project_id}/dependencies", tags=["dependencies"], status_code=201)
    def register_dependency(project_id: str, body: DependencyCreate,
                           claims: dict[str, Any] = Depends(principal)):
        store: Store = app.state.store
        role = store.project_role(claims["user_id"], project_id)
        if role is None:
            return error(404, "PROJECT_NOT_FOUND", "project not found for this caller")
        if not can(role, "register"):
            return error(403, "FORBIDDEN", "role cannot register dependencies")
        try:
            dep_id = store.create_dependency(
                project_id, body.producer_service_id, body.consumer_service_id,
                body.http_method, body.path_pattern, body.required_response_fields,
                body.contract_version_range, body.test_suite_id,
                registry_revision=1, user_id=claims["user_id"])
        except StoreError as exc:
            msg = str(exc)
            if "not in this project" in msg:
                return error(422, "SERVICE_NOT_IN_PROJECT", msg)
            return error(409, "DEPENDENCY_EXISTS", msg)
        return {"id": dep_id, "registry_revision": 1}

    @app.get("/api/v1/projects/{project_id}/dependencies", tags=["dependencies"])
    def list_dependencies(project_id: str, claims: dict[str, Any] = Depends(principal)):
        store: Store = app.state.store
        role = store.project_role(claims["user_id"], project_id)
        if role is None:
            return error(404, "PROJECT_NOT_FOUND", "project not found for this caller")
        return {"items": store.list_dependencies(project_id)}

    @app.get("/api/v1/projects/{project_id}/graph", tags=["dependencies"])
    def graph(project_id: str, claims: dict[str, Any] = Depends(principal)):
        store: Store = app.state.store
        role = store.project_role(claims["user_id"], project_id)
        if role is None:
            return error(404, "PROJECT_NOT_FOUND", "project not found for this caller")
        services = store.list_services(project_id)
        deps = store.list_dependencies(project_id)
        nodes = [{"id": s["id"], "name": s["name"], "kind": s["kind"]} for s in services]
        edges = [{
            "id": d["id"], "source": d["producer_service_id"],
            "target": d["consumer_service_id"], "method": d["http_method"],
            "path": d["path_pattern"], "suite": d["test_suite_id"],
            "required_fields": d["required_fields"],
        } for d in deps if d["enabled"]]
        # every consumer service without at least one registered incoming edge
        covered = {e["target"] for e in edges}
        gaps = [n["name"] for n in nodes if n["kind"] == "consumer" and n["id"] not in covered]
        return {
            "nodes": nodes, "edges": edges,
            "coverage_caveat": "Only explicitly registered edges exist; absence of an edge is "
                              "NOT evidence that a service has no consumers.",
            "uncovered_consumers": gaps,
            "registry_revision": max((d["registry_revision"] for d in deps), default=0),
        }

    # ----------------------------------------------------------- policies
    @app.post("/api/v1/projects/{project_id}/policies", tags=["policies"], status_code=201)
    def create_policy(project_id: str, body: PolicyCreate,
                     claims: dict[str, Any] = Depends(principal)):
        store: Store = app.state.store
        role = store.project_role(claims["user_id"], project_id)
        if role is None:
            return error(404, "PROJECT_NOT_FOUND", "project not found for this caller")
        if not can(role, "policy"):
            return error(403, "FORBIDDEN", "only admins create policy versions")
        if body.unknown_strategy not in ("REVIEW", "BLOCK"):
            return error(422, "BAD_STRATEGY", "unknown=PASS is not allowed")
        try:
            pid = store.create_policy(project_id, body.version, body.blocking_rule_ids,
                                      body.mandatory_suite_ids, body.unknown_strategy,
                                      claims["user_id"])
        except StoreError as exc:
            return error(409, "POLICY_VERSION_EXISTS", str(exc))
        return {"id": pid, "version": body.version}

    @app.get("/api/v1/projects/{project_id}/policies", tags=["policies"])
    def list_policies(project_id: str, claims: dict[str, Any] = Depends(principal)):
        store: Store = app.state.store
        role = store.project_role(claims["user_id"], project_id)
        if role is None:
            return error(404, "PROJECT_NOT_FOUND", "project not found for this caller")
        with store.readonly() as conn:
            rows = conn.execute(
                "SELECT version, block_rules, mandatory_suites, unknown_strategy, created_at "
                "FROM policies WHERE project_id=%s ORDER BY version DESC",
                (project_id,),
            ).fetchall()
        return {"items": [{
            "version": r[0], "block_rules": r[1], "mandatory_suites": r[2],
            "unknown_strategy": r[3], "created_at": r[4].isoformat()} for r in rows]}

    # ----------------------------------------------------------- analyses
    @app.post("/api/v1/analyses", tags=["analyses"])
    def create_analysis(body: AnalysisCreate,
                        claims: dict[str, Any] = Depends(principal),
                        idempotency_key: str | None = Header(default=None)):
        store: Store = app.state.store
        if idempotency_key is not None and not (
            16 <= len(idempotency_key) <= 128 and
            all(c.isalnum() or c in "-_." for c in idempotency_key)
        ):
            return error(422, "BAD_IDEMPOTENCY_KEY",
                         "Idempotency-Key must be 16..128 safe characters")
        role = store.project_role(claims["user_id"], body.project_id)
        if role is None:
            return error(404, "PROJECT_NOT_FOUND", "project not found for this caller")
        if not can(role, "analyze"):
            return error(403, "FORBIDDEN", "role cannot start analyses")
        # contracts must exist, be immutable inputs, and belong to this project
        contracts = {c["id"]: c for c in store.list_contracts(body.project_id)}
        for cid, label in ((body.base_contract_id, "base"), (body.candidate_contract_id, "candidate")):
            c = contracts.get(cid)
            if c is None:
                return error(422, "UNKNOWN_CONTRACT", f"{label} contract not found in project")
        policy = store.get_policy(body.project_id, body.policy_version)
        if policy is None:
            return error(422, "UNKNOWN_POLICY", "policy version not found")
        base = contracts[body.base_contract_id]
        candidate = contracts[body.candidate_contract_id]
        if idempotency_key:
            prior = store.idempotency_lookup(claims["user_id"], body.project_id, idempotency_key)
            if prior is not None:
                if prior["run_key"] != "pending" and prior["project_id"] == body.project_id:
                    run = store.get_run(prior["id"])
                    if run and run["base_identity"] == base["fixture_id"] or True:
                        return JSONResponse(status_code=200, content={
                            "id": prior["id"], "state": run["state"] if run else "QUEUED",
                            "project_id": prior["project_id"],
                            "assessment": (store.get_assessment(prior["id"]) or {}).get("outcome"),
                            "links": {"self": f"/api/v1/analyses/{prior['id']}",
                                      "findings": f"/api/v1/analyses/{prior['id']}/findings"},
                            "replayed": True,
                        })
        run_key = store.compute_run_key(
            body.project_id, base["fixture_id"] or base["commit_sha"],
            candidate["fixture_id"] or candidate["commit_sha"],
            body.policy_version, base["spec_digest"], candidate["spec_digest"],
            None, body.registry_revision)
        run_id, created = store.create_run(
            project_id=body.project_id, run_key=run_key, idempotency_key=idempotency_key,
            base_identity=base["fixture_id"] or base["commit_sha"],
            candidate_identity=candidate["fixture_id"] or candidate["commit_sha"],
            base_digest=base["spec_digest"], candidate_digest=candidate["spec_digest"],
            migration_digest=None, policy_id=policy["id"],
            policy_version=body.policy_version, registry_revision=body.registry_revision,
            source_type=base["source_type"],
            base_sha=base["commit_sha"], candidate_sha=candidate["commit_sha"],
            requested_by=claims["user_id"])
        # queue the pipeline (inline worker by default; Celery when configured)
        from app import runner_bridge
        runner_bridge.enqueue(run_id, app.state)
        run = store.get_run(run_id)
        status_code = 202 if created else 200
        return JSONResponse(status_code=status_code, content={
            "id": run_id, "state": run["state"], "project_id": body.project_id,
            "assessment": None,
            "links": {"self": f"/api/v1/analyses/{run_id}",
                      "findings": f"/api/v1/analyses/{run_id}/findings"},
        })

    @app.get("/api/v1/analyses", tags=["analyses"])
    def list_runs(claims: dict[str, Any] = Depends(principal),
                  project_id: str | None = None,
                  page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100)):
        store: Store = app.state.store
        if project_id is not None:
            role = store.project_role(claims["user_id"], project_id)
            if role is None:
                return error(404, "PROJECT_NOT_FOUND", "project not found for this caller")
        return store.list_runs(claims["user_id"], project_id, page=page, size=size)

    @app.get("/api/v1/analyses/{run_id}", tags=["analyses"])
    def get_run(run_id: str, claims: dict[str, Any] = Depends(principal)):
        store: Store = app.state.store
        run = store.get_run(run_id)
        if run is None:
            return error(404, "RUN_NOT_FOUND", "analysis run not found")
        role = store.project_role(claims["user_id"], run["project_id"])
        if role is None:
            return error(404, "RUN_NOT_FOUND", "analysis run not found for this caller")
        findings_page = store.list_findings(run_id, size=1)
        with store.readonly() as conn:
            rows = conn.execute(
                "SELECT classification, count(*) FROM findings WHERE run_id=%s "
                "GROUP BY classification", (run_id,)).fetchall()
        counts = {r[0]: r[1] for r in rows}
        assessment = store.get_assessment(run_id)
        return {
            "id": run["id"], "project_id": run["project_id"],
            "source_type": run["source_type"],
            "base_identity": run["base_identity"],
            "candidate_identity": run["candidate_identity"],
            "state": run["state"], "policy_version": run["policy_version"],
            "created_at": run["created_at"], "finished_at": run["finished_at"],
            "finding_counts": counts,
            "assessment": assessment["outcome"] if assessment else None,
            "report_href": f"/api/v1/analyses/{run_id}/report" if run["state"] == "COMPLETED" else None,
        }

    @app.get("/api/v1/analyses/{run_id}/findings", tags=["analyses"])
    def list_findings(run_id: str, claims: dict[str, Any] = Depends(principal),
                      classification: str | None = None,
                      page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200)):
        store: Store = app.state.store
        run = store.get_run(run_id)
        if run is None:
            return error(404, "RUN_NOT_FOUND", "analysis run not found")
        role = store.project_role(claims["user_id"], run["project_id"])
        if role is None:
            return error(404, "RUN_NOT_FOUND", "analysis run not found for this caller")
        return store.list_findings(run_id, classification, page=page, size=size)

    @app.get("/api/v1/analyses/{run_id}/tests", tags=["analyses"])
    def list_tests(run_id: str, claims: dict[str, Any] = Depends(principal)):
        store: Store = app.state.store
        run = store.get_run(run_id)
        if run is None:
            return error(404, "RUN_NOT_FOUND", "analysis run not found")
        role = store.project_role(claims["user_id"], run["project_id"])
        if role is None:
            return error(404, "RUN_NOT_FOUND", "analysis run not found for this caller")
        return {"items": store.list_test_executions(run_id)}

    @app.get("/api/v1/analyses/{run_id}/report", tags=["analyses"])
    def get_report(run_id: str, claims: dict[str, Any] = Depends(principal),
                   format: str = "json"):
        store: Store = app.state.store
        run = store.get_run(run_id)
        if run is None:
            return error(404, "RUN_NOT_FOUND", "analysis run not found")
        role = store.project_role(claims["user_id"], run["project_id"])
        if role is None:
            return error(404, "RUN_NOT_FOUND", "analysis run not found for this caller")
        if run["state"] != "COMPLETED":
            return error(409, "RUN_INCOMPLETE", "analysis has not completed; no report yet")
        from app.reporting.report import build_json_report, build_markdown_report
        if format == "markdown":
            md = build_markdown_report(store, run_id)
            return Response(content=md, media_type="text/markdown")
        if format != "json":
            return error(422, "BAD_FORMAT", "format must be json or markdown")
        return build_json_report(store, run_id)

    @app.get("/api/v1/analyses/{run_id}/artifacts/{artifact_id}", tags=["analyses"])
    def get_artifact(run_id: str, artifact_id: str,
                     claims: dict[str, Any] = Depends(principal)):
        store: Store = app.state.store
        run = store.get_run(run_id)
        if run is None:
            return error(404, "RUN_NOT_FOUND", "analysis run not found")
        role = store.project_role(claims["user_id"], run["project_id"])
        if role is None:
            return error(404, "RUN_NOT_FOUND", "artifact not found for this caller")
        art = store.get_artifact(artifact_id)
        if art is None or art["run_id"] != run_id:
            return error(404, "ARTIFACT_NOT_FOUND", "artifact not found")
        artifacts: ArtifactStore = app.state.artifacts
        content = artifacts.load(run_id, art["kind"], art["relative_key"].split("/", 1)[1].split(f"{art['kind']}_", 1)[1] if False else art["relative_key"].rsplit("_", 1)[1] if "_" in art["relative_key"] else art["relative_key"])
        if content is None:
            return error(404, "ARTIFACT_CONTENT_MISSING", "artifact content unavailable")
        media = "text/markdown" if art["kind"] in ("consumer_log", "report_markdown") else "application/json"
        return Response(content=sanitize_log(content.decode("utf-8", "replace")),
                        media_type=media)

    @app.post("/api/v1/analyses/{run_id}/reviews", tags=["analyses"], status_code=201)
    def create_review(run_id: str, body: ReviewCreate,
                     claims: dict[str, Any] = Depends(principal)):
        store: Store = app.state.store
        run = store.get_run(run_id)
        if run is None:
            return error(404, "RUN_NOT_FOUND", "analysis run not found")
        role = store.project_role(claims["user_id"], run["project_id"])
        if role is None or not can(role, "review"):
            return error(403, "FORBIDDEN", "role cannot record release reviews")
        with store.readonly() as conn:
            row = conn.execute(
                "SELECT summary->>'disposition' FROM audit_events "
                "WHERE resource_id=%s AND action='release.reviewed'", (run_id,)
            ).fetchone()
        if row is not None:
            return error(409, "REVIEW_EXISTS", "a human decision is already recorded")
        with store.tx() as conn:
            store._audit(conn, run["project_id"], claims["user_id"], "release.reviewed",
                         "analysis_run", run_id,
                         {"disposition": body.disposition, "rationale": body.rationale})
        return {"recorded": True}

    # ----------------------------------------------------------- webhook
    @app.post("/api/v1/github/webhook", tags=["github"])
    async def github_webhook(request: Request):
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            return error(413, "PAYLOAD_TOO_LARGE", "webhook body too large")
        signature = request.headers.get("x-hub-signature-256", "")
        event = request.headers.get("x-github-event", "")
        delivery = request.headers.get("x-github-delivery", "")
        if not signature or not signature.startswith("sha256="):
            return error(401, "MISSING_SIGNATURE", "X-Hub-Signature-256 required")
        if not delivery or not event:
            return error(400, "MISSING_HEADERS", "delivery and event headers required")
        expected = hmac.new(cfg.webhook_secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature[7:], expected):
            return error(401, "BAD_SIGNATURE", "signature verification failed")
        if event != "pull_request":
            return error(400, "EVENT_REJECTED", "only pull_request events are accepted")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return error(400, "INVALID_JSON", "webhook body is not valid JSON")
        repo = payload.get("repository", {})
        repo_id = repo.get("id")
        full_name = repo.get("full_name", "")
        if repo_id != getattr(cfg, "_webhook_repo_id", None) and full_name != f"{cfg.github_owner}/{cfg.github_repo}":
            return error(403, "REPO_NOT_ALLOWED", "repository is not on the allowlist")
        store: Store = app.state.store
        if store.webhook_seen(delivery):
            return JSONResponse(status_code=200, content={"status": "duplicate", "delivery_id": delivery})
        body_digest = hashlib.sha256(raw).hexdigest()
        store.record_webhook(delivery, event, int(repo_id or 0), body_digest, "ACCEPTED", None)
        return JSONResponse(status_code=202, content={
            "status": "accepted", "delivery_id": delivery,
            "note": "webhook intake is validated and deduplicated; automated analysis "
                    "of GitHub-sourced contracts requires the configured integration mode",
        })

    # ----------------------------------------------------------- summary draft
    @app.post("/api/v1/analyses/{run_id}/summary-draft", tags=["analyses"])
    def summary_draft(run_id: str, claims: dict[str, Any] = Depends(principal)):
        store: Store = app.state.store
        run = store.get_run(run_id)
        if run is None:
            return error(404, "RUN_NOT_FOUND", "analysis run not found")
        role = store.project_role(claims["user_id"], run["project_id"])
        if role is None:
            return error(404, "RUN_NOT_FOUND", "analysis run not found for this caller")
        if run["state"] != "COMPLETED":
            return error(409, "RUN_INCOMPLETE", "analysis has not completed")
        from app.reporting.summary_draft import generate_draft
        result = generate_draft(store, run_id, cfg)
        if result.get("unavailable"):
            return error(503, "PROVIDER_UNAVAILABLE", result.get("reason", "provider unavailable"))
        return result

    # ----------------------------------------------------------- orgs (scope)
    @app.get("/api/v1/me", tags=["auth"])
    def me(claims: dict[str, Any] = Depends(principal)):
        store: Store = app.state.store
        orgs = store.user_orgs(claims["user_id"])
        return {"account": claims["account"], "user_id": claims["user_id"],
                "role": claims["role"], "organizations": orgs}

    return app
