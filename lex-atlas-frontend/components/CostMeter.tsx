"use client";

import { useGraphStore } from "@/lib/store";
import { formatCents } from "@/lib/utils";

/**
 * CostMeter — the live per-query cost readout, ticking up as the agent runs.
 *
 * Reads from the Zustand store. The store is updated by the `cost` SSE event
 * dispatched by AnswerStream on every Drafter token-batch.
 *
 * Displayed twice on the demo: once in the left filter panel (running),
 * once in the bottom-right corner of the answer view (final). The brief's
 * €1.00 cap is shown as a faint reference line in the bar.
 */

interface CostMeterProps {
  /** Cap in cents — defaults to 100 (€1.00 per the hackathon brief). */
  capCents?: number;
  variant?: "stat" | "bar";
}

export function CostMeter({ capCents = 100, variant = "stat" }: CostMeterProps) {
  const cents = useGraphStore((s) => s.costCents);
  const pct = Math.min((cents / capCents) * 100, 100);

  if (variant === "stat") {
    return (
      <div className="space-y-1">
        <div className="flex items-baseline justify-between">
          <span className="section-number">COST</span>
          <span className="font-mono text-sm text-text-primary">{formatCents(cents)}</span>
        </div>
        <div className="text-xs text-text-tertiary">
          {(pct).toFixed(1)}% of €1 cap · local Gemma 3 27B
        </div>
      </div>
    );
  }

  // Bar variant
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between">
        <span className="section-number">cost · this query</span>
        <span className="font-mono text-sm">
          {formatCents(cents)}
          <span className="ml-1 text-text-tertiary">/ €1.00 cap</span>
        </span>
      </div>
      <div className="h-1 w-full overflow-hidden rounded bg-bg-panel">
        <div
          className="h-full rounded bg-success transition-all duration-200"
          style={{ width: `${pct}%` }}
          aria-hidden
        />
      </div>
    </div>
  );
}
