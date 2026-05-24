"use client";

/**
 * CitationDrawer — restyled for the Stitch light theme. Slides up from the
 * bottom on cite-anchor hover, shows the actual Finnish HTML excerpt.
 */

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useGraphStore } from "@/lib/store";
import type { ExcerptResponse } from "@/lib/types";

const cache = new Map<string, ExcerptResponse>();

export function CitationDrawer() {
  const hoveredNodeId = useGraphStore((s) => s.hoveredNodeId);
  const [excerpt, setExcerpt] = useState<ExcerptResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!hoveredNodeId) {
      setExcerpt(null);
      setLoading(false);
      return;
    }

    const cached = cache.get(hoveredNodeId);
    if (cached) {
      setExcerpt(cached);
      return;
    }

    const t = setTimeout(() => {
      const ac = new AbortController();
      abortRef.current?.abort();
      abortRef.current = ac;
      setLoading(true);
      fetch(`/api/excerpt?node_id=${encodeURIComponent(hoveredNodeId)}`, {
        signal: ac.signal,
      })
        .then((r) => (r.ok ? r.json() : null))
        .then((data: ExcerptResponse | null) => {
          if (!data) return;
          cache.set(hoveredNodeId, data);
          setExcerpt(data);
        })
        .catch(() => {})
        .finally(() => setLoading(false));
    }, 150);

    return () => {
      clearTimeout(t);
      abortRef.current?.abort();
    };
  }, [hoveredNodeId]);

  return (
    <AnimatePresence>
      {hoveredNodeId && (excerpt || loading) && (
        <motion.div
          initial={{ y: 280, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: 280, opacity: 0 }}
          transition={{ duration: 0.2, ease: [0.4, 0, 0.2, 1] }}
          className="fixed inset-x-0 bottom-0 z-40 mx-auto max-w-4xl border-t border-outline-variant bg-surface-container-lowest p-5"
          role="region"
          aria-label="Source excerpt"
        >
          {loading && !excerpt && (
            <div className="font-mono text-sm italic text-on-surface-variant">
              resolving cite…
            </div>
          )}
          {excerpt && (
            <article className="space-y-3">
              <header className="flex items-baseline justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="section-number">SOURCE</span>
                    <span className="meta-pill">{excerpt.publisher.toUpperCase()}</span>
                    {excerpt.docketNumber && (
                      <span className="font-mono text-xs text-on-surface-variant">
                        {excerpt.docketNumber}
                      </span>
                    )}
                  </div>
                  <h3 className="mt-1 truncate font-serif text-lg font-semibold text-on-surface">
                    {excerpt.docTitle}
                  </h3>
                </div>
                <a
                  href={excerpt.sourceUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="shrink-0 font-mono text-sm text-secondary transition hover:underline"
                >
                  open ↗
                </a>
              </header>

              <div
                className="font-sans text-on-surface [&_mark.claim-match]:rounded-sm [&_mark.claim-match]:bg-secondary/20 [&_mark.claim-match]:px-0.5 [&_mark.claim-match]:text-on-surface"
                style={{ fontSize: 15, lineHeight: 1.65 }}
                dangerouslySetInnerHTML={{ __html: excerpt.excerptHtml }}
              />

              {(excerpt.tValid || excerpt.tInvalid !== undefined) && (
                <div className="flex gap-4 font-mono text-xs text-on-surface-variant">
                  {excerpt.tValid && <span>valid from {excerpt.tValid}</span>}
                  <span>valid until {excerpt.tInvalid ?? "present"}</span>
                </div>
              )}
            </article>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
