"""Log redaction for runner output.

Kept standalone (no app.* import) so the runner package can be used from the
worker, CI, and tests without dragging the API process with it.
"""
from __future__ import annotations

import re

MAX_LOG_BYTES = 512 * 1024

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "ghp_[REDACTED]"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "github_pat_[REDACTED]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email-redacted]"),
    (re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AKIA[REDACTED]"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{16,}"), "Bearer [REDACTED]"),
)


def sanitize_log(text: str) -> str:
    """Redact credential-like content and cap size. Order: patterns, then bytes."""
    out = text
    for pattern, replacement in _PATTERNS:
        out = pattern.sub(replacement, out)
    if len(out.encode("utf-8")) > MAX_LOG_BYTES:
        out = out[:MAX_LOG_BYTES] + "\n[truncated]"
    return out
