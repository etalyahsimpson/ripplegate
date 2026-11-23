"use client";
import Link from "next/link";

export function OutcomeChip({ outcome }: { outcome: string | null }) {
  if (!outcome) return <span className="chip chip-UNKNOWN">PENDING</span>;
  return <span className={`chip chip-${outcome}`}>{outcome}</span>;
}
export function ClassChip({ classification }: { classification: string }) {
  return <span className={`chip chip-${classification}`}>{classification}</span>;
}
export function StateChip({ state }: { state: string }) {
  return <span className="chip chip-teal">{state}</span>;
}
export function EmptyState({ message }: { message: string }) {
  return <div className="card muted" role="status">{message}</div>;
}
export function ErrorPanel({ error, retry }: { error: Error; retry?: () => void }) {
  return (
    <div className="card" role="alert">
      <p style={{ color: "#FF6B6B", fontWeight: 700 }}>Something failed: {error.message}</p>
      {retry && <button className="btn" onClick={retry}>Retry</button>}
    </div>
  );
}
export function EvidenceLadder({ items }: { items: Array<{ label: string; value: string }> }) {
  return (
    <ol style={{ listStyle: "none", padding: 0 }}>
      {items.map((it, i) => (
        <li key={i} style={{ display: "flex", gap: "0.75rem", alignItems: "flex-start", padding: "0.5rem 0", borderTop: i ? "1px solid rgba(98,155,255,.12)" : "none" }}>
          <span aria-hidden style={{ color: "#37D9BC", fontWeight: 800 }}>{i + 1}</span>
          <span><strong style={{ display: "block" }}>{it.label}</strong><span className="muted" style={{ fontSize: "0.85rem" }}>{it.value}</span></span>
        </li>
      ))}
    </ol>
  );
}
export function DemoLauncher({ projectId, baseId, candId, label, idemKey }: { projectId: string; baseId: string; candId: string; label: string; idemKey: string }) {
  return <Link className="btn btn-teal" href={`/analyses?launch=${idemKey}&base=${baseId}&cand=${candId}&project=${projectId}`} style={{ display: "inline-block", fontSize: "0.85rem" }}>{label}</Link>;
}
