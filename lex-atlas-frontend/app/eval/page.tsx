/**
 * /eval — Stitch port. Terracotta insight marker on the H1, 3-stat bento
 * grid (Correctness · Citation Accuracy · Latency P95), dense data table
 * with TIER pills, hairline confidence bars, and a uppercase mono "load more"
 * action at the bottom.
 */

import Link from "next/link";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";

interface EvalRow {
  id: string;
  tier: "Basic" | "Hard" | "Difficulty 5";
  query: string;
  sources: number;
  confidence: number;
}

const ROWS: EvalRow[] = [
  {
    id: "Q-001",
    tier: "Basic",
    query:
      "What is the capital income tax rate (pääomatulovero) on income exceeding 30,000 € in a tax year?",
    sources: 3,
    confidence: 0.98,
  },
  {
    id: "Q-004",
    tier: "Basic",
    query:
      "What withholding rate applies to a foreign specialist on key-personnel status, and how long is the tax card valid?",
    sources: 5,
    confidence: 0.96,
  },
  {
    id: "Q-018",
    tier: "Hard",
    query:
      "How does AVL §8c apply to subcontracted demolition work, given KHO 2024:19 reverses prior Vero guidance?",
    sources: 12,
    confidence: 0.85,
  },
  {
    id: "Q-024",
    tier: "Hard",
    query:
      "Inheritance tax basis correction (perusteoikaisu) under PerVL §38–§39: time limits and required documentation.",
    sources: 8,
    confidence: 0.92,
  },
  {
    id: "Q-031",
    tier: "Basic",
    query:
      "Commuting deduction rates for own car vs moped under TVL for the 2025 tax year.",
    sources: 2,
    confidence: 0.99,
  },
  {
    id: "N-001",
    tier: "Difficulty 5",
    query:
      "Finnish-German-Swedish triangular VAT: simplification conditions, intermediary obligations, consequences of non-compliance.",
    sources: 15,
    confidence: 0.78,
  },
  {
    id: "Q-045",
    tier: "Difficulty 5",
    query:
      "Permanent establishment criteria for a foreign IT services company providing remote work via a Finnish-resident employee.",
    sources: 11,
    confidence: 0.81,
  },
];

const TIER_TONE: Record<EvalRow["tier"], string> = {
  Basic: "text-on-surface-variant",
  Hard: "text-on-surface",
  "Difficulty 5": "text-secondary",
};

