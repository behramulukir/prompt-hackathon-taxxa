/**
 * /methodology
 *
 *   1. Chat (the spine: 7 numbered quotes from 23.05).
 *   2. Part I: 6 things we tried, each tagged with the chat point that killed it.
 *   3. Part II: RAGTAG, 9 pieces, each tagged with the chat point it answers.
 *   4. Receipts (Q1, Q12, Q41, cost).
 *   5. References.
 *
 * Every card has at least one source chip.
 */

import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";

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
    body: "Schema lifted from SAT-Graph RAG (JURIX 2025).",
    sources: ["SAT-Graph RAG · arXiv:2505.00039", "LRMoo · IFLA"],
    killedBy: ["01"],
    cut: "Two days into the ontology, still zero answers.",
  },
  {
    number: "02",
    title: "BGE-M3 hybrid retrieval",
    italic: "dense + sparse + ColBERT, fused at k=60.",
    body: "Voyage voyage-3-large was already ranking the right chunk in the top 30.",
    sources: ["BGE-M3 · BAAI", "ColBERT · SIGIR 2020", "RRF · SIGIR 2009"],
    killedBy: ["01"],
    cut: "Second stack, no measurable lift.",
  },
  {
    number: "03",
    title: "Courtroom-style debate",
    italic: "prosecutor, defense, judge.",
    body: "Three LLMs arguing per conflict, pattern from AgenticSimLaw.",
    sources: ["AgenticSimLaw · arXiv:2601.21936", "Multi-Agent Debate · NeurIPS 2023"],
    killedBy: ["03", "01"],
    cut: "Chat #03 handed us the lattice. One integer compare resolves every conflict in our eval set.",
  },
  {
    number: "04",
    title: "63,660-node constellation map",
    italic: "WebGL force layout of the whole corpus.",
    body: "Attribution view modelled on Anthropic Circuit Tracer.",
    sources: ["@cosmos.gl/graph", "Anthropic Circuit Tracing · 2025"],
    killedBy: ["04"],
    cut: "Judges need one answer's reasoning, not the corpus shape.",
  },
  {
    number: "05",
    title: "Live SPARQL ground-truth fallback",
    italic: "CRAG escalation into Semantic Finlex.",
    body: "Self-RAG reflection tokens for citation overlap.",
    sources: ["CRAG · arXiv:2401.15884", "Self-RAG · ICLR 2024", "data.finlex.fi/sparql"],
    killedBy: ["01"],
    cut: "Cold SPARQL hit 9 seconds. Verifier + AmendmentCaveat covers 'unsure' offline.",
  },
  {
    number: "06",
    title: "EU-lex contradictions",
    italic: "primacy of EU law over national act.",
    body: "transposes edge type stays in the schema as a future hook.",
    sources: ["EUR-Lex · hierarchy of norms", "Lex superior · UN OLA"],
    killedBy: ["02"],
    cut: "Chat #02 declared this out of scope.",
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
    title: "Anchor, then regex, then LLM",
    italic: "~95% of edges from HTML anchors.",
    body: "Finlex publishes in Akoma Ntoso (OASIS legal XML). Regex catches plain references. LLM only for ambiguous citations.",
    sources: ["Akoma Ntoso · OASIS LegalDocML", "Finlex Akoma Ntoso · data.finlex.fi"],
    delivers: ["07"],
  },
  {
    number: "02",
    title: "Two files, one section_id",
    italic: "LanceDB for vectors, SQLite for the graph.",
    body: "No graph database server to operate.",
    sources: ["LanceDB · lancedb.com", "SQLite · sqlite.org"],
    delivers: ["01"],
  },
  {
    number: "03",
    title: "Strategy router, six presets",
    italic: "case_law, recency, definition, cross_source, multi_hop, default.",
    body: "Keyword + regex classifier picks an ExpansionStrategy per question. Routing pattern from CRAG.",
    sources: ["CRAG · arXiv:2401.15884"],
    delivers: ["04"],
  },
  {
    number: "04",
    title: "Bounded BFS with hub-skip",
    italic: "skip nodes above per-edge degree caps.",
    body: "Defaults: incoming interprets > 30, outgoing cites > 15, incoming parent_of > 50.",
    sources: ["BFS · standard CS", "src/retrieval/graph_expand.py"],
    delivers: ["04"],
  },
  {
    number: "05",
    title: "Cross-encoder rerank",
    italic: "BAAI/bge-reranker-v2-m3, multilingual.",
    body: "Final score: 0.6 cross-encoder + 0.3 cosine + 0.1 metadata. The biggest quality lever in v2.",
    sources: ["bge-reranker-v2-m3 · BAAI", "Sentence-BERT · EMNLP 2019"],
    delivers: ["04"],
  },
  {
    number: "06",
    title: "Four narrow agents",
    italic: "Planner, Extractor, Verifier, Clarifier.",
    body: "One agent per failure mode. Pattern from DSPy.",
    sources: ["DSPy · Stanford NLP"],
    delivers: ["01"],
  },
  {
    number: "07",
    title: "Temporal correctness",
    italic: "version_chain + as_of, in SQLite.",
    body: "Per-SECTION chain of muutetaan / kumotaan / lisätään steps. text_at(section_id, as_of) plays it forward.",
    sources: ["SAT-Graph RAG · arXiv:2505.00039", "Snodgrass, 1999"],
    delivers: ["05"],
  },
  {
    number: "08",
    title: "Authority is one integer",
    italic: "Finlex 100, KHO 85, Vero 50 to 60.",
    body: "Verifier compares ranks, picks higher, states the rule. Lattice direct from chat #03; doctrine is lex superior.",
    sources: ["Team chat #03", "Lex superior · UN OLA"],
    delivers: ["03"],
  },
  {
    number: "09",
    title: "DeepSeek-V4-Flash via Featherless",
    italic: "Gemma 3 27B local fallback on Ollama.",
    body: "Hosted ≈ €0.04 / query. Local ≈ €0.005 / query. Brief cap €1.",
    sources: ["DeepSeek", "Featherless", "Gemma 3", "Ollama"],
    delivers: ["06", "01"],
  },
];

