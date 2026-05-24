/**
 * Seed graph — synthetic but plausible Finnish-tax-law ecosystem of ~480 nodes.
 *
 * Generated deterministically so the Constellation visual is reproducible across
 * refreshes. Used until the real ingest pipeline populates Neo4j (Saturday
 * 18:00 milestone per the plan).
 *
 * Node distribution by kind matches the real corpus proportions roughly:
 *   - work:     ~120  (statutes, decrees, treaties)
 *   - action:   ~140  (amendment events)
 *   - case:      ~80  (KHO + KKO precedents)
 *   - guidance: ~100  (Vero ohjeet / kannanotot)
 *   - concept:   ~40  (semantic anchors)
 *
 * Edges follow the typed schema (references, has_part, interprets, rules_on,
 * defines) with realistic in-degree distributions so the cosmos.gl force
 * layout produces visible kind-clusters.
 *
 * Plus: the Q4 ecosystem (avainhenkilö ↔ AVL ↔ amendments ↔ Vero ohjeet) is
 * present with stable IDs that match the SSE fixture so the orbital pull
 * animates against real visible nodes in the Constellation.
 */

import type { ConstellationNode, NodeKind } from "./types";

interface SeedEdge {
  source: number;
  target: number;
}

interface SeedGraph {
  nodes: ConstellationNode[];
  edges: SeedEdge[];
}

const SPACE_SIZE = 6500;

/** Cluster centers per node kind — drives the visible galaxy regions. */
const CLUSTER_CENTERS: Record<NodeKind, { x: number; y: number }> = {
  work:         { x: -800, y:  -400 },   // statutes — top-left cluster
  expression:   { x: -800, y:  -400 },
  component:    { x: -800, y:  -400 },
  ctv:          { x:    0, y:  1200 },   // amendments — bottom (time axis)
  action:       { x:    0, y:  1200 },
  case:         { x:  1500, y: -200 },   // KHO/KKO — right cluster
  guidance:     { x: -100, y: -1200 },   // Vero — top center
  concept:      { x:  100, y:   100 },   // concepts — center, anchors
  authority:    { x:  100, y:   100 },
  jurisdiction: { x:  100, y:   100 },
  theme:        { x:  100, y:   100 },
};

const CLUSTER_RADIUS: Partial<Record<NodeKind, number>> = {
  work: 850,
  action: 950,
  case: 700,
  guidance: 750,
  concept: 380,
};

