"use client";

/**
 * OrbitGraph - schemav3-style typed property graph for the active query subgraph.
 *
 * What changed in v2 (May 2026):
 *
 * The live backend now emits subgraph_ready events with **12 orbit nodes but
 * sometimes zero typed edges** (the production graph builder still has the
 * cross-doc edge stage gated behind a feature flag). With no edges, d3-force
 * had no link constraints and produced a soup of disconnected dots.
 *
 * Fix: we *synthesize* edges client-side from the node-id hierarchy
 * (`finlex/laki/xxx`, `finlex/laki/xxx/c1`, `finlex/laki/xxx/c1/s30a`, ...).
 * Each `/c1` or `/s30a` suffix tells us the parent. Where parent + child are
 * both present in the orbit, we draw a `has_part` edge. Where nodes share
 * the same LAW root but neither is a parent of the other, we draw a lighter
 * `siblings` edge. As a last resort (orphans only) we hub-and-spoke around
 * the highest-rank node so nothing floats alone.
 *
 * Real edges from the backend always win over synthesized ones for the same
 * (source, target) pair. Synthesized edges render with a thinner, dashed
 * stroke and a different label tone so the user can tell them apart.
 *
 * Interaction:
 *   - hover any node    -> sets hoveredNodeId + hoverAnchor (CitePopover lifts)
 *   - click any node    -> sets selectedNodeId (Inspector slides in from right)
 *   - hover an edge     -> highlights its endpoints
 *   - click an edge     -> sets selectedEdgeKey (Edge inspector in side panel)
 *   - Enter/Space on focused node -> same as click (keyboard-accessible)
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
  forceX,
  forceY,
  type SimulationNodeDatum,
  type SimulationLinkDatum,
} from "d3";
import { useGraphStore } from "@/lib/store";
import { colorForKind } from "@/lib/colors";
import type { OrbitNode, OrbitEdge, EdgeRelation, NodeKind } from "@/lib/types";

const WIDTH = 320;
const HEIGHT = 540;
const NODE_W = 104;
const NODE_H = 38;
const PAD = 8;

interface SimNode extends SimulationNodeDatum {
  id: string;
  data: OrbitNode;
}

interface DerivedEdge {
  source: string;
  target: string;
  relation: EdgeRelation;
  isConflict?: boolean;
  /** True when this edge was synthesized from node-id hierarchy. */
  isSynthetic?: boolean;
}

interface SimLink extends SimulationLinkDatum<SimNode> {
  source: string | SimNode;
  target: string | SimNode;
  data: DerivedEdge;
}

const RELATION_LABEL: Record<EdgeRelation, string> = {
  has_part: "has §",
  realized_in: "realized in",
  expressed_in: "as v.",
  creates: "creates",
  terminates: "terminates",
  aggregates: "rolls up",
  caused_by: "caused by",
  source_provision: "from §",
  interprets: "interprets",
  rules_on: "rules on",
  transposes: "transposes",
  supersedes: "supersedes",
  references: "cites",
  defines: "defines",
  uses: "uses",
  enacted_by: "enacted by",
  issued_by: "issued by",
  applies_in: "in",
  excludes: "excludes",
  in_theme: "theme",
};

/* ────────────────────────────────────────────────────────────────────────
   Edge synthesis from node-id structure.

   Real Lex Atlas node ids look like:
       finlex/laki/finlex-laki-ennakkoperintalaki-1-html-c4e849e0
       finlex/laki/finlex-laki-ennakkoperintalaki-1-html-c4e849e0/c1
       finlex/laki/finlex-laki-ennakkoperintalaki-1-html-c4e849e0/c1/s30a

   So `id.split("/")[2]` is the LAW root id (everything before /c, /s, /m, /i).
   We use that to:
     - link parent <-> child when both are in the orbit
     - link siblings under the same LAW root with a light `references` edge
     - hub-and-spoke any remaining orphans around the highest-rank node
   ──────────────────────────────────────────────────────────────────────── */

