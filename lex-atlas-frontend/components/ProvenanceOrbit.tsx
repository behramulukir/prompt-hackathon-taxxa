"use client";

/**
 * Provenance Orbit — the per-query subgraph view modeled directly on Anthropic's
 * circuit-tracer interface. Five concentric rings indexed by authority rank
 * (binding law innermost, informal outermost), nodes glide into position when
 * the agent commits to a subgraph (the "orbital pull" moment).
 *
 * Tech: D3 selections + Framer Motion v12 for SVG path/transform animation.
 * Framer is React-19-compatible at v12+. Hover handlers update Zustand state
 * directly (no React re-render) so latency stays under 100ms.
 *
 * Inputs (from Zustand):
 *   - orbitNodes, orbitEdges, centerNodeId, conflictPairs, hoveredNodeId, asof
 *
 * Visual states:
 *   - Default: rings faint, nodes at full opacity if isActive (at asof), else 0.3
 *   - Hover: node halo expands, label opacity 1
 *   - Conflict: red dashed arc draws between the conflicting pair
 *   - Asof change: active halo jumps to the newly-valid CTV
 */

import { useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useGraphStore } from "@/lib/store";
import { colorForKind, ORBIT_RING_RADIUS, AUTHORITY_LABELS } from "@/lib/colors";
import type { OrbitNode } from "@/lib/types";

/** Recompute isActive against the current asof using (tValid, tInvalid). */
function isActiveAt(node: OrbitNode, asof: string): boolean {
  // If neither validity bound is set, fall back to the payload's flag
  if (!node.tValid && node.tInvalid === undefined) return node.isActive;
  const now = new Date(asof).getTime();
  const v = node.tValid ? new Date(node.tValid).getTime() : -Infinity;
  const iv = node.tInvalid ? new Date(node.tInvalid).getTime() : Infinity;
  return now >= v && now < iv;
}

const VIEWBOX_W = 800;
const VIEWBOX_H = 720;
const CENTER = { x: VIEWBOX_W / 2, y: VIEWBOX_H / 2 };

interface PlacedNode extends OrbitNode {
  x: number;
  y: number;
}

function placeNodes(nodes: OrbitNode[], centerNodeId: string | null): PlacedNode[] {
  return nodes.map((n) => {
    if (n.id === centerNodeId || n.isCenter) {
      return { ...n, x: CENTER.x, y: CENTER.y };
    }
    const r = ORBIT_RING_RADIUS[n.authorityRank] ?? 250;
    const sameRank = nodes.filter((m) => m.authorityRank === n.authorityRank && m.id !== centerNodeId);
    const idxInRank = sameRank.findIndex((m) => m.id === n.id);
    const angle = (idxInRank / Math.max(sameRank.length, 1)) * 2 * Math.PI - Math.PI / 2;
    return {
      ...n,
      x: CENTER.x + r * Math.cos(angle),
      y: CENTER.y + r * Math.sin(angle),
    };
  });
}

function arcPath(a: { x: number; y: number }, b: { x: number; y: number }, curve = 0.4): string {
  const mx = (a.x + b.x) / 2;
  const my = (a.y + b.y) / 2;
  // Pull control point toward center for orbital feel
  const cx = mx + (CENTER.x - mx) * curve;
  const cy = my + (CENTER.y - my) * curve;
  return `M${a.x},${a.y} Q${cx},${cy} ${b.x},${b.y}`;
}

