/**
 * /methodology
 *
 * Two-part page anchored to Taxxa's 23.05 chat. Every claim cited to a
 * file path or a research paper. Audited for accuracy on 24.05 against
 * the actual repo.
 */

import { Header } from "@/components/Header";

/* ─────────────────────────────────────────────────────────────────
 * Data
 * ──────────────────────────────────────────────────────────────── */

interface ChatPoint {
  n: string;
  topic: string;
  quote: string;
}

const TEAM_CHAT: ChatPoint[] = [
  { n: "01", topic: "Pricing", quote: "€60 per user per month. Queries have to be cheap." },
  { n: "02", topic: "Corpus", quote: "Connect Finlex, Vero, case law. EU-lex out of scope." },
  { n: "03", topic: "Authority", quote: "Case laws refer to Finlex. Vero is just an interpreter. Case laws can overwrite Vero." },
  { n: "04", topic: "Retrieval", quote: "Can't bring 1,000 chunks per question. 25M-page DB." },
  { n: "05", topic: "Timeline", quote: "Active now, not then, not later." },
  { n: "06", topic: "Stack", quote: "Run RAG locally first. DeepSeek is good and cheap." },
  { n: "07", topic: "Extraction", quote: "Reference-extraction by regex / NLP is a good idea. We aren't doing it." },
];

interface ExploredCard {
  number: string;
  title: string;
  italic: string;
  body: string;
  sources: string[];
  killedBy: string[];
  cut: string;
}

const EXPLORED: ExploredCard[] = [
  {
    number: "01",
    title: "Bitemporal graph on Neo4j",
    italic: "every edge with its own validity window.",
    body: "Schema from SAT-Graph RAG (JURIX 2025). The whole ontology in a graph database.",
    sources: ["SAT-Graph RAG · arXiv:2505.00039", "LRMoo · IFLA"],
    killedBy: ["01"],
    cut: "Two days into the ontology, still zero answers. We kept the bitemporal idea and rebuilt it in SQLite as version_chain (see RAGTAG #08).",
  },
  {
    number: "02",
    title: "BGE-M3 hybrid retrieval",
    italic: "dense + sparse + ColBERT, fused at k=60.",
    body: "BAAI's multilingual model with three signal heads. RRF for fusion, HyDE for English to Finnish query expansion.",
    sources: ["BGE-M3 · BAAI", "ColBERT · SIGIR 2020", "RRF · SIGIR 2009", "HyDE · Gao et al. 2022"],
    killedBy: ["01"],
    cut: "Voyage voyage-3-large already ranked the right chunk in the top 30 on every eval question. Adding a second stack failed the cost test.",
  },
  {
    number: "03",
    title: "Courtroom-style debate",
    italic: "prosecutor, defense, judge.",
    body: "Three LLMs arguing per conflict, pattern from AgenticSimLaw.",
    sources: ["AgenticSimLaw · arXiv:2601.21936", "Multi-Agent Debate · NeurIPS 2023"],
    killedBy: ["03", "01"],
    cut: "Chat #03 handed us the rule directly. One integer compare resolves every conflict in our eval set; seven LLM turns cost real money.",
  },
  {
    number: "04",
    title: "63,660-node constellation",
    italic: "WebGL force layout of the whole corpus.",
    body: "Attribution view inspired by Anthropic Circuit Tracer.",
    sources: ["@cosmos.gl/graph", "Anthropic Circuit Tracing · 2025"],
    killedBy: ["04"],
    cut: "Judges need one answer's reasoning, not the corpus shape. The reasoning panel animates the 5 to 10 nodes that actually mattered.",
  },
  {
    number: "05",
    title: "Live SPARQL fallback",
    italic: "CRAG escalation into Semantic Finlex.",
    body: "Self-RAG reflection tokens to enforce citation coverage at draft time.",
    sources: ["CRAG · arXiv:2401.15884", "Self-RAG · ICLR 2024", "data.finlex.fi/sparql"],
    killedBy: ["01"],
    cut: "Cold SPARQL hit 9 seconds on the public endpoint. We can surface 'unsure' offline via AmendmentCaveat instead (RAGTAG #08).",
  },
  {
    number: "06",
    title: "EU-lex contradictions",
    italic: "primacy of EU law over national act.",
    body: "Ingest EUR-Lex directives, model a transposes edge, surface EU vs national conflicts.",
    sources: ["EUR-Lex · hierarchy of norms", "Lex superior · UN OLA"],
    killedBy: ["02"],
    cut: "Chat #02 declared this out of scope. Adding it later is not an architectural rewrite: the `transposes` edge type is already in the EdgeType enum, the authority-rank lattice extends to an EU tier with one number, and the strategy router treats it as another `cross_source` route. New corpus, not new infrastructure.",
  },
];

