"use client";

/**
 * NavigationProgress — top-of-page progress bar that fires on every
 * client-side link click and stays animated until the new route is
 * interactive. Without it, in dev mode every Next.js route compiles on
 * first visit (3–30s) and the user sees NO feedback at all — clicking the
 * "Methodology" link feels like nothing happens.
 *
 * Strategy:
 *   1. Intercept clicks on every anchor (capture phase) and check if it
 *      points to a different in-app path. If yes, start the bar.
 *   2. Also start the bar when `router.push` is called programmatically
 *      (we listen on the global `lex:nav-start` custom event for that).
 *   3. While active, fake-progress to 90% with a non-linear easing.
 *   4. End on `usePathname()` change (route swapped) OR via 12s safety
 *      timeout. Final 100% → 300ms fade → reset.
 *
 * Renders nothing when not active.
 */

import { useEffect, useRef, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";

const SAFETY_MS = 12_000;
const TICK_MS = 180;
const FILL_PER_TICK = 6; // %
const COMPLETE_HOLD_MS = 280;

function isInternalSamePathClick(target: Element): { internal: boolean; samePath: boolean } {
  const anchor = target.closest("a");
  if (!anchor) return { internal: false, samePath: false };
  const href = anchor.getAttribute("href");
  if (!href) return { internal: false, samePath: false };
  if (href.startsWith("#")) return { internal: false, samePath: false };
  if (anchor.hasAttribute("download")) return { internal: false, samePath: false };
  if (anchor.getAttribute("target") === "_blank") return { internal: false, samePath: false };
  let url: URL;
  try {
    url = new URL(href, window.location.href);
  } catch {
    return { internal: false, samePath: false };
  }
  if (url.origin !== window.location.origin) return { internal: false, samePath: false };
  const samePath =
    url.pathname === window.location.pathname && url.search === window.location.search;
  return { internal: true, samePath };
}

export function NavigationProgress() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [active, setActive] = useState(false);
  const [progress, setProgress] = useState(0);
  // We only want to "complete" the bar when the route ACTUALLY changes,
  // not on the initial pathname read. This ref tracks the last pathname
  // we saw while active so we can detect a real transition.
  const startedFromPath = useRef<string | null>(null);

  /* ── Start: intercept anchor clicks at the document level ──────────── */
  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      // Only primary-button, no modifier, left-button-only clicks count as
      // "navigate" — let modifier-clicks open in new tabs normally.
      if (e.defaultPrevented) return;
      if (e.button !== 0) return;
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const target = e.target as Element | null;
      if (!target) return;
      const { internal, samePath } = isInternalSamePathClick(target);
      if (!internal) return;
      if (samePath) return; // no navigation will happen
      startedFromPath.current = window.location.pathname + window.location.search;
      setActive(true);
      setProgress(8);
    };
    document.addEventListener("click", onDocClick, true);
    // Also expose a programmatic start, e.g. for router.push():
    //   window.dispatchEvent(new CustomEvent("lex:nav-start"));
    const onCustom = () => {
      startedFromPath.current = window.location.pathname + window.location.search;
      setActive(true);
      setProgress(8);
    };
    window.addEventListener("lex:nav-start", onCustom);
    return () => {
      document.removeEventListener("click", onDocClick, true);
      window.removeEventListener("lex:nav-start", onCustom);
    };
  }, []);

  /* ── Tick: fake-progress to 90% while active ───────────────────────── */
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => {
      setProgress((p) => {
        if (p >= 90) return p;
        const remaining = 90 - p;
        return p + Math.max(0.5, Math.min(FILL_PER_TICK, remaining * 0.15));
      });
    }, TICK_MS);
    return () => window.clearInterval(id);
  }, [active]);

  /* ── End: when path or search-params change while active, complete ─── */
  useEffect(() => {
    if (!active) return;
    const current = pathname + (searchParams ? `?${searchParams.toString()}` : "");
    if (startedFromPath.current && current !== startedFromPath.current) {
      setProgress(100);
      const t = window.setTimeout(() => {
        setActive(false);
        setProgress(0);
        startedFromPath.current = null;
      }, COMPLETE_HOLD_MS);
      return () => window.clearTimeout(t);
    }
  }, [pathname, searchParams, active]);

  /* ── Safety: cap any nav at SAFETY_MS so the bar never gets stuck ─── */
  useEffect(() => {
    if (!active) return;
    const t = window.setTimeout(() => {
      setProgress(100);
      window.setTimeout(() => {
        setActive(false);
        setProgress(0);
        startedFromPath.current = null;
      }, COMPLETE_HOLD_MS);
    }, SAFETY_MS);
    return () => window.clearTimeout(t);
  }, [active]);

  if (!active && progress === 0) return null;

  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-x-0 top-0 z-[100]"
      style={{ height: 2 }}
    >
      <div
        style={{
          height: "100%",
          width: `${progress}%`,
          background: "var(--color-secondary)",
          boxShadow:
            progress > 0 && progress < 100
              ? "0 0 8px var(--color-secondary), 0 0 2px var(--color-secondary)"
              : "none",
          transition:
            progress >= 100 ? "width 220ms ease, opacity 220ms ease 80ms" : "width 220ms ease-out",
          opacity: progress >= 100 ? 0 : 1,
        }}
      />
    </div>
  );
}
