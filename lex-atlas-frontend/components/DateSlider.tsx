"use client";

/**
 * DateSlider — the time-travel scrub.
 *
 * Drag from 1990-01-01 to today. The RAGTAG store's `asof` updates,
 * which triggers a CSS-selector swap in ProvenanceOrbit (active/inactive
 * halo jumps to the newly-valid CTV) and a word-level FLIP cross-fade in
 * the answer text. No re-query of the agent — the cached subgraph holds
 * every dated version.
 *
 * Notches mark major amendment dates of the active statutes (passed via
 * props). On scrub, when the slider crosses a notch the corresponding
 * Action node in the orbit flashes.
 */

import { useCallback } from "react";
import { useGraphStore } from "@/lib/store";

export interface AmendmentNotch {
  date: string;      // ISO yyyy-mm-dd
  label: string;     // e.g. "AVL 22.12.2025/1358"
  nodeId: string;
}

interface DateSliderProps {
  minDate?: string;   // ISO
  maxDate?: string;
  notches?: AmendmentNotch[];
  onChange?: (asof: string) => void;
}

const DEFAULT_MIN = "1990-01-01";

export function DateSlider({
  minDate = DEFAULT_MIN,
  maxDate,
  notches = [],
  onChange,
}: DateSliderProps) {
  const today = new Date().toISOString().slice(0, 10);
  const max = maxDate ?? today;
  const asof = useGraphStore((s) => s.asof);
  const setAsof = useGraphStore((s) => s.setAsof);

  const minTs = new Date(minDate).getTime();
  const maxTs = new Date(max).getTime();
  const span = Math.max(maxTs - minTs, 1);
  const ratio = (new Date(asof).getTime() - minTs) / span;

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const r = parseFloat(e.target.value);
      const ts = minTs + r * span;
      const iso = new Date(ts).toISOString().slice(0, 10);
      setAsof(iso);
      onChange?.(iso);
    },
    [minTs, span, setAsof, onChange]
  );

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between text-xs font-mono text-text-tertiary">
        <span>{minDate}</span>
        <span className="text-sm font-semibold text-text-primary">{asof}</span>
        <span>{max}</span>
      </div>

      <div className="relative h-4">
        {/* Notches */}
        {notches.map((n) => {
          const r = (new Date(n.date).getTime() - minTs) / span;
          if (r < 0 || r > 1) return null;
          return (
            <div
              key={n.date + n.nodeId}
              className="absolute top-0 h-4 w-px bg-stroke-subtle"
              style={{ left: `${r * 100}%` }}
              title={`${n.date} · ${n.label}`}
            />
          );
        })}

        <input
          type="range"
          min={0}
          max={1}
          step={0.001}
          value={ratio}
          onChange={handleChange}
          aria-label="As-of date for the query"
          className="absolute inset-0 w-full cursor-pointer appearance-none bg-transparent
                     [&::-webkit-slider-thumb]:appearance-none
                     [&::-webkit-slider-thumb]:h-4
                     [&::-webkit-slider-thumb]:w-4
                     [&::-webkit-slider-thumb]:rounded-full
                     [&::-webkit-slider-thumb]:bg-accent
                     [&::-webkit-slider-thumb]:cursor-grab
                     [&::-webkit-slider-thumb]:active:cursor-grabbing
                     [&::-moz-range-thumb]:h-4
                     [&::-moz-range-thumb]:w-4
                     [&::-moz-range-thumb]:rounded-full
                     [&::-moz-range-thumb]:border-0
                     [&::-moz-range-thumb]:bg-accent"
        />
      </div>
    </div>
  );
}