export function ProvenanceOrbit() {
  const nodes = useGraphStore((s) => s.orbitNodes);
  const edges = useGraphStore((s) => s.orbitEdges);
  const centerNodeId = useGraphStore((s) => s.centerNodeId);
  const conflictPairs = useGraphStore((s) => s.conflictPairs);
  const hoveredNodeId = useGraphStore((s) => s.hoveredNodeId);
  const setHoveredNodeId = useGraphStore((s) => s.setHoveredNodeId);
  const asof = useGraphStore((s) => s.asof);

  // Recompute isActive against the current as-of date so the time-travel
  // slider visibly swaps which node wears the active halo. This is the
  // SAT-Graph RAG temporal model surfacing as a UI affordance.
  const dated = useMemo(
    () => nodes.map((n) => ({ ...n, isActive: isActiveAt(n, asof) })),
    [nodes, asof]
  );

  const placed = useMemo(() => placeNodes(dated, centerNodeId), [dated, centerNodeId]);
  const byId = useMemo(() => {
    const m = new Map<string, PlacedNode>();
    for (const n of placed) m.set(n.id, n);
    return m;
  }, [placed]);

  // Which rings have nodes on them?
  const ranksInUse = useMemo(() => {
    const set = new Set<number>();
    for (const n of dated) if (n.id !== centerNodeId) set.add(n.authorityRank);
    return Array.from(set).sort((a, b) => b - a);
  }, [dated, centerNodeId]);

  if (nodes.length === 0) {
    return (
      <div className="flex h-full w-full items-center justify-center text-text-tertiary">
        <span className="section-number">Provenance orbit — ask a question to populate</span>
      </div>
    );
  }

  return (
    <svg
      viewBox={`0 0 ${VIEWBOX_W} ${VIEWBOX_H}`}
      className="h-full w-full"
      role="img"
      aria-label="Provenance orbit — the subgraph supporting the current answer"
    >
      {/* 1. Authority-rank concentric rings (faint) */}
      <g aria-hidden>
        {ranksInUse.map((rank) => {
          const r = ORBIT_RING_RADIUS[rank] ?? 250;
          return (
            <g key={rank}>
              <circle
                cx={CENTER.x}
                cy={CENTER.y}
                r={r}
                fill="none"
                stroke="#3F3F3F"
                strokeOpacity={0.12}
              />
              {/* Ring label, top-right of each ring */}
              <text
                x={CENTER.x + r + 8}
                y={CENTER.y - 6}
                fontSize={9}
                fill="#7A7A7A"
                fontFamily="var(--font-mono)"
              >
                rank {rank} · {AUTHORITY_LABELS[rank]?.toLowerCase()}
              </text>
            </g>
          );
        })}
      </g>

      {/* 2. Edges as cubic Bezier arcs curving toward center */}
      <g>
        {edges.map((e, i) => {
          const a = byId.get(e.source);
          const b = byId.get(e.target);
          if (!a || !b) return null;
          return (
            <motion.path
              key={`${e.source}-${e.target}-${i}`}
              d={arcPath(a, b)}
              fill="none"
              stroke={colorForKind(a.kind)}
              strokeOpacity={0.32}
              strokeWidth={1.2}
              initial={{ pathLength: 0, opacity: 0 }}
              animate={{ pathLength: 1, opacity: 0.32 }}
              transition={{ duration: 0.7, ease: [0.4, 0, 0.2, 1] }}
            />
          );
        })}
      </g>

      {/* 3. Conflict arcs (red dashed) — draw when Verifier surfaces equal-rank disagreement */}
      <g>
        {conflictPairs.map(([aId, bId], i) => {
          const a = byId.get(aId);
          const b = byId.get(bId);
          if (!a || !b) return null;
          return (
            <motion.path
              key={`conflict-${i}`}
              d={`M${a.x},${a.y} L${b.x},${b.y}`}
              fill="none"
              stroke="#D27B9C"
              strokeWidth={1.6}
              strokeDasharray="4 4"
              initial={{ pathLength: 0, opacity: 0 }}
              animate={{ pathLength: 1, opacity: 0.85 }}
              transition={{ duration: 0.5, ease: [0.4, 0, 0.2, 1] }}
            />
          );
        })}
      </g>

      {/* 4. Nodes — group per node with halo + core + label */}
      <g>
        <AnimatePresence>
          {placed.map((n) => {
            const isHovered = n.id === hoveredNodeId;
            const isCenter = n.id === centerNodeId || n.isCenter;
            const showLabel = isHovered || isCenter;
            const haloR = isHovered ? 18 : n.isActive ? 14 : 0;
            const haloOpacity = isHovered ? 0.7 : n.isActive ? 0.4 : 0;
            const coreR = isCenter ? 8 : 5;
            const coreOpacity = n.isActive || isCenter ? 1 : 0.3;
            const fill = colorForKind(n.kind);

            return (
              <motion.g
                key={n.id}
                initial={{ opacity: 0, scale: 0.6 }}
                animate={{
                  opacity: 1,
                  scale: 1,
                  x: n.x,
                  y: n.y,
                }}
                exit={{ opacity: 0, scale: 0.6 }}
                transition={{ duration: 0.7, ease: [0.4, 0, 0.2, 1] }}
                style={{ cursor: "pointer" }}
                onMouseEnter={() => setHoveredNodeId(n.id)}
                onMouseLeave={() => setHoveredNodeId(null)}
              >
                {/* Outer halo */}
                <motion.circle
                  r={haloR}
                  fill={fill}
                  initial={false}
                  animate={{ r: haloR, opacity: haloOpacity }}
                  transition={{ duration: 0.2, ease: [0.4, 0, 0.2, 1] }}
                />
                {/* Solid core */}
                <motion.circle
                  r={coreR}
                  fill={fill}
                  initial={false}
                  animate={{ opacity: coreOpacity }}
                  transition={{ duration: 0.2 }}
                />
                {/* Conflict marker — small red ring on conflicted nodes */}
                {n.isConflicted && (
                  <circle
                    r={coreR + 4}
                    fill="none"
                    stroke="#D27B9C"
                    strokeWidth={1.2}
                    strokeDasharray="2 2"
                  />
                )}
                {/* Label */}
                <motion.text
                  y={-14}
                  textAnchor="middle"
                  fontSize={11}
                  fontFamily="var(--font-sans)"
                  fill="#F4F4F4"
                  initial={false}
                  animate={{ opacity: showLabel ? 1 : 0 }}
                  transition={{ duration: 0.2 }}
                  style={{ pointerEvents: "none" }}
                >
                  {n.label}
                </motion.text>
              </motion.g>
            );
          })}
        </AnimatePresence>
      </g>
    </svg>
  );
}
