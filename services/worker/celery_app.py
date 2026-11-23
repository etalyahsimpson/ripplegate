"""Celery app: Redis is queue transport ONLY; Postgres stays authoritative."""
from __future__ import annotations

import os

from celery import Celery

redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

app = Celery("ripplegate", broker=redis_url, backend=redis_url)
app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,             # redelivery tolerant; pipeline is idempotent
    worker_prefetch_multiplier=1,    # fair dispatch for long analysis jobs
    task_time_limit=int(os.environ.get("MAX_RUN_SECONDS", "120")) + 60,
    task_soft_time_limit=int(os.environ.get("MAX_RUN_SECONDS", "120")),
    broker_connection_retry_on_startup=True,
)

import importlib.util
import pathlib
import sys

_API = pathlib.Path(__file__).resolve().parents[2] / "services" / "api"


def _ensure_app_importable() -> None:
    if str(_API) not in sys.path:
        sys.path.insert(0, str(_API))


@app.task(name="ripplegate.process_analysis", bind=True, max_retries=3,
          default_retry_delay=5)
def process_analysis(self, run_id: str) -> dict:
    """Run the same pipeline the inline worker runs; retries are safe (idempotent)."""
    _ensure_app_importable()
    from app.config import load_settings
    from app.infra.artifacts import ArtifactStore
    from app.infra.store import Store
    from app.worker.pipeline import run_pipeline

    settings = load_settings()
    store = Store(settings)
    artifacts = ArtifactStore(settings)
    try:
        state = type("State", (), {})()
        state.store = store
        state.artifacts = artifacts
        state.settings = settings
        state.project_root = str(pathlib.Path(__file__).resolve().parents[2])
        return run_pipeline(run_id, state)
    finally:
        store.close()
