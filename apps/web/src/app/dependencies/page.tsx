"use client";
import { useQuery } from "@tanstack/react-query";
import { api, DEMO_PROJECT } from "@/lib/api";
import { EmptyState, ErrorPanel } from "@/components/Shared";

export default function DependenciesPage() {
  const graph = useQuery({ queryKey: ["graph"], queryFn: () => { void api.ensureSession(); return api.getGraph(DEMO_PROJECT); }, retry: 1 });
  if (graph.isLoading) return <EmptyState message="Loading registered dependencies…" />;
  if (graph.isError) return <ErrorPanel error={graph.error as Error} retry={() => graph.refetch()} />;
  const g = graph.data;
  if (!g) return <EmptyState message="No dependency graph." />;
  const xs = 80, ys = 60, w = 480, h = 240;
  const producers = g.nodes.filter((n) => n.kind === "producer");
  const consumers = g.nodes.filter((n) => n.kind === "consumer");
  const pos = (id: string) => {
    const p = producers.findIndex((n) => n.id === id);
    const c = consumers.findIndex((n) => n.id === id);
    if (p >= 0) return [w / 4, ys + p * 70];
    if (c >= 0) return [(3 * w) / 4, ys + c * 70];
    return [w / 2, h / 2];
  };
  return (
    <>
      <h1>Registered consumer dependency graph</h1>
      <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Producer to consumer dependency graph: orders-api feeds billing-service and reporting-service" style={{ maxWidth: "100%", height: "auto", display: "block", margin: "0 auto" }}>
        {g.edges.map((e) => {
          const [x1, y1] = pos(e.source); const [x2, y2] = pos(e.target);
          return <g key={e.id}>
            <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#629BFF" strokeWidth="2" aria-hidden />
            <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 6} fill="#E9EEF5" fontSize="10" textAnchor="middle">{e.method} {e.path}</text>
          </g>;
        })}
        {g.nodes.map((n) => {
          const [x, y] = pos(n.id);
          return <g key={n.id}>
            <rect x={x - 70} y={y - 18} width="140" height="36" rx="8" fill={n.kind === "producer" ? "#1D2A42" : "#151F32"} stroke={n.kind === "producer" ? "#37D9BC" : "#629BFF"} />
            <text x={x} y={y + 4} fill="#E9EEF5" fontSize="11" textAnchor="middle">{n.name}</text>
          </g>;
        })}
      </svg>
      <table className="data" aria-label="Registered edges">
        <thead><tr><th>Producer</th><th>Consumer</th><th>Endpoint</th><th>Required fields</th><th>Suite</th></tr></thead>
        <tbody>
          {g.edges.map((e) => {
            const pn = g.nodes.find((n) => n.id === e.source)?.name;
            const cn = g.nodes.find((n) => n.id === e.target)?.name;
            return <tr key={e.id}><td>{pn}</td><td>{cn}</td><td className="muted">{e.method} {e.path}</td><td className="muted">{e.required_fields.join(", ")}</td><td className="muted">{e.suite}</td></tr>;
          })}
        </tbody>
      </table>
      <p className="card muted" style={{ fontSize: "0.85rem" }}>{g.coverage_caveat}</p>
    </>
  );
}
