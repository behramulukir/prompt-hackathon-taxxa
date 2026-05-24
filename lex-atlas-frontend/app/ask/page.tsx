"use client";

/**
 * /ask — chat-style multi-turn workspace.
 *
 * The thread is the source of truth: each submit appends a `ChatTurn` and
 * mounts an <AnswerStream> for the latest one. Completed turns render via
 * <RenderedAnswer> — same cite anchors, no streaming UI. The history sent
 * to the sidecar on each follow-up is built from prior turns' question +
 * cite-stripped answer pairs.
 *
 * Layout
 *  - Empty state (no turns):  hero composer at top + demo prompts + history
 *  - Chat state (≥1 turn):    scrolling thread above, sticky composer at bottom
 *  - Side rail: orbit/timeline tracks the LATEST turn (resets on new turn)
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Header } from "@/components/Header";
import { AnswerStream, RenderedAnswer } from "@/components/AnswerStream";
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
import type { ChatMessage, ChatTurn } from "@/lib/types";

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

/** Strip the frontend's cite markup back to plain labels so the LLM doesn't
 *  see `[cite:node:X]Source 1[/cite]` noise in prior assistant turns.
 *  `[cite:node:X]Source 1[/cite]` → `Source 1`. */
function stripCiteTokens(s: string): string {
  return s.replace(/\[cite:node:[^\]]+\]([^[]*?)\[\/cite\]/g, "$1");
}

/** Flatten completed turns into the OpenAI-format history the sidecar wants.
 *  In-flight (un-done) turns are skipped — they have no committed answer. */
function buildHistory(turns: ChatTurn[]): ChatMessage[] {
  const out: ChatMessage[] = [];
  for (const t of turns) {
    if (!t.answer || !t.done) continue;
    out.push({ role: "user", content: t.question });
    out.push({ role: "assistant", content: stripCiteTokens(t.answer) });
  }
  return out;
}

