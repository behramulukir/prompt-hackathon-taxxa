"use client";

/**
 * /ask — workspace.
 *
 * Layout (fixed after audit screenshot):
 *  - Composer with right-aligned ASK button in a flex-end footer (was absolute,
 *    broke when the textarea wrapped past 2 lines).
 *  - Prompt picker grids 3-col at md+ (was sm, didn't fire at ~1024px because of
 *    the side rail's reserved width).
 *  - Side rail docks at md+ (was lg+, left a 320px hole at 1024–1279).
 *  - Side-rail content swaps automatically: empty-state → constellation backdrop
 *    → OrbitGraph once `subgraph_ready` fires.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";
import { AnswerStream } from "@/components/AnswerStream";
import { AgentProgress } from "@/components/AgentProgress";
import { CitePopover } from "@/components/CitePopover";
import { Inspector } from "@/components/Inspector";
import { DebatePanel } from "@/components/DebatePanel";
import { OrbitGraph } from "@/components/OrbitGraph";
import { LawTimeline } from "@/components/LawTimeline";
import { HistoryButton, HistoryList } from "@/components/HistoryList";
import { useGraphStore } from "@/lib/store";
import { useQueryHistory, type HistoryEntry } from "@/lib/history";
import { formatCents } from "@/lib/utils";

const PROMPTS = [
  {
    label: "Withholding · key-personnel",
    tag: "Q4 · basic",
    text:
      "What withholding rate applies to a foreign specialist on key-personnel status, and how long is the tax card valid?",
  },
  {
    label: "The Debate · KHO vs Vero",
    tag: "conflict",
    text:
      "Does the reverse-charge VAT regime apply to demolition contracts under AVL §8c when KHO has ruled on it?",
  },
  {
    label: "Triangular VAT",
    tag: "N1 · hard",
    text:
      "A Finnish company buys from a German supplier and ships direct to a Swedish customer. Does the triangular VAT simplification apply?",
  },
];

function genQueryId(): string {
  // 12 hex chars in three groups (XXXX-XXXX-XXXX). 16^12 ≈ 281 trillion
  // combos — collisions vanish in practice. Prefers ``crypto.randomUUID``
  // (CSPRNG) when available; falls back to ``Math.random`` for older
  // browsers / non-secure contexts.
  let hex: string;
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    hex = crypto.randomUUID().replace(/-/g, "").toUpperCase();
  } else {
    const chars = "0123456789ABCDEF";
    let s = "";
    for (let i = 0; i < 12; i++) s += chars[Math.floor(Math.random() * 16)];
    hex = s;
  }
  return `${hex.slice(0, 4)}-${hex.slice(4, 8)}-${hex.slice(8, 12)}`;
}

function nowHHMM(): string {
  const d = new Date();
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function AskPage() {
  const [question, setQuestion] = useState("");
  const [submitted, setSubmitted] = useState<string | null>(null);
  const [submittedDemo, setSubmittedDemo] = useState<HistoryEntry["demo"]>("custom");
  const [queryId, setQueryId] = useState<string>("");
  const [timestamp, setTimestamp] = useState<string>("");
  const [graphView, setGraphView] = useState<"graph" | "timeline">("graph");

  const asof = useGraphStore((s) => s.asof);
  const setAsof = useGraphStore((s) => s.setAsof);
  const orbitNodes = useGraphStore((s) => s.orbitNodes);
  const debateActive = useGraphStore((s) => s.debateActive);
  const reset = useGraphStore((s) => s.reset);
  const setSelectedNodeId = useGraphStore((s) => s.setSelectedNodeId);
  const setSelectedEdgeKey = useGraphStore((s) => s.setSelectedEdgeKey);
  const phase = useGraphStore((s) => s.phase);
  const walkedCount = useGraphStore((s) => s.walkedCount);

  /* Local query history (localStorage-backed; SSR-safe). Destructured so
     the push/remove/clear callbacks are stable references — otherwise the
     AnswerStream useEffect would see onComplete identity change every render
     of this page and re-fire the SSE fetch on every state update. */
  const {
    entries: historyEntries,
    push: pushHistory,
    remove: removeHistory,
    clear: clearHistory,
  } = useQueryHistory();

  const submit = useCallback(
    (override?: string, opts?: { demo?: HistoryEntry["demo"]; asof?: string }) => {
      const q = (override ?? question).trim();
      if (!q) return;
      reset();
      if (opts?.asof) setAsof(opts.asof);
      setQueryId(genQueryId());
      setTimestamp(nowHHMM());
      setSubmitted(q);
      setSubmittedDemo(opts?.demo ?? "custom");
    },
    [question, reset, setAsof]
  );

  /* Recall a saved query: set question + asof, then submit, then push to top. */
  const recall = useCallback(
    (entry: HistoryEntry) => {
      setQuestion(entry.question);
      submit(entry.question, { demo: entry.demo, asof: entry.asof });
      // Scroll the page back to the top so the freshly-submitted query is visible.
      if (typeof window !== "undefined") {
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
    },
    [submit]
  );

  /* Auto-save on `done`. We use a ref-relay so the callback identity stays
     stable across renders (AnswerStream lists onComplete in its SSE-effect
     deps; an unstable callback would re-trigger the fetch on every render). */
  const completeRef = useRef<() => void>(() => {});
  useEffect(() => {
    completeRef.current = () => {
      if (!submitted || !queryId) return;
      const s = useGraphStore.getState();
      pushHistory({
        id: queryId,
        question: submitted,
        asof,
        demo: submittedDemo,
        costCents: s.costCents > 0 ? s.costCents : undefined,
        hadDebate: s.debateActive,
      });
    };
  }, [submitted, queryId, asof, submittedDemo, pushHistory]);
  const handleAnswerComplete = useCallback(() => completeRef.current?.(), []);

  // URL-driven auto-submit: ?demo=q4|debate|n1 or ?q=<text>, with ?instant=1
  // to flush the SSE fixture without delays (used for screenshots/e2e).
  const ranAutoSubmit = useRef(false);
  const [instant, setInstant] = useState(false);
  useEffect(() => {
    if (ranAutoSubmit.current) return;
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const demo = params.get("demo");
    const q = params.get("q");
    if (params.get("instant") === "1") setInstant(true);
    const map: Record<string, string> = {
      q4: PROMPTS[0].text,
      debate: PROMPTS[1].text,
      n1: PROMPTS[2].text,
    };
    const auto = q?.trim() || (demo ? map[demo] : undefined);
    if (auto) {
      ranAutoSubmit.current = true;
      setQuestion(auto);
      const demoKey: HistoryEntry["demo"] =
        demo === "q4" || demo === "debate" || demo === "n1" ? demo : "custom";
      setTimeout(() => submit(auto, { demo: demoKey }), 0);
    }
    // Allow URL-driven Inspector preselect for screenshots / e2e:
    //   ?inspect=node:<id> opens the node inspector
    //   ?inspect=edge:<src>-><dst> opens the edge inspector
    const inspect = params.get("inspect");
    if (inspect) {
      // wait for subgraph_ready before flipping selection on
      const delay = params.get("instant") === "1" ? 200 : 3000;
      setTimeout(() => {
        if (inspect.startsWith("edge:")) {
          setSelectedEdgeKey(inspect.slice("edge:".length));
        } else if (inspect.startsWith("node:")) {
          setSelectedNodeId(inspect.slice("node:".length));
        } else {
          setSelectedNodeId(inspect);
        }
      }, delay);
    }
  }, [submit, setSelectedNodeId, setSelectedEdgeKey]);

  return (
    <main className="flex min-h-screen flex-col">
      <Header />

      <div
        className="relative z-10 mx-auto flex w-full max-w-6xl flex-1 flex-col px-6 py-14 md:flex-row lg:py-20"
        style={{ gap: "var(--space-8)" }}
      >
        {/* Main column */}
        <div
          className="flex min-w-0 flex-1 flex-col"
          style={{ gap: "var(--space-7)" }}
        >
          {/* ─── Composer ─── THE hero. Three hairline strips, gradient face. */}
          <section className="border border-outline-variant bg-gradient-to-b from-surface-container-lowest to-surface-container-low/40">
            {/* Meta strip */}
            <div
              className="flex items-center justify-between border-b border-outline-variant"
              style={{ paddingInline: "var(--space-5)", paddingBlock: "var(--space-2)" }}
            >
              <div className="flex flex-wrap items-center" style={{ gap: "var(--space-2)" }}>
                <span className="meta-pill">AS OF {asof.replace(/-/g, ".")}</span>
                <span className="meta-pill">EN-FI</span>
                <span
                  className="meta-pill"
                  style={{ color: "var(--color-secondary)", borderColor: "var(--color-secondary)" }}
                  title="1,967,776 nodes + 2,250,021 edges (96.9% resolved)"
                >
                  1.97M N · 2.25M E
                </span>
              </div>
              <div
                className="hidden items-center font-mono text-on-surface-variant sm:flex"
                style={{ gap: "var(--space-2)", fontSize: "var(--text-overline)" }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: "var(--icon-xs)" }}>
                  keyboard_command_key
                </span>
                + Enter
              </div>
            </div>

            {/* Query area - serif 26px, room to breathe (textarea min-h ~72px) */}
            <div style={{ paddingInline: "var(--space-6)", paddingBlock: "var(--space-6)" }}>
              <textarea
                value={question}
                onChange={(e) => {
                  setQuestion(e.target.value);
                  const el = e.currentTarget;
                  el.style.height = "auto";
                  el.style.height = Math.min(el.scrollHeight, 280) + "px";
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
                }}
                aria-label="Question"
                placeholder="What is the withholding rate on key-personnel pay in 2026?"
                rows={1}
                style={{ minHeight: 72, lineHeight: 1.35, fontSize: 26 }}
                className="block w-full resize-none border-0 bg-transparent p-0 font-serif text-on-surface placeholder:font-serif placeholder:font-normal placeholder:italic placeholder:text-on-surface-variant/55 focus:outline-none focus:ring-0"
              />
            </div>

            {/* Action strip */}
            <div
              className="flex items-center justify-between border-t border-outline-variant"
              style={{ paddingInline: "var(--space-5)", paddingBlock: "var(--space-3)" }}
            >
              <span
                className="font-mono uppercase tracking-wider text-on-surface-variant"
                style={{ fontSize: "var(--text-overline)" }}
              >
                {question.trim()
                  ? `${question.trim().length} chars`
                  : "Cmd + Enter to ask"}
              </span>
              <button
                onClick={() => submit()}
                disabled={!question.trim()}
                className="btn-primary btn-sm shrink-0"
              >
                Ask
                <span className="material-symbols-outlined" style={{ fontSize: "var(--icon-sm)" }}>
                  send
                </span>
              </button>
            </div>
          </section>

          {/* ─── Demo prompts ─── 3-col grid, no centered-text perception. */}
          {!submitted && (
            <section style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
              <div className="flex items-center justify-between">
                <p
                  className="font-mono uppercase tracking-widest text-on-surface-variant"
                  style={{ fontSize: "var(--text-overline)" }}
                >
                  Try a demo prompt
                </p>
                <p
                  className="font-mono uppercase tracking-wider text-on-surface-variant"
                  style={{ fontSize: "var(--text-meta)" }}
                >
                  {PROMPTS.length} reproducible
                </p>
              </div>
              <ul className="divide-y divide-outline-variant border-y border-outline-variant">
                {PROMPTS.map((p) => (
                  <li key={p.label}>
                    <button
                      onClick={() => setQuestion(p.text)}
                      className="group flex w-full items-center text-left transition-colors hover:bg-surface-container-low/60"
                      style={{
                        gap: "var(--space-5)",
                        paddingInline: "var(--space-2)",
                        paddingBlock: "var(--space-3)",
                      }}
                    >
                      {/* Tag chip - fixed 80px column on the left */}
                      <span
                        className="w-20 shrink-0 font-mono uppercase tracking-wider text-on-surface-variant"
                        style={{ fontSize: "var(--text-overline)" }}
                      >
                        {p.tag}
                      </span>

                      {/* Label and body on ONE line, separated by an em-dash.
                          Single-line + truncate kills the "centered label" perception. */}
                      <span
                        className="flex min-w-0 flex-1 items-baseline truncate"
                        style={{ gap: "var(--space-3)" }}
                      >
                        <span
                          className="shrink-0 font-sans font-semibold text-on-surface"
                          style={{ fontSize: "var(--text-body)" }}
                        >
                          {p.label}
                        </span>
                        <span
                          className="hidden text-on-surface-variant sm:inline"
                          style={{ fontSize: "var(--text-body)" }}
                        >
                          /
                        </span>
                        <span
                          className="min-w-0 flex-1 truncate font-sans text-on-surface-variant"
                          style={{ fontSize: "var(--text-body-sm)" }}
                        >
                          {p.text}
                        </span>
                      </span>

                      <span
                        className="material-symbols-outlined shrink-0 text-on-surface-variant transition-all group-hover:translate-x-0.5 group-hover:text-secondary"
                        style={{ fontSize: "var(--icon-md)" }}
                      >
                        arrow_forward
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
              <p
                className="font-sans italic text-on-surface-variant"
                style={{ fontSize: "var(--text-meta)" }}
              >
                Pick any prompt above or type your own. Answers stream live with inline citations.
              </p>
            </section>
          )}

          {/* ─── Local query history (only if user has any) ─── */}
          {!submitted && historyEntries.length > 0 && (
            <HistoryList
              entries={historyEntries}
              onRecall={recall}
              onRemove={removeHistory}
              onClear={clearHistory}
              variant="inline"
            />
          )}

          {/* Conversation flow */}
          {submitted && (
            <div className="flex flex-col" style={{ gap: "var(--space-7)" }}>
              {/* User query - avatar + heading + meta. More breathing room. */}
              <div
                className="flex items-start pl-4 md:pl-10"
                style={{ gap: "var(--space-4)" }}
              >
                <div
                  className="flex shrink-0 items-center justify-center border border-outline-variant bg-surface-variant"
                  style={{ width: 36, height: 36 }}
                >
                  <span
                    className="material-symbols-outlined text-on-surface-variant"
                    style={{ fontSize: "var(--icon-md)" }}
                  >
                    person
                  </span>
                </div>
                <div className="flex-1" style={{ paddingTop: 2 }}>
                  <div
                    className="font-serif leading-snug text-on-surface"
                    style={{ fontSize: 22, lineHeight: 1.3 }}
                  >
                    {submitted}
                  </div>
                  <div
                    className="font-mono text-on-surface-variant"
                    style={{
                      marginTop: "var(--space-3)",
                      fontSize: "var(--text-overline)",
                      letterSpacing: "0.05em",
                    }}
                  >
                    Q-ID: {queryId} · {timestamp}
                  </div>
                </div>
              </div>

              {/* Debate */}
              <DebatePanel />

              {/* Synthesis & Resolution */}
              <div className="pl-4 md:pl-10">
                <div
                  className="border border-outline-variant bg-surface-container-lowest"
                  style={{ paddingInline: "var(--space-6)", paddingBlock: "var(--space-6)" }}
                >
                  <div
                    className="flex flex-wrap items-center border-b border-outline-variant"
                    style={{
                      marginBottom: "var(--space-5)",
                      paddingBottom: "var(--space-4)",
                      gap: "var(--space-3)",
                    }}
                  >
                    <span
                      className="material-symbols-outlined text-secondary"
                      style={{ fontSize: "var(--icon-lg)" }}
                    >
                      verified
                    </span>
                    <span
                      className="font-serif font-semibold text-on-surface"
                      style={{ fontSize: "var(--text-h4)", lineHeight: 1.2 }}
                    >
                      Synthesis &amp; Resolution
                    </span>
                    {/* Status / cost pill — visible while streaming and
                        flips to the final cost once the agent emits ``done``.
                        Replaces the "Confidence: High" plank, which was a
                        canned claim the pipeline doesn't actually compute. */}
                    <AnswerStatusPill phase={phase} />
                  </div>

                  {/* Progressive loading indicator above the answer. */}
                  <AgentProgress />

                  <div
                    className="space-y-4 text-on-surface"
                    style={{ fontSize: 18, lineHeight: 1.65 }}
                  >
                    <AnswerStream
                      question={submitted}
                      asof={asof}
                      lang="en"
                      instant={instant}
                      onComplete={handleAnswerComplete}
                    />
                  </div>

                  {/* Action strip. Notes for future edits:
                      - ``overflow-x-auto`` is intentionally NOT used here. It
                        clips the History dropdown (which is absolute-
                        positioned), which is why History silently broke when
                        we previously had three buttons forcing horizontal
                        scroll. Stay on a single line.
                      - "Draft Memo" / "Share Citation" were stubbed-out
                        affordances; removed until they wire to real handlers.
                      - "New Query" is the primary action (most reached-for
                        button), so it's filled (btn-primary) and on the
                        left — first thing the eye lands on. */}
                  <div className="mt-6 flex flex-wrap items-center gap-3 border-t border-outline-variant pb-2 pt-4">
                    <button
                      onClick={() => {
                        setSubmitted(null);
                        setQuestion("");
                        reset();
                      }}
                      className="btn-primary btn-sm shrink-0"
                    >
                      <span className="material-symbols-outlined" style={{ fontSize: "var(--icon-sm)" }}>
                        refresh
                      </span>
                      New Query
                    </button>
                    <HistoryButton
                      entries={historyEntries}
                      onRecall={recall}
                      onRemove={removeHistory}
                      onClear={clearHistory}
                    />
                    {/* Cost readout — also surfaced as a pill at the top of
                        the card, but having it pinned to the action strip
                        makes the per-query economics visible after the
                        answer is read. */}
                    <AnswerCostReadout className="ml-auto" />
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* ─── Side panel · Provenance Orbit ─── slim when empty, full when populated. */}
        <aside className="w-full shrink-0 md:w-72 lg:w-80">
          {/* EMPTY or WIRING UP: hairline card. Switches copy based on phase. */}
          {orbitNodes.length === 0 && (
            <div
              className="sticky top-24 border border-outline-variant bg-surface-container-lowest"
              style={{ padding: "var(--space-5)" }}
            >
              <div
                className="flex items-center"
                style={{ gap: "var(--space-2)" }}
              >
                <span
                  className="material-symbols-outlined text-on-surface-variant"
                  style={{ fontSize: "var(--icon-sm)" }}
                >
                  account_tree
                </span>
                <h3
                  className="font-mono uppercase tracking-wider text-on-surface"
                  style={{ fontSize: "var(--text-overline)" }}
                >
                  {phase === "idle" || phase === "done"
                    ? "Orbit ready"
                    : "Wiring subgraph"}
                </h3>
              </div>

              {phase === "idle" || phase === "done" ? (
                <p
                  className="text-on-surface-variant"
                  style={{
                    marginTop: "var(--space-3)",
                    fontSize: "var(--text-body-sm)",
                    lineHeight: 1.55,
                  }}
                >
                  <span className="font-mono text-secondary">1,967,776</span>{" "}
                  nodes available. Pick a prompt and the subgraph wires up live.
                </p>
              ) : (
                <>
                  <p
                    className="text-on-surface-variant"
                    style={{
                      marginTop: "var(--space-3)",
                      fontSize: "var(--text-body-sm)",
                      lineHeight: 1.55,
                    }}
                  >
                    {phase === "starting" &&
                      "Waiting for the first agent event..."}
                    {phase === "planning" &&
                      "Planner extracting entities + sub-questions"}
                    {phase === "retrieving" && (
                      <>
                        Walking typed edges,{" "}
                        <span className="font-mono text-secondary">
                          {walkedCount}
                        </span>{" "}
                        nodes traversed
                      </>
                    )}
                    {(phase === "subgraph_ready" ||
                      phase === "debating" ||
                      phase === "drafting" ||
                      phase === "verifying") &&
                      "Subgraph ready, expanding panel..."}
                  </p>
                  {/* Inline skeleton bars to telegraph imminent content. */}
                  <div
                    style={{
                      marginTop: "var(--space-4)",
                      display: "flex",
                      flexDirection: "column",
                      gap: 6,
                    }}
                  >
                    <span className="lex-skeleton" style={{ height: 10, width: "85%" }} />
                    <span className="lex-skeleton" style={{ height: 10, width: "70%" }} />
                    <span className="lex-skeleton" style={{ height: 10, width: "55%" }} />
                  </div>
                </>
              )}

              <div
                className="border-t border-outline-variant"
                style={{
                  marginTop: "var(--space-5)",
                  paddingTop: "var(--space-4)",
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  rowGap: "var(--space-3)",
                  columnGap: "var(--space-5)",
                }}
              >
                <KindLegend kind="work" label="Statute" />
                <KindLegend kind="action" label="Amendment" />
                <KindLegend kind="case" label="KHO ruling" />
                <KindLegend kind="guidance" label="Vero ohje" />
              </div>
            </div>
          )}

          {/* POPULATED: full panel with graph/timeline toggle. */}
          {orbitNodes.length > 0 && (
            <div className="sticky top-24 border border-outline-variant bg-surface-container-lowest">
              <div
                className="flex items-center justify-between border-b border-outline-variant"
                style={{ paddingInline: "var(--space-4)", paddingBlock: "var(--space-3)" }}
              >
                <h3
                  className="flex items-center font-mono uppercase tracking-wider text-on-surface"
                  style={{ gap: "var(--space-2)", fontSize: "var(--text-overline)" }}
                >
                  <span
                    className="material-symbols-outlined"
                    style={{ fontSize: "var(--icon-sm)" }}
                  >
                    account_tree
                  </span>
                  Provenance Orbit
                </h3>
                <div className="flex border border-outline-variant" role="tablist">
                  <button
                    onClick={() => setGraphView("graph")}
                    role="tab"
                    aria-selected={graphView === "graph"}
                    className={
                      "font-mono uppercase tracking-wider transition-colors " +
                      (graphView === "graph"
                        ? "bg-primary text-on-primary"
                        : "text-on-surface-variant hover:bg-surface-container hover:text-on-surface")
                    }
                    style={{
                      paddingInline: 10,
                      paddingBlock: 4,
                      fontSize: "var(--text-overline)",
                    }}
                  >
                    Graph
                  </button>
                  <button
                    onClick={() => setGraphView("timeline")}
                    role="tab"
                    aria-selected={graphView === "timeline"}
                    className={
                      "border-l border-outline-variant font-mono uppercase tracking-wider transition-colors " +
                      (graphView === "timeline"
                        ? "bg-primary text-on-primary"
                        : "text-on-surface-variant hover:bg-surface-container hover:text-on-surface")
                    }
                    style={{
                      paddingInline: 10,
                      paddingBlock: 4,
                      fontSize: "var(--text-overline)",
                    }}
                  >
                    Timeline
                  </button>
                </div>
              </div>

              <div style={{ padding: "var(--space-4)" }}>
                {graphView === "graph" && <OrbitGraph />}
                {graphView === "timeline" && <LawTimeline />}

                <div
                  className="border-t border-outline-variant"
                  style={{ marginTop: "var(--space-4)", paddingTop: "var(--space-3)" }}
                >
                  <div
                    className="font-sans italic leading-snug text-on-surface-variant"
                    style={{ fontSize: "var(--text-meta)" }}
                  >
                    {debateActive
                      ? "Hierarchy: judicial precedent overrides administrative guidelines."
                      : "Hover for a peek -- click any node or edge to pin the full Inspector."}
                  </div>
                  <div
                    className="grid"
                    style={{
                      marginTop: "var(--space-3)",
                      gridTemplateColumns: "1fr 1fr",
                      rowGap: 6,
                      columnGap: "var(--space-3)",
                    }}
                  >
                    <KindLegend kind="work" label="Statute" />
                    <KindLegend kind="action" label="Amendment" />
                    <KindLegend kind="case" label="KHO ruling" />
                    <KindLegend kind="guidance" label="Vero ohje" />
                  </div>
                </div>
              </div>
            </div>
          )}
        </aside>
      </div>

      <CitePopover />
      <Inspector />
      <Footer />
    </main>
  );
}

/** Pill at the top-right of the synthesis card. While the agent is
 *  working, shows "Streaming…". On done, shows the cost. The previous
 *  copy ("Confidence: High") was a hard-coded claim the pipeline doesn't
 *  compute — replacing it with cost surfaces a real signal in the same
 *  visual slot. */
function AnswerStatusPill({ phase }: { phase: string }) {
  const cents = useGraphStore((s) => s.costCents);
  const done = phase === "done";
  if (!done) {
    return <span className="meta-pill ml-auto">Streaming…</span>;
  }
  return (
    <span
      className="meta-pill ml-auto"
      style={{
        color: "var(--color-secondary)",
        borderColor: "var(--color-secondary)",
      }}
      title="Estimated cost of the DeepSeek call for this query"
    >
      {cents > 0 ? formatCents(cents) : "Done"}
    </span>
  );
}

/** Cost label sitting in the action strip under the answer. Stays low-key
 *  until the agent finishes, then shows the final cents. Pinned to the
 *  right via ``ml-auto`` from the caller. */
function AnswerCostReadout({ className }: { className?: string }) {
  const cents = useGraphStore((s) => s.costCents);
  if (cents <= 0) return null;
  return (
    <div
      className={
        "flex items-baseline gap-2 font-mono text-on-surface-variant " +
        (className ?? "")
      }
      title="DeepSeek V4 Pro · estimated from input+output tokens, cache-miss price"
    >
      <span
        className="uppercase tracking-wider"
        style={{ fontSize: "var(--text-overline)" }}
      >
        cost
      </span>
      <span style={{ fontSize: "var(--text-body-sm)", color: "var(--color-on-surface)" }}>
        {formatCents(cents)}
      </span>
    </div>
  );
}

function KindLegend({ kind, label }: { kind: string; label: string }) {
  const COLORS: Record<string, string> = {
    work: "#1a1c1b",
    action: "#944921",
    case: "#9c2b5f",
    guidance: "#006b70",
  };
  return (
    <div className="flex items-center" style={{ gap: 10 }}>
      <span
        className="inline-block shrink-0"
        style={{
          width: 9,
          height: 9,
          borderRadius: "9999px",
          background: COLORS[kind],
          boxShadow: `0 0 0 1.5px ${COLORS[kind]}33`,
        }}
        aria-hidden
      />
      <span
        className="font-mono uppercase tracking-wider text-on-surface-variant"
        style={{ fontSize: "var(--text-overline)" }}
      >
        {label}
      </span>
    </div>
  );
}
