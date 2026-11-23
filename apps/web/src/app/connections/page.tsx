"use client";
export default function ConnectionsPage() {
  return (
    <>
      <h1>Connections</h1>
      <section className="card" aria-label="Repository configuration">
        <h2 style={{ fontSize: "1rem", marginTop: 0 }}>Repository</h2>
        <p style={{ fontSize: "0.9rem" }}><code>etalyahsimpson/ripplegate</code> · integration mode: <span className="chip chip-teal">actions</span></p>
        <p className="muted" style={{ fontSize: "0.85rem" }}>Allowlisted contract paths: <code>examples/orders-api/openapi-base.json</code>, <code>examples/orders-api/openapi-candidate-*.json</code></p>
      </section>
      <section className="card" aria-label="Integration modes">
        <h2 style={{ fontSize: "1rem" }}>GitHub integration modes (evidence classes, never conflated)</h2>
        <ul style={{ fontSize: "0.9rem" }}>
          <li><strong>Actions</strong> (verified): the repository's own CI workflow produces PR checks on real SHAs.</li>
          <li><strong>GitHub App Checks API</strong> <span className="chip chip-UNKNOWN">APP_MODE_UNCONFIGURED</span>: requires an authenticated App installation; not configured, so no custom check runs are created or claimed.</li>
          <li><strong>Webhook</strong>: intake validates HMAC-SHA256 on raw bytes, dedupes by delivery ID, allowlists the repository. See <code>POST /api/v1/github/webhook</code>.</li>
        </ul>
      </section>
      <p className="card muted" style={{ fontSize: "0.85rem" }}>No unearned “connected” badges: statuses reflect the actually configured integration only.</p>
    </>
  );
}
