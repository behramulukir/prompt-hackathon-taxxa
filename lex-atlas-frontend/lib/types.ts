/**
 * Shared types across the Next.js frontend and Python agent sidecar.
 * Mirrored from `lex_atlas/observability/events.py` on the Python side.
 *
 * Note: kept deliberately stable — every event type maps 1:1 to a UI affordance.
 */

/** Node kinds in our LRMoo-aligned schema. Colors map 1:1 in `lib/colors.ts`. */
export type NodeKind =
  | "work"        // F1 Work (statute, decree, treaty as abstract concept)
  | "expression"  // F2 Expression — versioned text at a point in time
  | "component"   // Component-Work (§ as a concept)
  | "ctv"         // Component Temporal Version (SAT-Graph RAG §3.2)
  | "action"      // F28 Expression Creation (amendment, repeal, enactment)
  | "case"        // KHO / KKO precedent
  | "guidance"    // Vero ohje / kannanotto / päätös
  | "concept"     // skos:Concept (avainhenkilö, lähdevero, etc.)
  | "authority"   // Eduskunta, Verohallinto, KHO, EU
  | "jurisdiction" // FI, EU, Åland
  | "theme";      // SAT-Graph §3.6 curated structural community

/** Edge relations — all carry bitemporal (t_valid, t_invalid) on the wire. */
export type EdgeRelation =
  | "has_part"
  | "realized_in"
  | "expressed_in"
  | "creates"
  | "terminates"
  | "aggregates"     // SAT-Graph §3.4 CTV aggregation
  | "caused_by"
  | "source_provision"
  | "interprets"
  | "rules_on"
  | "transposes"     // FI statute → EU directive
  | "supersedes"
  | "references"
  | "defines"
  | "uses"
  | "enacted_by"
  | "issued_by"
  | "applies_in"
  | "excludes"
  | "in_theme";

/** Authority priority lattice — higher rank wins on conflict resolution. */
export type AuthorityRank = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8;

/** Minimal node payload for the Constellation Map (63k nodes). Float32-packed on the wire. */
export interface ConstellationNode {
  id: string;
  kind: NodeKind;
  /** Initial position (optional — cosmos.gl will run force layout if absent). */
  x?: number;
  y?: number;
  /** In-degree of incoming `references` / `interprets` edges — drives node size. */
  weight?: number;
}

/** Richer node payload for the Provenance Orbit (≤ 12 nodes). */
export interface OrbitNode {
  id: string;
  kind: NodeKind;
  label: string;
  authorityRank: AuthorityRank;
  /** Whether `t_valid <= asof < t_invalid`. Drives the active halo. */
  isActive: boolean;
  /** When true, the node is the center of the orbit (typically a Concept). */
  isCenter?: boolean;
  /** Set when the Verifier flagged this node as part of a conflict. */
  isConflicted?: boolean;
  /** ISO dates for tooltips. */
  tValid?: string;
  tInvalid?: string | null;
}

export interface OrbitEdge {
  source: string;
  target: string;
  relation: EdgeRelation;
  /** Set when the edge is part of a conflict arc (drawn red, dashed). */
  isConflict?: boolean;
}

/** TextUnit payload returned by the `/api/excerpt` endpoint for the Citation Drawer. */
export interface ExcerptResponse {
  nodeId: string;
  sourceUrl: string;
  publisher: "finlex" | "vero" | "eur-lex" | "sparql";
  docTitle: string;
  excerptHtml: string;     // pre-highlighted with <mark class="claim-match">
  contextHtml: string;     // surrounding paragraph
  lang: "fi" | "sv" | "en";
  tValid?: string;
  tInvalid?: string | null;
  /** Diaarinumero for Vero docs, e.g. "VH/2811/00.01.00/2021". */
  docketNumber?: string;
}

/** Self-RAG reflection token classes emitted inline by the Drafter. */
export interface SelfRagReflection {
  isRel: "y" | "n";
  isSup: "full" | "partial" | "none";
  isUse?: 1 | 2 | 3 | 4 | 5;
}

/** Per-claim verification record returned by the Verifier agent. */
export interface ClaimVerification {
  sentenceIdx: number;
  text: string;
  citedNodes: string[];
  support: "full" | "partial" | "none";
  conflictDetected: boolean;
  overlapScore: number;
}

/** The complete final answer payload — also the source for the PDF receipt. */
export interface GroundedAnswer {
  question: string;
  asof: string;        // ISO date
  lang: "fi" | "sv" | "en";
  answer: string;       // with inline [cite:node:X]…[/cite] tokens preserved
  claims: ClaimVerification[];
  orbitNodes: OrbitNode[];
  orbitEdges: OrbitEdge[];
  conflictPairs: [string, string][];
  costCents: number;
  wallTimeMs: number;
  /** The Debate, if it fired. */
  debate?: DebateTrace;
}

/** AgenticSimLaw-style debate transcript (when Verifier detects equal-rank conflict). */
export interface DebateTrace {
  proposition: string;       // The question
  partyA: { label: string; role: "vero" | "guidance"; text: string; cites: string[] };
  partyB: { label: string; role: "kho" | "case"; text: string; cites: string[] };
  judge: { reasoning: string; resolution: "A" | "B" | "synthesis"; principle: string };
  turnsElapsed: number;
}

/* ───────────────────────────────────────────────────────────────────────────
   SSE event types — every event from /api/ask maps to a UI affordance.
   Mirrored exactly from lex_atlas/observability/events.py.
   ─────────────────────────────────────────────────────────────────────────── */

export type AgentEvent =
  | { type: "ner_pulse"; entityNodeIds: string[] }                    // typing → faint constellation pulse
  | { type: "plan"; subQuestions: string[]; entityNodeIds: string[] }   // Planner trail draws
  | { type: "walked"; nodeId: string; score: number; step: number }    // each retriever step → halo
  | { type: "subgraph_ready"; orbitNodes: OrbitNode[]; orbitEdges: OrbitEdge[] } // orbital pull begins
  | { type: "debate_open"; partyAId: string; partyBId: string }         // The Debate splits the answer area
  | { type: "debate_token"; party: "A" | "B"; text: string }            // streaming both sides
  | { type: "debate_judge"; judge: DebateTrace["judge"] }               // Judge resolution
  | { type: "draft_token"; text: string }                                // final answer streaming
  | { type: "claim_verified"; sentenceIdx: number; support: ClaimVerification["support"] }
  | { type: "conflict"; nodeA: string; nodeB: string; principle: string } // red conflict arc draws
  | { type: "cost"; cents: number }                                      // live cost meter update
  | { type: "done"; answer: GroundedAnswer }
  | { type: "error"; message: string };
