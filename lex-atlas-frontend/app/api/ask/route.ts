/**
 * /api/ask — SSE proxy from Next.js to the Python agent sidecar.
 *
 * Per 2026 Next.js best practices:
 *   - `runtime = "nodejs"` (edge has 30s timeout; agent runs ~8-15s)
 *   - `dynamic = "force-dynamic"` (otherwise Next caches the route)
 *   - `Content-Type: text/event-stream`
 *   - `X-Accel-Buffering: no` (disables nginx/Vercel buffering)
 *
 * We pipe upstream SSE bytes verbatim. The Python sidecar at AGENT_SIDECAR_URL
 * (defaults to /agent/* via next.config rewrite) formats events as
 * `data: {json}\n\n` already.
 *
 * Demo fallback: if AGENT_SIDECAR_URL is unreachable, we replay a canned
 * SSE event sequence from `data/demo_q4_replay.jsonl` so the demo never
 * fails even when the sidecar is down. This is the safety net.
 */

import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const maxDuration = 60;

interface AskBody {
  question: string;
  asof: string;
  lang: "fi" | "sv" | "en";
  mode?: "ask" | "draft_email" | "debate_only";
  /** When true, fixture replay skips all setTimeout delays. Used for screenshots / e2e. */
  instant?: boolean;
}

