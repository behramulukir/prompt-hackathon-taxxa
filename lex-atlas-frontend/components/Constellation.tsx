"use client";

/**
 * Constellation Map — the GPU-rendered galaxy of the Finlex + Vero corpus.
 * Uses @cosmos.gl/graph v2.6.x (regl + WebGL1, force simulation on GPU).
 *
 * v2.x is synchronous: `new Graph(div, config)` returns a usable instance
 * immediately. v3 added the `await graph.ready` promise but isn't published
 * on npm yet.
 *
 * Subscribes to useGraphStore for:
 *   - highlightedIndices → per-node halo (walk-discovery pulses)
 *   - dimmed → global opacity dim (orbital pull active)
 *   - focusedIndices → camera fit to a subset
 */

import { useEffect, useRef } from "react";
import { Graph as CosmosGraph } from "@cosmos.gl/graph";
import { useGraphStore } from "@/lib/store";
import { colorForKindFloat32 } from "@/lib/colors";
import type { ConstellationNode, NodeKind } from "@/lib/types";

// Loose typing for the cosmos.gl Graph — v2.x has subtle differences
// across patch releases for optional methods (setPointOpacities, setPointSizes).
// We feature-detect at call time rather than relying on a stable type.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyGraph = any;

const SPACE_SIZE = 8192;
const DEFAULT_POINT_SIZE = 1.5;
const HIGHLIGHT_POINT_SIZE = 4.5;

interface ConstellationProps {
  nodes: ConstellationNode[];
  edges: Array<{ source: number; target: number }>;
  /** Render quality knobs — lower for slower machines */
  pointSize?: number;
  /** Show a faint connection mesh; true is more atmospheric but eats GPU */
  showLinks?: boolean;
  onPointClick?: (nodeId: string) => void;
}

