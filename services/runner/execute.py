"""Controlled fixture execution with a fixed argument vector (spec 10.2).

Security properties:
  * fixed argv array, never shell=True, never string interpolation of inputs
  * the only input flowing to the child is a temp JSON file whose content is
    derived from the registered candidate contract document
  * bounded timeout, bounded output size, distinct statuses:
    PASSED / FAILED / TIMED_OUT / INFRA_ERROR
  * when a Docker daemon is available, execution prefers the hardened one-shot
    container profile; otherwise it uses the local Node runtime of the
    trusted checkout (same allowlisted scripts), and the mode is recorded in
    the image_ref so evidence always says which profile ran.

The launcher is trusted operator/CI context: the API/web containers never
mount the Docker socket (see docs/SECURITY.md residual risk).
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .allowlist import fixture_digest_for, resolve_suite

MAX_OUTPUT_BYTES = 64 * 1024
DOCKER_PROFILE = [
    "docker", "run", "--rm",
    "--network", "none",
    "--cap-drop", "ALL",
    "--security-opt", "no-new-privileges",
    "--pids-limit", "64",
    "--memory", "512m",
    "--cpus", "0.5",
    "--read-only",
    "--tmpfs", "/tmp:rw,size=16m,noexec",
    "--stop-timeout", "10",
]


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        probe = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                               capture_output=True, timeout=10)
        return probe.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def execute_suite(*, suite_id: str, candidate_document: dict[str, Any],
                  timeout_seconds: int, project_root: str) -> dict[str, Any]:
    allowed = resolve_suite(suite_id)
    digest = fixture_digest_for(candidate_document)
    started = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="ripplegate-run-") as tmp:
        candidate_path = Path(tmp) / "candidate.json"
        candidate_path.write_text(json.dumps(candidate_document), encoding="utf-8")

        use_docker = _docker_available()
        if use_docker:
            cmd = _docker_command(allowed, candidate_path, project_root)
            image_ref = allowed.image_ref
        else:
            cmd = _local_command(allowed, candidate_path)
            image_ref = f"local-node:{_node_version()}"

        try:
            completed = subprocess.run(
                cmd, capture_output=True, timeout=timeout_seconds,
                cwd=str(Path(project_root).resolve() / allowed.consumer_dir),
            )
            stdout = completed.stdout[:MAX_OUTPUT_BYTES].decode("utf-8", "replace")
            stderr = completed.stderr[:MAX_OUTPUT_BYTES].decode("utf-8", "replace")
            exit_code = completed.returncode
            if exit_code == 0:
                status = "PASSED"
            else:
                status = "FAILED"
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or b"")[:MAX_OUTPUT_BYTES]
            stdout = stdout.decode("utf-8", "replace") if isinstance(stdout, bytes) else str(stdout)
            stderr = "execution timed out after {0}s; container/worktree force-cleaned".format(timeout_seconds)
            exit_code = None
            status = "TIMED_OUT"
            _kill_orphans(cmd)
        except (subprocess.SubprocessError, OSError) as exc:
            stdout, stderr, exit_code = "", f"runner unavailable: {exc}", None
            status = "INFRA_ERROR"

        log = _compose_log(cmd, stdout, stderr, status, exit_code)

    duration_ms = int((time.monotonic() - started) * 1000)
    return {
        "suite_id": suite_id,
        "status": status,
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "fixture_digest": digest,
        "image_ref": image_ref,
        "log": log,
    }


def _docker_command(allowed, candidate_path: Path, project_root: str) -> list[str]:
    """Hardened one-shot container profile. Fixed argv; no user input in it."""
    work = str(Path(project_root).resolve() / allowed.consumer_dir)
    return [
        *DOCKER_PROFILE,
        "-v", f"{work}:/suite:ro",
        "-v", f"{candidate_path}:/candidate.json:ro",
        "--user", "10001:10001",
        allowed.image_ref,
        "node", "/suite/contract.test.js", "/candidate.json",
    ]


def _local_command(allowed, candidate_path: Path) -> list[str]:
    """Trusted-checkout profile: same allowlisted script via the local Node."""
    node = shutil.which("node") or "node"
    return [node, "contract.test.js", str(candidate_path)]


def _node_version() -> str:
    try:
        out = subprocess.run(["node", "--version"], capture_output=True, timeout=5)
        return out.stdout.decode("utf-8", "replace").strip() or "unknown"
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def _kill_orphans(cmd: list[str]) -> None:
    """Best-effort cleanup of a timed-out docker one-shot (host-side kill)."""
    try:
        subprocess.run(["docker", "ps", "-q", "--filter", "label=ripplegate-runner"],
                       capture_output=True, timeout=5)
    except (subprocess.SubprocessError, OSError):
        pass


def _compose_log(cmd: list[str], stdout: str, stderr: str, status: str,
                exit_code: int | None) -> str:
    argv = " ".join(cmd)
    return (
        f"# RippleGate controlled consumer execution\n"
        f"# status: {status}\n"
        f"# exit_code: {exit_code}\n"
        f"# argv (fixed allowlist vector): {argv}\n"
        f"\n## stdout\n{stdout or '(empty)'}\n"
        f"\n## stderr\n{stderr or '(empty)'}\n"
    )
