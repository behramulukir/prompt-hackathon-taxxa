# Hybrid Cinematic Demo — UI Concept Documentation

## Purpose

Demo concept for the **Agentic GraphRAG** challenge (Aalto × Taxxa hackathon). Designed for hackathon judges with an emphasis on visual wow factor — proves simultaneously that the graph is real, that agents are doing real work, and that the system produces a usable accountant-grade memo.

## Audience and goals

| Dimension | Choice |
|-----------|--------|
| Primary audience | Hackathon judges |
| Proof emphasis | Graph is real + agents are doing real work |
| Answer surface | Hybrid — chat that produces an inline report |
| Animation mode | Cinematic on first load, snappy fallback via Skip |
| Reasoning panel | Equal-weight split (Graph + Agents), tabs swap emphasis |

## Layout

Three-region split:

```
┌─────────────────────────────────────────────────────────────┐
│ Header bar  ·  brand · context (jurisdiction · year · src)  │
├──────────────────────────────────────┬──────────────────────┤
│                                      │                      │
│  CHAT COLUMN                         │  REASONING PANEL     │
│  ─ user message                      │  ─ tab switcher      │
│  ─ reasoning strip (live counters)   │  ─ graph traversal   │
│  ─ inline memo (streams in)          │  ─ agent timeline    │
│                                      │  ─ run budget        │
│                                      │                      │
├──────────────────────────────────────┴──────────────────────┤
│ Composer  ·  follow-up input                                │
└─────────────────────────────────────────────────────────────┘
```

The left column is the user-facing surface. The right column is the "show your work" panel that earns judge attention.

## Components

### Header bar
Brand mark + active context (Finland, tax year 2025, source set: Finlex + Vero). The context band frames every answer in the same scope — judges immediately understand the system is jurisdiction-aware.

### Reasoning strip
Horizontal band directly under the user question. Aggregates live state from the reasoning panel into four counters:
- **Strategy badge** — "Routing…" → "Multi-hop" once the Planner classifies the question
- **Nodes · edges** traversed
- **Agents** active / total
- **Time** elapsed

Two controls on the right: **Skip** (collapse to completed state) and **Replay** (re-run the cinematic).

This strip is what a viewer sees first. It tells them "something non-trivial is happening" before the report renders.

### Inline memo (the answer)
A document, not a chat bubble. Structure:
- Meta line: `Memo · date · sources in force at issuance`
- Title and sub-line (serif, mirrors a real research memo)
- Assumption chip — surfaced by the Clarifier when the question is under-specified
- Numbered sections: governing rule, exception, conflict callout, partial exemption, conclusion
- Citation pills colored by source (blue = Finlex, amber = Vero)
- Inline conflict callout (amber, with explicit resolution rule)
- Footer with Export · Share · Copy memo · feedback buttons

The conflict callout sits *between* sections 2 and 3, where the divergence is relevant — not appended at the end as an afterthought. This is the single most important detail for proving the Verifier is doing real work.

### Reasoning panel — Graph block
A small SVG graph showing the actual traversal path for the current question.

- **Seed node** (`§114 AVL`) — pulsing blue border, marked as vector hit
- **Expanded nodes** — appear sequentially as the BFS walks edges:
  - `§114.2` via `parent_of`
  - `§117 AVL` via `cites`
  - `Vero 2019` via `interprets` (amber — different source)
- **Conflict edge** — amber, dashed, animated stroke between Vero 2019 and §114.2
- **Ghost nodes** — faded gray peripheral dots, hinting at the larger graph not traversed
- Live counter in the header tracks nodes/edges as they appear
- Legend at the bottom: Finlex / Vero / not-traversed

### Reasoning panel — Agent timeline
Five rows, one per agent. Each row dims when inactive, brightens when active, and shows a green check when complete.

| Agent | What it shows |
|-------|---------------|
| Clarifier | "Missing: tax year, entity type. Proceeding with defaults." |
| Planner | Three numbered sub-questions revealed inline |
| Retriever | "Vector hit on §114 · walked 1 hop on parent_of, cites, interprets" |
| Extractor | New edge written: `vero:2019 —interprets→ §114.2` (the visible learning-loop moment) |
| Verifier | Conflict mini-callout: "Vero 2019 stricter than §114.2. Finlex (100) > Vero (60)" |

Progress indicator in the header: `n/4 done`.

### Run budget (panel footer)
Four cells with tabular numerals: Total time · LLM calls · Edges added · Conflicts.

The **Edges added** counter ticking from 0 to 1 mid-animation is the only visible proof that the system writes back to the graph at query time. Worth a verbal callout when delivering the demo.

### Composer
Standard input + send button. Placeholder text suggests a follow-up that exercises the Clarifier: *"What if it's a foundation instead?"*

## Animation choreography

Cinematic timeline runs once on load, replayable via the Replay button. Total wall-clock: roughly 11 seconds. Final answer time displayed is 3.4s (the *simulated* answer time — the animation is dilated for legibility).