export default function AskPage() {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [graphView, setGraphView] = useState<"graph" | "timeline">("graph");

  const asof = useGraphStore((s) => s.asof);
  const setAsof = useGraphStore((s) => s.setAsof);
  const orbitNodes = useGraphStore((s) => s.orbitNodes);
  const debateActive = useGraphStore((s) => s.debateActive);
  const reset = useGraphStore((s) => s.reset);
  const restoreFromCache = useGraphStore((s) => s.restoreFromCache);
  const setSelectedNodeId = useGraphStore((s) => s.setSelectedNodeId);
  const setSelectedEdgeKey = useGraphStore((s) => s.setSelectedEdgeKey);
  const phase = useGraphStore((s) => s.phase);
  const walkedCount = useGraphStore((s) => s.walkedCount);

  // Zustand store outlives route changes; the local `turns` does not. Without
  // this, navigating away (e.g. via the header title) and back leaves the
  // previous turn's orbit hanging in the right rail with no thread to anchor it.
  useEffect(() => {
    reset();
  }, [reset]);

  // Latest turn — the one currently streaming (or last completed).
  const activeTurn = turns.length > 0 ? turns[turns.length - 1] : null;
  const isStreaming = activeTurn ? !activeTurn.done : false;

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
      // Reset the global orbit so the new turn's SSE stream populates fresh.
      // Previous turns lose their orbit visualization but keep their answer
      // text in the thread — acceptable tradeoff for v1; a richer version
      // would snapshot the orbit into each ChatTurn and swap on click.
      reset();
      if (opts?.asof) setAsof(opts.asof);

      setTurns((prev) => {
        const history = buildHistory(prev);
        const newTurn: ChatTurn = {
          id: genQueryId(),
          question: q,
          asof: opts?.asof ?? asof,
          lang: "en",
          mode: "ask",
          timestamp: nowHHMM(),
          history,
        };
        return [...prev, newTurn];
      });
      setQuestion("");
    },
    [question, reset, setAsof, asof]
  );

  /* Recall a saved query: starts a NEW conversation with the recalled
     question as turn 1. Carries asof forward.
     Two paths:
       1. The entry has a cached snapshot — push a pre-completed turn so
          `isActive=false` and the renderer uses <RenderedAnswer> instead
          of <AnswerStream>. Restore the orbit via `restoreFromCache`.
          No /api/ask call, no re-billing.
       2. No snapshot (legacy entry) — fall back to a live submit. */
  const recall = useCallback(
    (entry: HistoryEntry) => {
      setQuestion("");
      reset();
      if (typeof window !== "undefined") {
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
      if (entry.cached) {
        // Cache-replay path: hydrate the orbit + push a done turn.
        setAsof(entry.asof);
        restoreFromCache({
          orbitNodes: entry.cached.orbitNodes,
          orbitEdges: entry.cached.orbitEdges,
          conflictPairs: entry.cached.conflictPairs,
          debate: entry.cached.debate,
          costCents: entry.costCents,
          confidence: entry.cached.confidence ?? null,
        });
        setTurns([
          {
            id: entry.id,
            question: entry.question,
            asof: entry.asof,
            lang: "en",
            mode: "ask",
            timestamp: nowHHMM(),
            history: [],
            answer: entry.cached.answer,
            done: true,
            costCents: entry.costCents,
            confidence: entry.cached.confidence,
          },
        ]);
        return;
      }
      // Legacy entry: re-run the pipeline.
      setTurns([]);
      setTimeout(() => submit(entry.question, { demo: entry.demo, asof: entry.asof }), 0);
    },
    [submit, reset, setAsof, restoreFromCache]
  );

  const newConversation = useCallback(() => {
    setTurns([]);
    setQuestion("");
    reset();
  }, [reset]);

  /* On `done`, freeze the streamed answer into the turn and re-push the
     conversation's history entry. The entry is keyed on turn-1's id, so
     every completion (turn 1, turn 2, ...) updates the same row.
     Cost is cumulative across all completed turns — a 2-turn chat that
     billed 0.22 ¢ then 0.22 ¢ surfaces 0.44 ¢ in history, not 0.22 ¢. */
  const handleTurnComplete = useCallback(
    (turnId: string) => (answer: string) => {
      const s = useGraphStore.getState();
      const cents = s.costCents;
      const hadDebate = s.debateActive;
      const confidence = s.confidence;
      setTurns((prev) => {
        const next = prev.map((t) =>
          t.id === turnId
            ? {
                ...t,
                answer,
                done: true,
                costCents: cents > 0 ? cents : undefined,
                confidence: confidence ?? undefined,
              }
            : t
        );
        const firstId = next[0]?.id;
        if (firstId) {
          // Sum costs across every completed turn in this conversation.
          // ``next`` already reflects the just-completed turn, so this
          // run includes it.
          const totalCents = next.reduce(
            (acc, t) => acc + (t.costCents ?? 0),
            0
          );
          pushHistory({
            id: firstId,
            question: next[0].question,
            asof: next[0].asof,
            demo: "custom",
            costCents: totalCents > 0 ? totalCents : undefined,
            hadDebate,
            cached: {
              answer,
              orbitNodes: s.orbitNodes,
              orbitEdges: s.orbitEdges,
              conflictPairs: s.conflictPairs,
              debate: s.debate,
              confidence: confidence ?? undefined,
            },
          });
        }
        return next;
      });
    },
    [pushHistory]
  );

  // Auto-scroll to the latest turn when it's added.
  const latestTurnId = activeTurn?.id ?? null;
  const threadEndRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!latestTurnId) return;
    threadEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [latestTurnId]);

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
      setTimeout(() => submit(auto), 0);
    }
    // Allow URL-driven Inspector preselect for screenshots / e2e.
    const inspect = params.get("inspect");
    if (inspect) {
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

  // Memoize the active-turn onComplete so AnswerStream's effect doesn't
  // re-fire when this page re-renders for unrelated reasons.
  const activeOnComplete = useMemo(
    () => (activeTurn ? handleTurnComplete(activeTurn.id) : undefined),
    [activeTurn, handleTurnComplete]
  );

  const isEmpty = turns.length === 0;

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
          {/* ─── Composer (HERO) ─── empty state only. */}
          {isEmpty && (
            <Composer
              question={question}
              setQuestion={setQuestion}
              onSubmit={() => submit()}
              asof={asof}
              variant="hero"
            />
          )}

          {/* ─── Demo prompts ─── empty state only. */}
          {isEmpty && (
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
                      <span
                        className="w-20 shrink-0 font-mono uppercase tracking-wider text-on-surface-variant"
                        style={{ fontSize: "var(--text-overline)" }}
                      >
                        {p.tag}
                      </span>
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
                Pick any prompt above or type your own. Each follow-up keeps the prior turns as context.
              </p>
            </section>
          )}

          {/* ─── Local query history (only if user has any) ─── */}
          {isEmpty && historyEntries.length > 0 && (
            <HistoryList
              entries={historyEntries}
              onRecall={recall}
              onRemove={removeHistory}
              onClear={clearHistory}
              variant="inline"
            />
          )}

          {/* ─── Chat thread ─── one card per turn. */}
          {!isEmpty && (
            <div className="flex flex-col" style={{ gap: "var(--space-8)" }}>
              {/* Thread header — turn count + actions. */}
              <div className="flex items-center justify-between">
                <span
                  className="font-mono uppercase tracking-wider text-on-surface-variant"
                  style={{ fontSize: "var(--text-overline)", letterSpacing: "0.08em" }}
                >
                  Conversation · {turns.length} {turns.length === 1 ? "turn" : "turns"}
                </span>
                <div className="flex items-center" style={{ gap: "var(--space-3)" }}>
                  <HistoryButton
                    entries={historyEntries}
                    onRecall={recall}
                    onRemove={removeHistory}
                    onClear={clearHistory}
                  />
                  <button
                    onClick={newConversation}
                    disabled={isStreaming}
                    className="btn-ghost btn-sm shrink-0"
                  >
                    <span
                      className="material-symbols-outlined"
                      style={{ fontSize: "var(--icon-sm)" }}
                    >
                      refresh
                    </span>
                    New conversation
                  </button>
                </div>
              </div>

              {turns.map((turn, i) => {
                const isLatest = i === turns.length - 1;
                const isActive = isLatest && !turn.done;
                return (
                  <TurnCard
                    key={turn.id}
                    turn={turn}
                    isActive={isActive}
                    instant={instant}
                    showDebatePanel={isActive}
                    onComplete={isActive ? activeOnComplete : undefined}
                  />
                );
              })}

              {/* Spacer so the sticky composer doesn't cover the latest turn. */}
              <div ref={threadEndRef} style={{ height: 96 }} aria-hidden />
            </div>
          )}
        </div>

        {/* ─── Side panel · Provenance Orbit ─── */}
        <aside className="w-full shrink-0 md:w-72 lg:w-80">
          {orbitNodes.length === 0 && (
            <div
              className="sticky top-24 border border-outline-variant bg-surface-container-lowest"
              style={{ padding: "var(--space-5)" }}
            >
              <div className="flex items-center" style={{ gap: "var(--space-2)" }}>
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
                  {phase === "idle" || phase === "done" ? "Orbit ready" : "Wiring subgraph"}
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
                    {phase === "starting" && "Waiting for the first agent event..."}
                    {phase === "planning" && "Planner extracting entities + sub-questions"}
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
                      : "Orbit tracks the latest turn. Hover for a peek -- click any node or edge to pin the full Inspector."}
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

      {/* ─── Sticky bottom composer ─── chat state only. Backdrop blur so
          the thread fades behind it instead of bleeding into the textarea. */}
      {!isEmpty && (
        <div
          className="sticky bottom-0 z-20 border-t border-outline-variant bg-surface/85 backdrop-blur supports-[backdrop-filter]:bg-surface/70"
          style={{ paddingBlock: "var(--space-4)" }}
        >
          <div className="mx-auto w-full max-w-6xl px-6">
            <div className="md:pr-80 lg:pr-[336px]">
              <Composer
                question={question}
                setQuestion={setQuestion}
                onSubmit={() => submit()}
                asof={asof}
                variant="sticky"
                disabled={isStreaming}
                disabledReason={
                  isStreaming
                    ? "Streaming — wait for the current answer to finish"
                    : undefined
                }
              />
            </div>
          </div>
        </div>
      )}

      <CitePopover />
      <Inspector />
    </main>
  );
}