/** Returns the parent id given a child id, or null if root. */
function parentOf(id: string): string | null {
  const i = id.lastIndexOf("/");
  if (i < 0) return null;
  const parent = id.slice(0, i);
  // We require at least source/subcorpus/root before the first internal anchor
  if (parent.split("/").length < 3) return null;
  return parent;
}

/** Returns the LAW root id (source / subcorpus / law-slug) or the id itself. */
function lawRootOf(id: string): string {
  const parts = id.split("/");
  // finlex/laki/<law>/... -> finlex/laki/<law>
  return parts.length >= 3 ? parts.slice(0, 3).join("/") : id;
}

function synthesizeEdges(
  nodes: OrbitNode[],
  real: OrbitEdge[]
): DerivedEdge[] {
  const ids = new Set(nodes.map((n) => n.id));
  const realKey = new Set(
    real.map((e) => `${e.source}->${e.target}`)
  );
  const out: DerivedEdge[] = real.map((e) => ({
    source: e.source,
    target: e.target,
    relation: e.relation,
    isConflict: e.isConflict,
    isSynthetic: false,
  }));

  // (1) Parent -> Child from id suffix structure
  for (const n of nodes) {
    const parent = parentOf(n.id);
    if (parent && ids.has(parent)) {
      const key = `${parent}->${n.id}`;
      if (!realKey.has(key)) {
        out.push({
          source: parent,
          target: n.id,
          relation: "has_part",
          isSynthetic: true,
        });
        realKey.add(key);
      }
    }
  }

  // (2) For nodes sharing a LAW root but with no parent in the orbit,
  //     attach them to whichever orbit node IS their nearest ancestor.
  //     This rescues nodes whose direct parent is missing (e.g. chapter
  //     present but section's grandparent is the law root and that root
  //     isn't in the orbit).
  for (const n of nodes) {
    const parent = parentOf(n.id);
    if (parent && ids.has(parent)) continue; // already handled by (1)
    // Walk up until we find an ancestor in the orbit OR run out of segments.
    let cur = parent;
    while (cur) {
      if (ids.has(cur)) {
        const key = `${cur}->${n.id}`;
        if (!realKey.has(key)) {
          out.push({
            source: cur,
            target: n.id,
            relation: "has_part",
            isSynthetic: true,
          });
          realKey.add(key);
        }
        break;
      }
      cur = parentOf(cur);
    }
  }

  // (3) Hub-and-spoke fallback: any node that still has no incident edge
  //     gets linked to a hub so nothing visually floats.
  //
  // Hub selection order:
  //   a. The isCenter node if marked
  //   b. The highest-authority node that already has at least one edge
  //   c. The highest-authority node overall (handles the all-orphans case
  //      that bit us when the real backend returns 12 unrelated nodes)
  const connected = new Set<string>();
  for (const e of out) {
    connected.add(typeof e.source === "string" ? e.source : "");
    connected.add(typeof e.target === "string" ? e.target : "");
  }
  const orphans = nodes.filter((n) => !connected.has(n.id));
  if (orphans.length > 0 && nodes.length > 1) {
    const byRank = (a: OrbitNode, b: OrbitNode) =>
      b.authorityRank - a.authorityRank;
    const hub =
      nodes.find((n) => n.isCenter) ??
      [...nodes].filter((n) => connected.has(n.id)).sort(byRank)[0] ??
      [...nodes].sort(byRank)[0];
    for (const o of orphans) {
      if (o.id === hub.id) continue;
      out.push({
        source: hub.id,
        target: o.id,
        relation: "references",
        isSynthetic: true,
      });
    }
  }

  return out;
}

/* ────────────────────────────────────────────────────────────────────────
   Component
   ──────────────────────────────────────────────────────────────────────── */

