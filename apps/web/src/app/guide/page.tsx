"use client";
import { useEffect, useState } from "react";
import { api, DEMO_PROJECT } from "@/lib/api";

export default function GuidePage() {
  const [contracts, setContracts] = useState<Array<{ id: string; fixture_id: string | null }>>([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ id: string; state: string; assessment: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.ensureSession().then(() => api.listContracts(DEMO_PROJECT).then((d) => setContracts(d.items))).catch((e) => setError(String(e)));
  }, []);
  const launch = async (baseFid: string, candFid: string, key: string) => {
    setBusy(true); setError(null); setResult(null);
    try {
      await api.ensureSession();
      const base = contracts.find((c) => c.fixture_id === baseFid);
      const cand = contracts.find((c) => c.fixture_id === candFid);
      if (!base || !cand) throw new Error("contracts not registered yet");
      const r = await api.createAnalysis(DEMO_PROJECT, base.id, cand.id, key);
      const detail = await api.getRun(r.id);
      setResult({ id: r.id, state: detail.state, assessment: detail.assessment });
    } catch (e) { setError(String((e as Error).message)); }
    setBusy(false);
  };
  const f = (id: string) => contracts.find((c) => c.fixture_id === id)?.id ?? "";
  return (
    <>
      <h1>Break it yourself: the two-case tutorial</h1>
      <p className="muted" style={{ maxWidth: "48rem" }}>A controlled demo produces real stored evidence when clicked. Case 1 renames <code>customer_id</code> to <code>account_id</code>: the billing assertion fails and the policy BLOCKs. Case 2 adds an optional <code>fulfillment_note</code>: both registered suites pass and the policy PASSes.</p>
      <section className="card" aria-label="Case 1 breaking">
        <h2 style={{ fontSize: "1rem", marginTop: 0 }}>Case 1 · Breaking rename</h2>
        <p style={{ fontSize: "0.9rem" }}>What it proves: a real Jest-style assertion fails only on the breaking candidate; the verdict carries the executed evidence.</p>
        <button className="btn" disabled={busy || !contracts.length} onClick={() => launch("fixture-base-v1", "fixture-candidate-breaking-v2", "guide-breaking-case-0001")}>Run analysis (synthetic demonstration)</button>
      </section>
      <section className="card" aria-label="Case 2 additive">
        <h2 style={{ fontSize: "1rem", marginTop: 0 }}>Case 2 · Additive control</h2>
        <p style={{ fontSize: "0.9rem" }}>What it does NOT prove: that every real-world consumer tolerates the change; only the two registered suites are executed.</p>
        <button className="btn btn-teal" disabled={busy || !contracts.length} onClick={() => launch("fixture-base-v1", "fixture-candidate-additive-v2", "guide-additive-case-0002")}>Run analysis (synthetic demonstration)</button>
      </section>
      {result && (
        <section className="card" aria-label="Result" aria-live="polite">
          <p style={{ margin: 0 }}>Run <code>{result.id.slice(0, 8)}</code> · state <strong>{result.state}</strong> · outcome <strong>{result.assessment ?? "PENDING"}</strong></p>
          <a href={`/analyses/${result.id}`}>Open the evidence ladder →</a>
        </section>
      )}
      {error && <p role="alert" style={{ color: "#FF6B6B" }}>{error}</p>}
      <section className="card" aria-label="Commands">
        <h2 style={{ fontSize: "1rem", marginTop: 0 }}>Safe reproduction commands</h2>
        <pre>{`bash scripts/demo-breaking.sh      # rename -> BLOCK
bash scripts/demo-compatible.sh   # additive -> PASS
node examples/billing-service/contract.test.js examples/orders-api/openapi-candidate-breaking.json  # exit 1`}</pre>
      </section>
    </>
  );
}
