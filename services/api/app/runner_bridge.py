"""Worker bridge: enqueue analysis pipeline execution.

Two safe modes:
  * inline  (default): the pipeline runs in-process synchronously; no broker.
    This is the local/demo/CI mode and stays deterministic.
  * celery  : the same pipeline function runs as a Celery task over Redis.

Both modes execute EXACTLY the same `run_pipeline(run_id, ctx)` code; the queue
is transport, not logic. Redis never stores verdicts; Postgres does.
"""
from __future__ import annotations

from typing import Any


def enqueue(run_id: str, app_state: Any) -> str:
    from app.config import Settings
    settings: Settings = app_state.settings
    if settings.worker_inline:
        from app.worker.pipeline import run_pipeline
        run_pipeline(run_id, app_state)
        return "inline"
    from celery_app import process_analysis
    process_analysis.delay(str(run_id))
    return "celery"


def load_runner_execute():
    """Load services/runner/execute.py without requiring package installs."""
    import importlib.util
    import pathlib
    import sys

    root = pathlib.Path(__file__).resolve().parents[3]
    pkg_dir = root / "services" / "runner"
    if "rg_runner_execute" in sys.modules:
        return sys.modules["rg_runner_execute"].execute_suite
    spec = importlib.util.spec_from_file_location("rg_runner_execute", pkg_dir / "execute.py",
        submodule_search_locations=[str(pkg_dir)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["rg_runner_execute"] = module
    spec.loader.exec_module(module)
    return module.execute_suite
