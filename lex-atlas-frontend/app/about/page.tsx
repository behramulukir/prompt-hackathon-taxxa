/**
 * /about — what the shipping system actually does, with real numbers.
 *
 * Two halves:
 *  - "The corpus" — counts pulled from ``output/graph.db`` and
 *    ``output/lancedb`` at the time of the last full ingest.
 *    Mirror these constants when you re-ingest.
 *  - "The pipeline" — a Mermaid flowchart of the RAG + Graph layers,
 *    plus narrative for each stage. Intentionally describes only the
 *    data + retrieval flow; frontend / sidecar wiring lives elsewhere.
 */

import Link from "next/link";
import { Header } from "@/components/Header";
import { MermaidDiagram } from "@/components/MermaidDiagram";

// ---------------------------------------------------------------------------
// Snapshot numbers. Source-of-truth queries (run from project root):
//   sqlite3 output/graph.db 'SELECT type, COUNT(*) FROM nodes GROUP BY type'
//   sqlite3 output/graph.db 'SELECT type, COUNT(*) FROM edges GROUP BY type'
//   .venv/bin/python -c "import lancedb; t=lancedb.connect('output/lancedb').open_table('chunks'); print(t.count_rows())"
// ---------------------------------------------------------------------------

const NODE_BREAKDOWN: Array<{ kind: string; count: number; note: string }> = [
  { kind: "SUBSECTION",      count: 1_184_915, note: "momentit — atomic operative paragraphs" },
  { kind: "SECTION",         count:   344_156, note: "§ inside a law/asetus" },
  { kind: "ITEM",            count:   320_453, note: "list items inside subsections" },
  { kind: "LAW",             count:    54_678, note: "root acts (laki / asetus / SK)" },
  { kind: "CHAPTER",         count:    27_611, note: "luku inside a law" },
  { kind: "AMENDMENT_BLOCK", count:    14_145, note: "muutoslaki bodies" },
  { kind: "DEFINITION",      count:    12_835, note: "domain terms · linked via `defines`" },
  { kind: "CASE",            count:     7_040, note: "KHO / KKO precedents" },
  { kind: "GUIDE",           count:     1_826, note: "Vero ohje / kannanotto / päätös" },
  { kind: "TREATY",          count:       117, note: "tax treaties" },
];

const EDGE_BREAKDOWN: Array<{ kind: string; count: number; note: string }> = [
  { kind: "parent_of",      count: 1_904_115, note: "structural containment (law → section → subsection)" },
  { kind: "defines",        count:   234_570, note: "statute or section defines a domain term" },
  { kind: "amends",         count:    26_880, note: "amendment LAW → target LAW" },
  { kind: "amends_section", count:    24_036, note: "muutetaan / kumotaan / lisätään directives" },
  { kind: "applies",        count:    18_259, note: "KHO/KVL case applies a statutory provision" },
  { kind: "interprets",     count:    16_613, note: "Vero/KHO interpretation of a section" },
  { kind: "cites",          count:     7_164, note: "textual cross-reference (\"see §117\")" },
  { kind: "repeals",        count:       161, note: "amendment action repealing a section" },
];

const TOTAL_NODES = NODE_BREAKDOWN.reduce((s, n) => s + n.count, 0);
const TOTAL_EDGES = EDGE_BREAKDOWN.reduce((s, e) => s + e.count, 0);

const VECTOR_COUNT = 402_088;
const EMBED_DIM = 1024;
const EMBED_MODEL = "Voyage AI · voyage-3-large";
const LLM_MODEL = "DeepSeek V4 Pro · via Featherless";

// ---------------------------------------------------------------------------
// Mermaid source. Two subgraphs:
//   - Ingest: how the corpus becomes the typed graph + vector store.
//   - Retrieve: how one question becomes an answer.
// Intentionally omits the frontend / SSE plumbing — this is the
// pipeline, not the app shell.
// ---------------------------------------------------------------------------

