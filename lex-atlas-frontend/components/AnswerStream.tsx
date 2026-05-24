"use client";

/**
 * AnswerStream — consumes SSE events from /api/ask. Stitch-styled output
 * with terracotta highlights on color-coded cite anchors. Strips reflection
 * tokens. Hovering a sentence sets the orbit's hoveredNodeId.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useGraphStore } from "@/lib/store";
import { colorForKind } from "@/lib/colors";
import type { AgentEvent, ChatMessage, NodeKind } from "@/lib/types";

interface AnswerStreamProps {
  question: string;
  asof: string;
  lang: "fi" | "sv" | "en";
  mode?: "ask" | "draft_email" | "debate_only";
  /** Skip SSE timing delays — used by screenshot/e2e tests. */
  instant?: boolean;
  /** Prior turns as OpenAI-format messages. Empty/undefined on first turn. */
  history?: ChatMessage[];
  /** Replay an already-completed answer instead of hitting /api/ask.
   *  When set, the SSE fetch is skipped, ``rawAnswer`` is hydrated from
   *  this string, phase flips to "done", and ``onComplete`` fires once
   *  on mount. Used by the history-recall flow so users don't re-pay
   *  for an answer they already have. */
  cachedAnswer?: string;
  /** Fires once on `done`. Receives the final streamed answer (with cite
   *  tokens intact) so the parent can freeze it into the chat thread. */
  onComplete?: (answer: string) => void;
}

