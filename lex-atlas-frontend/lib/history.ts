"use client";

/**
 * Local query history — persists every completed query to localStorage so
 * the user can recall them later. SSR-safe (returns empty array on the
 * server). Cross-tab sync via the `storage` event so two open tabs stay
 * consistent.
 *
 * Design choices:
 *   - Keyed by a versioned storage key so we can migrate the schema later.
 *   - Capped at MAX so localStorage doesn't grow unbounded.
 *   - Same question+asof bumps to the top instead of duplicating, like a
 *     normal recent-files list.
 *   - We save on the agent's `done` event (passed via `push`), so failed
 *     or aborted queries don't pollute the history.
 */

import { useCallback, useEffect, useState } from "react";

export interface HistoryEntry {
  /** Stable query id (queryId in /ask/page.tsx). */
  id: string;
  question: string;
  /** ISO date at submit time. */
  asof: string;
  /** Unix ms when the query completed. */
  ts: number;
  /** Optional: which demo this came from, used for the chip color. */
  demo?: "q4" | "debate" | "n1" | "custom";
  /** Optional: cents spent on the query (from the cost event). */
  costCents?: number;
  /** Optional: was a debate detected and resolved? */
  hadDebate?: boolean;
}

const KEY = "lex-atlas:query-history:v1";
const MAX = 50;

function isEntry(v: unknown): v is HistoryEntry {
  if (!v || typeof v !== "object") return false;
  const o = v as Record<string, unknown>;
  return (
    typeof o.id === "string" &&
    typeof o.question === "string" &&
    typeof o.asof === "string" &&
    typeof o.ts === "number"
  );
}

function read(): HistoryEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isEntry).slice(0, MAX);
  } catch {
    return [];
  }
}

function write(entries: HistoryEntry[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(entries.slice(0, MAX)));
  } catch {
    /* quota exceeded or private-mode disables storage — soft-fail */
  }
}

export function useQueryHistory() {
  const [entries, setEntries] = useState<HistoryEntry[]>([]);

  // Read once on mount + listen for cross-tab updates.
  useEffect(() => {
    setEntries(read());
    const onStorage = (e: StorageEvent) => {
      if (e.key === KEY) setEntries(read());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const push = useCallback((entry: Omit<HistoryEntry, "ts">) => {
    setEntries((prev) => {
      // Dedupe: same question+asof bumps to the top instead of duplicating.
      const filtered = prev.filter(
        (e) => !(e.question === entry.question && e.asof === entry.asof)
      );
      const next: HistoryEntry[] = [
        { ...entry, ts: Date.now() },
        ...filtered,
      ].slice(0, MAX);
      write(next);
      return next;
    });
  }, []);

  const remove = useCallback((id: string) => {
    setEntries((prev) => {
      const next = prev.filter((e) => e.id !== id);
      write(next);
      return next;
    });
  }, []);

  const clear = useCallback(() => {
    setEntries([]);
    write([]);
  }, []);

  return { entries, push, remove, clear };
}

/** Format a unix-ms timestamp as a human relative time ("3m ago", "yesterday"). */
export function relativeTime(ts: number, now: number = Date.now()): string {
  const diff = Math.max(0, now - ts);
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d === 1) return "yesterday";
  if (d < 7) return `${d}d ago`;
  // Older than a week: show date.
  const date = new Date(ts);
  return date.toISOString().slice(0, 10);
}
