"use client";

/**
 * AgentProgress
 * =============
 *
 * Progressive loading bar shown inside the Synthesis card while the agent is
 * still working. Subscribes to the `phase` slice of useGraphStore and shows:
 *
 *   1. A status line ("Planner extracting entities", "Walking subgraph", ...)
 *   2. A horizontal hairline progress bar that fills as phases advance
 *   3. A 6-step phase ticker (Plan / Retrieve / Subgraph / Debate / Draft / Verify)
 *      with the current step highlighted and prior steps marked done
 *   4. Live counters when relevant (sub-questions, walked nodes, draft chars)
 *
 * Once `phase === "done"` the component fades out so the answer text owns the
 * card. Once `phase === "error"` it stays visible in error red so the user
 * can see where things broke.
 */

import { useGraphStore, type AgentPhase } from "@/lib/store";

/* ── Phase order + target progress percentages ─────────────────────────────
   Each phase has a "base" percentage. Retrieving fills inside its slot based
   on `walkedCount`. Draft fills inside its slot based on `draftCharsReceived`.
   ──────────────────────────────────────────────────────────────────────── */
const PHASE_ORDER: AgentPhase[] = [
  "planning",
  "retrieving",
  "subgraph_ready",
  "debating",
  "drafting",
  "verifying",
];

const PHASE_BASE: Record<AgentPhase, number> = {
  idle:           0,
  starting:       3,
  planning:       12,
  retrieving:     30,
  subgraph_ready: 55,
  debating:       70,
  drafting:       85,
  verifying:      96,
  done:           100,
  error:          100,
};

const PHASE_LABEL: Record<AgentPhase, string> = {
  idle:           "Idle",
  starting:       "Initializing agent",
  planning:       "Planner extracting entities & sub-questions",
  retrieving:     "Walking the typed subgraph",
  subgraph_ready: "Subgraph committed, drafting",
  debating:       "Verifier opened the debate",
  drafting:       "Drafting answer with inline citations",
  verifying:      "Verifying claims against source HTML",
  done:           "Done",
  error:          "Agent error",
};

const PHASE_TICKER: { id: AgentPhase; short: string }[] = [
  { id: "planning",       short: "Plan"     },
  { id: "retrieving",     short: "Retrieve" },
  { id: "subgraph_ready", short: "Subgraph" },
  { id: "debating",       short: "Debate"   },
  { id: "drafting",       short: "Draft"    },
  { id: "verifying",      short: "Verify"   },
];

function phaseIndex(p: AgentPhase): number {
  const i = PHASE_ORDER.indexOf(p);
  return i === -1 ? -1 : i;
}