const REFLECTION_TOKEN_RE = /\[(?:IsRel|IsSup|IsUse):[^\]]+\]/g;
const CITE_TOKEN_RE = /\[cite:node:([^\]]+)\]([^[]*?)\[\/cite\]/g;

export function AnswerStream({ question, asof, lang, mode = "ask", instant = false, history, cachedAnswer, onComplete }: AnswerStreamProps) {
  const [rawAnswer, setRawAnswer] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const setHoveredNodeId = useGraphStore((s) => s.setHoveredNodeId);
  const setHoverAnchor = useGraphStore((s) => s.setHoverAnchor);
  const setSelectedNodeId = useGraphStore((s) => s.setSelectedNodeId);
  const pushHighlightedNode = useGraphStore((s) => s.pushHighlightedNode);
  const setOrbit = useGraphStore((s) => s.setOrbit);
  const mergeOrbitNodeKinds = useGraphStore((s) => s.mergeOrbitNodeKinds);
  const setDimmed = useGraphStore((s) => s.setDimmed);
  const setCenterNodeId = useGraphStore((s) => s.setCenterNodeId);
  const setConflictPairs = useGraphStore((s) => s.setConflictPairs);
  const setDebate = useGraphStore((s) => s.setDebate);
  const setDebateActive = useGraphStore((s) => s.setDebateActive);
  const appendDebateMessage = useGraphStore((s) => s.appendDebateMessage);
  const clearDebateMessages = useGraphStore((s) => s.clearDebateMessages);
  const setCostCents = useGraphStore((s) => s.setCostCents);
  const setConfidence = useGraphStore((s) => s.setConfidence);
  const nodeKind = useGraphStore((s) => s.nodeKind);
  const phase = useGraphStore((s) => s.phase);
  const setPhase = useGraphStore((s) => s.setPhase);
  const incWalked = useGraphStore((s) => s.incWalked);
  const setPlanCounts = useGraphStore((s) => s.setPlanCounts);
  const addDraftChars = useGraphStore((s) => s.addDraftChars);

  useEffect(() => {
    if (!question) return;

    // Cache-replay path: a HistoryRecall flow supplied the final answer
    // text. Hydrate the renderer with it, mark phase=done, and fire
    // onComplete on mount. We deliberately skip the SSE fetch entirely
    // so the user isn't re-billed for an answer they already have.
    if (cachedAnswer !== undefined) {
      setRawAnswer(cachedAnswer);
      setDone(true);
      setError(null);
      setPhase("done");
      onComplete?.(cachedAnswer);
      return;
    }

    const ac = new AbortController();
    abortRef.current = ac;
    setRawAnswer("");
    setDone(false);
    setError(null);
    setPhase("starting");
    // Clear the global cost + confidence so the active-turn pill
    // doesn't show the previous turn's values while the new turn is
    // mid-stream. Both events fire near the tail of the SSE stream and
    // will overwrite these placeholders before ``done``.
    setCostCents(0);
    setConfidence(null);

    // Local accumulator. setRawAnswer is async + batched, so we can't read
    // back the post-update value synchronously inside `dispatch`. Keep our
    // own copy here so the `done` handler can hand the FULL streamed answer
    // back to the parent (which freezes it into the chat thread).
    let accumulatedAnswer = "";

    const run = async () => {
      try {
        const res = await fetch("/api/ask", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question,
            asof,
            lang,
            mode,
            instant,
            history: history ?? [],
          }),
          signal: ac.signal,
        });
        if (!res.ok || !res.body) throw new Error(`Upstream ${res.status}`);
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";

        while (true) {
          const { value, done: rDone } = await reader.read();
          if (rDone) break;
          buf += decoder.decode(value, { stream: true });
          // Robust to both LF (\n\n, Next.js fixture) and CRLF (\r\n\r\n,
          // Python sidecar via sse-starlette). The Python backend was the
          // reason the loading bar froze - chunks never separated, so
          // dispatch() never ran.
          const chunks = buf.split(/\r?\n\r?\n/);
          buf = chunks.pop() ?? "";
          for (const c of chunks) {
            // Each chunk may have multiple SSE fields; pick the data: lines.
            const lines = c.split(/\r?\n/);
            for (const line of lines) {
              if (!line.startsWith("data:")) continue;
              const payload = line.slice(5).trim();
              if (!payload) continue;
              try {
                const evt: AgentEvent = JSON.parse(payload);
                dispatch(evt);
              } catch {
                /* skip malformed */
              }
            }
          }
        }
      } catch (err: unknown) {
        if (ac.signal.aborted) return;
        setError(err instanceof Error ? err.message : String(err));
      }
    };

    function dispatch(e: AgentEvent) {
      switch (e.type) {
        case "ner_pulse":
          setPhase("planning");
          for (const id of e.entityNodeIds) pushHighlightedNode(id);
          break;
        case "plan":
          setPhase("planning");
          setPlanCounts(e.subQuestions.length, e.entityNodeIds.length);
          for (const id of e.entityNodeIds) pushHighlightedNode(id);
          break;
        case "walked":
          setPhase("retrieving");
          incWalked();
          pushHighlightedNode(e.nodeId);
          break;
        case "subgraph_ready":
          setPhase("subgraph_ready");
          setOrbit(e.orbitNodes, e.orbitEdges);
          mergeOrbitNodeKinds(e.orbitNodes);
          setCenterNodeId(e.orbitNodes.find((n) => n.isCenter)?.id ?? null);
          setDimmed(true);
          break;
        case "debate_open":
          setPhase("debating");
          clearDebateMessages();
          setDebateActive(true);
          break;
        case "debate_token":
          appendDebateMessage({ party: e.party, text: e.text });
          break;
        case "debate_judge":
          setDebate({
            proposition: question,
            partyA: { label: "Vero", role: "vero", text: "", cites: [] },
            partyB: { label: "KHO", role: "kho", text: "", cites: [] },
            judge: e.judge,
            turnsElapsed: 7,
          });
          break;
        case "draft_token":
          setPhase("drafting");
          addDraftChars(e.text.length);
          accumulatedAnswer += e.text;
          setRawAnswer((r) => r + e.text);
          break;
        case "claim_verified":
          setPhase("verifying");
          break;
        case "conflict":
          setConflictPairs([[e.nodeA, e.nodeB]]);
          break;
        case "cost":
          setCostCents(e.cents);
          break;
        case "confidence":
          setConfidence(e.level);
          break;
        case "done":
          setPhase("done");
          setDone(true);
          onComplete?.(accumulatedAnswer);
          break;
        case "error":
          setPhase("error");
          setError(e.message);
          break;
      }
    }

    run();
    return () => ac.abort();
  }, [
    question, asof, lang, mode, instant, history,
    pushHighlightedNode, setOrbit, mergeOrbitNodeKinds,
    setDimmed, setCenterNodeId,
    setConflictPairs, setDebate, setDebateActive,
    appendDebateMessage, clearDebateMessages,
    setCostCents, setConfidence, onComplete,
    setPhase, incWalked, setPlanCounts, addDraftChars,
  ]);

  const handleHover = useCallback(
    (
      citedNodeId: string | null,
      anchor: { x: number; y: number; w?: number; h?: number } | null
    ) => {
      setHoveredNodeId(citedNodeId);
      setHoverAnchor(anchor);
    },
    [setHoveredNodeId, setHoverAnchor]
  );
  const handleClick = useCallback(
    (citedNodeId: string) => setSelectedNodeId(citedNodeId),
    [setSelectedNodeId]
  );

  const rendered = useMemo(
    () => renderAnswer(rawAnswer, nodeKind, handleHover, handleClick),
    [rawAnswer, nodeKind, handleHover, handleClick]
  );

  // While the agent is still working but no draft tokens have arrived yet,
  // render a 3-line skeleton so the synthesis card isn't visually empty.
  const showSkeleton =
    !done &&
    !error &&
    rawAnswer.length === 0 &&
    phase !== "idle" &&
    phase !== "done";

  return (
    <div className="space-y-4">
      {error && (
        <div
          role="alert"
          className="flex items-start border border-error/40 bg-error-container/30"
          style={{ gap: "var(--space-3)", padding: "var(--space-4)" }}
        >
          <span
            className="material-symbols-outlined shrink-0 text-error"
            style={{ fontSize: "var(--icon-md)" }}
          >
            error
          </span>
          <div className="min-w-0 flex-1" style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
            <p
              className="font-sans font-semibold text-error"
              style={{ fontSize: "var(--text-body)" }}
            >
              The agent couldn&apos;t finish that query
            </p>
            <p
              className="font-sans text-on-surface-variant"
              style={{ fontSize: "var(--text-body-sm)", lineHeight: 1.55 }}
            >
              The retrieval pipeline disconnected before the answer was
              committed. Your question hasn&apos;t been billed. Click{" "}
              <strong>Ask</strong> again to retry. Most failures are
              transient. If it keeps happening the sidecar may be unreachable
              from this browser.
            </p>
            <details
              className="font-mono text-on-surface-variant"
              style={{ fontSize: "var(--text-overline)", marginTop: 4 }}
            >
              <summary
                className="cursor-pointer uppercase tracking-widest"
                style={{ paddingBlock: 2 }}
              >
                technical detail
              </summary>
              <code
                className="block break-words"
                style={{ marginTop: 6, padding: 6, background: "var(--color-surface-container)", borderRadius: 2 }}
              >
                {error}
              </code>
            </details>
          </div>
        </div>
      )}
      {showSkeleton ? (
        <div className="space-y-2.5" aria-busy="true" aria-label="Drafting answer">
          <span className="lex-skeleton block" style={{ height: 14, width: "95%" }} />
          <span className="lex-skeleton block" style={{ height: 14, width: "88%" }} />
          <span className="lex-skeleton block" style={{ height: 14, width: "72%" }} />
          <span className="lex-skeleton block" style={{ height: 14, width: "50%" }} />
        </div>
      ) : (
        <div
          className="font-sans text-on-surface"
          style={{ fontSize: 17, lineHeight: 1.65 }}
        >
          {rendered}
          {!done && rawAnswer.length > 0 && (
            <span
              className="ml-1 inline-block h-4 w-2 animate-pulse align-middle"
              style={{ background: "var(--color-secondary)" }}
              aria-hidden
            />
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Static renderer for an already-streamed answer (no SSE, no skeleton, no
 * cursor). Used by completed turns in the chat thread — they keep their
 * clickable cite anchors, but don't re-run the pipeline. Reuses the same
 * `renderAnswer` machinery as the streaming variant so hover/click still
 * flips the global `hoveredNodeId` / `selectedNodeId`.
 */
export function RenderedAnswer({ answer }: { answer: string }) {
  const setHoveredNodeId = useGraphStore((s) => s.setHoveredNodeId);
  const setHoverAnchor = useGraphStore((s) => s.setHoverAnchor);
  const setSelectedNodeId = useGraphStore((s) => s.setSelectedNodeId);
  const nodeKind = useGraphStore((s) => s.nodeKind);

  const handleHover = useCallback(
    (
      citedNodeId: string | null,
      anchor: { x: number; y: number; w?: number; h?: number } | null
    ) => {
      setHoveredNodeId(citedNodeId);
      setHoverAnchor(anchor);
    },
    [setHoveredNodeId, setHoverAnchor]
  );
  const handleClick = useCallback(
    (citedNodeId: string) => setSelectedNodeId(citedNodeId),
    [setSelectedNodeId]
  );

  const rendered = useMemo(
    () => renderAnswer(answer, nodeKind, handleHover, handleClick),
    [answer, nodeKind, handleHover, handleClick]
  );

  return (
    <div
      className="font-sans text-on-surface"
      style={{ fontSize: 17, lineHeight: 1.65 }}
    >
      {rendered}
    </div>
  );
}

function renderAnswer(
  text: string,
  nodeKind: Record<string, NodeKind>,
  onHover: (
    id: string | null,
    anchor: { x: number; y: number; w?: number; h?: number } | null
  ) => void,
  onClick: (id: string) => void
): React.ReactNode {
  const cleaned = text.replace(REFLECTION_TOKEN_RE, "");
  const parts: React.ReactNode[] = [];
  let lastIdx = 0;
  let m: RegExpExecArray | null;
  let counter = 0;
  let prevWasCite = false;
  const re = new RegExp(CITE_TOKEN_RE.source, "g");
  while ((m = re.exec(cleaned)) !== null) {
    const [full, nodeId, label] = m;
    // Plain text between this match and the previous one.
    if (m.index > lastIdx) {
      const between = cleaned.slice(lastIdx, m.index);
      parts.push(...renderMarkdownInline(between, `t-${counter}`));
      // ``prevWasCite`` only stays true when there was no visible text
      // between two cite tokens — that's the case we need to separate.
      prevWasCite = false;
    }
    // Two cite tokens back-to-back with nothing between → inject a thin
    // separator so the underlines don't merge into one long blob.
    if (prevWasCite) {
      parts.push(
        <span
          key={`sep-${counter}`}
          className="cite-separator"
          aria-hidden
        >
          ,{" "}
        </span>
      );
    }
    const kind = nodeKind[nodeId] ?? "work";
    const color = colorForKind(kind);
    parts.push(
      <CiteAnchor
        key={`cite-${counter++}-${nodeId}`}
        nodeId={nodeId}
        color={color}
        onHover={onHover}
        onClick={onClick}
      >
        {label}
      </CiteAnchor>
    );
    lastIdx = m.index + full.length;
    prevWasCite = true;
  }
  if (lastIdx < cleaned.length) {
    parts.push(...renderMarkdownInline(cleaned.slice(lastIdx), `t-tail`));
  }
  return parts;
}

// Minimal inline markdown: **bold**, *italic*, _italic_. Anything else
// (lists, headers, code blocks) passes through as plain text — the
// agent's answers don't use them and we don't want to invite XSS via
// dangerouslySetInnerHTML.
const _BOLD_RE = /\*\*([^*\n]+?)\*\*/;
const _ITAL_STAR_RE = /(?:^|[^*])\*([^*\n]+?)\*(?!\*)/;
const _ITAL_UNDER_RE = /(?:^|[^_\w])_([^_\n]+?)_(?!_)/;

function renderMarkdownInline(
  text: string,
  keyPrefix: string
): React.ReactNode[] {
  if (!text) return [];
  const out: React.ReactNode[] = [];
  let remaining = text;
  let i = 0;
  // Loop: at each step find the EARLIEST of {bold, italic-star, italic-under},
  // emit the leading plain text + the styled span, then continue with the rest.
  while (remaining.length > 0) {
    type Match = { kind: "b" | "i"; full: string; inner: string; idx: number };
    const candidates: Match[] = [];
    const mb = _BOLD_RE.exec(remaining);
    if (mb) candidates.push({ kind: "b", full: mb[0], inner: mb[1], idx: mb.index });
    const mis = _ITAL_STAR_RE.exec(remaining);
    if (mis) {
      // Capture group 1 sits one char inside ``full`` when the lookbehind
      // matched a non-* character; align ``idx`` to the literal ``*``.
      const starIdx = remaining.indexOf("*", mis.index);
      candidates.push({
        kind: "i",
        full: `*${mis[1]}*`,
        inner: mis[1],
        idx: starIdx,
      });
    }
    const miu = _ITAL_UNDER_RE.exec(remaining);
    if (miu) {
      const underIdx = remaining.indexOf("_", miu.index);
      candidates.push({
        kind: "i",
        full: `_${miu[1]}_`,
        inner: miu[1],
        idx: underIdx,
      });
    }
    if (candidates.length === 0) {
      out.push(remaining);
      break;
    }
    candidates.sort((a, b) => a.idx - b.idx);
    const winner = candidates[0];
    if (winner.idx > 0) out.push(remaining.slice(0, winner.idx));
    const tag = winner.kind === "b" ? "strong" : "em";
    out.push(
      tag === "strong" ? (
        <strong key={`${keyPrefix}-md-${i}`}>{winner.inner}</strong>
      ) : (
        <em key={`${keyPrefix}-md-${i}`}>{winner.inner}</em>
      )
    );
    remaining = remaining.slice(winner.idx + winner.full.length);
    i += 1;
  }
  return out;
}

function CiteAnchor({
  nodeId,
  color,
  onHover,
  onClick,
  children,
}: {
  nodeId: string;
  color: string;
  onHover: (
    id: string | null,
    anchor: { x: number; y: number; w?: number; h?: number } | null
  ) => void;
  onClick: (id: string) => void;
  children: React.ReactNode;
}) {
  const handleEnter = (ev: React.MouseEvent<HTMLSpanElement>) => {
    const rect = ev.currentTarget.getBoundingClientRect();
    onHover(nodeId, { x: rect.left, y: rect.top, w: rect.width, h: rect.height });
  };
  const handleLeave = () => onHover(null, null);
  return (
    <span
      className="cite-anchor"
      style={{
        textDecorationColor: color,
        color: "var(--color-on-surface)",
      }}
      onMouseEnter={handleEnter}
      onMouseLeave={handleLeave}
      onClick={() => onClick(nodeId)}
      role="button"
      tabIndex={0}
      onFocus={(ev) => {
        const rect = (ev.currentTarget as HTMLSpanElement).getBoundingClientRect();
        onHover(nodeId, { x: rect.left, y: rect.top, w: rect.width, h: rect.height });
      }}
      onBlur={handleLeave}
      onKeyDown={(ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          onClick(nodeId);
        }
      }}
      aria-label={`Source for ${nodeId}. Click to inspect.`}
    >
      {children}
    </span>
  );
}