export function Constellation({
  nodes,
  edges,
  pointSize = DEFAULT_POINT_SIZE,
  showLinks = true,
  onPointClick,
}: ConstellationProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<AnyGraph | null>(null);
  const readyRef = useRef(false);

  const highlightedIndices = useGraphStore((s) => s.highlightedIndices);
  const dimmed = useGraphStore((s) => s.dimmed);
  const focusedIndices = useGraphStore((s) => s.focusedIndices);
  const setLookups = useGraphStore((s) => s.setLookups);

  // 1. One-time initialization — runs on mount, never re-runs.
  // cosmos.gl v2.x is synchronous: `new Graph(div, config)` returns a
  // usable instance immediately. No `graph.ready` promise.
  useEffect(() => {
    if (!containerRef.current || nodes.length === 0) return;

    let graph: AnyGraph | null = null;
    try {
      // CosmosGraph is the v2.x default export from @cosmos.gl/graph.
      // v2 is synchronous — no `await graph.ready` needed.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const GraphCtor = CosmosGraph as any;

      graph = new GraphCtor(containerRef.current, {
        spaceSize: SPACE_SIZE,
        backgroundColor: "#0A0A0A",
        // Physics — chill, not chaotic
        simulationFriction: 0.12,
        simulationGravity: 0.05,
        simulationRepulsion: 0.5,
        simulationLinkSpring: 0.3,
        simulationLinkDistance: 6,
        // Visuals
        pointSize,
        linkWidth: showLinks ? 0.5 : 0,
        linkColor: "#3F3F3F",
        linkOpacity: showLinks ? 0.22 : 0,
        curvedLinks: true,
        // Interaction
        fitViewOnInit: true,
        fitViewDelay: 1200,
        fitViewPadding: 0.18,
        enableDrag: false,
        enableZoom: true,
        // Events — bridge cosmos.gl integer index back to our string ID
        onClick: (idx: number | undefined) => {
          if (idx === undefined || !onPointClick) return;
          const node = nodes[idx];
          if (node) onPointClick(node.id);
        },
      });
    } catch (err) {
      // WebGL unavailable / package incompatible — fail gracefully (no galaxy,
      // page still works).
      console.warn("[Constellation] cosmos.gl init failed:", err);
      return;
    }

    if (!graph) return;
    graphRef.current = graph;

    // Pack positions
    const positions = new Float32Array(nodes.length * 2);
    for (let i = 0; i < nodes.length; i++) {
      positions[i * 2] = nodes[i].x ?? (Math.random() - 0.5) * SPACE_SIZE * 0.7;
      positions[i * 2 + 1] = nodes[i].y ?? (Math.random() - 0.5) * SPACE_SIZE * 0.7;
    }

    // Pack colors (4 floats per node: RGBA, normalized)
    const colors = new Float32Array(nodes.length * 4);
    for (let i = 0; i < nodes.length; i++) {
      const [r, g, b, a] = colorForKindFloat32(nodes[i].kind);
      colors[i * 4] = r;
      colors[i * 4 + 1] = g;
      colors[i * 4 + 2] = b;
      colors[i * 4 + 3] = a;
    }

    // Pack sizes
    const sizes = new Float32Array(nodes.length).fill(pointSize);

    // Pack links
    const linkBuf =
      edges.length > 0 ? new Float32Array(edges.length * 2) : undefined;
    if (linkBuf) {
      for (let i = 0; i < edges.length; i++) {
        linkBuf[i * 2] = edges[i].source;
        linkBuf[i * 2 + 1] = edges[i].target;
      }
    }

    // Apply data — try new API first (setPointPositions), fall back to v1 setData.
    try {
      if (typeof graph.setPointPositions === "function") {
        graph.setPointPositions(positions);
        if (linkBuf && typeof graph.setLinks === "function") {
          graph.setLinks(linkBuf);
        }
        if (typeof graph.setPointColors === "function") {
          graph.setPointColors(colors);
        }
        if (typeof graph.setPointSizes === "function") {
          graph.setPointSizes(sizes);
        }
      } else if (typeof graph.setData === "function") {
        // v1.x legacy fallback — object-shaped data
        const objNodes = nodes.map((n, i) => ({
          id: n.id,
          x: positions[i * 2],
          y: positions[i * 2 + 1],
          color: [colors[i * 4], colors[i * 4 + 1], colors[i * 4 + 2], colors[i * 4 + 3]],
          size: sizes[i],
        }));
        const objLinks = edges.map((e) => ({ source: e.source, target: e.target }));
        graph.setData(objNodes, objLinks);
      }

      // Build the lookup table for cross-component access
      const idToIdx: Record<string, number> = {};
      const kindMap: Record<string, NodeKind> = {};
      for (let i = 0; i < nodes.length; i++) {
        idToIdx[nodes[i].id] = i;
        kindMap[nodes[i].id] = nodes[i].kind;
      }
      setLookups(idToIdx, kindMap);

      // Render
      if (typeof graph.render === "function") graph.render();
      readyRef.current = true;
    } catch (err) {
      console.warn("[Constellation] data load failed:", err);
    }

    return () => {
      readyRef.current = false;
      try {
        graphRef.current?.stop?.();
        graphRef.current?.destroy?.();
      } catch {}
      graphRef.current = null;
    };
    // Intentionally mount-only — the corpus is static after ingest.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 2. Apply dim opacity when orbital pull is active.
  // setPointOpacities may not exist on all v2.x patch releases — feature-detect.
  useEffect(() => {
    if (!readyRef.current || !graphRef.current) return;
    const g = graphRef.current;
    if (typeof g.setPointOpacities !== "function") return;
    const opacities = new Float32Array(nodes.length);
    opacities.fill(dimmed ? 0.08 : 1.0);
    for (const idx of highlightedIndices) {
      if (idx >= 0 && idx < nodes.length) opacities[idx] = 1.0;
    }
    try {
      g.setPointOpacities(opacities);
    } catch {}
  }, [dimmed, highlightedIndices, nodes.length]);

  // 3. Walk-discovery halo animation (per-frame, 600ms ease).
  useEffect(() => {
    if (!readyRef.current || !graphRef.current || highlightedIndices.length === 0) return;
    const g = graphRef.current;
    if (typeof g.setPointSizes !== "function") return;

    const start = performance.now();
    let raf = 0;
    const animate = () => {
      const t = Math.min((performance.now() - start) / 600, 1);
      const eased = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      const envelope = eased * (1 - t) * 4;

      const sizes = new Float32Array(nodes.length).fill(pointSize);
      for (const idx of highlightedIndices) {
        if (idx >= 0 && idx < nodes.length) {
          sizes[idx] = pointSize + envelope * (HIGHLIGHT_POINT_SIZE - pointSize);
        }
      }
      try {
        g.setPointSizes(sizes);
      } catch {}
      if (t < 1) raf = requestAnimationFrame(animate);
    };
    raf = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(raf);
  }, [highlightedIndices, nodes.length, pointSize]);

  // 4. Camera focus on subset (orbital pull pre-positioning).
  useEffect(() => {
    if (!readyRef.current || !graphRef.current || focusedIndices.length === 0) return;
    try {
      graphRef.current.fitViewByPointIndices?.(focusedIndices, 700, 0.2);
    } catch {}
  }, [focusedIndices]);

  return (
    <div
      ref={containerRef}
      className="absolute inset-0 h-full w-full"
      style={{ background: "var(--color-bg-base)" }}
      role="img"
      aria-label={`Constellation map of ${nodes.length.toLocaleString()} corpus nodes`}
    />
  );
}