const ARCH_MERMAID = `flowchart LR
    %% ---------- Ingest ----------
    subgraph Ingest [Ingest — build the graph]
        direction TB
        F[Finlex laki / asetus<br/>+ Säädöskokoelma] --> P{Parsers}
        V[Vero · ohje · kannanotto · päätös] --> P
        K[KHO / KVL rulings] --> P
        T[Tax treaties] --> P
        P --> N[Typed nodes<br/>LAW · SECTION · CHAPTER<br/>CASE · GUIDE · TREATY]
        P --> E[Typed edges<br/>parent_of · cites · amends<br/>interprets · applies · defines]
        N --> GS[(Graph store<br/>SQLite)]
        E --> GS
        N --> C[Chunker]
        C --> EM[voyage-3-large<br/>1024-dim]
        EM --> VS[(Vector store<br/>LanceDB)]
    end

    %% ---------- Retrieve ----------
    subgraph Retrieve [Retrieve — answer one question]
        direction TB
        Q[Question] --> QR[Query rewrite<br/>FI / EN synonyms]
        QR --> H[Hybrid search<br/>dense + BM25 RRF]
        VSr[(Vector store)] --> H
        H --> RR[Rerank<br/>cosine + authority<br/>+ recency + term]
        GSr[(Graph store)] --> RR
        RR --> AS[Assemble context<br/>render typed cross-refs<br/>between cited sections]
        AS --> GEN[LLM · grounded answer<br/>with cited section ids]
        GEN --> CF[Confidence grader<br/>high · medium · low]
        AS --> ORB[Provenance orbit<br/>sub-graph for the UI]
        GEN --> OUT([Answer<br/>+ citations + cost])
        CF --> OUT
        ORB --> OUT
    end

    %% Cross-links so the two halves read as one system.
    GS -.-> GSr
    VS -.-> VSr

    classDef store fill:#fff7eb,stroke:#944921,stroke-width:1.2px;
    classDef io fill:#fafafa,stroke:#1a1c1b,stroke-width:1.2px;
    class GS,VS,GSr,VSr store;
    class OUT io;
`;

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

function fmt(n: number): string {
  return n.toLocaleString("en-US");
}

