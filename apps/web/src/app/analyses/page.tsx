"use client";
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api } from "@/lib/api";
import { OutcomeChip, StateChip, EmptyState, ErrorPanel } from "@/components/Shared";

export default function AnalysesPage() {
  useEffect(() => { void api.ensureSession().catch(() => undefined); }, []);
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api.listRuns(), retry: 1, refetchInterval: 5000, enabled: typeof window !== "undefined" });
  if (runs.isLoading) return <EmptyState message="Loading…" />;
  if (runs.isError) return <ErrorPanel error={runs.error as Error} retry={() => runs.refetch()} />;
  const items = runs.data?.items ?? [];
  return (
    <>
      <h1>Analysis history</h1>
      <table className="data">
        <thead><tr><th>Run</th><th>Source type</th><th>Base / Candidate</th><th>Policy</th><th>State</th><th>Outcome</th><th>Created</th></tr></thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.id}>
              <td><Link href={`/analyses/${r.id}`}>{r.id.slice(0, 8)}</Link></td>
              <td className="muted">{r.source_type === "FIXTURE" ? "Contract fixture" : "GitHub commit"}</td>
              <td className="muted" style={{ fontSize: "0.75rem" }}>{r.base_identity} / {r.candidate_identity}</td>
              <td className="muted">v{r.policy_version}</td>
              <td><StateChip state={r.state} /></td>
              <td><OutcomeChip outcome={r.assessment} /></td>
              <td className="muted" style={{ fontSize: "0.8rem" }}>{new Date(r.created_at).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {items.length === 0 && <EmptyState message="No analyses recorded yet." />}
    </>
  );
}
