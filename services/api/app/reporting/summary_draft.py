"""Optional evidence-grounded release summary draft (spec 7.2 last row).

Deterministic template ALWAYS works without any provider credential. An
opt-in OpenAI/Anthropic adapter only REWORDS the same immutable evidence and
can never mutate findings, verification states, or the assessment. When the
provider is configured but unreachable, the endpoint returns 503 rather than
silently degrading to template output that looks provider-authored.
"""
from __future__ import annotations

import json
import os
from typing import Any

from app.infra.store import Store


def generate_draft(store: Store, run_id: str, settings: Any) -> dict[str, Any]:
    run = store.get_run(run_id)
    if run is None:
        raise ValueError("run not found")
    assessment = store.get_assessment(run_id)
    findings = store.list_findings(run_id, size=200)["items"]
    tests = store.list_test_executions(run_id)
    impacts = store.list_impacts(run_id)

    template = _template_summary(run, assessment, findings, tests, impacts)
    provider = _provider_name(settings)
    if provider is None:
        return {
            "mode": "deterministic_template",
            "provider": None,
            "draft": template,
            "note": "No AI provider configured; deterministic template summary. "
                    "This draft never affects classification, policy or releases.",
        }
    try:
        enhanced = _call_provider(provider, template, settings)
    except ProviderUnavailable:
        return {"unavailable": True,
                "reason": f"{provider} provider configured but not reachable"}
    return {
        "mode": "provider_draft",
        "provider": provider,
        "draft": enhanced,
        "grounding": template,
        "note": "Provider output is a rewording of immutable evidence only.",
    }


def _template_summary(run: dict[str, Any], assessment: dict[str, Any] | None,
                      findings: list[dict[str, Any]],
                      tests: list[dict[str, Any]],
                      impacts: list[dict[str, Any]]) -> str:
    outcome = (assessment or {}).get("outcome", "PENDING")
    counts: dict[str, int] = {}
    for f in findings:
        counts[f["classification"]] = counts.get(f["classification"], 0) + 1
    breaking = [f for f in findings if f["classification"] == "BREAKING"]
    affected = [i for i in impacts if i["impact_state"] == "AFFECTED"]
    failed = [t for t in tests if t["status"] == "FAILED"]
    parts = [
        f"Release recommendation: {outcome}.",
        f"Analysis compared base `{run['base_identity']}` against candidate "
        f"`{run['candidate_identity']}` under policy version {run['policy_version']}.",
        f"Findings: " + (", ".join(f"{v} {k}" for k, v in sorted(counts.items())) if counts else "none") + ".",
    ]
    if breaking:
        top = breaking[0]
        parts.append(f"Highest-risk change: {top['rule_id']} at {top['location']} ({top['reason']}).")
    if affected:
        names = sorted({i['consumer_name'] for i in affected if i['consumer_name']})
        parts.append("Registered consumers impacted: " + ", ".join(names) + ".")
    else:
        parts.append("No registered consumer is impacted by these findings; coverage is limited to the registry.")
    if failed:
        for t in failed:
            parts.append(f"Executed consumer suite {t['suite_id']} failed with exit code {t['exit_code']}.")
    elif tests:
        parts.append("All executed consumer suites passed.")
    else:
        parts.append("No consumer suites were executed for this run.")
    if (assessment or {}).get("unknowns"):
        parts.append("Unknowns remain; the policy fails closed rather than guessing PASS.")
    parts.append("A human release owner retains final authority over shipping.")
    return " ".join(parts)


def _provider_name(settings: Any) -> str | None:
    openai = os.environ.get("OPENAI_API_KEY")
    anthropic = os.environ.get("ANTHROPIC_API_KEY")
    if openai and anthropic:
        return "openai"
    if openai:
        return "openai"
    if anthropic:
        return "anthropic"
    return None


class ProviderUnavailable(Exception):
    pass


def _call_provider(provider: str, template: str, settings: Any) -> str:
    """Standard-library REST call to the configured provider; opt-in only."""
    import urllib.error
    import urllib.request
    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
        body = json.dumps({
            "model": "gpt-4o-mini",
            "input": f"Rewrite for clarity without changing facts:\n\n{template}",
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openai.com/v1/responses", data=body, method="POST")
        req.add_header("Authorization", f"Bearer {key}")
        req.add_header("Content-Type", "application/json")
    else:
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        body = json.dumps({
            "model": "claude-3-5-haiku-latest",
            "max_tokens": 400,
            "messages": [{"role": "user",
                          "content": f"Rewrite for clarity without changing facts:\n\n{template}"}],
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=body, method="POST")
        req.add_header("x-api-key", key)
        req.add_header("anthropic-version", "2023-06-01")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ProviderUnavailable(str(exc)) from exc
    if provider == "openai":
        items = data.get("output", [])
        for item in items:
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    return c.get("text", template)
        return template
    blocks = data.get("content", [])
    for b in blocks:
        if b.get("type") == "text":
            return b.get("text", template)
    return template
