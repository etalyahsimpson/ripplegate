export type Outcome = "BLOCK" | "REVIEW" | "PASS" | "ERROR" | null;
export type RunState = string;
export interface ApiError { error: { code: string; message: string; request_id: string; details: Record<string, unknown> | null } }
export interface RunListItem { id: string; project_id: string; source_type: string; base_identity: string; candidate_identity: string; state: RunState; policy_version: number; created_at: string; finished_at: string | null; assessment: Outcome }
export interface Finding { id: string; rule_id: string; rule_version: string; surface: string; location: string; before_value: unknown; after_value: unknown; classification: string; severity: string; reason: string; verification_state: string; evidence_refs: Array<Record<string, unknown>>; confidence_basis: string }
export interface TestExecution { id: string; suite_id: string; fixture_digest: string; image_ref: string; status: string; duration_ms: number | null; exit_code: number | null; artifact_id: string | null; created_at: string; finished_at: string | null }
export interface Assessment { outcome: string; blocking_reasons: string[]; unknowns: string[]; evidence_digest: string; policy_version: number }
export interface RunDetail { id: string; project_id: string; source_type: string; base_identity: string; candidate_identity: string; state: RunState; policy_version: number; created_at: string; finished_at: string | null; finding_counts: Record<string, number>; assessment: Outcome; report_href: string | null }
export interface GraphData { nodes: Array<{ id: string; name: string; kind: string }>; edges: Array<{ id: string; source: string; target: string; method: string; path: string; suite: string; required_fields: string[] }>; coverage_caveat: string; uncovered_consumers: string[]; registry_revision: number }
export interface ProjectItem { id: string; owner: string; repository: string; display_name: string; status: string; organization_id: string; created_at: string }
