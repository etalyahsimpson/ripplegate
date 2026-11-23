"""Strict environment schema with safe defaults. Secrets never have defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_env: str = "local"
    demo_mode: bool = True
    public_base_url: str = "http://localhost:3000"
    api_base_url: str = "http://localhost:8000"
    database_url: str = ""
    redis_url: str = "redis://localhost:6379/0"
    session_signing_secret: str = ""
    webhook_secret: str = ""
    github_owner: str = "etalyahsimpson"
    github_repo: str = "ripplegate"
    github_integration_mode: str = "actions"
    github_app_configured: bool = False
    runner_mode: str = "local-launcher"
    runner_allowed_suites: tuple[str, ...] = ("billing-contract", "reporting-contract")
    max_run_seconds: int = 120
    artifact_retention_days: int = 30
    artifact_dir: str = "/var/lib/ripplegate/artifacts"
    max_openapi_bytes: int = 1_048_576
    cloud_artifacts_enabled: bool = False
    worker_inline: bool = True  # in-process pipeline execution (no external broker needed)


def _bool(raw: str | None, default: bool) -> bool:
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def load_settings(env: dict[str, str] | None = None) -> Settings:
    source = dict(os.environ) if env is None else env

    def get(name: str, default: str = "") -> str:
        return source.get(name, default)

    suites_raw = get("RUNNER_ALLOWED_SUITES", "billing-contract,reporting-contract")
    suites = tuple(s.strip() for s in suites_raw.split(",") if s.strip())
    return Settings(
        app_env=get("APP_ENV", "local"),
        demo_mode=_bool(get("DEMO_MODE"), True),
        public_base_url=get("PUBLIC_BASE_URL", "http://localhost:3000"),
        api_base_url=get("API_BASE_URL", "http://localhost:8000"),
        database_url=get("DATABASE_URL"),
        redis_url=get("REDIS_URL", "redis://localhost:6379/0"),
        session_signing_secret=get("SESSION_SIGNING_SECRET", "dev-only-session-secret"),
        webhook_secret=get("WEBHOOK_SECRET", "dev-only-webhook-secret"),
        github_owner=get("GITHUB_OWNER", "etalyahsimpson"),
        github_repo=get("GITHUB_REPO", "ripplegate"),
        github_integration_mode=get("GITHUB_INTEGRATION_MODE", "actions"),
        github_app_configured=bool(get("GITHUB_APP_APP_ID")) and bool(get("GITHUB_APP_PRIVATE_KEY_PATH")),
        runner_mode=get("RUNNER_MODE", "local-launcher"),
        runner_allowed_suites=suites or ("billing-contract", "reporting-contract"),
        max_run_seconds=int(get("MAX_RUN_SECONDS", "120") or 120),
        artifact_retention_days=int(get("ARTIFACT_RETENTION_DAYS", "30") or 30),
        artifact_dir=get("ARTIFACT_DIR", "/var/lib/ripplegate/artifacts"),
        max_openapi_bytes=int(get("MAX_OPENAPI_BYTES", "1048576") or 1048576),
        cloud_artifacts_enabled=_bool(get("CLOUD_ARTIFACTS_ENABLED"), False),
        worker_inline=_bool(get("WORKER_INLINE", "true"), True),
    )