export default function AboutPage() {
  return (
    <main className="flex min-h-screen flex-col">
      <Header />

      <div
        className="relative z-10 mx-auto w-full max-w-5xl px-6 py-14 lg:py-20"
        style={{ gap: "var(--space-8)" }}
      >
        {/* Hero */}
        <header className="mb-12">
          <p
            className="font-mono uppercase tracking-widest text-on-surface-variant"
            style={{ fontSize: "var(--text-overline)", marginBottom: 8 }}
          >
            About RAGTAG
          </p>
          <h1
            className="font-serif font-medium text-on-surface"
            style={{
              fontSize: "clamp(36px, 4.5vw, 60px)",
              lineHeight: 1.06,
              letterSpacing: "-0.02em",
              maxWidth: "20ch",
            }}
          >
            Retrieval Augmented{" "}
            <span className="italic text-on-surface-variant">
              Graph Tax Answer Generator.
            </span>
          </h1>
          <p
            className="mt-5 text-on-surface-variant"
            style={{
              fontSize: "var(--text-body-lg)",
              lineHeight: 1.55,
              maxWidth: "62ch",
            }}
          >
            RAGTAG answers Finnish tax-law questions by walking a typed legal
            graph instead of a flat vector index. Each statute, section,
            ruling, and Vero ohje becomes a node with bitemporal validity;
            amendments and interpretations become typed edges; retrieval
            uses both the graph topology and a Voyage embedding store, then
            grounds the answer in a DeepSeek call that cites the section
            ids it leaned on.
          </p>
        </header>

        {/* ─── The corpus ─────────────────────────────────────────── */}
        <section className="mb-14">
          <SectionTitle eyebrow="01 · Data" title="The corpus" />

          <div className="mt-6 grid grid-cols-1 sm:grid-cols-3" style={{ gap: "var(--space-4)" }}>
            <Stat
              big={fmt(TOTAL_NODES)}
              label="typed nodes"
              caption="10 node kinds, from LAW root down to ITEM leaves"
            />
            <Stat
              big={fmt(TOTAL_EDGES)}
              label="typed edges"
              caption="8 relation types, all bitemporal (t_valid / t_invalid)"
            />
            <Stat
              big={fmt(VECTOR_COUNT)}
              label="vector chunks"
              caption={`${EMBED_DIM}-dim dense embeddings via ${EMBED_MODEL}`}
            />
          </div>

          {/* Node breakdown */}
          <div className="mt-10">
            <SubTitle>Nodes — by type</SubTitle>
            <BreakdownTable rows={NODE_BREAKDOWN} total={TOTAL_NODES} />
          </div>

          {/* Edge breakdown */}
          <div className="mt-10">
            <SubTitle>Edges — by type</SubTitle>
            <BreakdownTable rows={EDGE_BREAKDOWN} total={TOTAL_EDGES} />
          </div>

          {/* Models */}
          <div className="mt-10 grid grid-cols-1 sm:grid-cols-2" style={{ gap: "var(--space-4)" }}>
            <ModelCard
              label="Embeddings"
              model={EMBED_MODEL}
              note={`${EMBED_DIM}-dim · cosine similarity · multilingual`}
            />
            <ModelCard
              label="Answer LLM"
              model={LLM_MODEL}
              note="grounded generation · cite-token output · confidence grader"
            />
          </div>
        </section>

        {/* ─── The pipeline ───────────────────────────────────────── */}
        <section className="mb-14">
          <SectionTitle eyebrow="02 · Architecture" title="The pipeline" />
          <p
            className="mt-4 text-on-surface-variant"
            style={{
              fontSize: "var(--text-body)",
              lineHeight: 1.6,
              maxWidth: "62ch",
            }}
          >
            Two halves. The left half runs once per corpus refresh and
            produces the graph + vector stores. The right half runs once per
            question and produces a grounded, cited answer.
          </p>

          <div className="mt-6">
            <MermaidDiagram
              code={ARCH_MERMAID}
              ariaLabel="RAGTAG architecture: ingest pipeline produces a typed graph store plus a vector store; retrieval combines hybrid search, graph-aware rerank, context assembly, and an LLM call that emits cited answers."
            />
          </div>

          <div className="mt-8 grid grid-cols-1 md:grid-cols-2" style={{ gap: "var(--space-5)" }}>
            <Step
              num="Ingest"
              title="Parse, type, embed"
              body="Finlex HTML, Vero ohje pages, KHO rulings, and treaties are parsed into typed nodes anchored to their source URL. Cross-references and amendment clauses become typed edges (cites / amends / interprets / applies / repeals / defines). Sections are also tokenised and embedded with voyage-3-large so retrieval has a hybrid lexical+semantic surface."
            />
            <Step
              num="Retrieve"
              title="Search, walk, rerank"
              body="The question is rewritten to surface Finnish equivalents, then a hybrid dense+BM25 search returns seed sections. Rerank blends cosine with authority rank, recency, term overlap, and a graded penalty pulled from the section's amendment history in the graph."
            />
            <Step
              num="Assemble"
              title="Context with typed edges"
              body="The top-N reranked chunks are rendered into a single prompt where every cross-reference between cited sections is surfaced verbatim — `Source 1 cites → Source 3`, `Source 5 interprets → Source 2`. The LLM treats the sources as a small graph, not a bag."
            />
            <Step
              num="Generate"
              title="Cite-token answer + grader"
              body="DeepSeek V4 Pro writes the answer with inline [Source N] cites, which the sidecar rewrites to clickable [cite:node:…] tokens. A second short LLM call grades confidence (high / medium / low); the UI surfaces an Ask-Specialist CTA when low."
            />
          </div>
        </section>

        {/* See also: methodology */}
        <section
          className="mt-12 border-t border-outline-variant pt-8"
          style={{ paddingBottom: "var(--space-7)" }}
        >
          <SubTitle>See also</SubTitle>
          <p
            className="mt-2 text-on-surface-variant"
            style={{ fontSize: "var(--text-body-sm)", lineHeight: 1.55, maxWidth: "62ch" }}
          >
            <Link
              href="/methodology"
              className="font-mono uppercase tracking-wider text-secondary hover:underline"
              style={{ fontSize: "var(--text-overline)" }}
            >
              Methodology →
            </Link>{" "}
            describes the richer LRMoo / SAT-Graph-style architecture we
            explored during the hackathon but did <strong>not</strong>{" "}
            ship. The system documented on this page is what actually
            backs <Link href="/ask" className="text-secondary hover:underline">/ask</Link>.
          </p>
        </section>
      </div>
    </main>
  );
}

/* ──────────────────────────────────────────────────────────────────── */
/* Small typography helpers                                            */
/* ──────────────────────────────────────────────────────────────────── */

