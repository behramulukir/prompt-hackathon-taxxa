"use client";

/**
 * LawTimeline — vertical, equal-spacing, chronological event list.
 *
 *   12 EVENTS                            2024-05-22
 *   ──────────────────────────────────────────────
 *   │
 *   ●  30 a §                          1995-01-01
 *   │
 *   ●  Muutossäädösten voimaantulo     1998-01-01
 *   │
 *   ●  3 §                             2004-08-15
 *   │
 *   ●═════════ ASOF ═════════
 *   │
 *   ●  1 §                             2006-09-01
 *   │  ...
 *
 * Why equal-spacing instead of date-proportional:
 *   The previous date-proportional layout pushed long stretches of empty
 *   axis between distant events (1989 → 2004 was a big void) AND clustered
 *   three same-day events (2020-01-01) on top of each other, which my
 *   collision-avoidance algorithm bumped down so they no longer matched
 *   their dates. Result: visually empty top + cluster of mis-aligned dots
 *   = "broken and not chronological at all".
 *
 *   The fix is to drop date-proportional Y entirely and give every event
 *   the same vertical slot. Order is strictly by tValid date so the list
 *   is unambiguously chronological. The asof bar still represents a date,
 *   not an index — its Y position is interpolated between the two events
 *   that bracket the current asof date, and dragging it sets a date
 *   linearly interpolated between those two events.
 */

import { useMemo, useRef, useState } from "react";
import { useGraphStore } from "@/lib/store";
import { colorForKind } from "@/lib/colors";
import type { OrbitNode } from "@/lib/types";

const W = 280;
const AXIS_X = 24;
const LABEL_X = 44;
const SLOT_H = 56;
const PAD_TOP = 18;
const PAD_BOTTOM = 18;

const TODAY = new Date().toISOString().slice(0, 10);

interface Pin {
  node: OrbitNode;
  date: string;
  ts: number;
  y: number;
}

/**
 * Compute the asof bar Y from a date by bracketing the two adjacent pins
 * and linearly interpolating between their Y positions.
 *   - asof before the first pin   → above the first pin by half a slot
 *   - asof after the last pin     → below the last pin by half a slot
 *   - asof on or between two pins → interpolate linearly in (date) space
 *                                    onto (Y) space
 */
function asofYFromDate(pins: Pin[], asofIso: string, height: number): number {
  if (pins.length === 0) return PAD_TOP;
  const ts = new Date(asofIso).getTime();
  if (ts <= pins[0].ts) return Math.max(PAD_TOP + 4, pins[0].y - SLOT_H / 2);
  const last = pins[pins.length - 1];
  if (ts >= last.ts) return Math.min(height - PAD_BOTTOM - 4, last.y + SLOT_H / 2);
  for (let i = 0; i < pins.length - 1; i++) {
    const a = pins[i];
    const b = pins[i + 1];
    if (ts >= a.ts && ts <= b.ts) {
      const span = b.ts - a.ts;
      const ratio = span > 0 ? (ts - a.ts) / span : 0;
      return a.y + ratio * (b.y - a.y);
    }
  }
  return last.y;
}

/**
 * Inverse: given the user dragged the asof bar to `targetY`, derive the
 * asof date by linear interpolation between the two pins that bracket
 * targetY in (Y) space.
 */
function dateFromAsofY(pins: Pin[], targetY: number): string {
  if (pins.length === 0) return TODAY;
  if (targetY <= pins[0].y) return pins[0].date;
  const last = pins[pins.length - 1];
  if (targetY >= last.y) return last.date;
  for (let i = 0; i < pins.length - 1; i++) {
    const a = pins[i];
    const b = pins[i + 1];
    if (targetY >= a.y && targetY <= b.y) {
      const span = b.y - a.y;
      const ratio = span > 0 ? (targetY - a.y) / span : 0;
      const ts = a.ts + ratio * (b.ts - a.ts);
      return new Date(ts).toISOString().slice(0, 10);
    }
  }
  return last.date;
}

