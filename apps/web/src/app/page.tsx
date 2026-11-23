"use client";
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api } from "@/lib/api";
import { OutcomeChip, StateChip, EmptyState, ErrorPanel } from "@/components/Shared";

export default function Dashboard() {
  useEffect(() => { void api.ensureSession().catch(() => undefined); }, []);
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api.listRuns(), retry: 1, refetchInterval: 5000, enabled: typeof window !== "undefined" });
  if (runs.isLoading) return <EmptyState message="Loading analyses from the API…" />;
  if (runs.isError) return <ErrorPanel error={runs.error as Error} retry={() => runs.refetch()} />;
  const items = runs.data?.items ?? [];
  const blocks = items.filter((r) => r.assessment === "BLOCK").length;
  const passes = items.filter((r) => r.assessment === "PASS").length;
  return (
    <>
      <section aria-labelledby="hero-title">
        <h1 id="hero-title" style={{ fontSize: "clamp(1.6rem, 4vw, 2.4rem)", margin: "0 0 0.5rem" }}>Release confidence backed by consumer evidence.</h1>
        <p className="muted" style={{ maxWidth: "48rem" }}>Producer-side green tests do not catch consumer-breaking API changes. RippleGate diffs OpenAPI contracts, links registered consumers, executes their contract suites in isolation, and recommends BLOCK / REVIEW / PASS from that evidence.</p>
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", margin: "1rem 0 1.5rem" }}>
          <Link className="btn" href="/guide">Run the breaking change →</Link>
          <Link className="btn btn-teal" href="/guide">See a compatible control →</Link>
        </div>
      </section>
      <section aria-label="Statistics" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "1rem", margin: "1.5rem 0" }}>
        <div className="card"><div style={{ fontSize: "2rem", fontWeight: 800 }}>{items.length}</div><div className="muted">analyses (computed from DB)</div></div>
        <div className="card"><div style={{ fontSize: "2rem", fontWeight: 800, color: "#FF6B6B" }}>{blocks}</div><div className="muted">open blockers</div></div>
        <div className="card"><div style={{ fontSize: "2rem", fontWeight: 800, color: "#4ADE9C" }}>{passes}</div><div className="muted">passing controls</div></div>
        <div className="card"><div style={{ fontSize: "2rem", fontWeight: 800 }}>v1</div><div className="muted">policy version</div></div>
      </section>
      <section aria-labelledby="recent-title">
        <h2 id="recent-title">Recent analyses</h2>
        <table className="data">
          <thead><tr><th>Run</th><th>Source</th><th>Base → Candidate</th><th>State</th><th>Outcome</th></tr></thead>
          <tbody>
            {items.slice(0, 8).map((r) => (
              <tr key={r.id}>
                <td><Link href={`/analyses/${r.id}`}>{r.id.slice(0, 8)}</Link></td>
                <td className="muted">{r.source_type === "FIXTURE" ? "Contract fixture" : "GitHub commit"}</td>
                <td className="muted" style={{ fontSize: "0.8rem" }}>{r.base_identity} → {r.candidate_identity}</td>
                <td><StateChip state={r.state} /></td>
                <td><OutcomeChip outcome={r.assessment} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        {items.length === 0 && <EmptyState message="No analyses yet. Use the Guide to run the breaking-change demonstration." />}
      </section>
    </>
  );
}