interface Receipt {
  k: string;
  label: string;
  body: string;
}

const RECEIPTS: Receipt[] = [
  { k: "Q1", label: "Capital income > €30k", body: "Single cite, TVL § 124." },
  { k: "Q12", label: "Meal voucher VAT", body: "KHO 2025:46 → KVL:004/2024 → Vero ohje." },
  { k: "Q41", label: "Avainhenkilö, 48 vs 84 months", body: "Rank 100 over rank 55. Finlex wins." },
  { k: "Cost", label: "Local · hosted · cap", body: "€0.005 · €0.04 · €1 cap." },
];

const RESEARCH = [
  ["SAT-Graph RAG", "de Martim, JURIX 2025", "arXiv:2505.00039"],
  ["TG-RAG", "Han et al., 2025", "arXiv:2510.13590"],
  ["LRMoo v1.1.1", "IFLA, 2026", "cidoc-crm.org/LRMoo"],
  ["Semantic Finlex", "SeCo Aalto + MoJ", "data.finlex.fi/sparql"],
  ["Akoma Ntoso", "OASIS LegalDocML", "docs.oasis-open.org"],
  ["Self-RAG", "Asai et al., 2024", "ICLR 2024"],
  ["CRAG", "Yan et al., 2024", "arXiv:2401.15884"],
  ["DSPy", "Khattab et al., Stanford NLP", "dspy.ai"],
  ["AgenticSimLaw", "Jan 2026", "arXiv:2601.21936"],
  ["Multi-Agent Debate", "Du et al., NeurIPS 2023", "arXiv:2305.14325"],
  ["BGE-M3", "Chen et al., BAAI", "bge-model.com"],
  ["bge-reranker-v2-m3", "BAAI", "bge-model.com"],
  ["ColBERT", "Khattab + Zaharia", "SIGIR 2020"],
  ["RRF", "Cormack et al.", "SIGIR 2009"],
  ["Sentence-BERT", "Reimers + Gurevych", "EMNLP 2019"],
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
              style={{ maxWidth: "60ch", fontSize: "var(--text-body-lg)" }}
            >
              <span className="font-mono text-secondary">RAGTAG</span>{" "}
              (Retrieval Augmented Graph Tax Answer Generator) answers
              Finnish tax questions with full citations across Finlex,
              Vero, and KHO case law. Every choice below is tagged to
              either a paper or a numbered point from Taxxa&rsquo;s team
              chat. We will present the demo live.
            </p>
          </div>
        </section>

        {/* Chat — the spine */}
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
                    style={{ fontSize: "var(--text-body-sm)", lineHeight: 1.5 }}
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
          italic="Nine pieces. Each answers a chat point."
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
            className="md:col-span-10 grid grid-cols-2 sm:grid-cols-4 border-t border-outline-variant"
            style={{ paddingTop: "var(--space-4)", gap: "var(--space-3)" }}
          >
            {RECEIPTS.map((r) => (
              <div
                key={r.k}
                className="border border-outline-variant bg-surface-container-lowest"
                style={{ paddingInline: "var(--space-3)", paddingBlock: "var(--space-3)" }}
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
                  style={{ marginTop: 6, fontSize: "var(--text-body-sm)", lineHeight: 1.5 }}
                >
                  {r.body}
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

      <Footer />
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