export function LawTimeline() {
  const orbitNodes = useGraphStore((s) => s.orbitNodes);
  const asof = useGraphStore((s) => s.asof);
  const setAsof = useGraphStore((s) => s.setAsof);
  const setSelectedNodeId = useGraphStore((s) => s.setSelectedNodeId);
  const setHoveredNodeId = useGraphStore((s) => s.setHoveredNodeId);
  const setHoverAnchor = useGraphStore((s) => s.setHoverAnchor);
  const hoveredNodeId = useGraphStore((s) => s.hoveredNodeId);
  const selectedNodeId = useGraphStore((s) => s.selectedNodeId);

  const svgRef = useRef<SVGSVGElement | null>(null);
  const [dragging, setDragging] = useState(false);

  /* ────── Build pins (strict chronological order, equal spacing) ────── */
  const { pins, height } = useMemo(() => {
    const dated = orbitNodes
      .filter((n) => n.tValid)
      .sort((a, b) => a.tValid!.localeCompare(b.tValid!));
    const pins: Pin[] = dated.map((n, i) => ({
      node: n,
      date: n.tValid!,
      ts: new Date(n.tValid!).getTime(),
      y: PAD_TOP + i * SLOT_H + SLOT_H / 2,
    }));
    const height = PAD_TOP + dated.length * SLOT_H + PAD_BOTTOM;
    return { pins, height };
  }, [orbitNodes]);

  /* ────── Empty states ─────── */
  if (orbitNodes.length === 0) {
    return (
      <div className="font-mono text-xs italic text-on-surface-variant">
        Timeline populates when the agent commits to a subgraph.
      </div>
    );
  }
  if (pins.length === 0) {
    return (
      <div className="font-mono text-xs italic text-on-surface-variant">
        No dated events in the current subgraph.
      </div>
    );
  }

  const asofY = asofYFromDate(pins, asof, height);

  /* ────── Drag handling ─────── */
  const yFromPointer = (ev: { clientY: number }): number => {
    const svg = svgRef.current;
    if (!svg) return asofY;
    const rect = svg.getBoundingClientRect();
    const yPx = ev.clientY - rect.top;
    return (yPx / rect.height) * height;
  };

  const onAxisPointerDown = (ev: React.PointerEvent<SVGSVGElement>) => {
    (ev.currentTarget as SVGSVGElement).setPointerCapture(ev.pointerId);
    setDragging(true);
    setAsof(dateFromAsofY(pins, yFromPointer(ev)));
  };
  const onAxisPointerMove = (ev: React.PointerEvent<SVGSVGElement>) => {
    if (!dragging) return;
    setAsof(dateFromAsofY(pins, yFromPointer(ev)));
  };
  const onAxisPointerUp = (ev: React.PointerEvent<SVGSVGElement>) => {
    if (dragging) {
      (ev.currentTarget as SVGSVGElement).releasePointerCapture(ev.pointerId);
      setDragging(false);
    }
  };

  return (
    <div className="space-y-2">
      {/* Header — event count + current asof. Nothing else. */}
      <div
        className="flex items-baseline justify-between font-mono uppercase tracking-wider text-on-surface-variant"
        style={{ fontSize: "var(--text-overline)" }}
      >
        <span>{pins.length} events</span>
        <span className="font-semibold text-on-surface">{asof}</span>
      </div>

      <div className="border border-outline-variant bg-surface-container-lowest">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${height}`}
          width="100%"
          height={height}
          style={{
            display: "block",
            cursor: dragging ? "grabbing" : "ns-resize",
            userSelect: "none",
          }}
          onPointerDown={onAxisPointerDown}
          onPointerMove={onAxisPointerMove}
          onPointerUp={onAxisPointerUp}
          onPointerCancel={onAxisPointerUp}
          aria-label="Law-events timeline (vertical)"
        >
          {/* The vertical spine */}
          <line
            x1={AXIS_X}
            y1={PAD_TOP}
            x2={AXIS_X}
            y2={height - PAD_BOTTOM}
            stroke="#c4c7c7"
            strokeWidth={1.5}
            pointerEvents="none"
          />

          {/* Event pins */}
          <g>
            {pins.map((p, i) => {
              const isHovered = hoveredNodeId === p.node.id;
              const isSelected = selectedNodeId === p.node.id;
              const focused = isHovered || isSelected;
              const color = colorForKind(p.node.kind);
              const r = focused ? 6 : 4.5;
              const label = truncate(p.node.label, 26);
              return (
                <g
                  key={`pin-${i}-${p.node.id}`}
                  style={{ cursor: "pointer" }}
                  onMouseEnter={(ev) => {
                    setHoveredNodeId(p.node.id);
                    const rect = (ev.currentTarget as SVGGElement).getBoundingClientRect();
                    setHoverAnchor({
                      x: rect.left,
                      y: rect.top,
                      w: rect.width,
                      h: rect.height,
                    });
                  }}
                  onMouseLeave={() => {
                    setHoveredNodeId(null);
                    setHoverAnchor(null);
                  }}
                  onPointerDown={(ev) => ev.stopPropagation()}
                  onClick={(ev) => {
                    ev.stopPropagation();
                    setSelectedNodeId(p.node.id);
                  }}
                >
                  {/* Glow when focused */}
                  {focused && (
                    <circle cx={AXIS_X} cy={p.y} r={r + 5} fill={color} opacity={0.18} />
                  )}
                  {/* Dot */}
                  <circle
                    cx={AXIS_X}
                    cy={p.y}
                    r={r}
                    fill={color}
                    stroke="#fff"
                    strokeWidth={1.5}
                  />
                  {/* Label */}
                  <text
                    x={LABEL_X}
                    y={p.y - 1}
                    fontSize={12}
                    fontFamily="var(--font-sans)"
                    fill={focused ? color : "#1a1c1b"}
                    fontWeight={focused ? 600 : 500}
                  >
                    {label}
                  </text>
                  {/* Date */}
                  <text
                    x={LABEL_X}
                    y={p.y + 13}
                    fontSize={10}
                    fontFamily="var(--font-mono)"
                    fill="#747878"
                  >
                    {p.date}
                  </text>
                </g>
              );
            })}
          </g>

          {/* ASOF bar — horizontal terracotta line + triangle handle. Its
              Y is interpolated between the two pins bracketing `asof`, so
              it always sits naturally between events as you scrub. */}
          <g pointerEvents="none">
            <line
              x1={6}
              y1={asofY}
              x2={W - 6}
              y2={asofY}
              stroke="var(--color-secondary)"
              strokeWidth={1.5}
              strokeDasharray="3 3"
            />
            <polygon
              points={`${AXIS_X - 10},${asofY - 5} ${AXIS_X - 10},${asofY + 5} ${AXIS_X - 2},${asofY}`}
              fill="var(--color-secondary)"
            />
            <text
              x={W - 8}
              y={asofY - 4}
              fontSize={9.5}
              fontFamily="var(--font-mono)"
              fill="var(--color-secondary)"
              fontWeight={700}
              textAnchor="end"
              style={{ letterSpacing: 0.5 }}
            >
              ASOF
            </text>
          </g>
        </svg>
      </div>

      <p
        className="font-sans italic leading-snug text-on-surface-variant"
        style={{ fontSize: "var(--text-meta)" }}
      >
        Drag the terracotta bar up or down to time-travel between events.
      </p>
    </div>
  );
}

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return s.slice(0, max - 1) + "…";
}