/* ─────────────────────────────────────────────────────────────────────────
   Components
   ───────────────────────────────────────────────────────────────────────── */

/** Composer in two visual modes:
 *  - `hero`:    full three-strip card with meta pills (empty state)
 *  - `sticky`:  slim single-line textarea + Ask button (bottom of chat)
 */
function Composer({
  question,
  setQuestion,
  onSubmit,
  asof,
  variant,
  disabled,
  disabledReason,
}: {
  question: string;
  setQuestion: (v: string) => void;
  onSubmit: () => void;
  asof: string;
  variant: "hero" | "sticky";
  disabled?: boolean;
  disabledReason?: string;
}) {
  const placeholder =
    variant === "hero"
      ? "What is the withholding rate on key-personnel pay in 2026?"
      : "Ask a follow-up… (Cmd + Enter to send)";

  if (variant === "sticky") {
    return (
      <div className="border border-outline-variant bg-surface-container-lowest">
        <div
          className="flex items-end"
          style={{
            paddingInline: "var(--space-4)",
            paddingBlock: "var(--space-3)",
            gap: "var(--space-3)",
          }}
        >
          <textarea
            value={question}
            onChange={(e) => {
              setQuestion(e.target.value);
              const el = e.currentTarget;
              el.style.height = "auto";
              el.style.height = Math.min(el.scrollHeight, 200) + "px";
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) onSubmit();
            }}
            aria-label="Follow-up question"
            placeholder={placeholder}
            rows={1}
            disabled={disabled}
            style={{ minHeight: 44, lineHeight: 1.4, fontSize: 17 }}
            className="block w-full resize-none border-0 bg-transparent p-0 font-sans text-on-surface placeholder:text-on-surface-variant/60 focus:outline-none focus:ring-0 disabled:opacity-60"
          />
          <button
            onClick={onSubmit}
            disabled={disabled || !question.trim()}
            className="btn-primary btn-sm shrink-0"
            title={disabledReason}
          >
            {disabled ? "Streaming…" : "Ask"}
            {!disabled && (
              <span
                className="material-symbols-outlined"
                style={{ fontSize: "var(--icon-sm)" }}
              >
                send
              </span>
            )}
          </button>
        </div>
        <div
          className="flex items-center justify-between border-t border-outline-variant"
          style={{
            paddingInline: "var(--space-4)",
            paddingBlock: "var(--space-2)",
          }}
        >
          <span
            className="font-mono uppercase tracking-wider text-on-surface-variant"
            style={{ fontSize: "var(--text-overline)" }}
          >
            AS OF {asof.replace(/-/g, ".")} · context carries
          </span>
          <span
            className="hidden font-mono text-on-surface-variant sm:flex"
            style={{ fontSize: "var(--text-overline)" }}
          >
            <span
              className="material-symbols-outlined"
              style={{ fontSize: "var(--icon-xs)" }}
            >
              keyboard_command_key
            </span>
            + Enter
          </span>
        </div>
      </div>
    );
  }

  // hero variant
  return (
    <section className="border border-outline-variant bg-gradient-to-b from-surface-container-lowest to-surface-container-low/40">
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
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) onSubmit();
          }}
          aria-label="Question"
          placeholder={placeholder}
          rows={1}
          style={{ minHeight: 72, lineHeight: 1.35, fontSize: 26 }}
          className="block w-full resize-none border-0 bg-transparent p-0 font-serif text-on-surface placeholder:font-serif placeholder:font-normal placeholder:italic placeholder:text-on-surface-variant/55 focus:outline-none focus:ring-0"
        />
      </div>

      <div
        className="flex items-center justify-between border-t border-outline-variant"
        style={{ paddingInline: "var(--space-5)", paddingBlock: "var(--space-3)" }}
      >
        <span
          className="font-mono uppercase tracking-wider text-on-surface-variant"
          style={{ fontSize: "var(--text-overline)" }}
        >
          {question.trim() ? `${question.trim().length} chars` : "Cmd + Enter to ask"}
        </span>
        <button
          onClick={onSubmit}
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
  );
}