export async function POST(req: NextRequest) {
  // req.json() throws on empty body (e.g. EventSource reconnect probe) — guard it.
  let body: AskBody;
  try {
    body = (await req.json()) as AskBody;
  } catch {
    return new Response("Invalid or empty JSON body", { status: 400 });
  }
  const { question } = body;
  if (!question || question.length < 4) {
    return new Response("Question too short", { status: 400 });
  }

  const sidecar = process.env.AGENT_SIDECAR_URL ?? "http://localhost:8000";
  const encoder = new TextEncoder();

  const stream = new ReadableStream({
    async start(controller) {
      const send = (event: object) => {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
      };

      let sidecarOk = false;
      try {
        const upstream = await fetch(`${sidecar}/ask`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
          signal: req.signal,
        });

        if (upstream.ok && upstream.body) {
          sidecarOk = true;
          // Pipe upstream SSE verbatim
          const reader = upstream.body.getReader();
          while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            controller.enqueue(value);
          }
        }
      } catch {
        // Connection refused, DNS error, etc. — falls through to fixture replay
      }

      if (!sidecarOk) {
        // Sidecar unreachable — replay the demo fixture so the UI still works
        try {
          await replayFixture(send, body);
        } catch (e) {
          send({ type: "error", message: String(e) });
        }
      }

      send({ type: "done" });
      controller.close();
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}

/* ───────────────────────────────────────────────────────────────────────── */

/**
 * Demo fixture replay — for when the Python sidecar is down. Walks through
 * a canned event sequence for Q4 (avainhenkilö withholding) at realistic
 * timing so the UI shows the full demo motion. Pass `instant: true` to skip
 * all delays (used for screenshots and e2e tests).
 */
async function replayFixture(
  send: (event: object) => void,
  body: AskBody
) {
  const wantsDebate =
    body.mode === "debate_only" ||
    /debate|kho|conflict|kolmikanta|disagree|override/i.test(body.question);

  const events: Array<[number, object]> = wantsDebate
    ? buildDebateFixture()
    : buildQ4Fixture();

  let prevT = 0;
  for (const [t, ev] of events) {
    if (!body.instant) {
      await new Promise((r) => setTimeout(r, t - prevT));
    }
    prevT = t;
    send(ev);
  }
}

/** Q4 fixture — the avainhenkilö withholding question, deterministic path. */
function buildQ4Fixture(): Array<[number, object]> {
  return [
    [200, { type: "ner_pulse", entityNodeIds: ["concept:avainhenkilo", "concept:lahdevero", "work:avainhenkilolaki"] }],
    [800, { type: "plan", subQuestions: ["What rate?", "How long is the card valid?", "What changed in 2026?"], entityNodeIds: ["work:avainhenkilolaki", "concept:lahdevero"] }],
    [1200, { type: "walked", nodeId: "ctv:avh:§3@2026-01-01", score: 0.93, step: 1 }],
    [1380, { type: "walked", nodeId: "ctv:avh:§3@2020-01-01", score: 0.78, step: 2 }],
    [1560, { type: "walked", nodeId: "work:vero-kannanotto:avainhenkilo-2020", score: 0.72, step: 3 }],
    [1740, { type: "walked", nodeId: "work:vero-ohje:rajoitetusti-2026", score: 0.81, step: 4 }],
    [1920, { type: "walked", nodeId: "comp:avh:§4", score: 0.65, step: 5 }],
    [2200, {
      type: "subgraph_ready",
      orbitNodes: [
        { id: "concept:avainhenkilo", kind: "concept", label: "concept · avainhenkilö", authorityRank: 1, isActive: true, isCenter: true },
        { id: "work:avainhenkilolaki", kind: "work", label: "avainhenkilölaki 1551/1995", authorityRank: 8, isActive: true },
        { id: "ctv:avh:§3@2026-01-01", kind: "action", label: "§3 · 1.1.2026 · rate 25%", authorityRank: 6, isActive: true, tValid: "2026-01-01" },
        { id: "ctv:avh:§3@2020-01-01", kind: "action", label: "§3 · 1.1.2020 · rate 32%", authorityRank: 6, isActive: false, tValid: "2020-01-01", tInvalid: "2025-12-31" },
        { id: "work:vero-kannanotto:avainhenkilo-2020", kind: "guidance", label: "Vero kannanotto · 2020 transition", authorityRank: 3, isActive: false, tValid: "2020-01-01", tInvalid: "2025-12-31" },
        { id: "work:vero-ohje:rajoitetusti-2026", kind: "guidance", label: "Vero ohje · Rajoitetusti (8.1.2026)", authorityRank: 3, isActive: true, tValid: "2026-01-08" },
      ],
      orbitEdges: [
        { source: "concept:avainhenkilo", target: "work:avainhenkilolaki", relation: "defines" },
        { source: "work:avainhenkilolaki", target: "ctv:avh:§3@2026-01-01", relation: "has_part" },
        { source: "work:avainhenkilolaki", target: "ctv:avh:§3@2020-01-01", relation: "has_part" },
        { source: "work:vero-kannanotto:avainhenkilo-2020", target: "ctv:avh:§3@2020-01-01", relation: "interprets" },
        { source: "work:vero-ohje:rajoitetusti-2026", target: "ctv:avh:§3@2026-01-01", relation: "interprets" },
      ],
    }],
    [3000, { type: "draft_token", text: "Under the avainhenkilölaki " }],
    [3100, { type: "draft_token", text: "[cite:node:work:avainhenkilolaki](1551/1995)[/cite], " }],
    [3300, { type: "draft_token", text: "wages paid on or after 1 January 2026 are subject to a flat withholding tax of " }],
    [3500, { type: "draft_token", text: "[cite:node:ctv:avh:§3@2026-01-01]25%[/cite], " }],
    [3700, { type: "draft_token", text: "having been reduced from the prior " }],
    [3850, { type: "draft_token", text: "[cite:node:ctv:avh:§3@2020-01-01]32%[/cite] " }],
    [4000, { type: "draft_token", text: "that applied through 31 December 2025. " }],
    [4400, { type: "draft_token", text: "The key-personnel tax card is valid for up to " }],
    [4550, { type: "draft_token", text: "[cite:node:comp:avh:§4]84 months[/cite] " }],
    [4700, { type: "draft_token", text: "from the start of employment under the 2026 rules. " }],
    [5000, { type: "cost", cents: 0.047 }],
    [5200, { type: "done" }],
  ];
}

/** Debate fixture — KHO ruling vs Vero ohje on a contested §, AgenticSimLaw-style. */
function buildDebateFixture(): Array<[number, object]> {
  return [
    [200, { type: "ner_pulse", entityNodeIds: ["concept:reverse-charge", "work:avl", "case:kho-2024-19"] }],
    [700, { type: "plan", subQuestions: ["What's Vero's interpretation?", "What did KHO rule?", "Which prevails?"], entityNodeIds: ["work:avl", "case:kho-2024-19"] }],
    [1100, { type: "walked", nodeId: "ctv:avl:§8c@2023", score: 0.91, step: 1 }],
    [1280, { type: "walked", nodeId: "work:vero-ohje:reverse-charge-construction", score: 0.86, step: 2 }],
    [1460, { type: "walked", nodeId: "case:kho-2024-19", score: 0.94, step: 3 }],
    [1640, { type: "walked", nodeId: "comp:avl:§8c", score: 0.72, step: 4 }],
    [1900, {
      type: "subgraph_ready",
      orbitNodes: [
        { id: "comp:avl:§8c", kind: "concept", label: "AVL §8c · reverse charge", authorityRank: 1, isActive: true, isCenter: true },
        { id: "work:avl", kind: "work", label: "Arvonlisäverolaki (1501/1993)", authorityRank: 8, isActive: true },
        { id: "case:kho-2024-19", kind: "case", label: "KHO 2024:19 · overrides Vero ohje", authorityRank: 7, isActive: true, isConflicted: true, tValid: "2024-03-15" },
        { id: "work:vero-ohje:reverse-charge-construction", kind: "guidance", label: "Vero ohje · käännetty verovelvollisuus rakennusalalla", authorityRank: 3, isActive: true, isConflicted: true, tValid: "2023-01-15" },
      ],
      orbitEdges: [
        { source: "comp:avl:§8c", target: "work:avl", relation: "has_part" },
        { source: "case:kho-2024-19", target: "comp:avl:§8c", relation: "rules_on" },
        { source: "work:vero-ohje:reverse-charge-construction", target: "comp:avl:§8c", relation: "interprets" },
      ],
    }],
    [2400, { type: "conflict", nodeA: "case:kho-2024-19", nodeB: "work:vero-ohje:reverse-charge-construction", principle: "case_law_overrides_authority_interpretation" }],
    // The Debate opens
    [2900, { type: "debate_open", partyAId: "work:vero-ohje:reverse-charge-construction", partyBId: "case:kho-2024-19" }],
    // Party A (Vero) streams
    [3100, { type: "debate_token", party: "A", text: "Vero's published guidance on AVL §8c (Dnro VH/3214/00.01.00/2023) " }],
    [3300, { type: "debate_token", party: "A", text: "treats subcontracted demolition as outside the construction-services reverse-charge regime. " }],
    [3550, { type: "debate_token", party: "A", text: "The rationale: demolition is not 'construction' under the directive's narrow reading. " }],
    // Party B (KHO) streams in parallel-ish
    [3200, { type: "debate_token", party: "B", text: "KHO 2024:19 (15.3.2024) holds that demolition contracts forming part of a continuous construction project " }],
    [3450, { type: "debate_token", party: "B", text: "fall within AVL §8c reverse charge, contradicting Vero's narrow construction. " }],
    [3700, { type: "debate_token", party: "B", text: "Court relied on EU VAT Directive 2006/112 Art. 199 and CJEU C-395/11. " }],
    // Continued
    [4000, { type: "debate_token", party: "A", text: "Authority response: Vero updated guidance pending further analysis. " }],
    [4200, { type: "debate_token", party: "B", text: "Court ruling is binding from 15.3.2024; supersedes prior Vero interpretation. " }],
    // Judge resolves
    [4900, {
      type: "debate_judge",
      judge: {
        principle: "Court rulings override tax-authority interpretation when they conflict on the same statutory provision.",
        resolution: "B",
        reasoning: "KHO 2024:19 (rank 7) supersedes the Vero ohje (rank 3) under the priority lattice. The reverse-charge regime applies to demolition contracts that form part of a continuous construction project, effective from the ruling date 15.3.2024. Vero subsequently updated its guidance to align.",
      },
    }],
    // Final synthesis
    [5300, { type: "draft_token", text: "On reverse-charge VAT under " }],
    [5400, { type: "draft_token", text: "[cite:node:comp:avl:§8c]AVL §8c[/cite], " }],
    [5600, { type: "draft_token", text: "demolition contracts forming part of a continuous construction project " }],
    [5800, { type: "draft_token", text: "fall within the reverse-charge regime per " }],
    [5950, { type: "draft_token", text: "[cite:node:case:kho-2024-19]KHO 2024:19[/cite], " }],
    [6150, { type: "draft_token", text: "which overrides the earlier narrower interpretation in " }],
    [6300, { type: "draft_token", text: "[cite:node:work:vero-ohje:reverse-charge-construction]Vero ohje[/cite]. " }],
    [6700, { type: "cost", cents: 0.082 }],
    [6900, { type: "done" }],
  ];
}
