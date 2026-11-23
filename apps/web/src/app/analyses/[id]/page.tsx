"use client";
import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api } from "@/lib/api";
import { OutcomeChip, ClassChip, EmptyState, ErrorPanel, EvidenceLadder } from "@/components/Shared";

export default function RunDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const run = useQuery({ queryKey: ["run", id], queryFn: () => { void api.ensureSession(); return api.getRun(id); }, retry: 1, refetchInterval: (q) => (q.state.data?.state === "COMPLETED" || q.state.data?.state === "ERROR" ? false : 3000) });
  const findings = useQuery({ queryKey: ["findings", id], queryFn: () => api.listFindings(id), enabled: !!run.data && run.data.state === "COMPLETED", retry: 1 });
  const tests = useQuery({ queryKey: ["tests", id], queryFn: () => api.listTests(id), enabled: !!run.data && run.data.state === "COMPLETED", retry: 1 });
  if (run.isLoading) return <EmptyState message="Loading run…" />;
  if (run.isError) return <ErrorPanel error={run.error as Error} retry={() => run.refetch()} />;
  const d = run.data;
  if (!d) return <EmptyState message="Run not found." />;
  return (
    <>
      <nav aria-label="Breadcrumb" className="muted" style={{ fontSize: "0.8rem" }}><Link href="/analyses">Analyses</Link> / {d.id.slice(0, 8)}</nav>
      <h1 style={{ margin: "0.5rem 0" }}>Run evidence <OutcomeChip outcome={d.assessment} /></h1>
      <section className="card" aria-label="Run identity">
        <p style={{ margin: 0 }}><strong>Source:</strong> {d.source_type === "FIXTURE" ? `fixture fingerprint (never a git SHA)` : "GitHub commit"}</p>
        <p className="muted" style={{ fontSize: "0.85rem" }}>base <code>{d.base_identity}</code> → candidate <code>{d.candidate_identity}</code> · policy v{d.policy_version} · state {d.state}</p>
      </section>
      <section aria-labelledby="ladder-title">
        <h2 id="ladder-title" style={{ marginTop: "1.5rem" }}>Evidence ladder</h2>
        <div className="card">
          <EvidenceLadder items={[
            { label: "1. Structural change detected", value: `${Object.values(d.finding_counts).reduce((a, b) => a + b, 0)} findings (BREAKING ${d.finding_counts.BREAKING || 0}, ADDITIVE ${d.finding_counts.ADDITIVE || 0}, UNKNOWN ${d.finding_counts.UNKNOWN || 0})` },
            { label: "2. Rule classification (versioned, deterministic)", value: findings.data?.items.map((f) => f.rule_id).join(", ") || "—" },
            { label: "3. Registered consumer impact", value: "billing-service (customer_id required) · reporting-service (total_cents required)" },
            { label: "4. Executed test outcome", value: tests.data?.items.map((t) => `${t.suite_id}: ${t.status}`).join(", ") || "—" },
          ]} />
        </div>
      </section>
      <section aria-labelledby="findings-title">
        <h2 id="findings-title">Findings</h2>
        {findings.data?.items.map((f) => (
          <div key={f.id} className="card" style={{ marginBottom: "0.75rem" }}>
            <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
              <ClassChip classification={f.classification} />
              <strong>{f.rule_id}</strong><span className="muted">v{f.rule_version}</span>
              <span className="chip chip-teal">{f.verification_state}</span>
            </div>
            <p className="muted" style={{ fontSize: "0.85rem", margin: "0.5rem 0" }}>{f.reason}</p>
            <p style={{ fontSize: "0.8rem" }}><code>{f.location}</code></p>
            <p style={{ fontSize: "0.8rem" }}>before <code>{JSON.stringify(f.before_value)}</code> → after <code>{JSON.stringify(f.after_value)}</code></p>
            <Link href={`/analyses/${id}/diff`} style={{ fontSize: "0.85rem" }}>View diff →</Link>
          </div>
        ))}
      </section>
      <section aria-labelledby="tests-title">
        <h2 id="tests-title">Executed consumer evidence</h2>
        {tests.data?.items.map((t) => (
          <div key={t.id} className="card" style={{ marginBottom: "0.5rem" }}>
            <strong>{t.suite_id}</strong> <span className={`chip chip-${t.status === "PASSED" ? "PASS" : "BREAKING"}`}>{t.status}</span>
            <p className="muted" style={{ fontSize: "0.8rem", margin: "0.25rem 0" }}>exit {t.exit_code} · {t.duration_ms}ms · digest <code>{t.fixture_digest.slice(0, 12)}</code> · {t.image_ref}</p>
            <Link href={`/analyses/${id}/tests`} style={{ fontSize: "0.85rem" }}>Logs and reproduction →</Link>
          </div>
        ))}
      </section>
      {d.finding_counts.UNKNOWN ? <p className="card" style={{ borderColor: "rgba(232,180,74,.5)" }}>⚠ Unknown findings present: the policy fails closed; this is never rendered as a pass.</p> : null}
    </>
  );
}