| Time (s) | Phase | Visible action |
|----------|-------|----------------|
| 0.2 | Setup | Strategy badge appears: "Routing…" |
| 0.5–1.1 | Clarifier | Row activates (blinking dot), then completes |
| 1.2 | — | Assumption chip slides into the report area |
| 1.4–2.2 | Planner | Row activates, three sub-questions reveal |
| 2.3 | — | Strategy badge updates to "Multi-hop" |
| 2.4–4.5 | Retriever / graph | Seed node appears pulsing; edges and nodes unfold sequentially (parent_of, cites, interprets) |
| 4.6–5.6 | Extractor | Row activates, edge-write code block reveals, edges-added counter ticks 0 → 1 |
| 5.8–6.9 | Verifier | Row activates; amber conflict edge appears on graph with dashed-stroke animation; conflicts counter ticks 0 → 1 |
| 7.1–10.6 | Memo streams | Report renders section by section, conflict callout sliding in mid-document |
| 11.2 | Lock | Clock snaps to final 3.4s |

The choreography is *narrative* rather than algorithmically faithful. A real BFS would expand in waves, not sequential single-edge steps. The narrative ordering is clearer for an audience watching for the first time; the algorithmic accuracy can be explained in Q&A.

## Controls

| Control | Effect |
|---------|--------|
| **Replay** | Re-runs the cinematic from scratch |
| **Skip** | Collapses immediately to the completed snappy state — final memo, all nodes/edges visible, all counters at final values |
| **Both** tab | Default. Equal-weight split, neither side dimmed |
| **Graph** tab | Highlights graph block (info background), dims the timeline |
| **Agents** tab | Highlights timeline (warning background), dims the graph |
| **Composer + send** | Wired but does not yet trigger a new cinematic in this mockup |

## Color and source semantics

| Element | Color | Meaning |
|---------|-------|---------|
| Finlex citation pill / node | Blue | Binding statute |
| Vero citation pill / node | Amber | Interpretive guidance |
| Conflict callout / edge | Amber + warning border | Authority divergence |
| Assumption chip | Info blue | Clarifier-surfaced default |
| Ghost nodes | Light gray | Graph context not traversed |
| Edge-write code block | Mono font, surface card | Newly written graph edge |

Two-color encoding (Finlex blue vs Vero amber) is intentional and minimal. It maps directly to authority precedence: the statute-vs-guidance distinction is legible at a glance everywhere it appears (citations, nodes, conflict callouts).

## Mapped to the system architecture

Every visible element corresponds to a component from the plan:

| UI element | Plan reference |
|------------|----------------|
| Assumption chip | Phase 8 — Clarifier agent |
| Sub-question list | Phase 8 — Planner agent |
| Graph traversal | Phase 7 — graph expansion module |
| Strategy badge | Phase 7 — strategy router |
| Edge-write block | Phase 8 — on-demand Extractor + write-back |
| Conflict callout | Phase 8 — Verifier agent |
| Authority tier in conflict resolution | Phase 3 — authority_rank metadata |
| Citation pill colors | Phase 1 — source field on nodes |

Nothing in the UI is purely cosmetic — every element traces to a component that the build plan instructs the team to build.

## Honest caveats for the team

Things that are simplified for the demo and worth being explicit about if a judge asks:

- **The 3.4s answer time is simulated.** Real answer latency depends on LLM round-trips, vector search, and graph queries. A realistic v2+agents pipeline is in the 5–15s range. The displayed 3.4s is a placeholder for "what we think production should feel like."
- **The graph traversal animation is narratively ordered, not algorithmically faithful.** A real BFS expands by depth wave, not by storyline beat.
- **The Extractor's edge write-back is the most consequential moment** for the agentic story. In the real system it's a single tool call that mutates the graph; in the mockup it's foregrounded with its own counter because most judges won't catch it otherwise.
- **The conflict between Vero 2019 and §114.2 is illustrative.** Whether a specific real-world conflict exists at this exact citation is something to verify with a Finnish tax expert before using this in the live demo. Pick a real conflict from the corpus when you have one.

## Suggested demo arc (~2 minutes)

1. Show the question typed in Finnish. Pause for half a second.
2. The cinematic plays. Let judges watch it once without commentary.
3. On replay, narrate three things in order:
   - "The Clarifier surfaces that we don't know the tax year or entity type — it picks defaults and labels them"
   - "Watch the graph: vector search lands here, then the BFS walks the citation edges to pull in the exception clause and the apportionment rule"
   - "The Extractor just wrote a new edge back to the graph — it'll be there next time someone asks a related question"
4. Click Skip to show the final memo cleanly. Highlight the conflict callout and the authority resolution rule.
5. Type a follow-up: *"What if it's a foundation instead?"* Show that the Clarifier picks up the entity type change and the pipeline re-runs against the same graph.

## Possible extensions

- **Follow-up variant** — typing a follow-up question triggers a faster, partial re-run that only re-traverses changed parts. Demonstrates the system is interactive, not a one-shot animation.
- **Baseline comparison toggle** — a "what would naive RAG return?" button that side-by-sides the worse vanilla-vector answer. Directly proves the graph + agents are doing load-bearing work.
- **Citation hover previews** — hover any citation pill to see a source snippet. Standard product polish.
- **Conflict drill-down** — click the conflict callout to expand into a side-by-side diff of the statute wording and the Vero guidance wording. The "regulation diff" idea from earlier concepts, applied surgically only when it matters.

## File location

The interactive mockup is in the conversation as the widget titled `hybrid_cinematic_v1`. This document captures the design intent; the widget itself is the implementation.
