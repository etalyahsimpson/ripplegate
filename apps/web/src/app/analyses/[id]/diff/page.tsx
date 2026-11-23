"use client";
import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { EmptyState, ErrorPanel } from "@/components/Shared";

export default function DiffPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const findings = useQuery({ queryKey: ["findings", id], queryFn: () => { void api.ensureSession(); return api.listFindings(id); }, retry: 1 });
  if (findings.isLoading) return <EmptyState message="Loading findings…" />;
  if (findings.isError) return <ErrorPanel error={findings.error as Error} retry={() => findings.refetch()} />;
  const items = findings.data?.items ?? [];
  return (
    <>
      <h1>Contract delta</h1>
      {items.map((f) => (
        <section key={f.id} className="card" style={{ marginBottom: "1rem" }} aria-label={`Finding ${f.rule_id}`}>
          <h2 style={{ fontSize: "1rem", margin: "0 0 0.5rem" }}>{f.rule_id} · {f.surface}</h2>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "1rem" }}>
            <div>
              <h3 className="muted" style={{ fontSize: "0.75rem", textTransform: "uppercase" }}>Before</h3>
              <pre>{JSON.stringify(f.before_value, null, 2)}</pre>
            </div>
            <div>
              <h3 className="muted" style={{ fontSize: "0.75rem", textTransform: "uppercase" }}>After</h3>
              <pre>{JSON.stringify(f.after_value, null, 2)}</pre>
            </div>
          </div>
          <p style={{ fontSize: "0.85rem" }}><strong>JSON pointer:</strong> <code>{f.location}</code></p>
          <p className="muted" style={{ fontSize: "0.85rem" }}>Why this changes compatibility: {f.reason}</p>
        </section>
      ))}
      {items.length === 0 && <EmptyState message="No findings recorded for this run." />}
    </>
  );
}
