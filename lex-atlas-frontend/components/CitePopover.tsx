"use client";

/**
 * CitePopover - the small floating overlay that appears next to whatever the
 * user is currently hovering. Two modes:
 *
 *   1. NODE hover: fetches /api/excerpt and shows the source title +
 *      truncated excerpt. Click anywhere to pin into the Inspector.
 *
 *   2. EDGE hover: shows the relation, plain-English description, and the
 *      two endpoint labels. No fetch needed - everything is already in the
 *      store. Same click-to-pin behavior.
 *
 * Anchored to `hoverAnchor.{x,y}` (set by whatever triggered the hover).
 * Auto-flips left/down if it would overflow the viewport. Suppresses itself
 * when the Inspector is already pinned on the same node/edge to avoid
 * showing duplicate info.
 */

import { useEffect, useState } from "react";
import { useGraphStore } from "@/lib/store";
import { colorForKind } from "@/lib/colors";
import type { ExcerptResponse, EdgeRelation } from "@/lib/types";

const cache = new Map<string, ExcerptResponse>();

const POPOVER_W = 360;
const POPOVER_H_ESTIMATE = 220;
const GAP = 12;
const SCREEN_PAD = 12;

/**
 * Place a popover of size `(pw, ph)` so it sits OUTSIDE the trigger rect.
 *
 * Strategy: try four sides in an order biased by trigger shape. For each
 * side we measure available space (gap to viewport edge minus popover
 * extent) and accept the first side that fits. If nothing fits, fall back
 * to the side with the most space and clamp the orthogonal axis. Result
 * is then clamped into the viewport with SCREEN_PAD margin.
 *
 * Bias: wide-and-short triggers (inline cites in flowing text) -> prefer
 * above/below; tall-or-square triggers (graph nodes/edges) -> prefer
 * right/left. This matches user expectations: a popover next to a single
 * word reads worse than one above it.
 */
function placePopover(
  trigger: { x: number; y: number; w: number; h: number },
  pw: number,
  ph: number
): { left: number; top: number } {
  const vw = typeof window !== "undefined" ? window.innerWidth : 1440;
  const vh = typeof window !== "undefined" ? window.innerHeight : 900;
  const tRight = trigger.x + trigger.w;
  const tBottom = trigger.y + trigger.h;

  // Available space in each cardinal direction.
  const spaceR = vw - tRight - SCREEN_PAD;
  const spaceL = trigger.x - SCREEN_PAD;
  const spaceA = trigger.y - SCREEN_PAD;
  const spaceB = vh - tBottom - SCREEN_PAD;

  const wide = trigger.w > trigger.h * 2; // inline-text heuristic
  const order: Array<"above" | "below" | "right" | "left"> = wide
    ? ["above", "below", "right", "left"]
    : ["right", "left", "above", "below"];

  // Candidate top-left positions for each side. We anchor the popover to
  // the trigger's leading edge on the orthogonal axis (so it visually
  // points back at the trigger).
  const candidates: Record<
    "above" | "below" | "right" | "left",
    { left: number; top: number; fits: boolean }
  > = {
    right: {
      left: tRight + GAP,
      top: trigger.y,
      fits: spaceR >= pw + GAP,
    },
    left: {
      left: trigger.x - pw - GAP,
      top: trigger.y,
      fits: spaceL >= pw + GAP,
    },
    above: {
      left: trigger.x + trigger.w / 2 - pw / 2,
      top: trigger.y - ph - GAP,
      fits: spaceA >= ph + GAP,
    },
    below: {
      left: trigger.x + trigger.w / 2 - pw / 2,
      top: tBottom + GAP,
      fits: spaceB >= ph + GAP,
    },
  };

  let picked: { left: number; top: number } | null = null;
  for (const side of order) {
    if (candidates[side].fits) {
      picked = { left: candidates[side].left, top: candidates[side].top };
      break;
    }
  }
  if (!picked) {
    // Nothing fit; pick the side with the most available space.
    const sides: Array<{ side: "above" | "below" | "right" | "left"; space: number }> = [
      { side: "above", space: spaceA },
      { side: "below", space: spaceB },
      { side: "right", space: spaceR },
      { side: "left", space: spaceL },
    ];
    sides.sort((a, b) => b.space - a.space);
    picked = { left: candidates[sides[0].side].left, top: candidates[sides[0].side].top };
  }

  // Clamp into viewport, keeping SCREEN_PAD margins.
  picked.left = Math.max(SCREEN_PAD, Math.min(picked.left, vw - pw - SCREEN_PAD));
  picked.top = Math.max(SCREEN_PAD, Math.min(picked.top, vh - ph - SCREEN_PAD));

  // Final overlap guard: if the chosen position still intersects the
  // trigger rect (can happen at tiny viewports), nudge it below the
  // trigger - that's the only direction guaranteed to clear.
  const overlapsTrigger =
    picked.left < tRight &&
    picked.left + pw > trigger.x &&
    picked.top < tBottom &&
    picked.top + ph > trigger.y;
  if (overlapsTrigger) {
    picked.top = Math.min(tBottom + GAP, vh - ph - SCREEN_PAD);
  }

  return picked;
}

