"use client";

/**
 * ProvenanceTimeline — Stitch's design for the Ask page side panel.
 *
 * Vertical timeline with colored dots (one per OrbitNode), each labelled by
 * authority class. Replaces the radial Provenance Orbit on the chat surface
 * because the vertical form fits the chat column better. The radial form is
 * preserved in components/ProvenanceOrbit.tsx for the standalone graph view.
 */

import { useGraphStore } from "@/lib/store";
import { colorForKind } from "@/lib/colors";
import type { AuthorityRank } from "@/lib/types";

const RANK_LABEL: Record<AuthorityRank, string> = {
  8: "Binding Law",
  7: "Supreme Precedent",
  6: "Recent Amendment",
  5: "Specific Rule",
  4: "Higher Authority",
  3: "Admin Guideline",
  2: "Older Rule",
  1: "Informal Note",
};

export function ProvenanceTimeline() {
  const nodes = useGraphStore((s) => s.orbitNodes);
  const setHoveredNodeId = useGraphStore((s) => s.setHoveredNodeId);

  if (nodes.length === 0) {
    return (
      <div className="text-xs font-mono italic text-on-surface-variant">
        Orbit populates when the agent commits to a subgraph.
      </div>
    );
  }

  // Sort by authority rank (high → low) so the binding law sits at top
  const sorted = [...nodes].sort((a, b) => b.authorityRank - a.authorityRank);

  return (
    <div className="relative space-y-6 border-l border-outline-variant pl-4">
      {sorted.map((n) => {
        const color = colorForKind(n.kind);
        const dim = n.isActive === false;
        return (
          <div
            key={n.id}
            className="relative cursor-pointer"
            onMouseEnter={() => setHoveredNodeId(n.id)}
            onMouseLeave={() => setHoveredNodeId(null)}
          >
            {/* Dot */}
            <div
              className="absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full border-2 border-surface-container-lowest"
              style={{ background: color, opacity: dim ? 0.4 : 1 }}
            />
            <div className="font-mono text-[11px] uppercase tracking-wider text-on-surface-variant">
              {RANK_LABEL[n.authorityRank] ?? "Source"}
            </div>
            <div
              className="mt-0.5 font-sans text-[15px] font-medium leading-snug hover:underline"
              style={{ color: dim ? "var(--color-on-surface-variant)" : color }}
            >
              {n.label}
            </div>
            {n.tValid && (
              <div className="mt-1 font-mono text-[11px] text-on-surface-variant">
                {n.tValid}
                {n.tInvalid && ` → ${n.tInvalid}`}
                {!n.tInvalid && n.tValid && " → present"}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
