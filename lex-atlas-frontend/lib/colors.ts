/**
 * Node-kind colors — light theme (Stitch palette).
 *
 * statutes/concepts → charcoal (primary text)
 * amendments       → terracotta (the persuasive accent)
 * court cases      → KHO pink
 * Vero guidance    → Vero teal
 * concept (alt)    → muted terracotta variant
 */

import type { NodeKind } from "./types";

export const NODE_COLOR: Record<string, string> = {
  work: "#1a1c1b",
  expression: "#1a1c1b",
  component: "#1a1c1b",
  ctv: "#944921",
  action: "#944921",
  case: "#9c2b5f",
  guidance: "#006b70",
  concept: "#76330b",
  authority: "#747878",
  jurisdiction: "#747878",
  theme: "#944921",
};

export function colorForKind(kind: NodeKind): string {
  return NODE_COLOR[kind] ?? "#1a1c1b";
}

export function colorForKindFloat32(
  kind: NodeKind
): [number, number, number, number] {
  const hex = colorForKind(kind);
  const r = parseInt(hex.slice(1, 3), 16) / 255;
  const g = parseInt(hex.slice(3, 5), 16) / 255;
  const b = parseInt(hex.slice(5, 7), 16) / 255;
  return [r, g, b, 1];
}

export const ORBIT_RING_RADIUS: Record<number, number> = {
  8: 70,
  7: 130,
  6: 190,
  5: 190,
  4: 250,
  3: 310,
  2: 370,
  1: 430,
};

export const AUTHORITY_LABELS: Record<number, string> = {
  8: "Binding law",
  7: "Court ruling",
  6: "Recent amendment",
  5: "Specific rule",
  4: "Higher authority",
  3: "Tax-authority interpretation",
  2: "Older rule",
  1: "Informal note",
};
