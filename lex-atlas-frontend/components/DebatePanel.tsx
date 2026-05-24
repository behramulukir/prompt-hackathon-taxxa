"use client";

/**
 * DebatePanel — when the Verifier detects an equal-rank conflict (typically
 * Vero guidance vs a KHO ruling), the agent splits the draft into a public
 * AgenticSimLaw-style debate.
 *
 * Layout (top → bottom):
 *
 *   1. Title strip with the "interpretive debate" badge
 *   2. <DebateVisualization>  - balance widget tilting toward the winner,
 *      cumulative argument metrics per party, and the judge principle
 *   3. Two argument cards side-by-side (Vero teal · KHO pink)
 *
 * Subscribes to useGraphStore for `debateActive`, `debate`, `debateMessages`.
 */

import { useMemo } from "react";
import { useGraphStore } from "@/lib/store";

const VERO_COLOR = "#006B70";
const KHO_COLOR = "#9C2B5F";

export function DebatePanel() {
  const debateActive = useGraphStore((s) => s.debateActive);
  const debate = useGraphStore((s) => s.debate);
  const messages = useGraphStore((s) => s.debateMessages);

  const partyAText = useMemo(
    () => messages.filter((m) => m.party === "A").map((m) => m.text).join(""),
    [messages]
  );
  const partyBText = useMemo(
    () => messages.filter((m) => m.party === "B").map((m) => m.text).join(""),
    [messages]
  );

  if (!debateActive) return null;

  return (
    <div className="insight-marker flex flex-col gap-4 pl-4 md:pl-10">
      <div className="mb-2 flex items-center gap-2 font-mono text-xs uppercase tracking-widest text-secondary">
        <span className="material-symbols-outlined" style={{ fontSize: 16 }}>
          balance
        </span>
        Interpretive Debate Detected
      </div>

      <DebateVisualization
        partyAText={partyAText}
        partyBText={partyBText}
        resolution={debate?.judge.resolution}
        principle={debate?.judge.principle}
        reasoning={debate?.judge.reasoning}
      />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* Vero column */}
        <DebateCard
          role="Vero (Tax Admin)"
          icon="account_balance"
          color={VERO_COLOR}
          docket="Guideline VH/1234/2025"
          text={partyAText}
          streaming={!debate}
        />
        {/* KHO column */}
        <DebateCard
          role="KHO (Supreme Admin Court)"
          icon="gavel"
          color={KHO_COLOR}
          docket="KHO:2024:89"
          text={partyBText}
          streaming={!debate}
        />
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────
   DebateVisualization

   A compact SVG that does three things at once:

     (a) Balance widget — a fulcrum at the top with two arms. The arm
         angle is driven by the judge's resolution (A = tilt left toward
         Vero, B = tilt right toward KHO, synthesis = level). While the
         debate is still streaming the beam wobbles gently with the
         current text-length ratio so the user sees it shift in real time.

     (b) Argument metrics — claim count (sentences) and citation count
         (\[cite:node:…\] tokens) per party. These are derived from the
         streamed text so they update live.

     (c) Principle ribbon — the priority principle that resolved the
         conflict (e.g. "Court ruling > Vero guidance").

   ───────────────────────────────────────────────────────────────────── */

interface DebateVisualizationProps {
  partyAText: string;
  partyBText: string;
  resolution?: "A" | "B" | "synthesis";
  principle?: string;
  reasoning?: string;
}