/** Plain-English explanation of each relation - same map as Inspector. */
const RELATION_DESC: Record<EdgeRelation, string> = {
  has_part:        "Structurally part of the parent (LRMoo F1 → F22).",
  realized_in:     "Versioned realization of a Work at a point in time.",
  expressed_in:    "Component Temporal Version - the section's text at that version.",
  creates:         "Amendment Action that created this Expression.",
  terminates:      "Amendment Action that terminated this Expression's validity.",
  aggregates:      "SAT-Graph aggregation up the section tree.",
  caused_by:       "One amendment caused by a higher-level event.",
  source_provision:"The court ruling reasoned from this statutory provision.",
  interprets:      "Vero's published interpretation of the cited node.",
  rules_on:        "Court issued a binding interpretation of this section.",
  transposes:      "Finnish law transposing EU primary law.",
  supersedes:      "Old node remains queryable for historic asof dates.",
  references:      "Plain textual cross-reference. No precedence implication.",
  defines:         "Statute that defines this domain term.",
  uses:            "Section using this term in its text.",
  enacted_by:      "Issued by the parliament (Eduskunta).",
  issued_by:       "Published by Verohallinto / KHO etc.",
  applies_in:      "Applies in this jurisdiction (FI / EU / Aaland).",
  excludes:        "Explicit exclusion from scope.",
  in_theme:        "Curated structural community.",
  // ── DB-native edge types from the Python pipeline ────────────────────
  parent_of:       "Structural containment (LAW → SECTION).",
  cites:           "Textual cross-reference between two sections.",
  amends:          "Amending act → target act.",
  amends_section:  "Amendment directive targeting a specific section.",
  repeals:         "Action repealing a section or whole act.",
  applies:         "Court ruling applied this statutory provision.",
};

