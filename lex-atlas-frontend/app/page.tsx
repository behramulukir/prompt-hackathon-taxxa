/**
 * Landing — "Utility Focus" — ported from Stitch.
 *
 * 5-col hero text + 7-col canvas topology box, then a 4-card hard-bordered
 * utility grid ("Core Utility Architecture v2.4.0"). Editorial EB Garamond
 * for the H1 with italic second line, terracotta insight marker on the hero.
 */

import Link from "next/link";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";
import { TopologyCanvas } from "@/components/TopologyCanvas";

const PILLARS = [
  {
    n: "01",
    icon: "account_tree",
    title: "Semantic Mapping",
    body:
      "Constructs dense vector representations of statutory text, aligning Vero guidance directly with overarching Finlex legislative intent.",
  },
  {
    n: "02",
    icon: "history",
    title: "Temporal Logic",
    body:
      "Tracks legislative amendments chronologically. Ensures retrieval agents isolate the exact regulatory framework active during the specified tax period.",
  },
  {
    n: "03",
    icon: "forum",
    title: "Agentic Debate",
    body:
      "Deploys adversarial LLM instances to cross-examine proposed tax interpretations against historical Supreme Administrative Court (KHO) rulings.",
  },
  {
    n: "04",
    icon: "format_quote",
    title: "Citations",
    body:
      "Generates immutable, hyperlinked audit trails for every assertion, mapping generated advice directly back to raw source paragraphs.",
  },
];

export default function LandingPage() {
  return (
    <main className="flex min-h-screen flex-col">
      <Header />

      <div
        className="mx-auto flex w-full max-w-[1440px] flex-grow flex-col px-6"
        style={{ paddingBlock: "var(--space-9)", gap: "var(--space-9)" }}
      >
        {/* ─── Hero ─── 5/7 split, generous spacing. */}
        <section
          className="grid grid-cols-1 items-center lg:grid-cols-12"
          style={{ gap: "var(--space-7)" }}
        >
          <div
            className="z-10 flex flex-col lg:col-span-5"
            style={{ gap: "var(--space-7)" }}
          >
            <div className="insight-marker" style={{ paddingLeft: "var(--space-5)" }}>
              <h1
                className="font-serif font-medium tracking-tight text-on-surface"
                style={{
                  marginBottom: "var(--space-5)",
                  fontSize: "clamp(40px, 5.5vw, 72px)",
                  lineHeight: 1.05,
                  letterSpacing: "-0.02em",
                }}
              >
                Agentic GraphRAG
                <br />
                <span className="italic text-on-surface-variant">
                  for Finnish tax law.
                </span>
              </h1>
              <p
                className="text-on-surface-variant"
                style={{
                  maxWidth: "44ch",
                  fontSize: "var(--text-body-lg)",
                  lineHeight: 1.6,
                }}
              >
                A continuous multi-agent retrieval and reasoning loop operating
                over Finlex and Vero guidelines. Lex Atlas synthesizes an
                authoritative, structured legal topology to resolve complex
                regulatory conflicts autonomously.
              </p>
            </div>
            <div
              className="flex flex-col sm:flex-row"
              style={{ gap: "var(--space-3)", paddingLeft: "var(--space-5)" }}
            >
              <Link href="/ask" className="btn-primary group">
                Initialize Workspace
                <span
                  className="material-symbols-outlined transition-transform group-hover:translate-x-1"
                  style={{ fontSize: "var(--icon-md)" }}
                >
                  arrow_forward
                </span>
              </Link>
              <Link href="/methodology" className="btn-secondary">
                Methodology
              </Link>
            </div>
          </div>

          {/* TOPOLOGY CANVAS - contained hero visualization */}
          <div className="relative h-[400px] overflow-hidden border border-outline-variant bg-surface-container-lowest lg:col-span-7 lg:h-[600px]">
            <div className="absolute right-4 top-4 z-10 system-label">
              SYS.VIS.01 // TOPOLOGY
            </div>
            <TopologyCanvas />
          </div>
        </section>

        {/* ─── Core Utility Architecture ─── 4-pillar grid, hairline-divided. */}
        <section
          className="flex flex-col"
          style={{ gap: "var(--space-6)" }}
        >
          <div
            className="flex items-center border-b border-outline-variant"
            style={{ gap: "var(--space-4)", paddingBottom: "var(--space-3)" }}
          >
            <h2
              className="font-serif font-medium text-on-surface"
              style={{ fontSize: "var(--text-h3)", lineHeight: 1.15 }}
            >
              Core Utility Architecture
            </h2>
            <span className="system-label">v2.4.0</span>
          </div>

          <div className="grid grid-cols-1 border-l border-t border-outline-variant md:grid-cols-2 lg:grid-cols-4">
            {PILLARS.map((p) => (
              <div
                key={p.n}
                className="group relative flex flex-col border-b border-r border-outline-variant bg-surface-container-lowest transition-colors hover:bg-surface"
                style={{ padding: "var(--space-6)", gap: "var(--space-3)" }}
              >
                <div
                  className="absolute font-mono text-outline-variant"
                  style={{
                    right: "var(--space-4)",
                    top: "var(--space-4)",
                    fontSize: "var(--text-meta)",
                  }}
                >
                  {p.n}
                </div>
                <div
                  className="flex items-center justify-center border border-outline-variant transition-colors group-hover:border-secondary"
                  style={{
                    width: 40,
                    height: 40,
                    marginBottom: "var(--space-3)",
                  }}
                >
                  <span
                    className="material-symbols-outlined text-on-surface"
                    style={{ fontSize: "var(--icon-md)" }}
                  >
                    {p.icon}
                  </span>
                </div>
                <h3
                  className="font-sans font-medium text-on-surface"
                  style={{ fontSize: "var(--text-h4)", lineHeight: 1.3 }}
                >
                  {p.title}
                </h3>
                <p
                  className="font-sans text-on-surface-variant"
                  style={{ fontSize: "var(--text-body-sm)", lineHeight: 1.55 }}
                >
                  {p.body}
                </p>
              </div>
            ))}
          </div>
        </section>
      </div>

      <Footer />
    </main>
  );
}
