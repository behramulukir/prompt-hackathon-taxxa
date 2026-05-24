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
 *   - Each completed entry carries a `cached` snapshot of the answer +
 *     orbit subgraph + debate (v2 schema). Recalling an entry can then
 *     re-render the synthesis instantly without re-running the pipeline
 *     and without re-billing.
 */

import { useCallback, useEffect, useState } from "react";
import type { OrbitNode, OrbitEdge, DebateTrace } from "@/lib/types";

/** Frozen snapshot of everything the synthesis view needs to redisplay a
 *  past query: the streamed answer text (still carrying [cite:node:X]
 *  tokens), the orbit subgraph that was wired up while the agent ran,
 *  any detected conflict pairs, and the debate transcript when one
 *  fired. Big chunks of state but the cap on MAX entries keeps the
 *  total localStorage footprint bounded. */
export interface CachedAnswer {
  /** Streamed answer text (with [cite:node:X]…[/cite] tokens intact). */
  answer: string;
  /** Orbit subgraph (≤ 12 nodes) at done-time. */
  orbitNodes: OrbitNode[];
  /** Orbit edges (typed relations). */
  orbitEdges: OrbitEdge[];
  /** Verifier-flagged conflict pairs. Empty list when none. */
  conflictPairs: [string, string][];
  /** Debate transcript when one fired. */
  debate?: DebateTrace | null;
}

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
  /** v2 — frozen snapshot of the rendered synthesis. Missing on entries
   *  written by older builds; recall() falls back to a fresh run when
   *  absent. */
  cached?: CachedAnswer;
}

// v2: payload schema now includes ``cached``. Versioned key means old v1
// entries are silently dropped on first read (no migration needed — they
// were never load-bearing across sessions).
const KEY = "lex-atlas:query-history:v2";
// Older keys we want to cleanly forget so the dropdown doesn't pick up
// stale rows from a previous build.
const LEGACY_KEYS = ["lex-atlas:query-history:v1"];
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
    // Drop entries whose ``id`` is already present earlier in the list.
    // localStorage can pick up duplicates from older bug versions where
    // the 8-hex-char id occasionally collided; we self-heal on every read
    // so React's keyed-list invariant holds even for pre-existing data.
    const seen = new Set<string>();
    const out: HistoryEntry[] = [];
    for (const v of parsed) {
      if (!isEntry(v)) continue;
      if (seen.has(v.id)) continue;
      seen.add(v.id);
      out.push(v);
    }
    return out.slice(0, MAX);
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
    // One-shot legacy-key cleanup: drop pre-v2 history so older entries
    // (no ``cached`` payload, possibly with the duplicate-id bug) don't
    // resurface in the dropdown.
    if (typeof window !== "undefined") {
      for (const k of LEGACY_KEYS) {
        try { window.localStorage.removeItem(k); } catch { /* ignore */ }
      }
    }
    setEntries(read());
    const onStorage = (e: StorageEvent) => {
      if (e.key === KEY) setEntries(read());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const push = useCallback((entry: Omit<HistoryEntry, "ts">) => {
    setEntries((prev) => {
      // Dedupe on TWO axes:
      //   1. ``id`` — covers the "onComplete fired twice" path (React 19
      //      StrictMode double-invoke, or any caller that retries push)
      //      and any pre-existing duplicate-id leftovers in localStorage.
      //   2. ``question + asof`` — keeps the list reading like a normal
      //      recent-files panel: re-asking the same thing bumps the
      //      existing entry to the top instead of stacking.
      const filtered = prev.filter(
        (e) =>
          e.id !== entry.id &&
          !(e.question === entry.question && e.asof === entry.asof)
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