function DebateVisualization({
  partyAText,
  partyBText,
  resolution,
  principle,
  reasoning,
}: DebateVisualizationProps) {
  /* ── Derive live metrics from streamed text ── */
  const metrics = useMemo(() => {
    const countClaims = (t: string) =>
      t.split(/[.!?]\s/).filter((s) => s.trim().length > 8).length;
    const countCites = (t: string) =>
      (t.match(/\[cite:node:[^\]]+\]/g) ?? []).length;
    return {
      a: {
        chars: partyAText.length,
        claims: countClaims(partyAText),
        cites: countCites(partyAText),
      },
      b: {
        chars: partyBText.length,
        claims: countClaims(partyBText),
        cites: countCites(partyBText),
      },
    };
  }, [partyAText, partyBText]);

  /* ── Compute beam tilt ──
     Final state: hard tilt toward the judge's winner.
     Streaming: tilt softly toward whichever party currently has more text.
     ─────────────────── */
  const finalTilt =
    resolution === "A" ? -16 : resolution === "B" ? 16 : 0; // degrees
  let liveTilt = 0;
  const totalChars = metrics.a.chars + metrics.b.chars;
  if (!resolution && totalChars > 0) {
    const ratio = (metrics.b.chars - metrics.a.chars) / Math.max(totalChars, 1);
    liveTilt = ratio * 8; // softer wobble during streaming
  }
  const tilt = resolution ? finalTilt : liveTilt;

  const winnerLabel = resolution
    ? resolution === "synthesis"
      ? "Synthesis"
      : resolution === "A"
      ? "Vero wins"
      : "KHO wins"
    : "Debate in progress";

  return (
    <div
      className="border border-outline-variant bg-surface-container-lowest"
      style={{ padding: "var(--space-5)" }}
    >
      <div className="flex items-stretch" style={{ gap: "var(--space-6)" }}>
        {/* ── Balance widget (SVG) ── */}
        <div className="shrink-0" style={{ width: 200 }}>
          <svg
            viewBox="0 0 200 130"
            width="100%"
            aria-label="Debate balance widget"
          >
            {/* Fulcrum base */}
            <polygon points="100,110 84,124 116,124" fill="#1a1c1b" />
            <rect x={88} y={110} width={24} height={4} fill="#1a1c1b" />
            {/* Vertical stand */}
            <line
              x1={100}
              y1={42}
              x2={100}
              y2={110}
              stroke="#1a1c1b"
              strokeWidth={1.5}
            />
            {/* Beam (rotates) */}
            <g
              transform={`rotate(${tilt} 100 42)`}
              style={{ transition: "transform 0.8s cubic-bezier(0.4, 0, 0.2, 1)" }}
            >
              <line
                x1={20}
                y1={42}
                x2={180}
                y2={42}
                stroke="#1a1c1b"
                strokeWidth={2}
              />
              {/* Hooks down to the pans */}
              <line x1={32} y1={42} x2={32} y2={58} stroke="#1a1c1b" strokeWidth={1} />
              <line x1={168} y1={42} x2={168} y2={58} stroke="#1a1c1b" strokeWidth={1} />
              {/* Left pan (Party A = Vero, teal) */}
              <ellipse cx={32} cy={62} rx={26} ry={5} fill={VERO_COLOR} opacity={0.18} />
              <path
                d="M 8 60 Q 32 84 56 60 Z"
                fill={VERO_COLOR}
                fillOpacity={0.3}
                stroke={VERO_COLOR}
                strokeWidth={1.2}
              />
              <text
                x={32}
                y={56}
                fontSize={9}
                fontFamily="var(--font-mono)"
                fill={VERO_COLOR}
                textAnchor="middle"
                fontWeight={600}
              >
                VERO
              </text>
              {/* Right pan (Party B = KHO, pink) */}
              <ellipse cx={168} cy={62} rx={26} ry={5} fill={KHO_COLOR} opacity={0.18} />
              <path
                d="M 144 60 Q 168 84 192 60 Z"
                fill={KHO_COLOR}
                fillOpacity={0.3}
                stroke={KHO_COLOR}
                strokeWidth={1.2}
              />
              <text
                x={168}
                y={56}
                fontSize={9}
                fontFamily="var(--font-mono)"
                fill={KHO_COLOR}
                textAnchor="middle"
                fontWeight={600}
              >
                KHO
              </text>
            </g>
            {/* Pivot point */}
            <circle cx={100} cy={42} r={3} fill="var(--color-secondary)" />
          </svg>
          <div
            className="mt-1 text-center font-mono uppercase tracking-wider"
            style={{
              fontSize: "var(--text-overline)",
              color: resolution
                ? "var(--color-secondary)"
                : "var(--color-on-surface-variant)",
              fontWeight: resolution ? 700 : 500,
            }}
          >
            {winnerLabel}
          </div>
        </div>

        {/* ── Metrics + principle ── */}
        <div
          className="min-w-0 flex-1"
          style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}
        >
          {/* Per-party metrics with proportional bars */}
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
            <MetricRow
              label="Vero"
              color={VERO_COLOR}
              claims={metrics.a.claims}
              cites={metrics.a.cites}
              chars={metrics.a.chars}
              total={Math.max(totalChars, 1)}
              winner={resolution === "A"}
            />
            <MetricRow
              label="KHO"
              color={KHO_COLOR}
              claims={metrics.b.claims}
              cites={metrics.b.cites}
              chars={metrics.b.chars}
              total={Math.max(totalChars, 1)}
              winner={resolution === "B"}
            />
          </div>

          {/* Resolution ribbon */}
          <div
            className="border-l-2 bg-surface-container-low/40"
            style={{
              borderLeftColor: resolution
                ? "var(--color-secondary)"
                : "var(--color-outline-variant)",
              padding: "var(--space-3) var(--space-4)",
            }}
          >
            <div
              className="font-mono uppercase tracking-wider text-on-surface-variant"
              style={{ fontSize: "var(--text-overline)" }}
            >
              {resolution ? "Resolved by" : "Awaiting verdict"}
            </div>
            {principle ? (
              <div
                className="mt-1 font-sans font-semibold text-on-surface"
                style={{ fontSize: "var(--text-body)", lineHeight: 1.4 }}
              >
                {principle}
              </div>
            ) : (
              <div
                className="mt-1 font-sans italic text-on-surface-variant"
                style={{ fontSize: "var(--text-body-sm)" }}
              >
                Judge is weighing the priority lattice…
              </div>
            )}
            {reasoning && (
              <p
                className="mt-2 font-sans text-on-surface-variant"
                style={{ fontSize: "var(--text-body-sm)", lineHeight: 1.55 }}
              >
                {reasoning}
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

interface MetricRowProps {
  label: string;
  color: string;
  claims: number;
  cites: number;
  chars: number;
  total: number;
  winner: boolean;
}

function MetricRow({ label, color, claims, cites, chars, total, winner }: MetricRowProps) {
  const pct = (chars / total) * 100;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div
        className="flex items-baseline justify-between"
        style={{ gap: "var(--space-3)" }}
      >
        <span
          className="flex items-center font-mono uppercase tracking-wider"
          style={{ gap: 6, color, fontSize: "var(--text-overline)" }}
        >
          {label}
          {winner && (
            <span
              className="font-mono uppercase"
              style={{
                fontSize: 9,
                background: color,
                color: "#fff",
                padding: "1px 5px",
                letterSpacing: 0.6,
              }}
            >
              winner
            </span>
          )}
        </span>
        <span
          className="font-mono text-on-surface-variant"
          style={{ fontSize: "var(--text-meta)" }}
        >
          {claims} claim{claims === 1 ? "" : "s"} · {cites} cite{cites === 1 ? "" : "s"}
        </span>
      </div>
      <div
        className="relative"
        style={{ height: 3, background: "var(--color-outline-variant)" }}
      >
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            height: "100%",
            width: `${pct}%`,
            background: color,
            transition: "width 0.4s ease",
          }}
        />
      </div>
    </div>
  );
}

