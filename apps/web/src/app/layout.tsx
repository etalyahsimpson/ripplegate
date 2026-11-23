import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "RippleGate",
  description: "Evidence-led API compatibility and release impact analysis",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>
        <header style={{ borderBottom: "1px solid rgba(98,155,255,.2)", padding: "0.75rem 1.5rem", display: "flex", alignItems: "center", gap: "1rem", position: "sticky", top: 0, background: "#0D1424", zIndex: 10 }}>
          <a href="/" style={{ fontWeight: 800, fontSize: "1.1rem", color: "#37D9BC", textDecoration: "none" }} aria-label="RippleGate home">◎ RippleGate</a>
          <nav aria-label="Primary" style={{ display: "flex", gap: "1rem", fontSize: "0.9rem", flexWrap: "wrap" }}>
            <a href="/analyses">Analyses</a>
            <a href="/dependencies">Dependencies</a>
            <a href="/policies">Policies</a>
            <a href="/connections">Connections</a>
            <a href="/guide">Guide</a>
          </nav>
        </header>
        <main style={{ maxWidth: "1100px", margin: "0 auto", padding: "1.5rem 1.25rem 4rem" }}>{children}</main>
        </Providers>
      </body>
    </html>
  );
}
