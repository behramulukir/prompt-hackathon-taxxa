"use client";

/**
 * Inspector - right-docked persistent panel that opens whenever the user
 * clicks a graph node, graph edge, or inline cite-anchor. Shows ALL the
 * provenance for that pick (kind / authority rank / temporal window /
 * conflict status / source URL / incident edges) plus the actual HTML
 * excerpt from the Finlex or Vero page that the agent grounded on.
 *
 * Decoupled from CitationDrawer (which is the transient bottom popover for
 * hover-quick-peek) - this is the persistent state, dismissed only by
 * clicking the X or selecting something else.
 */

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useGraphStore } from "@/lib/store";
import { colorForKind, AUTHORITY_LABELS } from "@/lib/colors";
import type { ExcerptResponse, OrbitNode, OrbitEdge, EdgeRelation, NodeKind } from "@/lib/types";

/** Map a NodeKind to a single short label so the rank's "1 / 8 ..." line
 *  finally says something useful when surfaced under the rank chip.
 *  AUTHORITY_LABELS keys off the 1-8 bucket only, which conflates
 *  e.g. "Vero ohje rank 3" with "older statute rank 3". This is kind-
 *  aware so the sub-line matches what you're actually looking at. */
const KIND_DESC: Record<NodeKind, string> = {
  work: "Statute (Finlex)",
  expression: "Versioned statute text",
  component: "Statute chapter",
  ctv: "Statute section",
  action: "Amendment",
  case: "Court ruling",
  guidance: "Tax-authority guidance",
  concept: "Domain concept",
  authority: "Issuing body",
  jurisdiction: "Jurisdiction",
  theme: "Topic cluster",
};

const excerptCache = new Map<string, ExcerptResponse>();

const RELATION_DESC: Record<EdgeRelation, string> = {
  has_part:        "Statute --> section. The section is structurally part of the statute (LRMoo F1-->F22).",
  realized_in:     "Work --> Expression. The Expression is a versioned realization of the Work at a point in time.",
  expressed_in:    "Expression --> CTV. The Component Temporal Version captures the section's text at that version.",
  creates:         "Action --> Expression. The amendment Action created this Expression (F28).",
  terminates:      "Action --> Expression. The amendment Action terminated the validity of this Expression.",
  aggregates:      "CTV --> CTV. SAT-Graph aggregation propagates validity bounds up the section tree.",
  caused_by:       "Action --> Action. One amendment was caused by a higher-level legislative event.",
  source_provision:"Case --> Section. The court ruling reasoned from this statutory provision.",
  interprets:      "Guidance --> Section/Case. Vero's published interpretation of the cited node.",
  rules_on:        "Case --> Section. The court issued a binding interpretation of this section.",
  transposes:      "National statute --> EU directive. Finnish law transposes EU primary law.",
  supersedes:      "New node supersedes the old. Old node remains queryable for historic asof dates.",
  references:      "Plain textual cross-reference. No precedence implication.",
  defines:         "Statute --> Concept. The statute defines this domain term.",
  uses:            "Section --> Concept. The section uses this term in its text.",
  enacted_by:      "Statute --> Authority. Issued by the parliament (Eduskunta).",
  issued_by:       "Guidance --> Authority. Published by Verohallinto / KHO etc.",
  applies_in:      "Node --> Jurisdiction. Applies in this jurisdiction (FI / EU / Aaland).",
  excludes:        "Node --> Node. Explicit exclusion from scope.",
  in_theme:        "Node --> Theme. SAT-Graph curated structural community.",
};