/** Mulberry32 — tiny deterministic PRNG. */
function makeRng(seed: number) {
  let t = seed;
  return () => {
    t = (t + 0x6D2B79F5) >>> 0;
    let r = t;
    r = Math.imul(r ^ (r >>> 15), r | 1);
    r ^= r + Math.imul(r ^ (r >>> 7), r | 61);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}

function clusterPos(kind: NodeKind, rng: () => number): { x: number; y: number } {
  const c = CLUSTER_CENTERS[kind];
  const r = CLUSTER_RADIUS[kind] ?? 500;
  // Gaussian-ish via Box-Muller approximation
  const u1 = rng();
  const u2 = rng();
  const mag = Math.sqrt(-2 * Math.log(u1 || 0.001));
  const angle = 2 * Math.PI * u2;
  return {
    x: c.x + r * mag * Math.cos(angle) * 0.6,
    y: c.y + r * mag * Math.sin(angle) * 0.6,
  };
}

/**
 * Build the seed graph deterministically.
 *
 * Includes ~480 ambient nodes plus the exact Q4 ecosystem with stable IDs
 * matching the SSE fixture so orbit pulses + halo highlight against real
 * positions in the Constellation.
 */
export function buildSeedGraph(): SeedGraph {
  const rng = makeRng(42); // deterministic
  const nodes: ConstellationNode[] = [];
  const edges: SeedEdge[] = [];

  // ── Q4 ecosystem — exact IDs matching the SSE fixture ─────────────────────
  const q4Nodes: Array<[string, NodeKind, number, number]> = [
    ["concept:avainhenkilo",                          "concept",  0,     0],
    ["concept:lahdevero",                             "concept",  120,   80],
    ["work:avainhenkilolaki",                         "work",     -700,  -350],
    ["ctv:avh:§3@2026-01-01",                         "action",   -50,   1150],
    ["ctv:avh:§3@2020-01-01",                         "action",   30,    1280],
    ["ctv:avh:§3@1995-01-01",                         "action",   -120,  1380],
    ["comp:avh:§4",                                   "component", -650, -420],
    ["work:vero-kannanotto:avainhenkilo-2020",        "guidance", -180,  -1180],
    ["work:vero-ohje:rajoitetusti-2026",              "guidance", -80,   -1240],
    ["work:vero-ohje:avainhenkiloiden-verotus",       "guidance", -160,  -1140],
    // Q4 neighbors — TVL ecosystem
    ["work:tuloverolaki",                             "work",     -900,  -310],
    ["work:lahdeverolaki",                            "work",     -780,  -480],
    // Q4 KHO neighbors
    ["case:kho-2023-55",                              "case",     1480,  -180],
    ["case:kho-2022-58",                              "case",     1540,  -240],
  ];
  for (const [id, kind, x, y] of q4Nodes) {
    nodes.push({ id, kind, x, y, weight: 8 });
  }
  // Q4 edges (anchor the cluster visually)
  const idToIdx = new Map<string, number>();
  nodes.forEach((n, i) => idToIdx.set(n.id, i));
  const edge = (a: string, b: string) => {
    const s = idToIdx.get(a);
    const t = idToIdx.get(b);
    if (s !== undefined && t !== undefined) edges.push({ source: s, target: t });
  };
  edge("concept:avainhenkilo", "work:avainhenkilolaki");
  edge("concept:avainhenkilo", "concept:lahdevero");
  edge("work:avainhenkilolaki", "ctv:avh:§3@2026-01-01");
  edge("work:avainhenkilolaki", "ctv:avh:§3@2020-01-01");
  edge("work:avainhenkilolaki", "ctv:avh:§3@1995-01-01");
  edge("work:avainhenkilolaki", "comp:avh:§4");
  edge("work:vero-ohje:rajoitetusti-2026", "ctv:avh:§3@2026-01-01");
  edge("work:vero-kannanotto:avainhenkilo-2020", "ctv:avh:§3@2020-01-01");
  edge("work:vero-ohje:avainhenkiloiden-verotus", "work:avainhenkilolaki");
  edge("work:tuloverolaki", "work:avainhenkilolaki");
  edge("work:lahdeverolaki", "work:avainhenkilolaki");
  edge("case:kho-2023-55", "work:avainhenkilolaki");

  // ── Ambient corpus — 480 plausible nodes around the Q4 ecosystem ──────────
  const counts: Array<[NodeKind, number]> = [
    ["work", 120],
    ["action", 140],
    ["case", 80],
    ["guidance", 100],
    ["concept", 40],
  ];
  for (const [kind, n] of counts) {
    for (let i = 0; i < n; i++) {
      const { x, y } = clusterPos(kind, rng);
      nodes.push({
        id: `seed:${kind}:${i}`,
        kind,
        x,
        y,
        weight: 1 + Math.floor(rng() * 6),
      });
    }
  }

  // ── Ambient edges — sparse, kind-biased (statutes-to-amendments dominant) ─
  // We anchor amendment nodes to a random Work in the work cluster.
  const workIndices: number[] = [];
  const actionIndices: number[] = [];
  const caseIndices: number[] = [];
  const guidanceIndices: number[] = [];
  const conceptIndices: number[] = [];
  nodes.forEach((n, i) => {
    if (n.kind === "work") workIndices.push(i);
    else if (n.kind === "action") actionIndices.push(i);
    else if (n.kind === "case") caseIndices.push(i);
    else if (n.kind === "guidance") guidanceIndices.push(i);
    else if (n.kind === "concept") conceptIndices.push(i);
  });

  const pick = (arr: number[]) => arr[Math.floor(rng() * arr.length)];

  // Each Action attaches to a Work (creates an amendment chain visually)
  for (const a of actionIndices) {
    edges.push({ source: pick(workIndices), target: a });
  }
  // Each Case rules_on a Work
  for (const c of caseIndices) {
    edges.push({ source: c, target: pick(workIndices) });
  }
  // Each Guidance interprets a Work
  for (const g of guidanceIndices) {
    edges.push({ source: g, target: pick(workIndices) });
  }
  // Concepts get a few outgoing defines edges
  for (const k of conceptIndices) {
    const fanout = 1 + Math.floor(rng() * 4);
    for (let i = 0; i < fanout; i++) {
      edges.push({ source: k, target: pick(workIndices) });
    }
  }
  // A few inter-Work references (cross-citations between statutes)
  for (let i = 0; i < 80; i++) {
    const s = pick(workIndices);
    let t = pick(workIndices);
    if (s !== t) edges.push({ source: s, target: t });
  }

  return { nodes, edges };
}

/** Cached singleton so the Constellation builds the graph once. */
let cached: SeedGraph | null = null;
export function getSeedGraph(): SeedGraph {
  if (!cached) cached = buildSeedGraph();
  return cached;
}
