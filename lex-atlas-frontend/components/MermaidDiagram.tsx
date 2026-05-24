"use client";

/**
 * MermaidDiagram — renders a Mermaid flowchart from a source string.
 *
 * Implementation notes:
 *  - Dynamic-imports the ``mermaid`` package on mount, so the diagram code
 *    is excluded from the main bundle (it's heavy — ~500 KB minified).
 *  - If the package isn't installed (``npm install mermaid`` was skipped),
 *    we fall back to a monospace block showing the diagram source. The
 *    diagram is still readable, just not laid out.
 *  - Renders once per ``code`` string; subsequent code changes re-render.
 *  - SVG is injected via ``dangerouslySetInnerHTML`` because mermaid
 *    returns a serialized SVG string. Source comes from us, never from
 *    user input.
 */

import { useEffect, useId, useState } from "react";

interface MermaidDiagramProps {
  code: string;
  /** Title shown above the diagram for screen readers. */
  ariaLabel?: string;
}

export function MermaidDiagram({ code, ariaLabel }: MermaidDiagramProps) {
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Stable id per instance so concurrent diagrams don't collide.
  const id = "m-" + useId().replace(/:/g, "_");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Dynamic import. If the ``mermaid`` package isn't installed this
        // throws ``Module not found`` and we render the fallback below.
        // mermaid ≥ 10 ships its API on the default export; older versions
        // exposed it on the namespace, so handle both shapes.
        const mod: unknown = await import("mermaid");
        if (cancelled) return;
        const mermaid =
          (mod as { default?: { initialize: unknown; render: unknown } }).default
          ?? (mod as { initialize: unknown; render: unknown });
        // Cast once to the minimal shape we actually call.
        const api = mermaid as {
          initialize: (cfg: Record<string, unknown>) => void;
          render: (id: string, code: string) => Promise<{ svg: string }>;
        };
        // ``default`` theme works on light backgrounds. ``securityLevel:
        // strict`` blocks click handlers in the source — we're rendering
        // a static doc page, not interactive.
        api.initialize({
          startOnLoad: false,
          theme: "default",
          securityLevel: "strict",
          fontFamily: "var(--font-jetbrains-mono), monospace",
        });
        const { svg } = await api.render(id, code);
        if (!cancelled) setSvg(svg);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [code, id]);

  if (svg) {
    return (
      <div
        role="img"
        aria-label={ariaLabel ?? "Architecture diagram"}
        className="overflow-x-auto border border-outline-variant bg-surface-container-lowest p-4"
        // Mermaid output is trusted (we author the source); the strict
        // securityLevel above also strips any inline event handlers.
        dangerouslySetInnerHTML={{ __html: svg }}
      />
    );
  }

  // Fallback path — package missing, or render error. The user can still
  // read the source and paste it into mermaid.live themselves.
  return (
    <div className="space-y-2">
      <div
        className="flex items-center gap-2 border border-outline-variant bg-surface-container-low px-3 py-2"
        role="note"
      >
        <span
          className="material-symbols-outlined text-on-surface-variant"
          style={{ fontSize: 18 }}
        >
          info
        </span>
        <div
          className="font-mono text-on-surface-variant"
          style={{ fontSize: "var(--text-meta)" }}
        >
          {error
            ? "Mermaid renderer reported an error — showing source. "
            : "Mermaid package not installed — showing source. "}
          Install with{" "}
          <code className="font-mono text-on-surface">npm install mermaid</code>{" "}
          to render the diagram, or paste the source into{" "}
          <a
            href="https://mermaid.live"
            target="_blank"
            rel="noopener noreferrer"
            className="text-secondary hover:underline"
          >
            mermaid.live
          </a>
          .
        </div>
      </div>
      <pre
        className="overflow-x-auto border border-outline-variant bg-surface-container-lowest p-4 font-mono text-on-surface"
        style={{ fontSize: "var(--text-body-sm)", lineHeight: 1.55 }}
      >
        {code}
      </pre>
    </div>
  );
}
