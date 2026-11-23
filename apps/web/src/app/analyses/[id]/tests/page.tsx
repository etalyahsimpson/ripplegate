"use client";
import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { EmptyState, ErrorPanel } from "@/components/Shared";

export default function TestsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const tests = useQuery({ queryKey: ["tests", id], queryFn: () => { void api.ensureSession(); return api.listTests(id); }, retry: 1 });
  if (tests.isLoading) return <EmptyState message="Loading test executions…" />;
  if (tests.isError) return <ErrorPanel error={tests.error as Error} retry={() => tests.refetch()} />;
  const items = tests.data?.items ?? [];
  return (
    <>
      <h1>Consumer test executions</h1>
      {items.map((t) => (
        <section key={t.id} className="card" style={{ marginBottom: "0.75rem" }}>
          <h2 style={{ fontSize: "1rem", margin: 0 }}>{t.suite_id}</h2>
          <table className="data"><tbody>
            <tr><td>Status</td><td><span className={`chip chip-${t.status === "PASSED" ? "PASS" : "BREAKING"}`}>{t.status}</span></td></tr>
            <tr><td>Exit code</td><td>{t.exit_code ?? "n/a"}</td></tr>
            <tr><td>Duration</td><td>{t.duration_ms ?? "n/a"} ms</td></tr>
            <tr><td>Fixture digest</td><td><code>{t.fixture_digest.slice(0, 24)}…</code></td></tr>
            <tr><td>Runner image</td><td className="muted">{t.image_ref}</td></tr>
            <tr><td>Reproduce</td><td><code>node examples/{t.suite_id === "billing-contract" ? "billing-service" : "reporting-service"}/contract.test.js &lt;candidate.json&gt;</code></td></tr>
          </tbody></table>
          {t.artifact_id && <p className="muted" style={{ fontSize: "0.8rem" }}>Sanitized log artifact: <code>{t.artifact_id.slice(0, 12)}…</code> (fetch via /api/v1/analyses/{id}/artifacts/{t.artifact_id})</p>}
        </section>
      ))}
      {items.length === 0 && <EmptyState message="No consumer suites executed for this run." />}
    </>
  );
}