interface ShippedCard {
  number: string;
  title: string;
  italic: string;
  body: string;
  sources: string[];
  delivers: string[];
}

const SHIPPED: ShippedCard[] = [
  {
    number: "01",
    title: "Three deterministic extraction passes",
    italic: "structural, anchor, regex.",
    body: "Edges are emitted by three rule-based passes over HTML and the document tree: structural (parent_of from the heading hierarchy), anchor (cross-references inside an <a href> attribute), and regex (text citations like '§ 102 AVL', 'KHO 2025:46'). No model in the batch graph build.",
    sources: [
      "src/extraction/structural_edges.py",
      "src/extraction/anchor_edges.py",
      "src/extraction/citations_regex.py",
      "src/extraction/definition_edges.py",
    ],
    delivers: ["07"],
  },
  {
    number: "02",
    title: "Two SQLite tables plus a local LanceDB",
    italic: "nodes, edges, chunks. Joined by section_id.",
    body: "1,967,776 nodes and 2,180,769 typed edges live in two SQLite tables (nodes, edges). 402,088 embedded chunks live in LanceDB on the filesystem (no remote service). Everything joins on section_id with an O(1) lookup.",
    sources: [
      "scripts/load_graph.py (nodes, edges CREATE TABLE)",
      "findings/04a_index_sanity.md (402,088 chunks)",
      "findings/04b_load_report.md (1.97M nodes, 2.18M edges)",
      "src/indexing/vector_store.py (LanceDB)",
    ],
    delivers: ["01"],
  },
  {
    number: "03",
    title: "Section-anchored chunking",
    italic: "800 to 1,500 tokens, 2,000 hard max, never split mid-citation.",
    body: "The chunk unit is the SECTION (§). Children are greedily packed under their § head and never split across sentence, item, or citation boundaries. The result: every chunk carries its own legal anchor.",
    sources: ["pipeline/chunks.py"],
    delivers: ["04"],
  },
  {
    number: "04",
    title: "Multilingual embeddings via Voyage",
    italic: "voyage-3-large, 1,024-dim, asymmetric query / document.",
    body: "Hosted but cheap. Asymmetric (input_type='query' vs 'document') to avoid the quality cliff Voyage warns about. Same embedding space carries Finnish, Swedish, and English.",
    sources: ["src/indexing/voyage_client.py (MODEL = voyage-3-large)", "voyageai.com"],
    delivers: ["02"],
  },
  {
    number: "05",
    title: "Strategy router, six presets",
    italic: "case_law, recency, definition, cross_source, multi_hop, default.",
    body: "A keyword and regex classifier on the question text picks one ExpansionStrategy. Each preset sets seed depth, edge types, BFS direction, max hops, and per-edge degree caps. Default falls back to vector-only retrieval.",
    sources: ["src/retrieval/strategy.py"],
    delivers: ["04"],
  },
  {
    number: "06",
    title: "Bounded BFS with hub-skip",
    italic: "interprets_in > 30, cites_out > 15, parent_of_in > 50.",
    body: "Default max_hops = 1. Hub nodes (widely cited statutes) are not expanded through. Final candidate set is truncated to fit a 25k-token context.",
    sources: ["src/retrieval/graph_expand.py"],
    delivers: ["04"],
  },
  {
    number: "07",
    title: "Two reranking paths, one cross-encoder",
    italic: "v2 uses bge-reranker-v2-m3, v1 uses metadata signals.",
    body: "v2 runs BAAI/bge-reranker-v2-m3 (a multilingual cross-encoder) over 30 to 40 candidates and combines 0.6 cross-encoder + 0.3 cosine + 0.1 metadata. v1 (the default path in the API sidecar today) uses a metadata reranker: authority_rank, recency, term overlap.",
    sources: [
      "src/retrieval/cross_encoder_rerank.py (bge-reranker-v2-m3)",
      "src/retrieval/rerank.py (metadata reranker)",
    ],
    delivers: ["04"],
  },
  {
    number: "08",
    title: "Temporal correctness",
    italic: "version_chain, as_of, AmendmentCaveat. All deterministic.",
    body: "Every SECTION carries a chronological version_chain of muutetaan, kumotaan, lisätään steps. GraphStore.text_at(section_id, as_of) plays it forward. Every cited chunk on a stale ancestor emits an AmendmentCaveat (suspect, stale, repealed). A separate check_temporal_mismatches function compares the drafted answer against the section's chain via difflib; no LLM in this check.",
    sources: [
      "src/indexing/graph_store.py (text_at)",
      "src/models.py (VersionStep, AmendmentCaveat)",
      "src/agents/verifier.py (check_temporal_mismatches)",
      "src/retrieval/pipeline_v2.py (wires both)",
    ],
    delivers: ["05"],
  },
  {
    number: "09",
    title: "Authority is one integer",
    italic: "Finlex 100, Treaty 90, KHO 80, Vero 60.",
    body: "Ranks are assigned at ingestion from source / source_subcorpus and stored on every node. Conflict surfacing compares the integer; the team's lattice (Finlex over Vero, KHO can overwrite Vero) drops out of this directly.",
    sources: [
      "src/extraction/authority.py",
      "findings/03_authority_ranks.md",
      "Lex superior · UN OLA",
    ],
    delivers: ["03"],
  },
  {
    number: "10",
    title: "Generation via DeepSeek-V4-Flash",
    italic: "hosted on Featherless. Query-rewrite is cached.",
    body: "The drafter is deepseek-ai/DeepSeek-V4-Flash served via Featherless. Per-question query rewrites are cached in process, which lowers cost on repeated framings. Per-query answers are not cached today; a localStorage history in the Next.js UI lets the user recall past questions but does not skip the call.",
    sources: [
      "src/retrieval/generate.py (MODEL = deepseek-ai/DeepSeek-V4-Flash)",
      "src/retrieval/query_rewrite.py (in-process cache)",
      "Featherless · featherless.ai",
    ],
    delivers: ["06", "01"],
  },
];

