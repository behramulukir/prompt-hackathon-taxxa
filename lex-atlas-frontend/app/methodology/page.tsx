/**
 * /methodology — Stitch port. Tech deep-dive with column layout:
 * 3-col left "CHAPTER 0X" label + 9-col right content with `border-t`
 * thin dividers. Headlines in Garamond with italic second lines.
 */

import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";

interface AgentCard {
  number: string;
  title: string;
  body: string;
  trace: string;
}

const AGENTS: AgentCard[] = [
  {
    number: "AGENT.01",
    title: "Planner",
    body: "Deconstructs complex user queries into sequential, actionable execution steps before any retrieval occurs.",
    trace: "> INIT: Task_Decomposition",
  },
  {
    number: "AGENT.02",
    title: "Extractor",
    body: "Navigates the structured topology to surface highly relevant legal clauses and metadata based on the Planner's blueprint.",
    trace: "> EXEC: Semantic_Query",
  },
  {
    number: "AGENT.03",
    title: "Verifier",
    body: "An adversarial agent that cross-references extracted data against immutable source documents to ensure zero hallucination.",
    trace: "> AUDIT: Fact_Check_Strict",
  },
  {
    number: "AGENT.04",
    title: "Clarifier",
    body: "Synthesizes verified data into structured, authoritative responses formatted for legal comprehension and immediate utility.",
    trace: "> FORMAT: Legal_Brief",
  },
];

const GRAPHRAG_POINTS = [
  "Entity Resolution: disambiguating complex legal entities across jurisdictions.",
  "Semantic Pathfinding: tracing precedence through interconnected case law.",
  "Contextual Grounding: pinning generation strictly to verified nodes.",
  "Temporal Filtering: every Cypher walk filters on t_valid ≤ asof < t_invalid.",
];

const RESEARCH = [
  ["SAT-Graph RAG", "de Martim, JURIX 2025", "arXiv:2505.00039"],
  ["TG-RAG", "Han et al., 2025", "arXiv:2510.13590"],
  ["LRMoo v1.1.1", "IFLA, 2026", "cidoc-crm.org/LRMoo"],
  ["Semantic Finlex", "SeCo Aalto + MoJ", "data.finlex.fi/sparql"],
  ["Self-RAG", "Asai et al., 2024", "ICLR 2024 oral"],
  ["CRAG", "Yan et al., 2024", "arXiv:2401.15884"],
  ["HyDE", "Gao et al., 2022", "Precise Zero-Shot Dense Retrieval"],
  ["DSPy + MIPROv2", "Khattab et al., Stanford NLP", "dspy.ai"],
  ["Multi-Agent Debate", "Du et al., NeurIPS 2023", "arXiv:2305.14325"],
  ["AgenticSimLaw", "Jan 2026", "arXiv:2601.21936"],
  ["BGE-M3", "Chen et al., BAAI", "bge-model.com"],
  ["Anthropic Circuit Tracing", "Mar 2025", "transformer-circuits.pub"],
];

