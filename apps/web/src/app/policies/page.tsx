"use client";
import { useQuery } from "@tanstack/react-query";
import { api, DEMO_PROJECT } from "@/lib/api";
import { EmptyState, ErrorPanel } from "@/components/Shared";
import { useState } from "react";

export default function PoliciesPage() {
  const [saved, setSaved] = useState(false);
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => { void api.ensureSession(); return api.listRuns(); }, retry: 1 });
  if (runs.isLoading) return <EmptyState message="Loading…" />;
  if (runs.isError) return <ErrorPanel error={runs.error as Error} retry={() => runs.refetch()} />;
  return (
    <>
      <h1>Release policy</h1>
      <section className="card" aria-label="Current policy">
        <h2 style={{ fontSize: "1rem", marginTop: 0 }}>Version 1 (immutable)</h2>
        <p style={{ fontSize: "0.9rem" }}>Blocking rules: <code>API-PATH-REMOVED, API-REQ-REQUIRED-ADDED, API-REQ-ENUM-REMOVED, API-RESP-REQUIRED-REMOVED, API-RESP-TYPE-CHANGED</code></p>
        <p style={{ fontSize: "0.9rem" }}>Mandatory suites: <code>billing-contract, reporting-contract</code></p>
        <p style={{ fontSize: "0.9rem" }}>Unknown strategy: <code>REVIEW</code> (fail closed; <em>unknown=PASS is rejected by the API</em>)</p>
      </section>
      <section className="card" aria-label="New version form">
        <h2 style={{ fontSize: "1rem" }}>Create new version (admin)</h2>
        <p className="muted" style={{ fontSize: "0.85rem" }}>Policies are immutable versioned rows. A new configuration is always a new version; history is never overwritten.</p>
        <form onSubmit={(e) => { e.preventDefault(); setSaved(true); }}>
          <label style={{ display: "block", margin: "0.5rem 0" }}>Version number <input name="version" type="number" min={2} defaultValue={2} required style={{ marginLeft: "0.5rem" }} /></label>
          <button className="btn" type="submit">Submit new version</button>
          {saved && <p className="muted" style={{ fontSize: "0.8rem" }}>POST /api/v1/projects/{DEMO_PROJECT}/policies with an admin session performs this operation server-side.</p>}
        </form>
      </section>
      <p className="card muted" style={{ fontSize: "0.85rem" }}>Enforcement disclaimer: the engine recommends; a human release owner retains final authority. RippleGate never ships anything by itself.</p>
    </>
  );
}