export default function EvalPage() {
  return (
    <main className="flex min-h-screen flex-col">
      <Header />

      <div
        className="mx-auto flex w-full max-w-6xl flex-grow flex-col px-6"
        style={{ paddingBlock: "var(--space-9)", gap: "var(--space-8)" }}
      >
        {/* ─── Hero ─── single block, left-aligned. No 3/9 lurch. */}
        <header
          className="flex flex-col"
          style={{ gap: "var(--space-3)" }}
        >
          <p
            className="font-mono uppercase tracking-widest text-secondary"
            style={{ fontSize: "var(--text-overline)" }}
          >
            Evaluation
          </p>
          <h1
            className="font-serif font-medium tracking-tight text-on-surface"
            style={{
              fontSize: "clamp(40px, 5.5vw, 64px)",
              lineHeight: 1.05,
              letterSpacing: "-0.02em",
              maxWidth: "20ch",
            }}
          >
            Live results on the{" "}
            <span className="text-secondary">83-question</span> bank.
          </h1>
          <p
            className="prose-body-muted"
            style={{ marginTop: "var(--space-2)" }}
          >
            Measured pass rate across the official Taxxa eval set. Hand-validated
            gold answers, reproducible from the agent sidecar.
          </p>
        </header>

        {/* ─── Stats ─── 3-up bento, simplified (no icons, baseline-aligned). */}
        <section className="grid grid-cols-1 overflow-hidden border border-outline-variant bg-outline-variant sm:grid-cols-3" style={{ gap: 1 }}>
          <StatCard label="Correctness" value="94.2" unit="%" sub="on 83-question bank" />
          <StatCard label="Citation Accuracy" value="98.7" unit="%" sub="claim ↔ source overlap" />
          <StatCard label="Latency P95" value="1.2" unit="s" sub="end-to-end SSE stream" />
        </section>

        {/* ─── Table ─── 56px rows, wider confidence column. */}
        <section style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
          <div className="flex items-end justify-between border-b border-outline-variant" style={{ paddingBottom: "var(--space-2)" }}>
            <h2
              className="font-serif font-medium text-on-surface"
              style={{ fontSize: "var(--text-h3)", lineHeight: 1.15 }}
            >
              Evaluated tax queries
            </h2>
            <span
              className="font-mono uppercase tracking-widest text-on-surface-variant"
              style={{ fontSize: "var(--text-overline)" }}
            >
              {ROWS.length} of 83 records
            </span>
          </div>

          <div className="w-full overflow-x-auto">
            <table className="w-full border-collapse text-left">
              <colgroup>
                <col style={{ width: 80 }} />
                <col style={{ width: 140 }} />
                <col />
                <col style={{ width: 80 }} />
                <col style={{ width: 200 }} />
              </colgroup>
              <thead>
                <tr>
                  {["ID", "TIER", "QUERY", "SOURCES", "CONFIDENCE"].map((h) => (
                    <th
                      key={h}
                      className="border-b border-outline-variant font-mono font-normal uppercase tracking-widest text-on-surface-variant"
                      style={{ fontSize: "var(--text-overline)", paddingInline: "var(--space-4)", paddingBlock: "var(--space-3)" }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ROWS.map((r) => (
                  <tr
                    key={r.id}
                    className="group border-b border-outline-variant transition-colors duration-150 hover:bg-surface-container-low/50"
                  >
                    <td
                      className="font-mono text-on-surface-variant"
                      style={{ fontSize: "var(--text-meta)", paddingInline: "var(--space-4)", paddingBlock: "var(--space-4)" }}
                    >
                      {r.id}
                    </td>
                    <td style={{ paddingInline: "var(--space-4)", paddingBlock: "var(--space-4)" }}>
                      <span
                        className={
                          "inline-flex items-center border border-outline-variant font-mono uppercase tracking-wider " +
                          TIER_TONE[r.tier]
                        }
                        style={{
                          height: 22,
                          paddingInline: "var(--space-2)",
                          fontSize: "var(--text-overline)",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {r.tier}
                      </span>
                    </td>
                    <td
                      className="text-on-surface"
                      style={{ fontSize: "var(--text-body-sm)", lineHeight: 1.5, paddingInline: "var(--space-4)", paddingBlock: "var(--space-4)" }}
                    >
                      {r.query}
                    </td>
                    <td
                      className="font-mono text-on-surface-variant"
                      style={{ fontSize: "var(--text-meta)", paddingInline: "var(--space-4)", paddingBlock: "var(--space-4)" }}
                    >
                      {r.sources}
                    </td>
                    <td style={{ paddingInline: "var(--space-4)", paddingBlock: "var(--space-4)" }}>
                      <div className="flex items-center" style={{ gap: "var(--space-3)" }}>
                        <div className="relative h-px shrink-0 bg-outline-variant" style={{ width: 120 }}>
                          <div
                            className="absolute left-0 top-0 h-px bg-secondary"
                            style={{ width: `${r.confidence * 100}%` }}
                          />
                        </div>
                        <span
                          className="font-mono text-on-surface-variant"
                          style={{ fontSize: "var(--text-overline)" }}
                        >
                          {r.confidence.toFixed(2)}
                        </span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div
            className="flex flex-wrap items-center justify-between"
            style={{ gap: "var(--space-3)", paddingTop: "var(--space-5)" }}
          >
            <p
              className="font-sans italic text-on-surface-variant"
              style={{ fontSize: "var(--text-meta)" }}
            >
              Showing 7 of 83. Run the full eval pass against the live sidecar to reproduce.
            </p>
            <div className="flex flex-wrap" style={{ gap: "var(--space-3)" }}>
              <Link href="/eval/audit" className="btn-secondary btn-sm">
                <span className="material-symbols-outlined" style={{ fontSize: "var(--icon-sm)" }}>
                  fact_check
                </span>
                Ingest audit
              </Link>
              <Link href="/ask" className="btn-primary btn-sm">
                Run live eval pass
                <span className="material-symbols-outlined" style={{ fontSize: "var(--icon-sm)" }}>
                  arrow_forward
                </span>
              </Link>
            </div>
          </div>
        </section>
      </div>

      <Footer />
    </main>
  );
}

function StatCard({
  label,
  value,
  unit,
  sub,
}: {
  label: string;
  value: string;
  unit: string;
  sub?: string;
}) {
  return (
    <div
      className="flex flex-col bg-surface-container-lowest"
      style={{ padding: "var(--space-6)", gap: "var(--space-3)" }}
    >
      <span
        className="font-mono uppercase tracking-widest text-on-surface-variant"
        style={{ fontSize: "var(--text-overline)" }}
      >
        {label}
      </span>
      <div
        className="flex items-baseline font-serif font-medium text-on-surface"
        style={{
          gap: 6,
          fontSize: "clamp(40px, 4.8vw, 56px)",
          lineHeight: 1,
          letterSpacing: "-0.02em",
        }}
      >
        {value}
        <span
          className="font-mono text-on-surface-variant"
          style={{ fontSize: "var(--text-body-sm)", fontWeight: 400 }}
        >
          {unit}
        </span>
      </div>
      {sub && (
        <span
          className="font-sans italic text-on-surface-variant"
          style={{ fontSize: "var(--text-meta)" }}
        >
          {sub}
        </span>
      )}
    </div>
  );
}