/** One turn in the conversation thread. Renders the user question header
 *  + a Synthesis card. The Synthesis card either streams (AnswerStream)
 *  or shows the frozen answer (RenderedAnswer). */
function TurnCard({
  turn,
  isActive,
  instant,
  showDebatePanel,
  onComplete,
}: {
  turn: ChatTurn;
  isActive: boolean;
  instant: boolean;
  showDebatePanel: boolean;
  onComplete?: (answer: string) => void;
}) {
  const phase = useGraphStore((s) => s.phase);
  const priorTurnCount = turn.history.length / 2; // history is user+assistant pairs

  return (
    <div className="flex flex-col" style={{ gap: "var(--space-5)" }}>
      {/* User question header */}
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
            {turn.question}
          </div>
          <div
            className="font-mono text-on-surface-variant"
            style={{
              marginTop: "var(--space-3)",
              fontSize: "var(--text-overline)",
              letterSpacing: "0.05em",
            }}
          >
            Q-ID: {turn.id} · {turn.timestamp}
            {priorTurnCount > 0 && (
              <span
                title="Prior turns sent to the model as conversation context"
                style={{ marginLeft: 8 }}
              >
                · with {priorTurnCount} prior{" "}
                {priorTurnCount === 1 ? "turn" : "turns"} as context
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Debate panel — only on the active turn (it consumes live SSE events). */}
      {showDebatePanel && <DebatePanel />}

      {/* Synthesis card */}
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
            <TurnStatus turn={turn} isActive={isActive} phase={phase} />
          </div>

          {/* Progressive loading indicator — only while the turn is active. */}
          {isActive && <AgentProgress />}

          <div
            className="space-y-4 text-on-surface"
            style={{ fontSize: 18, lineHeight: 1.65 }}
          >
            {isActive ? (
              <AnswerStream
                question={turn.question}
                asof={turn.asof}
                lang={turn.lang}
                mode={turn.mode}
                instant={instant}
                history={turn.history}
                onComplete={onComplete}
              />
            ) : turn.answer ? (
              <RenderedAnswer answer={turn.answer} />
            ) : (
              <p
                className="font-sans italic text-on-surface-variant"
                style={{ fontSize: "var(--text-body-sm)" }}
              >
                (no answer — stream was aborted)
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────
 * Synthesis card status: confidence pill + cost pill + (low-conf only)
 * an Ask-Specialist CTA. Read-paths split by active/inactive:
 *   - active turn:   pull from store (live SSE state)
 *   - inactive turn: pull from `turn.confidence` / `turn.costCents`
 * ─────────────────────────────────────────────────────────────────── */

function TurnStatus({
  turn,
  isActive,
  phase,
}: {
  turn: ChatTurn;
  isActive: boolean;
  phase: string;
}) {
  const liveConfidence = useGraphStore((s) => s.confidence);
  const liveCents = useGraphStore((s) => s.costCents);
  const [modalOpen, setModalOpen] = useState(false);

  const done = !isActive || phase === "done";
  if (!done) {
    return <span className="meta-pill ml-auto">Streaming…</span>;
  }

  const confidence = isActive ? liveConfidence : turn.confidence ?? null;
  const cents = isActive ? liveCents : turn.costCents ?? 0;

  return (
    <>
      <div className="ml-auto flex flex-wrap items-center gap-2">
        {confidence && <ConfidencePill level={confidence} />}
        {cents > 0 && (
          <span
            className="meta-pill"
            style={{
              color: "var(--color-secondary)",
              borderColor: "var(--color-secondary)",
            }}
            title="Estimated cost of the DeepSeek call for this query"
          >
            {formatCents(cents)}
          </span>
        )}
        {confidence === "low" && (
          <button
            type="button"
            onClick={() => setModalOpen(true)}
            className="flex items-center gap-1 border border-error/60 px-2 py-1 font-mono uppercase tracking-wider text-error transition-colors hover:bg-error-container/40"
            style={{ fontSize: "var(--text-overline)" }}
            title="The AI's confidence is low — escalate to a tax specialist"
          >
            <span className="material-symbols-outlined" style={{ fontSize: 14 }}>
              support_agent
            </span>
            Ask specialist
          </button>
        )}
      </div>
      {modalOpen && (
        <AskSpecialistModal
          turn={turn}
          onClose={() => setModalOpen(false)}
        />
      )}
    </>
  );
}

/* ─────────────────────────────────────────────────────────────────────
 * Confidence pill — color-coded by level. The high/medium/low strings
 * come straight from the LLM grader (see src/api/confidence.py).
 * ─────────────────────────────────────────────────────────────────── */

function ConfidencePill({ level }: { level: "high" | "medium" | "low" }) {
  // Re-use existing CSS color tokens so the pill matches the rest of
  // the design without inventing new colors:
  //   high   → secondary (terracotta) — same as the cost pill on done
  //   medium → on-surface-variant (neutral)
  //   low    → error (red)
  const palette = {
    high:   { color: "var(--color-secondary)",        border: "var(--color-secondary)" },
    medium: { color: "var(--color-on-surface-variant)", border: "var(--color-outline-variant)" },
    low:    { color: "var(--color-error)",            border: "var(--color-error)" },
  }[level];

  const tooltip = {
    high:   "The grader rated this answer well-supported and unambiguous.",
    medium: "Mostly supported, but with hedging or partial coverage.",
    low:    "The grader flagged this as unreliable — consider asking a specialist.",
  }[level];

  return (
    <span
      className="meta-pill"
      style={{ color: palette.color, borderColor: palette.border }}
      title={tooltip}
    >
      Confidence: {level.charAt(0).toUpperCase() + level.slice(1)}
    </span>
  );
}

/* ─────────────────────────────────────────────────────────────────────
 * Ask-Specialist modal — surfaces a copyable prewritten email so the
 * user can escalate the question to a Taxxa tax specialist with one
 * paste. Composed entirely client-side; no mailto: handler (would lose
 * the answer body in many clients).
 * ─────────────────────────────────────────────────────────────────── */

const SPECIALIST_EMAIL = "john.doe@taxxa.ai";

function AskSpecialistModal({
  turn,
  onClose,
}: {
  turn: ChatTurn;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState<"none" | "email" | "subject" | "body">("none");

  // Dismiss on Esc.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const subject = `Tax question (low-confidence AI answer): ${turn.question.slice(0, 60)}${turn.question.length > 60 ? "…" : ""}`;
  // Strip cite tokens from the answer so the email reads cleanly.
  const cleanAnswer = (turn.answer ?? "").replace(
    /\[cite:node:[^\]]+\]([^[]*?)\[\/cite\]/g,
    "$1"
  );
  const body =
    `Hi,\n\n` +
    `Our AI tax assistant produced a draft answer to the question below but ` +
    `graded its own confidence as LOW. Could you review and provide ` +
    `definitive guidance?\n\n` +
    `--- QUESTION ---\n${turn.question}\n\n` +
    (cleanAnswer
      ? `--- AI DRAFT (low confidence) ---\n${cleanAnswer}\n\n`
      : ``) +
    `Asof: ${turn.asof}\n` +
    `RAGTAG Q-ID: ${turn.id}\n\n` +
    `Best regards`;

  const copy = (text: string, kind: "email" | "subject" | "body") => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(text).then(() => {
        setCopied(kind);
        setTimeout(() => setCopied("none"), 1500);
      }).catch(() => {/* clipboard blocked — caller can still select manually */});
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="ask-specialist-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl border border-outline-variant bg-surface-container-lowest shadow-[0_24px_64px_rgba(0,0,0,0.18)]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-outline-variant px-5 py-3">
          <h2
            id="ask-specialist-title"
            className="flex items-center gap-2 font-serif font-medium text-on-surface"
            style={{ fontSize: "var(--text-h4)" }}
          >
            <span className="material-symbols-outlined text-error" style={{ fontSize: 22 }}>
              support_agent
            </span>
            Ask a Taxxa specialist
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center border border-outline-variant transition-colors hover:bg-surface-container"
            aria-label="Close"
          >
            <span className="material-symbols-outlined" style={{ fontSize: 16 }}>close</span>
          </button>
        </div>

        {/* Body */}
        <div className="space-y-4 px-5 py-4">
          <p
            className="font-sans text-on-surface-variant"
            style={{ fontSize: "var(--text-body-sm)", lineHeight: 1.55 }}
          >
            The AI graded its own confidence as <strong className="text-error">Low</strong>.
            Copy the draft email below into your mail client and send it for
            an expert review.
          </p>

          <CopyRow
            label="To"
            value={SPECIALIST_EMAIL}
            copied={copied === "email"}
            onCopy={() => copy(SPECIALIST_EMAIL, "email")}
          />
          <CopyRow
            label="Subject"
            value={subject}
            copied={copied === "subject"}
            onCopy={() => copy(subject, "subject")}
          />

          <div>
            <div className="mb-1 flex items-center justify-between">
              <span
                className="font-mono uppercase tracking-wider text-on-surface-variant"
                style={{ fontSize: "var(--text-overline)" }}
              >
                Body
              </span>
              <button
                type="button"
                onClick={() => copy(body, "body")}
                className="flex items-center gap-1 border border-outline-variant px-2 py-1 font-mono uppercase tracking-wider text-on-surface-variant transition-colors hover:bg-surface-container hover:text-on-surface"
                style={{ fontSize: "var(--text-overline)" }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: 14 }}>
                  {copied === "body" ? "check" : "content_copy"}
                </span>
                {copied === "body" ? "Copied" : "Copy"}
              </button>
            </div>
            <textarea
              readOnly
              value={body}
              className="w-full resize-none border border-outline-variant bg-surface-container-low p-3 font-mono text-on-surface focus:outline-none"
              style={{
                fontSize: "var(--text-body-sm)",
                lineHeight: 1.55,
                minHeight: 220,
              }}
              onFocus={(e) => e.currentTarget.select()}
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 border-t border-outline-variant px-5 py-3">
          <button
            type="button"
            onClick={() => copy(`${SPECIALIST_EMAIL}\n${subject}\n\n${body}`, "body")}
            className="btn-primary btn-sm"
          >
            <span className="material-symbols-outlined" style={{ fontSize: "var(--icon-sm)" }}>
              content_copy
            </span>
            Copy full email
          </button>
          <button
            type="button"
            onClick={onClose}
            className="flex items-center gap-2 border border-outline-variant px-3 py-1.5 font-mono text-xs uppercase tracking-wider text-on-surface-variant transition-colors hover:bg-surface-container hover:text-on-surface"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

function CopyRow({
  label,
  value,
  copied,
  onCopy,
}: {
  label: string;
  value: string;
  copied: boolean;
  onCopy: () => void;
}) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span
          className="font-mono uppercase tracking-wider text-on-surface-variant"
          style={{ fontSize: "var(--text-overline)" }}
        >
          {label}
        </span>
        <button
          type="button"
          onClick={onCopy}
          className="flex items-center gap-1 border border-outline-variant px-2 py-1 font-mono uppercase tracking-wider text-on-surface-variant transition-colors hover:bg-surface-container hover:text-on-surface"
          style={{ fontSize: "var(--text-overline)" }}
        >
          <span className="material-symbols-outlined" style={{ fontSize: 14 }}>
            {copied ? "check" : "content_copy"}
          </span>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <div
        className="break-all border border-outline-variant bg-surface-container-low px-3 py-2 font-mono text-on-surface"
        style={{ fontSize: "var(--text-body-sm)" }}
      >
        {value}
      </div>
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