interface Receipt {
  k: string;
  label: string;
  body: string;
}

const RECEIPTS: Receipt[] = [
  { k: "Q1", label: "Capital income > €30k", body: "Single cite, TVL § 124. No graph hop. The baseline case." },
  { k: "Q12", label: "Meal voucher VAT", body: "Three cites: KHO 2025:46, KVL:004/2024, Vero ohje. Two graph hops via cites and interprets." },
  { k: "Q41", label: "Avainhenkilö 48 vs 84 months", body: "Rank-100 Finlex statute outranks rank-60 Vero kannanotto. Verifier picks Finlex." },
  { k: "Cost", label: "Local · hosted · brief cap", body: "€0.005 local · €0.04 hosted · €1 brief cap. The cost meter UI is a char-count heuristic, not API billing." },
];

interface Lesson {
  k: string;
  title: string;
  body: string;
  source: string;
}

const LESSONS: Lesson[] = [
  {
    k: "01",
    title: "Mojibake recovered through the graph",
    body:
      "About 1.7% of chunks were double-encoded: the HTML sniffer mis-detected UTF-8 as Latin-1 and produced 'päätös → pรครคtรถs'-style chunks in LanceDB. We caught it by tracing RAG hits back to source files, fixed the parse layer to force UTF-8, and re-embedded the affected slice. The graph spine made the recovery surgical, not corpus-wide.",
    source: "scripts/reingest_corrupted_chunks.py · pipeline/html_utils.py",
  },
  {
    k: "02",
    title: "Not every tax question is in the law",
    body:
      "Eval question N49 asks about the account-number range commonly used for trade receivables and payables (myyntisaamiset / ostovelat) in the Finnish chart of accounts. Our system returned the correct legal answer (no universally binding range exists), which did not match the question-bank reference. The reference traces to KILA practice and platform-specific defaults, not Finlex. Honest UX would surface that the law is silent here and the convention lives elsewhere.",
    source: "eval/questions.json · question N49",
  },
];

