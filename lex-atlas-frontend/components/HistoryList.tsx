"use client";

/**
 * HistoryList — two shapes for the same data set:
 *
 *   <HistoryList variant="inline">  →  full list, suitable for the /ask
 *                                       empty state below the demo prompts.
 *
 *   <HistoryButton>                 →  small button + dropdown panel,
 *                                       suitable for the action strip of
 *                                       an active conversation.
 *
 * Both call back with `onRecall(entry)` when the user clicks a row, so the
 * page can `setAsof + setQuestion + submit` in one go.
 */

import { useEffect, useRef, useState } from "react";
import type { HistoryEntry } from "@/lib/history";
import { relativeTime } from "@/lib/history";
import { formatCents } from "@/lib/utils";

const DEMO_COLOR: Record<NonNullable<HistoryEntry["demo"]>, string> = {
  q4:     "#1a1c1b",
  debate: "#9c2b5f",
  n1:     "#006b70",
  custom: "#944921",
};

const DEMO_LABEL: Record<NonNullable<HistoryEntry["demo"]>, string> = {
  q4:     "DEMO · Q4",
  debate: "DEMO · DEBATE",
  n1:     "DEMO · N1",
  custom: "CUSTOM",
};

interface ListProps {
  entries: HistoryEntry[];
  onRecall: (entry: HistoryEntry) => void;
  onRemove: (id: string) => void;
  onClear: () => void;
  /** "inline" = full block list; "compact" = short rows in a dropdown. */
  variant?: "inline" | "compact";
}