export function CitePopover() {
  const hoveredNodeId = useGraphStore((s) => s.hoveredNodeId);
  const hoveredEdgeKey = useGraphStore((s) => s.hoveredEdgeKey);
  const hoverAnchor = useGraphStore((s) => s.hoverAnchor);
  const nodeKind = useGraphStore((s) => s.nodeKind);
  const orbitNodes = useGraphStore((s) => s.orbitNodes);
  const orbitEdges = useGraphStore((s) => s.orbitEdges);
  const selectedNodeId = useGraphStore((s) => s.selectedNodeId);
  const selectedEdgeKey = useGraphStore((s) => s.selectedEdgeKey);

  /* ------------------------------------------------------------------
     Mode resolution: edge wins over node if both are hovered at once
     (only happens on a stray pixel between two elements anyway).
     ------------------------------------------------------------------ */
  const mode: "edge" | "node" | "none" = hoveredEdgeKey
    ? "edge"
    : hoveredNodeId
    ? "node"
    : "none";

  /* Suppress when the Inspector is already pinned on the same target. */
  const suppress =
    (mode === "node" && selectedNodeId === hoveredNodeId) ||
    (mode === "edge" && selectedEdgeKey === hoveredEdgeKey);

  /* Excerpt fetch only for node mode. */
  const [excerpt, setExcerpt] = useState<ExcerptResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (mode !== "node" || !hoveredNodeId || suppress) {
      setExcerpt(null);
      setLoading(false);
      return;
    }
    const cached = cache.get(hoveredNodeId);
    if (cached) {
      setExcerpt(cached);
      return;
    }
    setExcerpt(null);
    setLoading(true);
    const ac = new AbortController();
    const timer = setTimeout(() => {
      fetch(`/api/excerpt?node_id=${encodeURIComponent(hoveredNodeId)}`, {
        signal: ac.signal,
      })
        .then((r) => (r.ok ? r.json() : null))
        .then((data: ExcerptResponse | null) => {
          if (!data) return;
          cache.set(hoveredNodeId, data);
          setExcerpt(data);
        })
        .catch(() => {})
        .finally(() => setLoading(false));
    }, 120);
    return () => {
      clearTimeout(timer);
      ac.abort();
    };
  }, [mode, hoveredNodeId, suppress]);

  if (mode === "none" || !hoverAnchor || suppress) return null;

  /* ----- Smart placement that NEVER covers the trigger ---------------
     Compute the trigger's full bounding rect, then pick the side with
     the most clear viewport space (preferring above/below for short
     inline triggers, right/left for wide rectangular nodes). Clamp the
     final position into the viewport. */
  const { left, top } = placePopover(
    { x: hoverAnchor.x, y: hoverAnchor.y, w: hoverAnchor.w ?? 0, h: hoverAnchor.h ?? 0 },
    POPOVER_W,
    POPOVER_H_ESTIMATE
  );

  if (mode === "edge" && hoveredEdgeKey) {
    return (
      <EdgePopover
        edgeKey={hoveredEdgeKey}
        orbitEdges={orbitEdges}
        orbitNodes={orbitNodes}
        left={left}
        top={top}
      />
    );
  }

  // mode === "node"
  if (!hoveredNodeId) return null;
  const kind =
    nodeKind[hoveredNodeId] ??
    orbitNodes.find((n) => n.id === hoveredNodeId)?.kind ??
    "work";
  const color = colorForKind(kind);

  return (
    <div
      className="pointer-events-none fixed z-50 border border-outline-variant bg-surface-container-lowest shadow-[0_8px_24px_rgba(0,0,0,0.08)]"
      style={{ left, top, width: POPOVER_W }}
      role="tooltip"
      aria-live="polite"
    >
      <div className="h-0.5 w-full" style={{ background: color }} aria-hidden />
      <div className="px-3 py-2.5">
        <div className="mb-1 flex items-center justify-between gap-2">
          <span
            className="font-mono text-[10px] uppercase tracking-wider"
            style={{ color }}
          >
            {kind}
          </span>
          <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
            hover preview
          </span>
        </div>
        {loading && !excerpt && (
          <div className="space-y-1.5">
            <span className="lex-skeleton block" style={{ height: 13, width: "80%" }} />
            <span className="lex-skeleton block" style={{ height: 9, width: "45%" }} />
            <div className="space-y-1" style={{ marginTop: 6 }}>
              <span className="lex-skeleton block" style={{ height: 9, width: "95%" }} />
              <span className="lex-skeleton block" style={{ height: 9, width: "88%" }} />
              <span className="lex-skeleton block" style={{ height: 9, width: "72%" }} />
            </div>
            <div
              className="flex items-center font-mono uppercase tracking-widest text-on-surface-variant"
              style={{ gap: 5, fontSize: 9, paddingTop: 4 }}
            >
              <span
                aria-hidden
                style={{
                  display: "inline-block",
                  width: 8,
                  height: 8,
                  borderRadius: "9999px",
                  border: "1.5px solid var(--color-outline-variant)",
                  borderTopColor: "var(--color-secondary)",
                  animation: "lex-spin 0.8s linear infinite",
                }}
              />
              Resolving source
            </div>
          </div>
        )}
        {excerpt && (
          <>
            <div className="font-serif text-sm font-semibold leading-snug text-on-surface">
              {excerpt.docTitle}
            </div>
            {excerpt.docketNumber && (
              <div className="mt-0.5 font-mono text-[10px] text-on-surface-variant">
                {excerpt.docketNumber}
              </div>
            )}
            <div
              className="mt-2 line-clamp-4 font-sans text-on-surface [&_mark.claim-match]:bg-secondary/25 [&_mark.claim-match]:px-0.5"
              style={{ fontSize: 12.5, lineHeight: 1.5 }}
              dangerouslySetInnerHTML={{ __html: excerpt.excerptHtml }}
            />
            <div className="mt-2 flex items-center justify-between border-t border-outline-variant pt-1.5 font-mono text-[10px] text-on-surface-variant">
              <span>{excerpt.publisher.toUpperCase()}</span>
              <span className="text-secondary">click to pin in inspector ↓</span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────
   Edge popover - terracotta accent strip, source/target pills, relation
   description. No fetch.
   ───────────────────────────────────────────────────────────────────── */

interface EdgePopoverProps {
  edgeKey: string;
  orbitEdges: ReturnType<typeof useGraphStore.getState>["orbitEdges"];
  orbitNodes: ReturnType<typeof useGraphStore.getState>["orbitNodes"];
  left: number;
  top: number;
}

function EdgePopover({ edgeKey, orbitEdges, orbitNodes, left, top }: EdgePopoverProps) {
  const [src, tgt] = edgeKey.split("->");
  // Match either against the real backend edges or fall back to a synthetic
  // edge by source/target alone.
  const edge = orbitEdges.find(
    (e) => `${e.source}->${e.target}` === edgeKey
  );
  const isSynthetic = !edge;
  // If no real edge exists, we still know src/tgt from the key and rely on
  // node metadata for the endpoint names.
  const relation = (edge?.relation ?? "references") as EdgeRelation;
  const isConflict = !!edge?.isConflict;
  const description = RELATION_DESC[relation];

  const srcNode = orbitNodes.find((n) => n.id === src);
  const tgtNode = orbitNodes.find((n) => n.id === tgt);

  const srcColor = srcNode ? colorForKind(srcNode.kind) : "#1a1c1b";
  const tgtColor = tgtNode ? colorForKind(tgtNode.kind) : "#1a1c1b";
  const accent = isConflict ? "#ba1a1a" : "var(--color-secondary)";

  return (
    <div
      className="pointer-events-none fixed z-50 border border-outline-variant bg-surface-container-lowest shadow-[0_8px_24px_rgba(0,0,0,0.08)]"
      style={{ left, top, width: POPOVER_W }}
      role="tooltip"
      aria-live="polite"
    >
      <div className="h-0.5 w-full" style={{ background: accent }} aria-hidden />
      <div className="px-3 py-2.5">
        <div className="mb-1 flex items-center justify-between gap-2">
          <span
            className="font-mono text-[10px] uppercase tracking-wider"
            style={{ color: accent }}
          >
            {relation}
            {isSynthetic ? " · inferred" : ""}
            {isConflict ? " · conflict" : ""}
          </span>
          <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
            edge preview
          </span>
        </div>
        <p
          className="font-sans text-on-surface"
          style={{ fontSize: 12.5, lineHeight: 1.55 }}
        >
          {description}
        </p>

        {/* Endpoints */}
        <div className="mt-2.5 space-y-1.5">
          {srcNode && (
            <div className="flex items-baseline gap-2">
              <span
                className="shrink-0 font-mono text-[9px] uppercase tracking-wider text-on-surface-variant"
                style={{ minWidth: 36 }}
              >
                FROM
              </span>
              <span
                className="font-mono text-[10px] uppercase tracking-wider"
                style={{ color: srcColor, minWidth: 56 }}
              >
                {srcNode.kind}
              </span>
              <span
                className="truncate font-sans"
                style={{ fontSize: 12, color: srcColor, fontWeight: 500 }}
              >
                {srcNode.label}
              </span>
            </div>
          )}
          {tgtNode && (
            <div className="flex items-baseline gap-2">
              <span
                className="shrink-0 font-mono text-[9px] uppercase tracking-wider text-on-surface-variant"
                style={{ minWidth: 36 }}
              >
                TO
              </span>
              <span
                className="font-mono text-[10px] uppercase tracking-wider"
                style={{ color: tgtColor, minWidth: 56 }}
              >
                {tgtNode.kind}
              </span>
              <span
                className="truncate font-sans"
                style={{ fontSize: 12, color: tgtColor, fontWeight: 500 }}
              >
                {tgtNode.label}
              </span>
            </div>
          )}
        </div>

        <div className="mt-2 flex items-center justify-between border-t border-outline-variant pt-1.5 font-mono text-[10px] text-on-surface-variant">
          <span>
            {isSynthetic ? "synthesized from id hierarchy" : "from typed graph"}
          </span>
          <span className="text-secondary">click to pin in inspector ↓</span>
        </div>
      </div>
    </div>
  );
}