export function AgentProgress() {
  const phase = useGraphStore((s) => s.phase);
  const walked = useGraphStore((s) => s.walkedCount);
  const plannedSubQ = useGraphStore((s) => s.plannedSubQuestions);
  const plannedEntities = useGraphStore((s) => s.plannedEntities);
  const draftChars = useGraphStore((s) => s.draftCharsReceived);
  const debateActive = useGraphStore((s) => s.debateActive);

  if (phase === "idle") return null;

  // Compute progress: phase base + intra-phase fill.
  let progress = PHASE_BASE[phase];
  if (phase === "retrieving") {
    // Each walked node adds ~3% inside the retrieving slot (cap at 53% so
    // we never overshoot the next phase's base of 55%).
    progress = Math.min(53, PHASE_BASE.retrieving + walked * 3);
  } else if (phase === "drafting") {
    // Draft fills 85 -> 95 based on chars received (cap at ~95% so the bar
    // visibly settles when verifying kicks in).
    progress = Math.min(95, PHASE_BASE.drafting + Math.floor(draftChars / 30));
  }

  // Once done, hide everything except a tiny "done" confirmation line.
  const isDone = phase === "done";
  const isError = phase === "error";

  // Per-phase detail line
  let detail: string | null = null;
  switch (phase) {
    case "starting":
      detail = "Waiting for the first event from the agent sidecar...";
      break;
    case "planning":
      detail =
        plannedSubQ > 0
          ? `${plannedSubQ} sub-question${plannedSubQ === 1 ? "" : "s"} · ${plannedEntities} seed entit${plannedEntities === 1 ? "y" : "ies"}`
          : "Named-entity recognition over the question";
      break;
    case "retrieving":
      detail = `${walked} node${walked === 1 ? "" : "s"} walked across typed edges`;
      break;
    case "subgraph_ready":
      detail = "Provenance Orbit pinned. Drafting begins next.";
      break;
    case "debating":
      detail = debateActive
        ? "Vero and KHO arguing the conflict side-by-side"
        : "Verifier opened the debate panel";
      break;
    case "drafting":
      detail = `${draftChars} character${draftChars === 1 ? "" : "s"} streamed with inline citations`;
      break;
    case "verifying":
      detail = "Cross-checking every cite anchor against the source paragraph";
      break;
  }

  const activeIndex = phaseIndex(phase);

  return (
    <div
      className={
        "border " +
        (isError
          ? "border-error/40 bg-error-container/30"
          : isDone
          ? "border-outline-variant bg-surface-container-low/50"
          : "border-outline-variant bg-surface-container-low/40")
      }
      style={{
        paddingInline: "var(--space-5)",
        paddingBlock: "var(--space-4)",
        marginBottom: "var(--space-5)",
      }}
      role="status"
      aria-live="polite"
    >
      {/* Top row: label + percentage */}
      <div
        className="flex items-center justify-between"
        style={{ marginBottom: "var(--space-3)" }}
      >
        <div className="flex items-center" style={{ gap: "var(--space-3)" }}>
          {!isDone && !isError && (
            <Spinner color={isError ? "var(--color-error)" : "var(--color-secondary)"} />
          )}
          {isDone && (
            <span
              className="material-symbols-outlined text-secondary"
              style={{ fontSize: "var(--icon-sm)" }}
            >
              check_circle
            </span>
          )}
          {isError && (
            <span
              className="material-symbols-outlined text-error"
              style={{ fontSize: "var(--icon-sm)" }}
            >
              error
            </span>
          )}
          <span
            className="font-mono uppercase tracking-widest"
            style={{
              fontSize: "var(--text-overline)",
              color: isError ? "var(--color-error)" : "var(--color-on-surface)",
            }}
          >
            {PHASE_LABEL[phase]}
          </span>
        </div>
        <span
          className="font-mono text-on-surface-variant"
          style={{ fontSize: "var(--text-overline)" }}
        >
          {progress}%
        </span>
      </div>

      {/* Progress bar - 4px so it's actually visible at 3% */}
      <div
        className="relative w-full overflow-hidden bg-outline-variant"
        style={{ height: 4 }}
      >
        <div
          className="absolute left-0 top-0 h-full"
          style={{
            width: `${Math.max(2, progress)}%`,
            background: isError ? "var(--color-error)" : "var(--color-secondary)",
            transition: "width 280ms cubic-bezier(0.4, 0, 0.2, 1)",
          }}
        />
      </div>

      {/* Detail line */}
      {detail && (
        <div
          className="font-sans text-on-surface-variant"
          style={{
            marginTop: "var(--space-4)",
            fontSize: "var(--text-body-sm)",
            lineHeight: 1.5,
          }}
        >
          {detail}
        </div>
      )}

      {/* Phase ticker - proper stepper with visible dots and clear separators */}
      <div
        className="flex flex-wrap items-center font-mono uppercase tracking-wider text-on-surface-variant"
        style={{
          marginTop: "var(--space-4)",
          gap: "var(--space-4)",
          fontSize: "var(--text-overline)",
        }}
      >
        {PHASE_TICKER.flatMap((step, i, arr) => {
          const stepIndex = phaseIndex(step.id);
          // Skip the Debate step on non-debate runs (it would never light up)
          if (step.id === "debating" && !debateActive && phase !== "debating") {
            return [];
          }
          const reached = activeIndex >= stepIndex && activeIndex !== -1;
          const isActive = phase === step.id;
          const isPast = reached && !isActive;
          const elements = [
            <span
              key={step.id}
              className="flex items-center"
              style={{ gap: 8, opacity: reached || isDone ? 1 : 0.55 }}
            >
              <span
                className="inline-block shrink-0"
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "9999px",
                  background: isActive
                    ? "var(--color-secondary)"
                    : isPast || isDone
                    ? "var(--color-on-surface)"
                    : "var(--color-outline-variant)",
                  boxShadow: isActive
                    ? "0 0 0 3.5px rgba(148,73,33,0.18)"
                    : undefined,
                }}
                aria-hidden
              />
              <span
                style={{
                  color: isActive
                    ? "var(--color-secondary)"
                    : isPast || isDone
                    ? "var(--color-on-surface)"
                    : "var(--color-on-surface-variant)",
                  fontWeight: isActive ? 600 : 400,
                }}
              >
                {step.short}
              </span>
            </span>,
          ];
          if (i < arr.length - 1) {
            elements.push(
              <span
                key={`sep-${i}`}
                className="text-on-surface-variant/35"
                aria-hidden
              >
                ─
              </span>
            );
          }
          return elements;
        })}
      </div>
    </div>
  );
}

/** Small spinning indicator. Uses inline SVG + CSS keyframes so it works even
 *  if Tailwind's `animate-spin` utility isn't in the safelist. */
function Spinner({ color }: { color: string }) {
  return (
    <span
      aria-hidden
      style={{
        display: "inline-block",
        width: 12,
        height: 12,
        borderRadius: "9999px",
        border: `1.5px solid ${color}33`,
        borderTopColor: color,
        animation: "lex-spin 0.8s linear infinite",
      }}
    />
  );
}