export default function MethodologyPage() {
  return (
    <main className="flex min-h-screen flex-col">
      <Header />

      <div
        className="mx-auto w-full max-w-6xl flex-grow px-6"
        style={{ paddingBlock: "var(--space-9)", display: "flex", flexDirection: "column", gap: "var(--space-9)" }}
      >
        {/* Hero - uses the same 2/10 grid as Chapter sections below so the
            small section label aligns with CHAPTER labels and the title +
            body sit in the same right-rail as the chapter content. */}
        <section className="grid grid-cols-1 md:grid-cols-12" style={{ gap: "var(--space-5)" }}>
          <div className="md:col-span-2">
            <p
              className="font-mono uppercase tracking-widest text-secondary"
              style={{ fontSize: "var(--text-overline)" }}
            >
              Architecture &amp; Methodology
            </p>
          </div>
          <div className="md:col-span-10">
            <h1
              className="font-serif font-medium text-primary"
              style={{
                marginBottom: "var(--space-5)",
                fontSize: "clamp(40px, 5.5vw, 72px)",
                lineHeight: 1.05,
                letterSpacing: "-0.02em",
              }}
            >
              Technical Rigor.
              <br />
              <span className="italic text-on-surface-variant">
                Transparent Execution.
              </span>
            </h1>
            <p className="prose-body-muted">
              Lex Atlas is built for absolute clarity. This document outlines
              the foundational pillars of our technical stack, designed for
              senior auditors and compliance professionals who require
              uncompromising reliability in data topology and agentic
              workflows.
            </p>
          </div>
        </section>

        {/* Chapter 01 — Second Brain */}
        <Chapter num="01" title="The Second Brain" italic="structured topology." insightMarker>
          <p className="mb-4">
            At the core of Lex Atlas lies a structured topology that acts as a
            secure, immutable "Second Brain." We eschew flat vector stores in
            favor of a multidimensional semantic network. Every piece of
            legislation, case law, and Vero guidance is mapped not just by
            keywords, but by ontological relationships grounded in the LRMoo /
            FRBR-extended schema published by IFLA and mirrored from Semantic
            Finlex's RDF endpoint.
          </p>
          <div
            className="border border-outline-variant bg-surface-container-lowest"
            style={{
              marginTop: "var(--space-6)",
              paddingInline: "var(--space-6)",
              paddingBlock: "var(--space-5)",
            }}
          >
            <div
              className="flex items-center justify-between border-b border-outline-variant"
              style={{
                marginBottom: "var(--space-5)",
                paddingBottom: "var(--space-3)",
              }}
            >
              <span
                className="font-mono uppercase tracking-widest text-on-surface"
                style={{ fontSize: "var(--text-overline)" }}
              >
                System Architecture
              </span>
              <span
                className="font-mono text-outline"
                style={{ fontSize: "var(--text-overline)" }}
              >
                v2.4.1
              </span>
            </div>
            <ArchSchema />
            <p
              className="font-mono italic text-on-surface-variant"
              style={{
                marginTop: "var(--space-5)",
                fontSize: "var(--text-overline)",
                lineHeight: 1.5,
              }}
            >
              Fig 1.1 · LRMoo-aligned node classes propagating CTV aggregation up the hierarchy.
            </p>
          </div>
        </Chapter>

        {/* Chapter 02 — From RAG to GraphRAG */}
        <Chapter num="02" title="From RAG to GraphRAG" italic="multi-hop reasoning over typed edges.">
          <p className="mb-4">
            Standard Retrieval-Augmented Generation is insufficient for complex
            legal queries that require multi-hop reasoning. We employ a typed
            graph traversal layered on top of BGE-M3 hybrid retrieval (dense +
            sparse + multi-vector) with Reciprocal Rank Fusion at k=60, then
            rerank with bge-reranker-v2-m3.
          </p>
          <ul className="mt-4 space-y-2 font-sans" style={{ fontSize: 16 }}>
            {GRAPHRAG_POINTS.map((p) => (
              <li key={p} className="flex items-start gap-2">
                <span
                  className="material-symbols-outlined text-secondary"
                  style={{ fontSize: 16, marginTop: 4 }}
                >
                  check_circle
                </span>
                <span>{p}</span>
              </li>
            ))}
          </ul>
        </Chapter>

        {/* Chapter 03 — Temporal logic */}
        <Chapter num="03" title="Temporal Logic" italic="every edge has a validity window.">
          <p className="mb-4">
            Every relationship in the graph carries a bitemporal{" "}
            <span className="font-mono text-sm text-secondary">(t_valid, t_invalid)</span>{" "}
            window. Drag the date slider in the workspace and the answer rewrites
            itself live, not via re-query but via a CSS-selector swap over the
            cached subgraph. The agent cannot accidentally answer a 2026
            question with a 2024 rule.
          </p>
          <p>
            Implementation: Neo4j 2026.01+ ships a <span className="font-mono text-sm">SEARCH</span>{" "}
            clause with in-index temporal filtering. The HNSW vector index
            behaves as if it only contained vectors valid at{" "}
            <span className="font-mono text-sm">$asof</span>, keeping latency
            sub-100ms even on a 250k-edge graph.
          </p>
        </Chapter>

        {/* Chapter 04 — The Debate */}
        <Chapter num="04" title="The Debate" italic="when sources disagree, make the argument visible." insightMarker>
          <p className="mb-4">
            Modeled on AgenticSimLaw (arXiv:2601.21936, Jan 2026): a courtroom-style
            7-turn protocol with explicit prosecutor / defense / judge roles. When
            our Verifier detects two equal-rank sources disagreeing (typically a
            Vero ohje vs a later KHO ruling), two Drafter agents read opposing
            sides of the priority lattice and stream their arguments side-by-side.
            A Judge resolves via the explicit lattice. Watching the AI argue
            with itself is the trust artifact.
          </p>
        </Chapter>

        {/* Chapter 05 — Agents */}
        <Chapter num="05" title="Where agents earn their keep" italic="specialised narrow-scope reasoning." insightMarker>
          <p
            className="mb-8 max-w-3xl text-on-background"
            style={{ fontSize: 18, lineHeight: 1.55 }}
          >
            Our system delegates tasks to specialised, narrow-scope AI agents.
            This separation of concerns ensures that reasoning, extraction, and
            verification are distinct processes, dramatically reducing
            hallucination rates and increasing auditability.
          </p>
          <div
            className="grid grid-cols-1 sm:grid-cols-2"
            style={{ gap: "var(--space-5)" }}
          >
            {AGENTS.map((a) => (
              <div
                key={a.number}
                className="group border border-outline-variant bg-surface-container-lowest transition-colors hover:bg-surface-container-low"
                style={{
                  paddingInline: "var(--space-6)",
                  paddingBlock: "var(--space-5)",
                }}
              >
                <div
                  className="flex items-baseline justify-between border-b border-outline-variant"
                  style={{
                    marginBottom: "var(--space-4)",
                    paddingBottom: "var(--space-3)",
                    gap: "var(--space-3)",
                  }}
                >
                  <span
                    className="font-serif text-primary"
                    style={{ fontSize: "var(--text-h4)", lineHeight: 1.2 }}
                  >
                    {a.title}
                  </span>
                  <span
                    className="font-mono text-outline transition-colors group-hover:text-secondary"
                    style={{ fontSize: "var(--text-overline)" }}
                  >
                    {a.number}
                  </span>
                </div>
                <p
                  className="text-on-surface-variant"
                  style={{
                    fontSize: "var(--text-body-sm)",
                    lineHeight: 1.6,
                    marginBottom: "var(--space-5)",
                    minHeight: "5em",
                  }}
                >
                  {a.body}
                </p>
                <div
                  className="border border-outline-variant bg-surface-container font-mono text-on-surface"
                  style={{
                    paddingInline: "var(--space-3)",
                    paddingBlock: "var(--space-2)",
                    fontSize: "var(--text-overline)",
                  }}
                >
                  {a.trace}
                </div>
              </div>
            ))}
          </div>
        </Chapter>

        {/* Chapter 06 — Citations and groundedness */}
        <Chapter num="06" title="Citations" italic="every claim has a node id and a URL.">
          <p className="mb-4">
            The Drafter cannot publish a sentence without a{" "}
            <span className="font-mono text-sm text-secondary">[cite:node:X]</span>{" "}
            token. The Verifier walks each cited claim back to its source text
            unit and rejects any sentence whose substring overlap with the cited
            HTML is below threshold. Refusal is engineered, not measured.
          </p>
          <p>
            Pattern lifted from Self-RAG (Asai et al., ICLR 2024 oral). Our
            prompt-engineered version of their trained reflection tokens.
            Combined with CRAG's retrieval evaluator (Yan et al., arXiv:2401.15884)
            which scores results as Correct / Incorrect / Ambiguous; on Ambiguous
            we fall back to live SPARQL against{" "}
            <span className="font-mono text-sm">data.finlex.fi/sparql</span> for
            government-grade ground truth.
          </p>
        </Chapter>

        {/* Chapter 07 — Cost */}
        <Chapter num="07" title="Cost economics" italic="same architecture, two regimes.">
          <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
            {[
              ["€0.005", "Local", "Gemma 3 27B on Ollama, electricity dominant."],
              ["€0.045", "Hosted", "Sonnet drafter on managed inference. 20× under cap."],
              ["€0.20", "Baseline", "Today's stuffed top-k RAG. We send less context."],
              ["€1.00", "Brief cap", "Lex Atlas lands 22–200× under it."],
            ].map(([n, label, body]) => (
              <div
                key={label}
                className="border border-outline-variant bg-surface-container-lowest p-5"
              >
                <div className="font-serif text-3xl font-medium text-primary">{n}</div>
                <div className="mt-1 font-mono text-xs uppercase tracking-wider text-on-surface-variant">
                  {label}
                </div>
                <p
                  className="mt-3 text-on-surface-variant"
                  style={{ fontSize: 14, lineHeight: 1.55 }}
                >
                  {body}
                </p>
              </div>
            ))}
          </div>
        </Chapter>

        {/* Research */}
        <section className="grid grid-cols-1 md:grid-cols-12" style={{ gap: "var(--space-5)" }}>
          <div className="md:col-span-2">
            <p
              className="font-mono uppercase tracking-widest text-on-surface-variant"
              style={{ fontSize: "var(--text-overline)" }}
            >
              References
            </p>
          </div>
          <div className="border-t border-outline-variant md:col-span-10" style={{ paddingTop: "var(--space-4)" }}>
            <h2
              className="font-serif font-medium text-primary"
              style={{
                maxWidth: "30ch",
                marginBottom: "var(--space-6)",
                fontSize: "clamp(28px, 3.2vw, 40px)",
                lineHeight: 1.12,
                letterSpacing: "-0.02em",
              }}
            >
              Everything we built on,{" "}
              <span className="italic text-on-surface-variant">cited in one place.</span>
            </h2>
            <ul
              className="grid grid-cols-1 sm:grid-cols-2"
              style={{ columnGap: "var(--space-7)", rowGap: "var(--space-5)" }}
            >
              {RESEARCH.map(([title, authors, ref]) => (
                <li
                  key={title}
                  className="flex flex-col border-l-2 border-outline-variant pl-3"
                  style={{ gap: 2 }}
                >
                  <span
                    className="font-sans font-medium text-on-surface"
                    style={{ fontSize: "var(--text-body)" }}
                  >
                    {title}
                  </span>
                  <span
                    className="font-sans text-on-surface-variant"
                    style={{ fontSize: "var(--text-body-sm)" }}
                  >
                    {authors}
                  </span>
                  <span
                    className="font-mono text-on-surface-variant"
                    style={{ fontSize: "var(--text-overline)" }}
                  >
                    {ref}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </section>
      </div>

      <Footer />
    </main>
  );
}

/* ───────────────────────────────────────────────────────────────────────── */

function Chapter({
  num,
  title,
  italic,
  children,
  insightMarker,
}: {
  num: string;
  title: string;
  italic: string;
  children: React.ReactNode;
  insightMarker?: boolean;
}) {
  return (
    <section className="relative grid grid-cols-1 md:grid-cols-12" style={{ gap: "var(--space-5)" }}>
      <div className="md:col-span-2">
        <div
          className="font-serif font-medium text-on-surface-variant/35"
          style={{
            fontSize: "clamp(48px, 4.6vw, 80px)",
            lineHeight: 1,
            letterSpacing: "-0.04em",
          }}
        >
          {num}
        </div>
      </div>
      <div
        className={
          "border-t border-outline-variant md:col-span-10 " +
          (insightMarker ? "insight-marker" : "")
        }
        style={{ paddingTop: "var(--space-4)" }}
      >
        <h2
          className="font-serif font-medium text-primary"
          style={{
            maxWidth: "30ch",
            marginBottom: "var(--space-5)",
            fontSize: "clamp(28px, 3.2vw, 40px)",
            lineHeight: 1.12,
            letterSpacing: "-0.02em",
          }}
        >
          {title}
          <span className="italic text-on-surface-variant">
            {" / "}
            {italic}
          </span>
        </h2>
        <div className="prose-body">{children}</div>
      </div>
    </section>
  );
}

/** Mini diagram of the LRMoo node classes used inside Chapter 01. */
function ArchSchema() {
  const NODES = [
    { kind: "Work", desc: "Statute as an abstract concept (AVL)" },
    { kind: "Expression", desc: "Versioned text at a date" },
    { kind: "Component", desc: "Section (§) as a concept" },
    { kind: "CTV", desc: "Component Temporal Version" },
    { kind: "Action", desc: "Amendment event (first-class)" },
    { kind: "Case", desc: "KHO / KKO ruling" },
    { kind: "Guidance", desc: "Vero ohje / kannanotto" },
    { kind: "Concept", desc: "Domain term (skos:Concept)" },
  ];
  return (
    <div
      className="grid grid-cols-2 sm:grid-cols-4"
      style={{ gap: 1, background: "var(--color-outline-variant)", border: "1px solid var(--color-outline-variant)" }}
    >
      {NODES.map((n) => (
        <div
          key={n.kind}
          className="bg-surface-container-lowest"
          style={{
            paddingInline: "var(--space-5)",
            paddingBlock: "var(--space-4)",
          }}
        >
          <div
            className="font-mono uppercase tracking-wider text-secondary"
            style={{ fontSize: "var(--text-overline)" }}
          >
            {n.kind}
          </div>
          <div
            className="text-on-surface-variant"
            style={{ marginTop: 6, fontSize: "var(--text-body-sm)", lineHeight: 1.5 }}
          >
            {n.desc}
          </div>
        </div>
      ))}
    </div>
  );
}