function SectionTitle({ eyebrow, title }: { eyebrow: string; title: string }) {
  return (
    <div>
      <p
        className="font-mono uppercase tracking-widest text-on-surface-variant"
        style={{ fontSize: "var(--text-overline)", marginBottom: 4 }}
      >
        {eyebrow}
      </p>
      <h2
        className="font-serif font-medium text-on-surface"
        style={{ fontSize: "var(--text-h3)", lineHeight: 1.15 }}
      >
        {title}
      </h2>
    </div>
  );
}

function SubTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3
      className="font-mono uppercase tracking-widest text-on-surface-variant"
      style={{ fontSize: "var(--text-overline)", marginBottom: 12 }}
    >
      {children}
    </h3>
  );
}

function Stat({ big, label, caption }: { big: string; label: string; caption: string }) {
  return (
    <div
      className="border border-outline-variant bg-surface-container-lowest"
      style={{ padding: "var(--space-5)" }}
    >
      <div
        className="font-serif font-medium text-on-surface"
        style={{ fontSize: "clamp(28px, 3.5vw, 44px)", lineHeight: 1, letterSpacing: "-0.01em" }}
      >
        {big}
      </div>
      <div
        className="mt-1 font-mono uppercase tracking-wider text-secondary"
        style={{ fontSize: "var(--text-overline)" }}
      >
        {label}
      </div>
      <div
        className="mt-2 font-sans text-on-surface-variant"
        style={{ fontSize: "var(--text-body-sm)", lineHeight: 1.5 }}
      >
        {caption}
      </div>
    </div>
  );
}

function BreakdownTable({
  rows,
  total,
}: {
  rows: Array<{ kind: string; count: number; note: string }>;
  total: number;
}) {
  return (
    <ul className="divide-y divide-outline-variant border-y border-outline-variant">
      {rows.map((r) => {
        const pct = (r.count / total) * 100;
        return (
          <li
            key={r.kind}
            className="grid grid-cols-12 items-baseline px-3 py-2"
            style={{ gap: "var(--space-3)" }}
          >
            <span
              className="col-span-3 font-mono uppercase tracking-wider text-on-surface"
              style={{ fontSize: "var(--text-overline)" }}
            >
              {r.kind}
            </span>
            <span
              className="col-span-2 text-right font-mono text-on-surface"
              style={{ fontSize: "var(--text-body-sm)" }}
            >
              {fmt(r.count)}
            </span>
            <span
              className="col-span-1 text-right font-mono text-on-surface-variant"
              style={{ fontSize: "var(--text-meta)" }}
            >
              {pct < 0.05 ? "<0.1%" : `${pct.toFixed(1)}%`}
            </span>
            <span
              className="col-span-6 font-sans italic text-on-surface-variant"
              style={{ fontSize: "var(--text-body-sm)", lineHeight: 1.5 }}
            >
              {r.note}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function ModelCard({ label, model, note }: { label: string; model: string; note: string }) {
  return (
    <div
      className="border border-outline-variant bg-surface-container-lowest"
      style={{ padding: "var(--space-5)" }}
    >
      <div
        className="font-mono uppercase tracking-widest text-on-surface-variant"
        style={{ fontSize: "var(--text-overline)" }}
      >
        {label}
      </div>
      <div
        className="mt-1 font-serif font-medium text-on-surface"
        style={{ fontSize: "var(--text-h5)", lineHeight: 1.2 }}
      >
        {model}
      </div>
      <div
        className="mt-2 font-sans text-on-surface-variant"
        style={{ fontSize: "var(--text-body-sm)", lineHeight: 1.5 }}
      >
        {note}
      </div>
    </div>
  );
}

function Step({ num, title, body }: { num: string; title: string; body: string }) {
  return (
    <div
      className="border border-outline-variant bg-surface-container-lowest"
      style={{ padding: "var(--space-5)" }}
    >
      <div className="flex items-baseline gap-3">
        <span
          className="font-mono uppercase tracking-widest text-secondary"
          style={{ fontSize: "var(--text-overline)" }}
        >
          {num}
        </span>
        <span
          className="font-serif font-medium text-on-surface"
          style={{ fontSize: "var(--text-h5)", lineHeight: 1.2 }}
        >
          {title}
        </span>
      </div>
      <p
        className="mt-3 font-sans text-on-surface-variant"
        style={{ fontSize: "var(--text-body-sm)", lineHeight: 1.6 }}
      >
        {body}
      </p>
    </div>
  );
}