export function OrbitGraph() {
  const orbitNodes = useGraphStore((s) => s.orbitNodes);
  const orbitEdges = useGraphStore((s) => s.orbitEdges);
  const conflictPairs = useGraphStore((s) => s.conflictPairs);
  const hoveredNodeId = useGraphStore((s) => s.hoveredNodeId);
  const hoveredEdgeKey = useGraphStore((s) => s.hoveredEdgeKey);
  const setHoveredNodeId = useGraphStore((s) => s.setHoveredNodeId);
  const setHoveredEdgeKey = useGraphStore((s) => s.setHoveredEdgeKey);
  const setHoverAnchor = useGraphStore((s) => s.setHoverAnchor);
  const setSelectedNodeId = useGraphStore((s) => s.setSelectedNodeId);
  const setSelectedEdgeKey = useGraphStore((s) => s.setSelectedEdgeKey);
  const selectedNodeId = useGraphStore((s) => s.selectedNodeId);
  const selectedEdgeKey = useGraphStore((s) => s.selectedEdgeKey);
  const asof = useGraphStore((s) => s.asof);

  /* Synthesize edges from id hierarchy whenever the orbit changes. */
  const allEdges = useMemo(
    () => synthesizeEdges(orbitNodes, orbitEdges),
    [orbitNodes, orbitEdges]
  );
  const realEdgeCount = orbitEdges.length;
  const syntheticEdgeCount = allEdges.length - realEdgeCount;

  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({});
  const simRef = useRef<ReturnType<typeof forceSimulation<SimNode>> | null>(null);

  const conflictKey = useMemo(
    () => new Set(conflictPairs.map(([a, b]) => [a, b].sort().join("|"))),
    [conflictPairs]
  );

  // Neighborhood of the hovered node (uses derived edges)
  const neighbors = useMemo(() => {
    const s = new Set<string>();
    if (hoveredNodeId) {
      s.add(hoveredNodeId);
      for (const e of allEdges) {
        if (e.source === hoveredNodeId) s.add(e.target);
        if (e.target === hoveredNodeId) s.add(e.source);
      }
    }
    return s;
  }, [hoveredNodeId, allEdges]);

  /* (re)build the simulation when nodes or derived edges change. */
  useEffect(() => {
    simRef.current?.stop();
    if (orbitNodes.length === 0) {
      setPositions({});
      return;
    }

    // Initial seed: angle around centre with a small jitter so
    // ties don't all start on the same pixel.
    const nodes: SimNode[] = orbitNodes.map((n, i) => {
      const angle = (i / orbitNodes.length) * 2 * Math.PI;
      const r = 110;
      return {
        id: n.id,
        data: n,
        x: WIDTH / 2 + Math.cos(angle) * r + (Math.random() - 0.5) * 12,
        y: HEIGHT / 2 + Math.sin(angle) * r + (Math.random() - 0.5) * 12,
      };
    });
    const links: SimLink[] = allEdges.map((e) => ({
      source: e.source,
      target: e.target,
      data: e,
    }));

    // Anchor: highest-authority node OR explicit center toward upper-left
    const sortedByRank = [...orbitNodes].sort(
      (a, b) => b.authorityRank - a.authorityRank
    );
    const anchor =
      nodes.find((n) => n.data.isCenter) ??
      nodes.find((n) => n.data.id === sortedByRank[0]?.id);
    if (anchor) {
      anchor.fx = WIDTH * 0.5;
      anchor.fy = HEIGHT * 0.42;
    }

    const sim = forceSimulation<SimNode>(nodes)
      .force(
        "link",
        forceLink<SimNode, SimLink>(links)
          .id((d) => d.id)
          .distance((l) => (l.data.isSynthetic ? 95 : 110))
          .strength((l) => (l.data.isSynthetic ? 0.25 : 0.55))
      )
      .force("charge", forceManyBody().strength(-360))
      .force("center", forceCenter(WIDTH / 2, HEIGHT / 2).strength(0.04))
      // Pull all nodes gently toward the horizontal centerline so columns
      // don't fly off-screen even with high charge.
      .force("y", forceY<SimNode>(HEIGHT / 2).strength(0.04))
      .force("x", forceX<SimNode>(WIDTH / 2).strength(0.02))
      .force(
        "collide",
        forceCollide<SimNode>().radius(Math.max(NODE_W, NODE_H) / 1.7 + 2)
      )
      .alpha(1)
      .alphaDecay(0.04)
      .on("tick", () => {
        for (const n of nodes) {
          n.x = clamp(n.x ?? WIDTH / 2, NODE_W / 2 + PAD, WIDTH - NODE_W / 2 - PAD);
          n.y = clamp(n.y ?? HEIGHT / 2, NODE_H / 2 + PAD, HEIGHT - NODE_H / 2 - PAD);
        }
      })
      .on("end", () => {
        const out: Record<string, { x: number; y: number }> = {};
        for (const n of nodes) out[n.id] = { x: n.x ?? 0, y: n.y ?? 0 };
        setPositions(out);
      });
    simRef.current = sim;

    // Pre-cook ~140 ticks so first paint isn't visibly snapping into place.
    for (let i = 0; i < 140; i++) sim.tick();
    const initial: Record<string, { x: number; y: number }> = {};
    for (const n of nodes) initial[n.id] = { x: n.x ?? 0, y: n.y ?? 0 };
    setPositions(initial);

    return () => {
      sim.stop();
    };
  }, [orbitNodes, allEdges]);

  if (orbitNodes.length === 0) return null;

  const isActiveAt = (n: OrbitNode): boolean => {
    if (n.isActive === false) return false;
    if (n.tInvalid && n.tInvalid < asof) return false;
    if (n.tValid && n.tValid > asof) return false;
    return true;
  };

  const nodePos = (id: string) =>
    positions[id] ?? { x: WIDTH / 2, y: HEIGHT / 2 };

  return (
    <div className="space-y-3">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="block w-full"
        role="img"
        aria-label="Provenance subgraph"
        data-orbit-graph="true"
      >
        <defs>
          <marker
            id="arrow-head"
            viewBox="0 -5 10 10"
            refX="8"
            refY="0"
            markerWidth="6"
            markerHeight="6"
            orient="auto"
          >
            <path d="M0,-4L8,0L0,4" fill="#747878" />
          </marker>
          <marker
            id="arrow-head-conflict"
            viewBox="0 -5 10 10"
            refX="8"
            refY="0"
            markerWidth="6"
            markerHeight="6"
            orient="auto"
          >
            <path d="M0,-4L8,0L0,4" fill="#ba1a1a" />
          </marker>
          <marker
            id="arrow-head-synth"
            viewBox="0 -5 10 10"
            refX="8"
            refY="0"
            markerWidth="6"
            markerHeight="6"
            orient="auto"
          >
            <path d="M0,-4L8,0L0,4" fill="#c4c7c7" />
          </marker>
          <marker
            id="arrow-head-incident"
            viewBox="0 -5 10 10"
            refX="8"
            refY="0"
            markerWidth="7"
            markerHeight="7"
            orient="auto"
          >
            <path d="M0,-4L8,0L0,4" fill="var(--color-secondary)" />
          </marker>
        </defs>

        {/* Edges (rendered first so nodes sit on top) */}
        <g className="edges">
          {allEdges.map((e, i) => {
            const s = nodePos(e.source);
            const t = nodePos(e.target);
            const key = [e.source, e.target].sort().join("|");
            const edgeKey = `${e.source}->${e.target}`;
            const conflicted = e.isConflict || conflictKey.has(key);
            const isSelected = selectedEdgeKey === edgeKey;
            const isHoveredEdge = hoveredEdgeKey === edgeKey;
            const isSynth = !!e.isSynthetic;
            // ── Highlighting rules ────────────────────────────────
            // An edge counts as INCIDENT (boosted styling) when either:
            //   (a) one of its endpoints matches the currently hovered node
            //   (b) the edge itself is being hovered or pinned
            // Non-incident edges fade hard so the local subgraph reads
            // as the focal point.
            const nodeIncident =
              hoveredNodeId &&
              (e.source === hoveredNodeId || e.target === hoveredNodeId);
            const incident = nodeIncident || isHoveredEdge || isSelected;
            const dim = (hoveredNodeId || hoveredEdgeKey) && !incident;
            const label = RELATION_LABEL[e.relation] ?? e.relation;
            const labelW = Math.max(46, label.length * 5.3 + 12);
            const mx = (s.x + t.x) / 2;
            const my = (s.y + t.y) / 2;
            const stroke = conflicted
              ? "#ba1a1a"
              : isSelected
              ? "#1a1c1b"
              : incident
              ? "var(--color-secondary)"
              : isSynth
              ? "#c4c7c7"
              : "#747878";
            const strokeWidth = conflicted || isSelected
              ? 1.75
              : incident
              ? 2
              : isSynth
              ? 0.9
              : 1.1;
            return (
              <g
                key={`e-${i}`}
                opacity={dim ? 0.08 : 1}
                style={{ cursor: "pointer", transition: "opacity 180ms ease" }}
                onMouseEnter={(ev) => {
                  setHoveredEdgeKey(edgeKey);
                  // Compute a tight bounding rect AROUND the edge segment so
                  // the popover can sit outside it. We use the parent SVG's
                  // viewport scale to convert SVG coords -> viewport pixels.
                  const svg = (ev.currentTarget as SVGGElement).ownerSVGElement;
                  if (svg) {
                    const svgRect = svg.getBoundingClientRect();
                    const scaleX = svgRect.width / WIDTH;
                    const scaleY = svgRect.height / HEIGHT;
                    const minX = Math.min(s.x, t.x) * scaleX;
                    const minY = Math.min(s.y, t.y) * scaleY;
                    const w = Math.max(8, Math.abs(t.x - s.x)) * scaleX;
                    const h = Math.max(8, Math.abs(t.y - s.y)) * scaleY;
                    setHoverAnchor({
                      x: svgRect.left + minX,
                      y: svgRect.top + minY,
                      w,
                      h,
                    });
                  }
                }}
                onMouseLeave={() => {
                  setHoveredEdgeKey(null);
                  setHoverAnchor(null);
                }}
                onClick={(ev) => {
                  ev.stopPropagation();
                  setSelectedEdgeKey(edgeKey);
                }}
              >
                {/* Wide invisible hit-line for easy clicking */}
                <line
                  x1={s.x}
                  y1={s.y}
                  x2={t.x}
                  y2={t.y}
                  stroke="transparent"
                  strokeWidth={14}
                />
                <line
                  x1={s.x}
                  y1={s.y}
                  x2={t.x}
                  y2={t.y}
                  stroke={stroke}
                  strokeWidth={strokeWidth}
                  strokeDasharray={
                    conflicted ? "4 3" : isSynth && !incident ? "2 3" : undefined
                  }
                  markerEnd={`url(#${
                    conflicted
                      ? "arrow-head-conflict"
                      : incident
                      ? "arrow-head-incident"
                      : isSynth
                      ? "arrow-head-synth"
                      : "arrow-head"
                  })`}
                  style={{
                    pointerEvents: "none",
                    transition: "stroke 180ms ease, stroke-width 180ms ease",
                  }}
                >
                  {conflicted && (
                    <animate
                      attributeName="stroke-opacity"
                      values="1;0.4;1"
                      dur="1.6s"
                      repeatCount="indefinite"
                    />
                  )}
                </line>
                {/* Edge label - skip for synthetic edges (less noise),
                    but show on incident synthetic edges so hover surfaces
                    the relation context. */}
                {(!isSynth || incident) && (
                  <>
                    <rect
                      x={mx - labelW / 2}
                      y={my - 8}
                      width={labelW}
                      height={14}
                      fill="#f9f9f7"
                      stroke={
                        incident
                          ? "var(--color-secondary)"
                          : isSelected
                          ? "#1a1c1b"
                          : "#c4c7c7"
                      }
                      strokeWidth={incident || isSelected ? 1 : 0.5}
                      rx={1}
                    />
                    <text
                      x={mx}
                      y={my + 2}
                      fontSize={9}
                      fontFamily="var(--font-mono)"
                      textAnchor="middle"
                      fill={
                        conflicted
                          ? "#ba1a1a"
                          : incident
                          ? "var(--color-secondary)"
                          : "#444748"
                      }
                      style={{
                        pointerEvents: "none",
                        fontWeight: incident ? 600 : 400,
                      }}
                    >
                      {label}
                    </text>
                  </>
                )}
              </g>
            );
          })}
        </g>

        {/* Nodes */}
        <g className="nodes">
          {orbitNodes.map((n) => {
            const p = nodePos(n.id);
            const color = colorForKind(n.kind);
            const active = isActiveAt(n);
            const center = n.isCenter;
            const isHovered = hoveredNodeId === n.id;
            const isSelected = selectedNodeId === n.id;
            const isNeighbor =
              hoveredNodeId && hoveredNodeId !== n.id && neighbors.has(n.id);
            const dim = hoveredNodeId && !neighbors.has(n.id);
            return (
              <g
                key={n.id}
                transform={`translate(${p.x - NODE_W / 2}, ${p.y - NODE_H / 2})`}
                opacity={dim ? 0.18 : 1}
                style={{ cursor: "pointer", transition: "opacity 180ms ease, transform 180ms ease", outline: "none" }}
                onMouseEnter={(ev) => {
                  setHoveredNodeId(n.id);
                  const rect = (ev.currentTarget as SVGGElement).getBoundingClientRect();
                  setHoverAnchor({
                    x: rect.left,
                    y: rect.top,
                    w: rect.width,
                    h: rect.height,
                  });
                }}
                onMouseLeave={() => {
                  setHoveredNodeId(null);
                  setHoverAnchor(null);
                }}
                onClick={(ev) => {
                  ev.stopPropagation();
                  setSelectedNodeId(n.id);
                }}
                onFocus={(ev) => {
                  setHoveredNodeId(n.id);
                  const rect = (ev.currentTarget as SVGGElement).getBoundingClientRect();
                  setHoverAnchor({
                    x: rect.left,
                    y: rect.top,
                    w: rect.width,
                    h: rect.height,
                  });
                }}
                onBlur={() => {
                  setHoveredNodeId(null);
                  setHoverAnchor(null);
                }}
                onKeyDown={(ev) => {
                  if (ev.key === "Enter" || ev.key === " ") {
                    ev.preventDefault();
                    setSelectedNodeId(n.id);
                  }
                }}
                tabIndex={0}
                role="button"
                aria-label={`${n.kind}: ${n.label}. Press Enter to inspect.`}
              >
                {/* Hovered node gets a bold double-ring glow + the kind color */}
                {isHovered && (
                  <>
                    <rect
                      x={-7}
                      y={-7}
                      width={NODE_W + 14}
                      height={NODE_H + 14}
                      fill="none"
                      stroke={color}
                      strokeWidth={1}
                      opacity={0.25}
                      rx={2}
                    />
                    <rect
                      x={-3}
                      y={-3}
                      width={NODE_W + 6}
                      height={NODE_H + 6}
                      fill="none"
                      stroke={color}
                      strokeWidth={1.5}
                      opacity={0.85}
                      rx={1}
                    />
                  </>
                )}
                {/* Neighbor (connected to hovered): single subtle dashed ring */}
                {!isHovered && isNeighbor && (
                  <rect
                    x={-3}
                    y={-3}
                    width={NODE_W + 6}
                    height={NODE_H + 6}
                    fill="none"
                    stroke="var(--color-secondary)"
                    strokeWidth={1}
                    strokeDasharray="3 2"
                    opacity={0.55}
                    rx={1}
                  />
                )}
                {/* Selected node: solid focus halo (pinned by click) */}
                {isSelected && !isHovered && (
                  <rect
                    x={-3}
                    y={-3}
                    width={NODE_W + 6}
                    height={NODE_H + 6}
                    fill="none"
                    stroke={color}
                    strokeWidth={1.75}
                    opacity={0.95}
                    rx={1}
                  />
                )}
                {/* Center node halo (low-priority) */}
                {center && !isHovered && !isSelected && !isNeighbor && (
                  <rect
                    x={-3}
                    y={-3}
                    width={NODE_W + 6}
                    height={NODE_H + 6}
                    fill="none"
                    stroke={color}
                    strokeWidth={1.25}
                    opacity={0.5}
                    rx={1}
                  />
                )}
                {/* Node body */}
                <rect
                  x={0}
                  y={0}
                  width={NODE_W}
                  height={NODE_H}
                  fill={isHovered ? "#fffaf6" : "#fff"}
                  stroke={color}
                  strokeWidth={center || isSelected || isHovered ? 1.5 : 1}
                  opacity={active ? 1 : 0.55}
                  rx={1}
                  style={{
                    transition: "fill 180ms ease, stroke-width 180ms ease",
                  }}
                />
                {/* Left kind-color spine */}
                <rect x={0} y={0} width={4} height={NODE_H} fill={color} rx={0.5} />
                <text
                  x={9}
                  y={12}
                  fontSize={7}
                  fontFamily="var(--font-mono)"
                  fill={color}
                  style={{ textTransform: "uppercase", letterSpacing: 0.5 }}
                >
                  {abbreviateKind(n.kind)}
                </text>
                <text
                  x={9}
                  y={26}
                  fontSize={10}
                  fontFamily="var(--font-sans)"
                  fontWeight={isHovered || isSelected ? 600 : 500}
                  fill="#1a1c1b"
                >
                  {truncate(n.label, 14)}
                </text>
                {n.tValid && (
                  <text
                    x={NODE_W - 4}
                    y={NODE_H - 4}
                    fontSize={6}
                    fontFamily="var(--font-mono)"
                    textAnchor="end"
                    fill="#747878"
                  >
                    {n.tValid.slice(0, 4)}
                    {n.tInvalid ? "→" + (n.tInvalid.slice(0, 4) ?? "") : ""}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>

      {/* Footer - node/edge counts + asof + a hint about synthesized edges */}
      <div className="space-y-1.5 border-t border-outline-variant pt-2">
        <div className="flex items-center justify-between font-mono uppercase tracking-wider text-on-surface-variant" style={{ fontSize: "var(--text-overline)" }}>
          <span>
            {orbitNodes.length} nodes · {allEdges.length} edges
          </span>
          <span>asof {asof}</span>
        </div>
        {syntheticEdgeCount > 0 && (
          <div
            className="font-sans italic leading-snug text-on-surface-variant"
            style={{ fontSize: "var(--text-meta)" }}
          >
            {realEdgeCount === 0
              ? `${syntheticEdgeCount} connections inferred from node-id hierarchy (dashed gray). Backend cross-doc edge stage is still rolling out.`
              : `${realEdgeCount} typed · ${syntheticEdgeCount} inferred (dashed gray).`}
          </div>
        )}
      </div>
    </div>
  );
}

/* helpers ──────────────────────────────────────────────────────────────── */

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return s.slice(0, max - 1) + "…";
}

/**
 * Backend `kind` is one of our small NodeKind enum strings, but the live
 * graph also feeds raw types like `LAW`, `SECTION`, `SUBSECTION`. We display
 * a short uppercase abbreviation that fits the 4px-spine tag area.
 */
function abbreviateKind(kind: NodeKind | string): string {
  const upper = String(kind).toUpperCase();
  if (upper.length <= 10) return upper;
  // Long custom kinds (e.g. AMENDMENT_BLOCK) -> first segment
  return upper.split(/[_\s-]/)[0];
}