const RESEARCH = [
  ["SAT-Graph RAG", "de Martim, JURIX 2025", "arXiv:2505.00039"],
  ["TG-RAG", "Han et al., 2025", "arXiv:2510.13590"],
  ["LRMoo v1.1.1", "IFLA, 2026", "cidoc-crm.org/LRMoo"],
  ["Semantic Finlex", "SeCo Aalto + MoJ", "data.finlex.fi/sparql"],
  ["Self-RAG", "Asai et al., 2024", "ICLR 2024"],
  ["CRAG", "Yan et al., 2024", "arXiv:2401.15884"],
  ["HyDE", "Gao et al., 2022", "Precise Zero-Shot Dense Retrieval"],
  ["AgenticSimLaw", "Jan 2026", "arXiv:2601.21936"],
  ["Multi-Agent Debate", "Du et al., NeurIPS 2023", "arXiv:2305.14325"],
  ["BGE-M3", "Chen et al., BAAI", "bge-model.com"],
  ["bge-reranker-v2-m3", "BAAI", "bge-model.com"],
  ["ColBERT", "Khattab + Zaharia", "SIGIR 2020"],
  ["RRF", "Cormack et al.", "SIGIR 2009"],
  ["Voyage voyage-3-large", "Voyage AI", "voyageai.com"],
  ["Anthropic Circuit Tracing", "Anthropic, 2025", "transformer-circuits.pub"],
  ["UN OLA · lex superior", "UN Office of Legal Affairs", "a_cn4_l682.pdf"],
];

/* ─────────────────────────────────────────────────────────────────
 * Page
 * ──────────────────────────────────────────────────────────────── */