export function HistoryList({ entries, onRecall, onRemove, onClear, variant = "inline" }: ListProps) {
  if (entries.length === 0) return null;
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
      <div className="flex items-baseline justify-between">
        <p
          className="font-mono uppercase tracking-widest text-on-surface-variant"
          style={{ fontSize: "var(--text-overline)" }}
        >
          Your recent queries
        </p>
        <div
          className="flex items-baseline font-mono uppercase tracking-wider text-on-surface-variant"
          style={{ gap: "var(--space-4)", fontSize: "var(--text-meta)" }}
        >
          <span>{entries.length} saved locally</span>
          <button
            type="button"
            onClick={onClear}
            className="transition-colors hover:text-error"
          >
            Clear
          </button>
        </div>
      </div>

      <ul className="divide-y divide-outline-variant border-y border-outline-variant">
        {entries.map((entry) => (
          // Defense in depth: ``entry.id`` SHOULD already be unique after
          // useQueryHistory's read/push dedupes, but mixing in ``ts``
          // guarantees React's keyed-list invariant even if a stale
          // localStorage payload sneaks through.
          <li key={`${entry.id}-${entry.ts}`}>
            <HistoryRow
              entry={entry}
              variant={variant}
              onRecall={onRecall}
              onRemove={onRemove}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}

/* ─────────────────────────────────────────────────────────────────────
   Row — one entry, hover + remove button. Used inside both inline + drawer.
   ───────────────────────────────────────────────────────────────────── */

interface RowProps {
  entry: HistoryEntry;
  variant: "inline" | "compact";
  onRecall: (entry: HistoryEntry) => void;
  onRemove: (id: string) => void;
}

function HistoryRow({ entry, variant, onRecall, onRemove }: RowProps) {
  const compact = variant === "compact";
  const demo = entry.demo ?? "custom";
  const chipColor = DEMO_COLOR[demo];
  const chipLabel = DEMO_LABEL[demo];

  return (
    <div
      className="group flex w-full items-center text-left transition-colors hover:bg-surface-container-low/60"
      style={{
        gap: compact ? "var(--space-3)" : "var(--space-5)",
        paddingInline: compact ? "var(--space-3)" : "var(--space-2)",
        paddingBlock: compact ? "var(--space-3)" : "var(--space-3)",
      }}
    >
      <button
        type="button"
        onClick={() => onRecall(entry)}
        className="flex min-w-0 flex-1 items-center text-left"
        style={{ gap: compact ? "var(--space-3)" : "var(--space-5)" }}
        aria-label={`Recall query: ${entry.question}`}
      >
        {/* Source/demo chip */}
        <span
          className="w-20 shrink-0 font-mono uppercase tracking-wider"
          style={{
            fontSize: "var(--text-overline)",
            color: chipColor,
            letterSpacing: "0.06em",
          }}
        >
          {chipLabel}
        </span>

        {/* Question + meta */}
        <span
          className="flex min-w-0 flex-1 flex-col"
          style={{ gap: 2 }}
        >
          <span
            className="truncate font-sans text-on-surface"
            style={{
              fontSize: compact ? "var(--text-body-sm)" : "var(--text-body)",
              fontWeight: 500,
            }}
            title={entry.question}
          >
            {entry.question}
          </span>
          <span
            className="font-mono uppercase tracking-wider text-on-surface-variant"
            style={{ fontSize: "var(--text-meta)" }}
          >
            <span>{relativeTime(entry.ts)}</span>
            <span> · asof {entry.asof}</span>
            {entry.costCents !== undefined && entry.costCents > 0 && (
              // Mirrors the synthesis-card pill (`AnswerStatusPill`). Both
              // call ``formatCents`` so a query's cost reads identically
              // wherever it surfaces — the prior `€${cents/100}` notation
              // looked like a different number even though it was the same
              // value in a different unit.
              <span> · {formatCents(entry.costCents)}</span>
            )}
            {entry.hadDebate && (
              <span style={{ color: "var(--color-secondary)" }}> · debate</span>
            )}
          </span>
        </span>

        <span
          className="material-symbols-outlined shrink-0 text-on-surface-variant transition-all group-hover:translate-x-0.5 group-hover:text-secondary"
          style={{ fontSize: "var(--icon-md)" }}
          aria-hidden
        >
          arrow_forward
        </span>
      </button>

      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onRemove(entry.id);
        }}
        className="shrink-0 text-on-surface-variant opacity-0 transition-opacity hover:text-error focus:opacity-100 group-hover:opacity-100"
        aria-label="Remove from history"
        title="Remove from history"
      >
        <span className="material-symbols-outlined" style={{ fontSize: "var(--icon-sm)" }}>
          close
        </span>
      </button>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────
   HistoryButton — small button + dropdown for the active conversation.
   ───────────────────────────────────────────────────────────────────── */

interface ButtonProps {
  entries: HistoryEntry[];
  onRecall: (entry: HistoryEntry) => void;
  onRemove: (id: string) => void;
  onClear: () => void;
}

export function HistoryButton({ entries, onRecall, onRemove, onClear }: ButtonProps) {
  const [open, setOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);

  /* Click-outside dismiss. */
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target as Node | null;
      if (!target) return;
      if (dropdownRef.current?.contains(target)) return;
      if (buttonRef.current?.contains(target)) return;
      setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  /* ESC to close. */
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const disabled = entries.length === 0;

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        className="flex shrink-0 items-center gap-2 border border-outline-variant px-3 py-1.5 font-mono text-xs transition-colors hover:bg-surface-container disabled:opacity-40 disabled:hover:bg-transparent"
        aria-haspopup="menu"
        aria-expanded={open}
        title={
          disabled
            ? "No history yet — complete a query and it'll be saved here"
            : `${entries.length} saved ${entries.length === 1 ? "query" : "queries"}`
        }
      >
        <span className="material-symbols-outlined" style={{ fontSize: 16 }}>
          history
        </span>
        History
        {entries.length > 0 && (
          <span
            className="ml-1 font-mono"
            style={{
              fontSize: 10,
              background: "var(--color-surface-container)",
              color: "var(--color-on-surface-variant)",
              padding: "1px 5px",
              letterSpacing: 0.5,
            }}
          >
            {entries.length}
          </span>
        )}
      </button>

      {open && (
        <div
          ref={dropdownRef}
          role="menu"
          className="absolute right-0 z-30 mt-2 border border-outline-variant bg-surface-container-lowest shadow-[0_8px_24px_rgba(0,0,0,0.08)]"
          style={{ width: 460, maxHeight: 480, overflowY: "auto" }}
        >
          <div
            className="sticky top-0 border-b border-outline-variant bg-surface-container-lowest"
            style={{
              paddingInline: "var(--space-4)",
              paddingBlock: "var(--space-3)",
              display: "flex",
              alignItems: "baseline",
              justifyContent: "space-between",
              gap: "var(--space-3)",
            }}
          >
            <span
              className="font-mono uppercase tracking-widest text-on-surface"
              style={{ fontSize: "var(--text-overline)" }}
            >
              Your recent queries
            </span>
            <button
              type="button"
              onClick={() => {
                onClear();
                setOpen(false);
              }}
              className="font-mono uppercase tracking-wider text-on-surface-variant transition-colors hover:text-error"
              style={{ fontSize: "var(--text-meta)" }}
            >
              Clear all
            </button>
          </div>
          <ul className="divide-y divide-outline-variant">
            {entries.map((entry) => (
              <li key={entry.id}>
                <HistoryRow
                  entry={entry}
                  variant="compact"
                  onRecall={(e) => {
                    onRecall(e);
                    setOpen(false);
                  }}
                  onRemove={onRemove}
                />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
