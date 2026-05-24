"use client";

import { create } from "zustand";
import type { OrbitEdge, OrbitNode, NodeKind, DebateTrace } from "./types";

/** Streamed debate fragment — accumulated per party as `debate_token` events arrive. */
export interface DebateFragment {
  party: "A" | "B";
  text: string;
}

/**
 * Agent execution phase. Drives the loading-progress UI on /ask:
 *
 *   idle           - before any submit
 *   starting       - submit fired, waiting for first SSE event
 *   planning       - Planner extracting entities + sub-questions
 *   retrieving     - walking the typed graph (walked events incoming)
 *   subgraph_ready - subgraph committed; about to draft
 *   debating       - two-party debate streaming (only on conflict queries)
 *   drafting       - final answer streaming token-by-token
 *   verifying      - Verifier confirming citations
 *   done           - finished cleanly
 *   error          - SSE error or upstream failure
 */
export type AgentPhase =
  | "idle"
  | "starting"
  | "planning"
  | "retrieving"
  | "subgraph_ready"
  | "debating"
  | "drafting"
  | "verifying"
  | "done"
  | "error";

/**
 * Cross-component graph state — the spine that ties together Constellation,
 * ProvenanceOrbit, AnswerStream, CitationDrawer, and DateSlider.
 *
 * Design principle: every viz component subscribes to a thin slice of this
 * store. State updates from SSE events flow into this store; components
 * re-render only on their relevant slice.
 *
 * Hover handlers (e.g. ProvenanceOrbit ↔ AnswerStream sentence hover) update
 * this store synchronously so the latency stays under 100ms.
 */
interface GraphStore {
  // Constellation state (which dots glow / dim)
  highlightedIndices: number[];
  dimmed: boolean;
  focusedIndices: number[];

  // Provenance Orbit state
  orbitNodes: OrbitNode[];
  orbitEdges: OrbitEdge[];
  centerNodeId: string | null;
  /** Transient — set on hover. Drives the inline cite popover + node halo. */
  hoveredNodeId: string | null;
  /**
   * Transient — set on edge hover. Drives the edge popover.
   * Encoded as `${sourceId}->${targetId}` for stability across re-renders.
   */
  hoveredEdgeKey: string | null;
  /** Persistent — set on click. Drives the right-side Inspector panel. */
  selectedNodeId: string | null;
  /**
   * Persistent — set when an edge is clicked. Identified by
   * `${sourceId}->${targetId}` for stability across re-renders.
   */
  selectedEdgeKey: string | null;
  /**
   * Trigger rect at hover-time, used to anchor popovers. `(x, y)` is the
   * trigger's top-left in viewport coords; `w` and `h` are its size so the
   * popover can place itself fully OUTSIDE the trigger and never cover the
   * thing being hovered. Legacy callers may still pass just `{x, y}` (treated
   * as a zero-size point at that location).
   */
  hoverAnchor: { x: number; y: number; w?: number; h?: number } | null;
  conflictPairs: [string, string][];

  // The Debate state
  debate: DebateTrace | null;
  debateActive: boolean;
  debateMessages: DebateFragment[];

  // Time-travel state
  asof: string;       // ISO date currently displayed
  defaultAsof: string;

  // Constellation lookup tables (built once on load)
  nodeIdToIndex: Record<string, number>;
  nodeKind: Record<string, NodeKind>;

  // Cost meter
  costCents: number;

  // ─── Loading / phase state ─────────────────────────────────────
  /** Current phase of the agent execution. Drives <AgentProgress>. */
  phase: AgentPhase;
  /** How many walked events have arrived during retrieval (drives the bar fill). */
  walkedCount: number;
  /** From `plan` event: number of sub-questions emitted by the Planner. */
  plannedSubQuestions: number;
  /** From `plan` event: number of seed entity nodes pulsed. */
  plannedEntities: number;
  /** How many draft-token chars have been received (used to fade out the progress bar). */
  draftCharsReceived: number;

  // Actions
  setHighlightedIndices: (n: number[] | ((prev: number[]) => number[])) => void;
  pushHighlightedNode: (nodeId: string) => void;
  setDimmed: (d: boolean) => void;
  setFocusedIndices: (n: number[]) => void;
  setOrbit: (nodes: OrbitNode[], edges: OrbitEdge[]) => void;
  /** Merge orbit-node kinds into the global nodeKind map so cite-anchors can color. */
  mergeOrbitNodeKinds: (orbit: OrbitNode[]) => void;
  setCenterNodeId: (id: string | null) => void;
  setHoveredNodeId: (id: string | null) => void;
  setHoveredEdgeKey: (key: string | null) => void;
  /** Set with `{x, y, w?, h?}` to anchor popovers; null to dismiss. */
  setHoverAnchor: (a: { x: number; y: number; w?: number; h?: number } | null) => void;
  setSelectedNodeId: (id: string | null) => void;
  setSelectedEdgeKey: (key: string | null) => void;
  /** Convenience: clear both selections (used by click-outside handler). */
  clearSelection: () => void;
  setConflictPairs: (p: [string, string][]) => void;
  setDebate: (d: DebateTrace | null) => void;
  setDebateActive: (a: boolean) => void;
  appendDebateMessage: (fragment: DebateFragment) => void;
  clearDebateMessages: () => void;
  setAsof: (iso: string) => void;
  setCostCents: (c: number) => void;

