import type { Assessment, Finding, GraphData, ProjectItem, RunDetail, RunListItem, TestExecution } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = typeof window !== "undefined" ? window.localStorage.getItem("rg_session") : null;
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(init?.headers || {}) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.error?.message || `request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

async function ensureSession(): Promise<void> {
  if (typeof window === "undefined") return;
  if (window.localStorage.getItem("rg_session")) return;
  const res = await fetch(`${API_BASE}/api/v1/demo/session`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ account: "demo-admin" }) });
  if (!res.ok) throw new Error("demo session unavailable");
  const body = await res.json();
  window.localStorage.setItem("rg_session", body.token);
}

export const api = {
  ensureSession,
  listRuns: (projectId?: string) => request<{ items: RunListItem[]; total: number }>(`/api/v1/analyses${projectId ? `?project_id=${projectId}` : ""}`),
  getRun: (id: string) => request<RunDetail>(`/api/v1/analyses/${id}`),
  listFindings: (id: string) => request<{ items: Finding[] }>(`/api/v1/analyses/${id}/findings`),
  listTests: (id: string) => request<{ items: TestExecution[] }>(`/api/v1/analyses/${id}/tests`),
  getGraph: (projectId: string) => request<GraphData>(`/api/v1/projects/${projectId}/graph`),
  listProjects: () => request<{ items: ProjectItem[] }>(`/api/v1/projects`),
  createAnalysis: (projectId: string, baseId: string, candidateId: string, key: string) =>
    request<{ id: string; state: string }>(`/api/v1/analyses`, { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify({ project_id: projectId, producer_service_id: "22222222-2222-4222-8222-222222222222", base_contract_id: baseId, candidate_contract_id: candidateId, migration_artifact_id: null, policy_version: 1, registry_revision: 1 }) }),
  getMarkdownReport: async (id: string) => {
    const res = await fetch(`${API_BASE}/api/v1/analyses/${id}/report?format=markdown`, { headers: { Authorization: `Bearer ${typeof window !== "undefined" ? window.localStorage.getItem("rg_session") : null}` } });
    if (!res.ok) throw new Error("report unavailable");
    return res.text();
  },
  listContracts: (projectId: string) => request<{ items: Array<{ id: string; fixture_id: string | null; commit_sha: string | null; source_type: string }> }>(`/api/v1/projects/${projectId}/contracts`),
};
export const DEMO_PROJECT = "11111111-1111-4111-8111-111111111111";
