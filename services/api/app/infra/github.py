"""GitHub REST adapter (standard-library networking only).

Three evidence modes, never conflated:
  * ACTIONS: the repository's own GitHub Actions workflow produces PR checks.
    This adapter only READS run/conclusion data; it never fabricates statuses.
  * APP: GitHub App Checks API requires installation credentials. When they
    are absent, code must report APP_MODE_UNCONFIGURED, not fake check runs.
  * NONE.

All requests use urllib from the standard library; the token arrives from the
runtime environment and is never logged or persisted.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


class GitHubAdapterError(Exception):
    pass


class GithubClient:
    def __init__(self, owner: str, repo: str, token: str | None = None) -> None:
        self.owner = owner
        self.repo = repo
        self.token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        self.base = "https://api.github.com"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ripplegate-analysis/1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        url = f"{self.base}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        for k, v in self._headers().items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                text = resp.read().decode("utf-8")
                return json.loads(text) if text else {}
        except urllib.error.HTTPError as exc:
            raise GitHubAdapterError(f"GitHub API {exc.code} for {method} {path}") from exc
        except urllib.error.URLError as exc:
            raise GitHubAdapterError(f"GitHub unreachable: {exc.reason}") from exc

    # --------------------------------------------------------------- reads
    def repo_info(self) -> dict[str, Any]:
        return self._request("GET", f"/repos/{self.owner}/{self.repo}")

    def get_commit(self, sha: str) -> dict[str, Any]:
        return self._request("GET", f"/repos/{self.owner}/{self.repo}/commits/{sha}")

    def list_workflow_runs(self, head_sha: str) -> list[dict[str, Any]]:
        data = self._request(
            "GET",
            f"/repos/{self.owner}/{self.repo}/actions/runs?head_sha={head_sha}&per_page=20",
        )
        return data.get("workflow_runs", [])

    def check_runs_for_ref(self, ref: str) -> list[dict[str, Any]]:
        data = self._request(
            "GET",
            f"/repos/{self.owner}/{self.repo}/commits/{ref}/check-runs?per_page=50",
        )
        return data.get("check_runs", [])

    def read_file(self, path: str, ref: str) -> bytes:
        """Fetch a repo file at a pinned ref (contents API, raw media type)."""
        url = (f"{self.base}/repos/{self.owner}/{self.repo}/contents/"
               f"{urllib.request.quote(path)}?ref={urllib.request.quote(ref)}")
        req = urllib.request.Request(url)
        for k, v in self._headers().items():
            req.add_header(k, v)
        req.add_header("Accept", "application/vnd.github.raw")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read(1_048_576 + 1)[:1_048_576]  # 1 MiB cap
        except urllib.error.HTTPError as exc:
            raise GitHubAdapterError(
                f"contents fetch failed ({exc.code}) for {path}@{ref}"
            ) from exc

    # ------------------------------------------------------- checks api
    def create_check_run(self, name: str, head_sha: str, conclusion: str,
                         output_title: str, output_summary: str) -> dict[str, Any]:
        """Checks API write. Requires a GitHub App token with checks:write.

        With a classic PAT this endpoint returns 403/422; callers must surface
        APP_MODE_UNCONFIGURED instead of pretending a check exists.
        """
        if not self.token:
            raise GitHubAdapterError("APP_MODE_UNCONFIGURED: no token available")
        return self._request(
            "POST",
            f"/repos/{self.owner}/{self.repo}/check-runs",
            {
                "name": name,
                "head_sha": head_sha,
                "status": "completed",
                "conclusion": conclusion,
                "output": {"title": output_title, "summary": output_summary},
            },
        )