  // Phase actions
  setPhase: (p: AgentPhase) => void;
  incWalked: () => void;
  setPlanCounts: (subQuestions: number, entities: number) => void;
  addDraftChars: (n: number) => void;
  setLookups: (nodeIdToIndex: Record<string, number>, nodeKind: Record<string, NodeKind>) => void;
  reset: () => void;
  /** Restore the synthesis view from a cached history entry. Skips the
   *  whole SSE flow — sets the orbit, debate, conflict pairs, and cost
   *  directly into the store and flips phase to "done" so the answer
   *  card renders the cached state. */
  restoreFromCache: (snapshot: {
    orbitNodes: OrbitNode[];
    orbitEdges: OrbitEdge[];
    conflictPairs: [string, string][];
    debate?: DebateTrace | null;
    costCents?: number;
  }) => void;
}

const DEFAULT_ASOF = new Date().toISOString().slice(0, 10);

export const useGraphStore = create<GraphStore>((set, get) => ({
  // initial state
  highlightedIndices: [],
  dimmed: false,
  focusedIndices: [],
  orbitNodes: [],
  orbitEdges: [],
  centerNodeId: null,
  hoveredNodeId: null,
  hoveredEdgeKey: null,
  selectedNodeId: null,
  selectedEdgeKey: null,
  hoverAnchor: null,
  conflictPairs: [],
  debate: null,
  debateActive: false,
  debateMessages: [],
  asof: DEFAULT_ASOF,
  defaultAsof: DEFAULT_ASOF,
  nodeIdToIndex: {},
  nodeKind: {},
  costCents: 0,
  phase: "idle",
  walkedCount: 0,
  plannedSubQuestions: 0,
  plannedEntities: 0,
  draftCharsReceived: 0,

  // actions
  setHighlightedIndices: (n) =>
    set((s) => ({ highlightedIndices: typeof n === "function" ? n(s.highlightedIndices) : n })),
  pushHighlightedNode: (nodeId) =>
    set((s) => {
      const idx = s.nodeIdToIndex[nodeId];
      if (idx === undefined) return s;
      return { highlightedIndices: [...s.highlightedIndices, idx] };
    }),
  setDimmed: (d) => set({ dimmed: d }),
  setFocusedIndices: (n) => set({ focusedIndices: n }),
  setOrbit: (nodes, edges) => set({ orbitNodes: nodes, orbitEdges: edges }),
  mergeOrbitNodeKinds: (orbit) =>
    set((s) => ({
      nodeKind: {
        ...s.nodeKind,
        ...Object.fromEntries(orbit.map((n) => [n.id, n.kind])),
      },
    })),
  setCenterNodeId: (id) => set({ centerNodeId: id }),
  setHoveredNodeId: (id) => set({ hoveredNodeId: id }),
  setHoveredEdgeKey: (key) => set({ hoveredEdgeKey: key }),
  setHoverAnchor: (a) => set({ hoverAnchor: a }),
  setSelectedNodeId: (id) =>
    set((s) => ({ selectedNodeId: id, selectedEdgeKey: id ? null : s.selectedEdgeKey })),
  setSelectedEdgeKey: (key) =>
    set((s) => ({ selectedEdgeKey: key, selectedNodeId: key ? null : s.selectedNodeId })),
  clearSelection: () => set({ selectedNodeId: null, selectedEdgeKey: null }),
  setConflictPairs: (p) => set({ conflictPairs: p }),
  setDebate: (d) => set({ debate: d }),
  setDebateActive: (a) => set({ debateActive: a }),
  appendDebateMessage: (fragment) =>
    set((s) => ({ debateMessages: [...s.debateMessages, fragment] })),
  clearDebateMessages: () => set({ debateMessages: [] }),
  setAsof: (iso) => set({ asof: iso }),
  setCostCents: (c) => set({ costCents: c }),
  setPhase: (p) => set({ phase: p }),
  incWalked: () => set((s) => ({ walkedCount: s.walkedCount + 1 })),
  setPlanCounts: (subQ, ent) =>
    set({ plannedSubQuestions: subQ, plannedEntities: ent }),
  addDraftChars: (n) => set((s) => ({ draftCharsReceived: s.draftCharsReceived + n })),
  setLookups: (nodeIdToIndex, nodeKind) => set({ nodeIdToIndex, nodeKind }),
  reset: () =>
    set({
      highlightedIndices: [],
      dimmed: false,
      focusedIndices: [],
      orbitNodes: [],
      orbitEdges: [],
      centerNodeId: null,
      hoveredNodeId: null,
      hoveredEdgeKey: null,
      selectedNodeId: null,
      selectedEdgeKey: null,
      hoverAnchor: null,
      conflictPairs: [],
      debate: null,
      debateActive: false,
      debateMessages: [],
      costCents: 0,
      phase: "idle",
      walkedCount: 0,
      plannedSubQuestions: 0,
      plannedEntities: 0,
      draftCharsReceived: 0,
    }),
  restoreFromCache: (snap) =>
    set({
      orbitNodes: snap.orbitNodes,
      orbitEdges: snap.orbitEdges,
      centerNodeId: snap.orbitNodes.find((n) => n.isCenter)?.id ?? null,
      // Carry the kind map so cite-anchors in the cached answer get
      // colored correctly when the AnswerStream replay re-renders them.
      nodeKind: Object.fromEntries(snap.orbitNodes.map((n) => [n.id, n.kind])),
      conflictPairs: snap.conflictPairs ?? [],
      debate: snap.debate ?? null,
      debateActive: !!snap.debate,
      debateMessages: [],
      costCents: snap.costCents ?? 0,
      dimmed: true,
      // Final phase so AgentProgress vanishes and the synthesis pill
      // flips to the cost glyph straight away.
      phase: "done",
      walkedCount: 0,
      plannedSubQuestions: 0,
      plannedEntities: 0,
      draftCharsReceived: 0,
      highlightedIndices: [],
      focusedIndices: [],
      hoveredNodeId: null,
      hoveredEdgeKey: null,
      selectedNodeId: null,
      selectedEdgeKey: null,
      hoverAnchor: null,
    }),
}));