interface DebateCardProps {
  role: string;
  icon: string;
  color: string;
  docket: string;
  text: string;
  streaming: boolean;
}

function DebateCard({ role, icon, color, docket, text, streaming }: DebateCardProps) {
  return (
    <div
      className="relative overflow-hidden border bg-surface-container-lowest p-5"
      style={{ borderColor: `${color}4D` }}
    >
      <div
        className="absolute left-0 top-0 h-full w-1"
        style={{ background: color }}
      />
      <div
        className="mb-3 flex items-start justify-between border-b pb-2"
        style={{ borderColor: `${color}33` }}
      >
        <span
          className="flex items-center gap-2 font-mono text-sm font-semibold"
          style={{ color }}
        >
          <span className="material-symbols-outlined" style={{ fontSize: 18 }}>
            {icon}
          </span>
          {role}
        </span>
        <span className="font-mono text-xs text-on-surface-variant">{docket}</span>
      </div>
      <p className="font-sans text-on-surface" style={{ fontSize: 15, lineHeight: 1.6 }}>
        {text || (
          <span className="italic text-on-surface-variant">Waiting for argument…</span>
        )}
        {streaming && text && (
          <span
            className="ml-1 inline-block h-4 w-2 animate-pulse align-middle"
            style={{ background: color }}
            aria-hidden
          />
        )}
      </p>
    </div>
  );
}