export function Inspector() {
  const orbitNodes = useGraphStore((s) => s.orbitNodes);
  const orbitEdges = useGraphStore((s) => s.orbitEdges);
  const selectedNodeId = useGraphStore((s) => s.selectedNodeId);
  const selectedEdgeKey = useGraphStore((s) => s.selectedEdgeKey);
  const clearSelection = useGraphStore((s) => s.clearSelection);

  const open = !!(selectedNodeId || selectedEdgeKey);
  const panelRef = useRef<HTMLElement | null>(null);

  // ESC dismisses the panel.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") clearSelection();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, clearSelection]);

  // Click-outside dismiss. Closes the Inspector if the user clicks anywhere
  // that is NOT inside the panel itself AND NOT inside the orbit graph SVG.
  // (Clicking inside the graph already changes the selection via OrbitGraph's
  // own handlers, so we don't want to fight that.)
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target as Element | null;
      if (!target) return;
      if (panelRef.current && panelRef.current.contains(target)) return;
      if (target.closest('[data-orbit-graph="true"]')) return;
      // Also keep the popovers alive - clicking the popover should not dismiss.
      if (target.closest('[role="tooltip"]')) return;
      clearSelection();
    };
    // Use pointerdown (not click) so it fires before a fresh selection click.
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open, clearSelection]);

  const selectedNode = selectedNodeId
    ? orbitNodes.find((n) => n.id === selectedNodeId) ?? null
    : null;
  const selectedEdge = selectedEdgeKey
    ? orbitEdges.find((e) => `${e.source}->${e.target}` === selectedEdgeKey) ?? null
    : null;

  return (
    <AnimatePresence>
      {open && (
        <motion.aside
          key="inspector"
          ref={panelRef as React.Ref<HTMLElement>}
          initial={{ x: 420, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 420, opacity: 0 }}
          transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
          className="fixed right-0 top-16 z-40 h-[calc(100vh-4rem)] w-full max-w-md overflow-y-auto border-l border-outline-variant bg-surface-container-lowest shadow-[0_0_40px_rgba(0,0,0,0.04)]"
          role="region"
          aria-label="Inspector"
        >
          {/* Header */}
          <div className="sticky top-0 z-10 flex items-center justify-between border-b border-outline-variant bg-surface-container-lowest px-5 py-3">
            <div className="flex items-center gap-2 font-mono text-xs uppercase tracking-wider text-on-surface-variant">
              <span className="material-symbols-outlined" style={{ fontSize: 16 }}>
                {selectedNode ? "info" : "fork_right"}
              </span>
              {selectedNode ? "Node Inspector" : "Edge Inspector"}
            </div>
            <button
              onClick={() => clearSelection()}
              className="flex h-7 w-7 items-center justify-center border border-outline-variant transition-colors hover:bg-surface-container"
              aria-label="Close inspector"
            >
              <span className="material-symbols-outlined" style={{ fontSize: 16 }}>
                close
              </span>
            </button>
          </div>

          {/* Body */}
          <div className="px-5 py-5">
            {selectedNode && <NodeBody node={selectedNode} edges={orbitEdges} />}
            {selectedEdge && (
              <EdgeBody
                edge={selectedEdge}
                source={orbitNodes.find((n) => n.id === selectedEdge.source) ?? null}
                target={orbitNodes.find((n) => n.id === selectedEdge.target) ?? null}
              />
            )}
            {/* Selected edge that the store doesn't know about — happens for
                synthetic "scaffolding" edges OrbitGraph adds to keep the
                layout connected. Show a clear panel instead of a blank one
                so the click doesn't feel broken. */}
            {!selectedNode && !selectedEdge && selectedEdgeKey && (
              <SyntheticEdgeBody edgeKey={selectedEdgeKey} />
            )}
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}

/* --------------------------------------------------------------------- */

function NodeBody({ node, edges }: { node: OrbitNode; edges: OrbitEdge[] }) {
  const color = colorForKind(node.kind);
  const incident = edges.filter((e) => e.source === node.id || e.target === node.id);

  return (
    <div className="space-y-5">
      {/* Kind + title */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <span
            className="h-2.5 w-2.5"
            style={{ background: color }}
            aria-hidden
          />
          <span
            className="font-mono text-[11px] uppercase tracking-wider"
            style={{ color }}
          >
            {node.kind}
          </span>
          {node.isCenter && (
            <span className="meta-pill" style={{ fontSize: 10 }}>
              CENTER
            </span>
          )}
          {node.isConflicted && (
            <span
              className="font-mono text-[10px] uppercase tracking-wider text-error"
              style={{ padding: "2px 6px", border: "1px solid #ba1a1a" }}
            >
              CONFLICTED
            </span>
          )}
        </div>
        <h2
          className="font-serif font-medium leading-tight"
          style={{ fontSize: 22 }}
        >
          {node.label}
        </h2>
        <div className="font-mono text-[11px] text-on-surface-variant">
          {node.id}
        </div>
      </div>

      {/* Metadata grid. Authority rank's sub-line is now kind-aware, not
          "Recent amendment" for every rank-6 thing. The Valid-from/until
          rows are only rendered when the backend actually supplied a date,
          so blank corpus metadata no longer fakes a temporal window. */}
      <dl className="grid grid-cols-2 gap-3 border-y border-outline-variant py-3">
        <Metric
          label="Authority rank"
          value={`${node.authorityRank} / 8`}
          sub={KIND_DESC[node.kind] ?? AUTHORITY_LABELS[node.authorityRank]}
        />
        <Metric
          label="Active at asof"
          value={node.isActive ? "Yes" : "No"}
          accent={node.isActive ? color : undefined}
        />
        {node.tValid && <Metric label="Valid from" value={node.tValid} />}
        {(node.tInvalid || node.tValid) && (
          <Metric
            label="Valid until"
            value={node.tInvalid ?? "present"}
          />
        )}
      </dl>

      {/* Incident edges */}
      {incident.length > 0 && (
        <div>
          <div className="mb-2 font-mono text-[11px] uppercase tracking-wider text-on-surface-variant">
            {incident.length} incident edge{incident.length === 1 ? "" : "s"}
          </div>
          <ul className="space-y-1.5">
            {incident.map((e, i) => (
              <li
                key={i}
                className="flex items-center gap-2 font-mono text-[11px] text-on-surface"
              >
                <span className="text-on-surface-variant">
                  {e.source === node.id ? "out" : "in "}
                </span>
                <span style={{ color }}>--{e.relation}--&gt;</span>
                <span className="truncate" title={e.source === node.id ? e.target : e.source}>
                  {e.source === node.id ? e.target : e.source}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Excerpt from /api/excerpt */}
      <NodeExcerpt nodeId={node.id} />
    </div>
  );
}

function SyntheticEdgeBody({ edgeKey }: { edgeKey: string }) {
  const [src, tgt] = edgeKey.split("->");
  return (
    <div className="space-y-4">
      <div>
        <div className="font-mono text-[11px] uppercase tracking-wider text-on-surface-variant">
          Layout edge
        </div>
        <h2
          className="mt-1 font-serif font-medium leading-tight"
          style={{ fontSize: 20 }}
        >
          {src ?? "?"}{" "}
          <span className="text-on-surface-variant">--scaffolding--&gt;</span>{" "}
          {tgt ?? "?"}
        </h2>
      </div>
      <p
        className="border-l-2 border-outline-variant pl-3 text-on-surface-variant"
        style={{ fontSize: 14, lineHeight: 1.55 }}
      >
        This line is rendered by the orbit layout to keep the graph
        connected, but there's no typed graph relation behind it. Click a
        solid edge (one with a relation label like <code>cites</code> or
        <code> interprets</code>) to see real edge metadata.
      </p>
    </div>
  );
}


function EdgeBody({
  edge,
  source,
  target,
}: {
  edge: OrbitEdge;
  source: OrbitNode | null;
  target: OrbitNode | null;
}) {
  const conflict = !!edge.isConflict;
  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <span
            className="font-mono text-[11px] uppercase tracking-wider"
            style={{ color: conflict ? "#ba1a1a" : "var(--color-on-surface-variant)" }}
          >
            {edge.relation}
          </span>
          {conflict && (
            <span
              className="font-mono text-[10px] uppercase tracking-wider text-error"
              style={{ padding: "2px 6px", border: "1px solid #ba1a1a" }}
            >
              CONFLICT
            </span>
          )}
        </div>
        <h2 className="font-serif font-medium leading-tight" style={{ fontSize: 22 }}>
          {edge.source} <span className="text-on-surface-variant">--{edge.relation}--&gt;</span> {edge.target}
        </h2>
      </div>

      <p
        className="border-l-2 border-outline-variant pl-3 text-on-surface"
        style={{ fontSize: 15, lineHeight: 1.55 }}
      >
        {RELATION_DESC[edge.relation]}
      </p>

      {/* Endpoints */}
      <div className="grid grid-cols-1 gap-3">
        {source && <EndpointCard label="SOURCE" node={source} />}
        {target && <EndpointCard label="TARGET" node={target} />}
      </div>

      {/* If conflict, briefly explain how it resolves */}
      {conflict && (
        <div className="border border-error/30 bg-error-container/30 p-3">
          <div className="mb-1 font-mono text-[11px] uppercase tracking-wider text-error">
            Resolution
          </div>
          <p className="text-on-surface" style={{ fontSize: 14, lineHeight: 1.55 }}>
            When two cited nodes disagree, the agent picks the one with the
            higher authority rank under the priority lattice. KHO (rank 7)
            overrides Vero ohje (rank 3). Unresolved equal-rank disagreements
            route to the Debate panel.
          </p>
        </div>
      )}
    </div>
  );
}

function EndpointCard({ label, node }: { label: string; node: OrbitNode }) {
  const color = colorForKind(node.kind);
  return (
    <div className="border border-outline-variant bg-surface-container-low p-3">
      <div className="mb-1 flex items-center gap-2">
        <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
          {label}
        </span>
        <span
          className="font-mono text-[10px] uppercase tracking-wider"
          style={{ color }}
        >
          {node.kind}
        </span>
      </div>
      <div className="font-sans text-sm font-medium" style={{ color }}>
        {node.label}
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: string;
}) {
  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
        {label}
      </div>
      <div
        className="mt-0.5 font-sans text-base"
        style={{ color: accent ?? "var(--color-on-surface)" }}
      >
        {value}
      </div>
      {sub && (
        <div className="font-sans text-[11px] text-on-surface-variant">{sub}</div>
      )}
    </div>
  );
}

function NodeExcerpt({ nodeId }: { nodeId: string }) {
  const [excerpt, setExcerpt] = useState<ExcerptResponse | null>(
    excerptCache.get(nodeId) ?? null
  );
  const [loading, setLoading] = useState(!excerptCache.has(nodeId));

  useEffect(() => {
    setExcerpt(excerptCache.get(nodeId) ?? null);
    if (excerptCache.has(nodeId)) {
      setLoading(false);
      return;
    }
    const ac = new AbortController();
    setLoading(true);
    fetch(`/api/excerpt?node_id=${encodeURIComponent(nodeId)}`, { signal: ac.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then((data: ExcerptResponse | null) => {
        if (!data) return;
        excerptCache.set(nodeId, data);
        setExcerpt(data);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
    return () => ac.abort();
  }, [nodeId]);

  if (loading && !excerpt) {
    // Real skeleton: pulse header line + 4 body lines mimicking the final layout.
    return (
      <div
        className="space-y-3 border-t border-outline-variant"
        style={{ paddingTop: "var(--space-4)" }}
      >
        <div className="flex items-baseline justify-between gap-3">
          <div className="flex-1 space-y-2">
            <div className="flex items-center" style={{ gap: 8 }}>
              <span className="lex-skeleton" style={{ height: 12, width: 56 }} />
              <span className="lex-skeleton" style={{ height: 18, width: 64 }} />
            </div>
            <span className="lex-skeleton block" style={{ height: 18, width: "85%" }} />
            <span className="lex-skeleton block" style={{ height: 11, width: "45%" }} />
          </div>
          <span className="lex-skeleton" style={{ height: 14, width: 48 }} />
        </div>
        <div className="space-y-1.5" style={{ paddingTop: 4 }}>
          <span className="lex-skeleton block" style={{ height: 12, width: "95%" }} />
          <span className="lex-skeleton block" style={{ height: 12, width: "92%" }} />
          <span className="lex-skeleton block" style={{ height: 12, width: "87%" }} />
          <span className="lex-skeleton block" style={{ height: 12, width: "60%" }} />
        </div>
        <div
          className="flex items-center font-mono uppercase tracking-widest text-on-surface-variant"
          style={{ gap: 6, fontSize: "var(--text-overline)", paddingTop: 4 }}
        >
          <span
            aria-hidden
            style={{
              display: "inline-block",
              width: 10,
              height: 10,
              borderRadius: "9999px",
              border: "1.5px solid var(--color-outline-variant)",
              borderTopColor: "var(--color-secondary)",
              animation: "lex-spin 0.8s linear infinite",
            }}
          />
          Resolving source HTML
        </div>
      </div>
    );
  }
  if (!excerpt) {
    return (
      <div className="font-sans text-sm italic text-on-surface-variant">
        No excerpt available for this node yet. The agent grounded on it via
        graph metadata only.
      </div>
    );
  }

  return (
    <div className="space-y-3 border-t border-outline-variant pt-4">
      <div className="flex items-baseline justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="section-number">SOURCE</span>
            <span className="meta-pill">{excerpt.publisher.toUpperCase()}</span>
          </div>
          <h3 className="mt-1 truncate font-serif text-base font-semibold">
            {excerpt.docTitle}
          </h3>
          {excerpt.docketNumber && (
            <div className="font-mono text-[11px] text-on-surface-variant">
              {excerpt.docketNumber}
            </div>
          )}
        </div>
        <a
          href={excerpt.sourceUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 font-mono text-sm text-secondary transition hover:underline"
        >
          open &uarr;
        </a>
      </div>
      <div
        className="font-sans text-on-surface [&_mark.claim-match]:rounded-sm [&_mark.claim-match]:bg-secondary/20 [&_mark.claim-match]:px-0.5"
        style={{ fontSize: 14, lineHeight: 1.6 }}
        dangerouslySetInnerHTML={{ __html: excerpt.excerptHtml }}
      />
      <SourceFrame url={excerpt.sourceUrl} />
    </div>
  );
}

/** Toggleable inline iframe of the source page.
 *
 *  Finlex and Vero don't always allow embedding (X-Frame-Options /
 *  Content-Security-Policy: frame-ancestors). We can't reliably detect
 *  that from cross-origin JS — ``onload`` still fires for blocked frames.
 *  Strategy: open the iframe optimistically with sandbox attributes; if
 *  the load takes longer than 4 s we assume it was blocked and show a
 *  fallback link. Either way, the "open ↗" button above still works. */
function SourceFrame({ url }: { url: string }) {
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [stalled, setStalled] = useState(false);
  const stallRef = useRef<number | null>(null);

  useEffect(() => {
    if (!open) return;
    setLoaded(false);
    setStalled(false);
    stallRef.current = window.setTimeout(() => setStalled(true), 4000);
    return () => {
      if (stallRef.current) window.clearTimeout(stallRef.current);
    };
  }, [open, url]);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex items-center gap-2 border border-outline-variant px-3 py-1.5 font-mono text-xs uppercase tracking-wider text-on-surface-variant transition hover:bg-surface-container hover:text-on-surface"
      >
        <span className="material-symbols-outlined" style={{ fontSize: 14 }}>
          open_in_full
        </span>
        Open page inline
      </button>
    );
  }

  return (
    <div className="space-y-2 border border-outline-variant bg-surface-container-low p-2">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
          {loaded ? "page embedded" : stalled ? "embedding blocked" : "loading source…"}
        </span>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant hover:text-on-surface"
          aria-label="Close inline source"
        >
          close
        </button>
      </div>
      {stalled && !loaded && (
        <div className="border border-outline-variant bg-surface-container-lowest p-3">
          <p
            className="font-sans text-on-surface-variant"
            style={{ fontSize: 13, lineHeight: 1.55 }}
          >
            This page didn't load inside the frame within 4 seconds — the
            publisher likely blocks embedding via{" "}
            <code>X-Frame-Options</code>. Use the link below to open it in a
            new tab.
          </p>
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-2 inline-flex items-center gap-1 font-mono text-xs text-secondary hover:underline"
          >
            {url}
            <span className="material-symbols-outlined" style={{ fontSize: 14 }}>
              open_in_new
            </span>
          </a>
        </div>
      )}
      <iframe
        src={url}
        title="Source page"
        sandbox="allow-same-origin allow-scripts allow-popups allow-forms"
        referrerPolicy="no-referrer"
        loading="lazy"
        onLoad={() => setLoaded(true)}
        style={{
          width: "100%",
          height: stalled && !loaded ? 0 : 480,
          border: "1px solid var(--color-outline-variant)",
          background: "var(--color-surface)",
          display: stalled && !loaded ? "none" : "block",
        }}
      />
    </div>
  );
}
