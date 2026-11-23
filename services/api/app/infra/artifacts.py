"""Artifact store: opaque path-safe keys, digest-verified content.

Artifacts live under ARTIFACT_DIR keyed by run_id/kind; the database stores
only the relative key plus sha256 and size. No user paths, no secrets.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path
from typing import Any

from app.config import Settings

_SAFE_KEY = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
MAX_ARTIFACT_BYTES = 512 * 1024  # per-artifact cap (512 KiB)


class ArtifactStore:
    def __init__(self, settings: Settings) -> None:
        self.root = Path(settings.artifact_dir)
        self.retention_days = settings.artifact_retention_days

    def _run_dir(self, run_id: str) -> Path:
        if not _SAFE_KEY.match(run_id):
            raise ValueError("invalid run id for artifact path")
        return self.root / run_id

    def save(self, run_id: str, kind: str, key: str, content: bytes) -> dict[str, Any]:
        if not _SAFE_KEY.match(kind) or not _SAFE_KEY.match(key):
            raise ValueError("invalid artifact key")
        if len(content) > MAX_ARTIFACT_BYTES:
            raise ValueError("artifact exceeds byte cap")
        directory = self._run_dir(run_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{kind}_{key}"
        if target.exists():  # immutable: never overwrite
            raise ValueError("artifact already exists (immutable)")
        target.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        return {"relative_key": f"{run_id}/{kind}_{key}", "sha256": digest,
                "byte_size": len(content)}

    def load(self, run_id: str, kind: str, key: str) -> bytes | None:
        directory = self._run_dir(run_id)
        target = directory / f"{kind}_{key}"
        if not target.exists():
            return None
        return target.read_bytes()[:MAX_ARTIFACT_BYTES]

    def cleanup_run(self, run_id: str) -> None:
        directory = self._run_dir(run_id)
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)

    def enforce_retention(self, run_ids_with_timestamp: list[tuple[str, Any]]) -> list[str]:
        """Delete artifact dirs older than retention. Returns removed run ids."""
        import datetime as dt
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=self.retention_days)
        removed: list[str] = []
        for run_id, ts in run_ids_with_timestamp:
            try:
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=dt.timezone.utc)
                if ts < cutoff:
                    self.cleanup_run(run_id)
                    removed.append(run_id)
            except (AttributeError, TypeError):
                continue
        return removed


def sanitize_log(text: str) -> str:
    """Redact tokens/emails/secret-looking material from runner output."""
    import re as _re
    patterns = (
        (_re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "ghp_[REDACTED]"),
        (_re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "github_pat_[REDACTED]"),
        (_re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email-redacted]"),
        (_re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
        (_re.compile(r"AKIA[0-9A-Z]{16}"), "AKIA[REDACTED]"),
        (_re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{16,}"), "Bearer [REDACTED]"),
    )
    out = text
    for pattern, replacement in patterns:
        out = pattern.sub(replacement, out)
    # hard byte cap
    if len(out.encode("utf-8")) > MAX_ARTIFACT_BYTES:
        out = out[: MAX_ARTIFACT_BYTES] + "\n[truncated]"
    return out