export default function MethodologyPage() {
  return (
    <main className="flex min-h-screen flex-col">
      <Header />

      <div
        className="mx-auto w-full max-w-6xl flex-grow px-6"
        style={{ paddingBlock: "var(--space-8)", display: "flex", flexDirection: "column", gap: "var(--space-7)" }}
      >
        {/* Hero */}
        <section className="grid grid-cols-1 md:grid-cols-12" style={{ gap: "var(--space-5)" }}>
          <div className="md:col-span-2">
            <p
              className="font-mono uppercase tracking-widest text-secondary"
              style={{ fontSize: "var(--text-overline)" }}
            >
              Methodology
            </p>
          </div>
          <div className="md:col-span-10">
            <h1
              className="font-serif font-medium text-primary"
              style={{
                marginBottom: "var(--space-3)",
                fontSize: "clamp(36px, 5vw, 64px)",
                lineHeight: 1.05,
                letterSpacing: "-0.02em",
              }}
            >
              Built from a chat,{" "}
              <span className="italic text-on-surface-variant">line by line.</span>
            </h1>
            <p
              className="text-on-surface-variant"
              style={{ maxWidth: "62ch", fontSize: "var(--text-body-lg)" }}
            >
              <span className="font-mono text-secondary">RAGTAG</span>{" "}
              (Retrieval Augmented Graph Tax Answer Generator) takes a tax
              question, retrieves the relevant Finnish statutes, court
              rulings and Vero guidance, and answers with citations. Every
              decision below is tagged either to a paper or to a numbered
              point from Taxxa&rsquo;s team chat on 23.05. We will present
              the demo live.
            </p>
          </div>
        </section>

        {/* Chat */}
        <section className="grid grid-cols-1 md:grid-cols-12" style={{ gap: "var(--space-5)" }}>
          <div className="md:col-span-2">
            <p
              className="font-mono uppercase tracking-widest text-secondary"
              style={{ fontSize: "var(--text-overline)" }}
            >
              Chat · 23.05
            </p>
          </div>
          <div
            className="border-t-2 border-primary md:col-span-10"
            style={{ paddingTop: "var(--space-4)" }}
          >
            <ul
              className="grid grid-cols-1 sm:grid-cols-2"
              style={{ columnGap: "var(--space-5)", rowGap: "var(--space-3)" }}
            >
              {TEAM_CHAT.map((p) => (
                <li
                  key={p.n}
                  className="border border-outline-variant bg-surface-container-lowest"
                  style={{ paddingInline: "var(--space-3)", paddingBlock: "var(--space-3)" }}
                >
                  <div
                    className="flex items-baseline justify-between"
                    style={{ gap: "var(--space-3)", marginBottom: 4 }}
                  >
                    <span
                      className="font-mono uppercase tracking-widest text-on-surface"
                      style={{ fontSize: "var(--text-overline)" }}
                    >
                      {p.topic}
                    </span>
                    <span
                      className="font-mono text-secondary"
                      style={{ fontSize: "var(--text-overline)" }}
                    >
                      #{p.n}
                    </span>
                  </div>
                  <p
                    className="italic text-on-surface-variant"
                    style={{ fontSize: "var(--text-body)", lineHeight: 1.5 }}
                  >
                    &ldquo;{p.quote}&rdquo;
                  </p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* Part I */}
        <PartHeader part="Part I" title="What we tried." italic="And what chat point killed it." />
        {EXPLORED.map((c) => (
          <ExploredChapter key={c.number} card={c} />
        ))}

        {/* Part II */}
        <PartHeader
          part="Part II"
          title="RAGTAG."
          italic="Ten pieces. Each cites file paths or papers."
          insightMarker
        />
        {SHIPPED.map((c) => (
          <ShippedChapter key={c.number} card={c} />
        ))}

        {/* Receipts */}
        <section className="grid grid-cols-1 md:grid-cols-12" style={{ gap: "var(--space-5)" }}>
          <div className="md:col-span-2">
            <p
              className="font-mono uppercase tracking-widest text-secondary"
              style={{ fontSize: "var(--text-overline)" }}
            >
              Receipts
            </p>
          </div>
          <div
            className="md:col-span-10 grid grid-cols-1 sm:grid-cols-2 border-t border-outline-variant"
            style={{ paddingTop: "var(--space-4)", gap: "var(--space-3)" }}
          >
            {RECEIPTS.map((r) => (
              <div
                key={r.k}
                className="border border-outline-variant bg-surface-container-lowest"
                style={{ paddingInline: "var(--space-4)", paddingBlock: "var(--space-3)" }}
              >
                <div
                  className="font-serif text-primary"
                  style={{ fontSize: "var(--text-h4)", lineHeight: 1.1 }}
                >
                  {r.k}
                </div>
                <div
                  className="font-mono uppercase tracking-wider text-on-surface-variant"
                  style={{ marginTop: 4, fontSize: "var(--text-overline)" }}
                >
                  {r.label}
                </div>
                <p
                  className="text-on-surface"
                  style={{ marginTop: 6, fontSize: "var(--text-body-sm)", lineHeight: 1.55 }}
                >
                  {r.body}
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* Lessons from the corpus */}
        <section className="grid grid-cols-1 md:grid-cols-12" style={{ gap: "var(--space-5)" }}>
          <div className="md:col-span-2">
            <p
              className="font-mono uppercase tracking-widest text-secondary"
              style={{ fontSize: "var(--text-overline)" }}
            >
              From the corpus
            </p>
            <p
              className="font-mono uppercase tracking-widest text-on-surface-variant"
              style={{ marginTop: 6, fontSize: "var(--text-overline)" }}
            >
              two things we found
            </p>
          </div>
          <div
            className="md:col-span-10 grid grid-cols-1 sm:grid-cols-2 border-t border-outline-variant"
            style={{ paddingTop: "var(--space-4)", gap: "var(--space-3)" }}
          >
            {LESSONS.map((l) => (
              <div
                key={l.k}
                className="border border-outline-variant bg-surface-container-lowest"
                style={{ paddingInline: "var(--space-4)", paddingBlock: "var(--space-4)" }}
              >
                <h3
                  className="font-serif font-medium text-primary"
                  style={{ fontSize: "var(--text-h4)", lineHeight: 1.2 }}
                >
                  {l.title}
                </h3>
                <p
                  className="text-on-surface"
                  style={{
                    marginTop: 6,
                    fontSize: "var(--text-body-sm)",
                    lineHeight: 1.55,
                  }}
                >
                  {l.body}
                </p>
                <p
                  className="font-mono uppercase tracking-widest text-on-surface-variant"
                  style={{ marginTop: 10, fontSize: "var(--text-overline)" }}
                >
                  source · {l.source}
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* References */}
        <section className="grid grid-cols-1 md:grid-cols-12" style={{ gap: "var(--space-5)" }}>
          <div className="md:col-span-2">
            <p
              className="font-mono uppercase tracking-widest text-on-surface-variant"
              style={{ fontSize: "var(--text-overline)" }}
            >
              References
            </p>
          </div>
          <div
            className="border-t border-outline-variant md:col-span-10"
            style={{ paddingTop: "var(--space-4)" }}
          >
            <ul
              className="grid grid-cols-1 sm:grid-cols-2"
              style={{ columnGap: "var(--space-5)", rowGap: "var(--space-3)" }}
            >
              {RESEARCH.map(([title, authors, ref]) => (
                <li
                  key={title}
                  className="flex flex-col border-l-2 border-outline-variant pl-3"
                >
                  <span
                    className="font-sans font-medium text-on-surface"
                    style={{ fontSize: "var(--text-body-sm)" }}
                  >
                    {title}
                  </span>
                  <span
                    className="font-mono text-on-surface-variant"
                    style={{ fontSize: "var(--text-overline)" }}
                  >
                    {authors} · {ref}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* CTA */}
        <section className="grid grid-cols-1 md:grid-cols-12" style={{ gap: "var(--space-5)" }}>
          <div className="md:col-span-2" />
          <a
            href="https://ragtag-timeline.vercel.app"
            target="_blank"
            rel="noopener"
            className="md:col-span-10 group block border border-outline-variant bg-surface-container-lowest transition-colors hover:bg-surface-container-low"
            style={{ paddingInline: "var(--space-5)", paddingBlock: "var(--space-4)" }}
          >
            <p
              className="font-mono uppercase tracking-widest text-secondary"
              style={{ fontSize: "var(--text-overline)" }}
            >
              Timeline · phone-friendly
            </p>
            <p
              className="text-on-surface"
              style={{ marginTop: "var(--space-2)", fontSize: "var(--text-body)" }}
            >
              The same story as a two-minute scroll on your phone.{" "}
              <span className="font-mono text-secondary underline">
                ragtag-timeline.vercel.app
              </span>
            </p>
          </a>
        </section>
      </div>
    </main>
  );
}

/* ─────────────────────────────────────────────────────────────────
 * Primitives
 * ──────────────────────────────────────────────────────────────── */

function PartHeader({
  part,
  title,
  italic,
  insightMarker,
}: {
  part: string;
  title: React.ReactNode;
  italic: string;
  insightMarker?: boolean;
}) {
  return (
    <section className="grid grid-cols-1 md:grid-cols-12" style={{ gap: "var(--space-5)" }}>
      <div className="md:col-span-2">
        <p
          className="font-mono uppercase tracking-widest text-secondary"
          style={{ fontSize: "var(--text-overline)" }}
        >
          {part}
        </p>
      </div>
      <div
        className={
          "md:col-span-10 border-t-2 border-primary " +
          (insightMarker ? "insight-marker" : "")
        }
        style={{ paddingTop: "var(--space-3)" }}
      >
        <h2
          className="font-serif font-medium text-primary"
          style={{
            fontSize: "clamp(24px, 3vw, 36px)",
            lineHeight: 1.1,
            letterSpacing: "-0.02em",
          }}
        >
          {title}{" "}
          {italic ? (
            <span className="italic text-on-surface-variant">{italic}</span>
          ) : null}
        </h2>
      </div>
    </section>
  );
}

function SourceChips({ items }: { items: string[] }) {
  return (
    <ul
      className="flex flex-wrap"
      style={{ gap: "var(--space-2)", marginTop: "var(--space-3)" }}
    >
      {items.map((c) => (
        <li
          key={c}
          className="border border-outline-variant bg-surface-container-lowest font-mono uppercase tracking-wider text-on-surface-variant"
          style={{
            paddingInline: "var(--space-2)",
            paddingBlock: 2,
            fontSize: "var(--text-overline)",
            letterSpacing: "0.06em",
          }}
        >
          {c}
        </li>
      ))}
    </ul>
  );
}

function ChatTagRow({ tags, label }: { tags: string[]; label: string }) {
  return (
    <div
      className="flex flex-wrap items-center"
      style={{ gap: "var(--space-2)", marginTop: "var(--space-2)" }}
    >
      <span
        className="font-mono uppercase tracking-widest text-on-surface-variant"
        style={{ fontSize: "var(--text-overline)" }}
      >
        {label}
      </span>
      {tags.map((n) => (
        <span
          key={n}
          className="font-mono text-on-secondary bg-secondary"
          style={{
            paddingInline: 6,
            paddingBlock: 2,
            fontSize: "var(--text-overline)",
            letterSpacing: "0.08em",
          }}
        >
          #{n}
        </span>
      ))}
    </div>
  );
}

function ExploredChapter({ card }: { card: ExploredCard }) {
  return (
    <section className="grid grid-cols-1 md:grid-cols-12" style={{ gap: "var(--space-5)" }}>
      <div className="md:col-span-2">
        <div
          className="font-serif font-medium text-on-surface-variant/35"
          style={{
            fontSize: "clamp(32px, 3.4vw, 56px)",
            lineHeight: 1,
            letterSpacing: "-0.04em",
          }}
        >
          {card.number}
        </div>
      </div>
      <div
        className="border-t border-outline-variant md:col-span-10"
        style={{ paddingTop: "var(--space-3)" }}
      >
        <h3
          className="font-serif font-medium text-primary"
          style={{
            marginBottom: 6,
            fontSize: "clamp(20px, 2.4vw, 26px)",
            lineHeight: 1.15,
            letterSpacing: "-0.015em",
          }}
        >
          {card.title}{" "}
          <span className="italic text-on-surface-variant">{card.italic}</span>
        </h3>
        <p
          className="text-on-surface"
          style={{ maxWidth: "60ch", fontSize: "var(--text-body)", lineHeight: 1.5 }}
        >
          {card.body}
        </p>
        <SourceChips items={card.sources} />
        <ChatTagRow tags={card.killedBy} label="Killed by" />
        <p
          className="text-on-surface-variant"
          style={{
            marginTop: "var(--space-2)",
            maxWidth: "60ch",
            fontSize: "var(--text-body-sm)",
            lineHeight: 1.5,
          }}
        >
          {card.cut}
        </p>
      </div>
    </section>
  );
}

function ShippedChapter({ card }: { card: ShippedCard }) {
  return (
    <section className="grid grid-cols-1 md:grid-cols-12" style={{ gap: "var(--space-5)" }}>
      <div className="md:col-span-2">
        <div
          className="font-serif font-medium text-primary"
          style={{
            fontSize: "clamp(32px, 3.4vw, 56px)",
            lineHeight: 1,
            letterSpacing: "-0.04em",
          }}
        >
          {card.number}
        </div>
        <p
          className="font-mono uppercase tracking-widest text-secondary"
          style={{ marginTop: 6, fontSize: "var(--text-overline)" }}
        >
          RAGTAG
        </p>
      </div>
      <div
        className="border-t border-outline-variant md:col-span-10"
        style={{ paddingTop: "var(--space-3)" }}
      >
        <h3
          className="font-serif font-medium text-primary"
          style={{
            marginBottom: 6,
            fontSize: "clamp(20px, 2.4vw, 26px)",
            lineHeight: 1.15,
            letterSpacing: "-0.015em",
          }}
        >
          {card.title}{" "}
          <span className="italic text-on-surface-variant">{card.italic}</span>
        </h3>
        <p
          className="text-on-surface"
          style={{ maxWidth: "60ch", fontSize: "var(--text-body)", lineHeight: 1.5 }}
        >
          {card.body}
        </p>
        <SourceChips items={card.sources} />
        <ChatTagRow tags={card.delivers} label="Answers" />
      </div>
    </section>
  );
}
