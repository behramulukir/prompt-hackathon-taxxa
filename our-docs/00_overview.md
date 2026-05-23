# GraphRAG for Finnish Accounting Regulation — Plan Overview

## Goal

Build a retrieval system over ~50,000 HTML documents from **Finlex** (laws, statutes) and **Vero** (tax authority guidance). The system answers multi-hop regulatory questions with correct citations and respects authority precedence: **statute (Finlex) > guidance (Vero)**.

> Out of scope: KKO case law, EU-lex contradictions. The architecture leaves room for them but does not depend on them.

## Source of truth

The spec for **node creation and chunking** (Step 1 of this plan) is the primary contract. Every downstream phase consumes its outputs (`nodes.jsonl`, `chunks.jsonl`, hierarchy index) without modifying the data model upstream.

If a downstream phase needs additional fields, they are added as **annotations** on existing nodes/chunks — not by changing the Step 1 schema.

## Strategy

Build **vector-first, graph-ready from day one**. Every chunk is anchored to a graph node; the graph carries `parent_of` / `cites` / `interprets` edges. Step 4 retrieves with vectors only. Step 6 adds graph traversal without rewriting ingestion. Step 7 adds agents.

## Cross-reference principles (the structural backbone)

Regulatory documents are defined by the references inside them. A chunk like `§ 102 AVL` is incomplete without `§ 114` (its exception), `§ 117` (the apportionment rule), and the Vero guidance that interprets it. Everything below is in service of making cross-references work — without these, you have RAG with extra steps.

Eight layers, each covered by one or more phases:

| # | Layer | Where it lives |
|---|-------|----------------|
| L1 | **Typed edges, not generic.** Every reference becomes an edge with a type (`cites`, `interprets`, `amends`, `applies-when`). Extract via anchors → regex → LLM, in that order of preference. Dangling edges are kept, not dropped. | Step 2 |
| L2 | **Bidirectional traversal.** Every edge is queryable in both directions. Inbound `interprets` from a Finlex node finds the Vero guidance that interprets it; outbound finds what the guidance interprets. | Step 4 (graph store adapter) |
| L3 | **Query-shaped traversal.** Different question types follow different edge types. Single-hop questions don't expand; multi-hop questions expand on a question-class-specific config. | Step 7 |
| L4 | **Degree caps and reranking.** Hub nodes (widely cited statutes) are skipped during expansion unless directly seeded. A cross-encoder rerank culls the expanded set before it reaches the LLM. | Step 7 |
| L5 | **Annotated context.** When chunks are assembled for the LLM, the relationships between them are made explicit (`[Source 2] interprets [Source 1]`), so the LLM reasons about the graph, not just the nodes. | Step 5 |
| L6 | **Definition propagation.** Defined terms get their definitions injected as separate sources when retrieved chunks use them. | Step 2 (`defines` edges) + Step 7 (traversal) |
| L7 | **Conflict surfacing, not silent choice.** When sources at different authority tiers (`authority_rank`) address the same target, the divergence is detected and surfaced, not averaged away. | Step 3 (metadata) + Step 8 (Verifier) |
| L8 | **Path-aware citations.** The system can show *how* a source was reached, not just that it was cited. | Step 5 + Step 7 (output assembly) |

The first four (L1–L4) are the minimum viable graph. L5 and L8 are small changes with high impact. L6 and L7 are second-pass refinements.

## Phase sequence

| # | Step | Output | Purpose |
|---|------|--------|---------|
| 1 | `01_node_creation_and_chunking.md` | `nodes.jsonl`, `chunks.jsonl`, hierarchy index | Deterministic, no LLM. The spec. |
| 2 | `02_edge_extraction.md` | `edges.jsonl` (citations + cross-references) | Turn the node forest into a graph |
| 3 | `03_metadata_enrichment.md` | Annotated nodes (status, dates, authority) | Enables filtering and ranking |
| 4a | `04_embedding_and_indexing.md` | `lancedb/` populated via Voyage `voyage-3-large` | Vector retrieval substrate. **Runs in parallel with 2 and 3.** |
| 4b | `04_embedding_and_indexing.md` | `graph.db` (SQLite) populated | Graph traversal substrate. Runs after 2 and 3. |
| 5 | `05_retrieval_v1_vector_only.md` | Working baseline RAG with citations | End-to-end loop |
| 6 | `06_evaluation_harness.md` | Test set + scoring | Measure before optimizing |
| 7 | `07_retrieval_v2_graph_traversal.md` | GraphRAG retrieval | Phase 2 of the brief — graph walk |
| 8 | `08_agentic_workflow.md` | Planner / Extractor / Verifier / Clarifier | Phase 3 of the brief — agents |

## Concurrent execution

Steps 2, 3, and 4a can run in parallel from Step 1's outputs. They write to disjoint files (see each phase's brief). Step 4b runs after 2 and 3 converge. Step 5 onward is sequential.

## How to use these documents

Each phase is a self-contained brief. Each contains:

- **Inputs** — what artifacts must exist before starting
- **Verification tasks** — quick checks against real data to confirm the spec holds (always small, focused)
- **Build tasks** — implementation
- **Outputs** — concrete artifacts produced
- **Done when** — checkable exit criteria

Verification tasks exist because the Step 1 spec makes assumptions about HTML structure that must hold across 50k documents. Don't skip them — they take little time and prevent late-stage rework.

## Repo layout

```
.
├── data/
│   ├── raw/                 # 50k HTML files (finlex/, vero/)
│   ├── parsed/              # intermediate JSON per document
│   ├── nodes.jsonl          # Step 1 output
│   ├── chunks.jsonl         # Step 1 output
│   ├── hierarchy.json       # Step 1 output
│   └── edges.jsonl          # Step 2 output
├── findings/                # verification outputs per phase
├── src/
│   ├── parsing/             # one parser per source
│   ├── nodes/               # node creation rules
│   ├── chunks/              # chunk packing
│   ├── extraction/          # citation + metadata extractors
│   ├── indexing/            # embedding + storage
│   ├── retrieval/           # query-time logic
│   ├── agents/              # Step 8
│   └── models.py            # Pydantic schemas
├── eval/
│   ├── questions.yaml
│   └── runner.py
└── scripts/                 # one-off ingestion + verification
```
