# Step 2 — Edge Extraction (Turning the Forest into a Graph)

> Step 1 produced ~1.97M nodes and ~402k chunks organized as one tree per document, linked only by `parent_id`. This step extracts the cross-document references that make it a graph.
>
> **Edges are the single highest-value extraction task in the project.** They are what make GraphRAG beat vanilla RAG. Without dense, typed, resolved edges, all later phases collapse back into vector retrieval with extra steps.

## Inputs

From the completed Step 1:
- `output/nodes.jsonl` (1.3 GB, 1,967,776 nodes)
- `output/chunks.jsonl` (691 MB, 402,098 chunks)
- `output/hierarchy.json` (159 MB)
- The original HTML under `data/` (needed for anchor extraction — anchors are lost during text-only parsing)

From the plan:
- Eight cross-reference layers from `00_overview.md` — Step 2 implements L1 (typed edges, three extraction methods, dangling edges) and seeds L6 (definition propagation).

## What "edge" means here

Three kinds of edges, all stored in the same `edges.jsonl` with a `type` field:

| Edge kind | How created | Volume estimate |
|-----------|-------------|-----------------|
| **Structural** | Derived from Step 1's `parent_id` field — `parent_of` and `child_of`. Already implicit in `nodes.jsonl`, materialized once here. | ~1.97M (one per non-root node) |
| **Reference** | Extracted from text via anchors → regex → LLM. Typed by content + source context. | Estimated 1–4M (regulatory text is reference-heavy) |
| **Derived** | Computed from other edges. E.g. `superseded_by` from `amends`/`repeals` chains. Done in Step 3. | <1% of total |

This phase produces the first two. Derived edges wait for Step 3.

## Edge taxonomy (locked from `00_overview.md` L1)

| Edge type | Direction | Semantics | Typical source → target |
|-----------|-----------|-----------|--------------------------|
| `parent_of` / `child_of` | structural | Hierarchical containment | LAW → SECTION, SECTION → SUBSECTION |
| `cites` | generic | Outbound reference, type unclear | any → SECTION / LAW |
| `interprets` | inbound from guidance | Vero guidance interpreting a Finlex clause | vero/* → finlex/* |
| `amends` | statute chronology | New statute modifying an older one | finlex/* → finlex/* |
| `repeals` | statute chronology | New statute repealing an older one | finlex/* → finlex/* |
| `transposes` | EU implementation | Finnish statute implementing an EU directive | finlex/* → eurlex/* (often dangling) |
| `applies` | case → statute | KHO case applying a statute clause | kho/* → finlex/* |
| `defines` | concept → context | DEFINITION node defining a term used elsewhere | DEFINITION → any node mentioning the term |

> `applies` is included because Step 1 ingested KHO (7,040 files, 228k nodes) even though it wasn't in the original plan scope. The team chose to include it; the edge taxonomy reflects that.

> `transposes` edges almost always dangle (we don't ingest EUR-Lex). They are kept regardless — see L1 in the overview.

## Verification tasks (before building)

### V2.1 — Anchor inventory

Walk the raw HTML under `data/` and count `<a href>` elements per source. For each:
- Total anchors
- Anchors pointing inside the same document (intra-doc)
- Anchors pointing to a different document in our corpus (inter-doc, *the gold*)
- Anchors pointing outside our corpus (likely EUR-Lex, KKO, or external)
- Sample 50 inter-doc anchors per source — do their `href` targets match Finlex/Vero URL conventions in a way that lets us normalize to canonical IDs?

**Output:** `findings/02_anchor_inventory.md` with per-source tables and a snippet of href patterns observed.

**Why it matters:** If anchors are dense and well-formed, we get a huge chunk of L1's "typed edges" for free with anchor extraction alone — no regex, no LLM. If they're sparse or malformed, the regex layer carries more load.

### V2.2 — Citation form survey

Sample 200 nodes of type SECTION / SUBSECTION across both Finlex subcorpora and Vero. Run a loose discovery regex (any `§`, year-number patterns, capitalized law abbreviations followed by digits, `EUVL`, `HE`, `KHO`). Dump the matches with 80 chars of context.

Catalogue forms with frequency counts:

| Form | Example | Approx frequency | Refers to | Edge type |
|------|---------|------------------|-----------|-----------|
| `§ NNN AVL` / `§ NNN, AVL` | `§ 102 AVL` | … | Finnish statute clause | `cites` |
| `AVL NNN §` | `AVL 102 §` | … | same, alternate ordering | `cites` |
| `NN luvun NN §:n AVL` | `10 luvun 102 §:n AVL` | … | with chapter prefix | `cites` |
| `lain N §:n N momentin N kohdan` | `… 2 momentin 3 kohdan` | … | deep clause reference | `cites` |
| `NNNN/NNN/EY` or `NNNN/NN/EU` | `2006/112/EY` | … | EU directive | `cites` (dangling) |
| `KHO YYYY:NN` / `KHO:YYYY:NN` | `KHO 2023:55` | … | KHO precedent | `applies` (if source is KHO node) or `cites` |
| `HE NN/YYYY [vp]` | `HE 88/1993 vp` | … | Government bill | `cites` (dangling) |
| `muutettu lailla NNN/YYYY` | … | … | amendment chain | `amends` |
| `kumottu lailla NNN/YYYY` | … | … | repeal chain | `repeals` |
| Anaphoric: `edellä mainit-`, `tässä laissa`, `kyseinen` | … | … | self-ref / context-dep | LLM-only |
| Natural: `tuloverolain 4 §:ssä` | … | … | spelled-out cite | regex w/ NER for law-name |

Also flag the **fuzzy, regex-resistant cases**:
- Anaphoric: "the aforementioned article" / "edellä mainitussa pykälässä"
- Self-referential: "this Act" / "tässä laissa"
- Natural-language full names: "tuloverolain 4 §:ssä" (full law name spelled out, not abbreviated)

**Output:** `findings/02_citation_forms.md`. Used to drive the regex priority list in B2.2.

### V2.3 — Cross-source linkage probe

Pick 5 high-traffic Finlex statutes likely to be heavily cited (AVL, TVL, EVL, KPL, OYL — or whichever the data shows). For each:

- How many Vero guidance documents reference it? (substring search on the law abbreviation in `chunks.jsonl`)
- How many KHO cases reference it?
- What's the rough density — handful of references or hundreds?

This sets degree expectations for Step 7's hub-cap logic. If AVL has 2000 inbound `interprets` edges, hub-skipping is critical. If it has 50, you can be looser.

**Output:** `findings/02_linkage_density.md`

### V2.4 — Decide LLM-extractor scope

From V2.2, list the fuzzy citation cases. For each, write down:
- Can regex catch it with reasonable precision? (if yes — write the regex, skip LLM)
- Does the resolved target actually exist in our corpus? (if no — extracting it produces only dangling edges of marginal value)
- How frequent is it? (if rare — skip)

**Recommendation:**
- **Do** handle natural-language full-name citations via regex + a small lookup table of law-name → abbreviation
- **Skip** anaphoric references in v1 (low precision, low value, high cost)
- **Defer** to query-time LLM extraction (Step 8 Extractor agent) for the rest — saves ingestion-time LLM budget

**Output:** `findings/02_llm_extractor_scope.md`

## Build tasks

### B2.1 — Structural edges (the free wins)

`src/extraction/structural_edges.py`:

```python
def build_structural_edges(nodes_jsonl: Path) -> Iterator[Edge]:
    """Emit parent_of/child_of edges from node.parent_id. Trivial — one pass."""
```

For every node with a `parent_id`, emit:
- `(parent_id, node_id, "parent_of", confidence=1.0, extracted_by="structural")`

No need to also emit `child_of` — the graph store adapter (Step 4 B4.2) supports bidirectional traversal, so one direction is enough. **Storing both directions wastes ~2M rows and adds no information.**

Expected output: ~1.97M edges. This is the floor — Step 2 produces at least this many even if extraction goes badly.

### B2.2 — Anchor-based edges (highest precision, do first)

`src/extraction/anchor_edges.py`:

```python
def extract_anchor_edges(html_path: Path, node_index: NodeIndex) -> Iterator[Edge]:
    """For every <a href> in the HTML, find the source node containing it
    (via source_html_id), normalize the href to a canonical node ID, and
    emit an edge."""
```

Implementation notes:
- Walk the original HTML, not the parsed `nodes.jsonl` (anchors are lost during text-only extraction)
- For each anchor, find the source node by walking up the DOM to the nearest element with a recognized structural marker, then look up its node ID via `source_html_id`
- Normalize the href to a canonical ID using `src/ids.py` (Step 1 already has these)
- Confidence is 1.0 — the document author explicitly linked
- Edge type defaults to `cites`, refined by source/target heuristics in B2.5

Expected precision: ≥99%. Anchors that don't resolve to a known node become dangling (target_id=null), still recorded, logged.

**Why this is first:** anchors are free, deterministic, and high-volume in Finlex. Skipping straight to regex misses references the document author explicitly marked.

### B2.3 — Regex extractors

`src/extraction/citations_regex.py` — one named pattern per form from V2.2's frequency-ordered list.

Each pattern is a function:

```python
def kho_case(text: str) -> Iterator[CitationMatch]: ...
def section_avl_inline(text: str) -> Iterator[CitationMatch]: ...
# ...
```

A `CitationMatch` carries: matched string, char span, normalized target ID (or None), suggested edge type, confidence.

**Order matters.** Run the most specific patterns first, the most general last. A `KHO 2023:55` inside text that also contains `§ 5` should match KHO once, not "5" as a generic section reference. Each pattern can mark consumed spans so subsequent patterns skip them.

**Anchor-exempt.** Before running regex on a node, look up which character spans were already consumed by anchor extraction (B2.2). Skip those spans. Avoids double-extracting the same reference.

Expected precision: ≥95% per pattern on a hand-labeled sample. Patterns falling below this are tightened or dropped.

### B2.4 — LLM extractor (constrained, on-demand only)

`src/extraction/citations_llm.py`:

```python
def extract_citations_llm(text: str, source_node: Node) -> list[CitationMatch]:
    """Used ONLY when:
    (a) the node contains citation-like trigger keywords
        (§, EUVL, directive, pykälä, viitataan, mainittu, tarkoitettu)
    (b) AND regex + anchor extraction produced no matches in this node.
    Returns matches with confidence < 1.0 and extracted_by='llm'."""
```

Structured output via Pydantic schema → JSON mode. Prompt asks for: target citation string, target node type guess, edge type, model self-confidence, one-sentence justification.

**Strict trigger filter is essential.** Without it, the LLM extractor runs on every node and burns the entire LLM budget. With it, the LLM extractor runs on maybe 1–5% of nodes — the ones where structured extraction failed but the text still looks reference-bearing.

**Defer most LLM extraction to Step 8.** The Step 8 Extractor agent runs at *query time* on the small set of retrieved chunks. That's cheaper and more targeted than running over all 1.97M nodes at ingestion. Step 2's LLM extractor should be conservative — only used for nodes where regex strongly suggests a missed reference.

### B2.5 — Edge type refinement

The extractors above all default to `cites`. The actual edge type is refined by **source + target context**:

```python
def refine_edge_type(edge: Edge, source_node: Node, target_node: Node | None) -> str:
    if source_node.source.startswith("vero") and target_node and target_node.source.startswith("finlex"):
        return "interprets"
    if source_node.source.startswith("kho") and target_node and target_node.source.startswith("finlex"):
        return "applies"
    if "muutettu lailla" in edge.context_snippet:
        return "amends"
    if "kumottu lailla" in edge.context_snippet:
        return "repeals"
    if target_node and target_node.source.startswith("eurlex"):  # dangling but typed
        return "transposes"
    return "cites"
```

This runs after extraction but before resolution. The `context_snippet` (50 chars around the matched citation) is preserved on the `CitationMatch` for this purpose.

> **Layer 1 in action.** Typed edges, not generic ones. The retriever can ask for "all Vero guidance that *interprets* this Finlex section" — not just "all guidance that mentions it."

### B2.6 — Definition edges (seeds Layer 6)

Step 1 already emits `DEFINITION` nodes when text contains explicit definition triggers (`tarkoitetaan`, `määritellään`). Step 2 connects them.

`src/extraction/definition_edges.py`:

```python
def extract_definition_edges(definition_node: Node, all_nodes: NodeIndex) -> Iterator[Edge]:
    """For each DEFINITION node:
    1. Extract the defined term (first noun phrase before/after the trigger)
    2. Find all SECTION/SUBSECTION/ITEM nodes in the same LAW that use the term
    3. Emit a `defines` edge from DEFINITION → each user node"""
```

Caveats:
- "Term extraction" is hard. Start simple: pull the noun phrase immediately preceding `tarkoitetaan` or following `määritellään`. Verify on 50 hand-picked DEFINITION nodes.
- Limit scope to *same-LAW* usage in v1. Cross-LAW definitions are noisy (the same word can mean different things in different statutes).
- Confidence: 0.7 (lower than regex citations — the term-matching is fuzzy).

This is **lower priority than B2.2–B2.5**. Skip in v1 if time is tight; Layer 6 still works partially through plain `cites` edges. Returns highest value on definition-lookup eval questions, where the cost-benefit is clear.

### B2.7 — Edge resolution

`src/extraction/resolve_edges.py`:

```python
def resolve(raw_matches: Iterator[CitationMatch], node_index: NodeIndex) -> Iterator[Edge]:
    """For each extracted match:
    1. Normalize the citation string to a canonical node ID via src/ids.py
    2. Look up the canonical ID in node_index
    3. If found → set target_id, emit resolved edge
    4. If not found → emit edge with target_id=null, target_ref=raw citation,
       log to data/dangling_edges.log with reason"""
```

> **Layer 1 — dangling edges are kept, not dropped.** Resolution is a separate pass, re-runnable as the corpus grows. A `cites` edge to `2006/112/EY` is recorded today and may resolve tomorrow if EU directives are ever ingested.

Reasons for dangling, logged separately:
- `out_of_corpus` — target is in a source we don't ingest (EUR-Lex, government bills)
- `not_yet_parsed` — target should be in our corpus but isn't (parser bug? regex over-matched?)
- `normalization_failed` — the citation string doesn't fit the canonical ID format (regex over-permissive?)

Each reason triggers a different follow-up: `out_of_corpus` is expected, `not_yet_parsed` is investigated, `normalization_failed` is debugged.

### B2.8 — Pipeline runner

`scripts/extract_edges.py`:

```
1. Load node index (id → Node metadata) once, in memory. ~2GB peak.
2. Pass 1: structural edges (B2.1). Write to edges.jsonl.
3. Pass 2: anchor edges (B2.2). Walk raw HTML, write to edges.jsonl.
4. Pass 3: regex edges (B2.3) on nodes not yet covered by anchors.
5. Pass 4: LLM edges (B2.4) on flagged residual nodes.
6. Pass 5: definition edges (B2.6).
7. Edge type refinement (B2.5) across all extracted matches.
8. Resolution (B2.7) — split into resolved + dangling.
```

Parallelize passes 2–4 across workers (the M3 + 9 workers setup from Step 1 already works). Passes 1, 7, 8 are single-threaded but fast.

**Track and report:**
- Total edges per type
- % resolved vs dangling, with reason breakdown
- Edge count per source pair (e.g. vero→finlex `interprets` count)
- Top 50 most-cited nodes (sanity check — should be widely-referenced statute articles like AVL §1, TVL §1, etc.)
- Estimated 50%+ of all edges should be `parent_of` (structural). The rest are reference edges.

### B2.9 — Cross-source linkage verification

After extraction, verify against V2.3's predictions: for the 5 popular statutes probed, do the actual incoming-edge counts match the rough estimates? If wildly off (under 50% or over 200%), investigate before declaring Step 2 done — extraction is probably broken in a way the hand sample didn't catch.

**Output:** `findings/02_extraction_report.md` — final stats, top-cited nodes, known gaps, and either confirmation of V2.3 predictions or a documented discrepancy.

## Output artifacts

### `output/edges.jsonl`
One JSON object per line:
```json
{
  "source_id": "finlex_laki/avl/c10/s114",
  "target_id": "finlex_laki/avl/c10/s117",
  "target_ref": "§ 117",
  "type": "cites",
  "confidence": 1.0,
  "extracted_by": "anchor",
  "context_snippet": "...lukuun ottamatta § 117 mainittua...",
  "properties": {}
}
```

### `output/dangling_edges.log`
Same shape, `target_id: null`, plus `dangling_reason`. Used for diagnostics and future resolution passes.

### `output/edge_stats.json`
```json
{
  "total": 4_300_000,
  "by_type": {"parent_of": 1_967_775, "cites": 1_500_000, "interprets": 420_000, ...},
  "resolved": 0.78,
  "dangling_by_reason": {"out_of_corpus": 720_000, "normalization_failed": 12_000, ...},
  "top_cited": [{"node_id": "...", "incoming_count": 4870}, ...]
}
```

## Quality checks (`pipeline.verify_edges`)

Reject the run if:
- An edge `source_id` doesn't resolve to a node in `nodes.jsonl`
- An edge `type` is not in the taxonomy
- An edge confidence is outside [0, 1]
- An anchor-based edge is dangling with reason ≠ `out_of_corpus` (anchors should resolve — if they don't, ID normalization is broken)
- The number of `parent_of` edges does not equal (number of non-root nodes)
- Resolution rate on regex-extracted edges to in-corpus targets is below 60% (probably means ID normalization regressed)

## Done when

- `output/edges.jsonl` exists with all four edge classes (structural, anchor, regex, optionally LLM + definitions)
- `verify_edges.py` passes with zero violations
- Anchor extraction precision ≥99% on a 100-sample manual check
- Regex extraction precision ≥95% on a 100-sample manual check
- ≥70% of regex-extracted edges to in-corpus targets resolve (lower if EUR-Lex / HE references dominate — that's fine, they'll dangle as `out_of_corpus`)
- The 5 popular statutes from V2.3 have plausible incoming-edge counts matching the rough estimate
- Top-cited nodes are recognizable major statute articles (smell test)
- `edge_stats.json` shows the expected `parent_of` count (~1.97M) and a reference-edge total > 1M

## Sequencing notes for downstream phases

This step makes Layers 1 and (partly) 6 from the overview real. The remaining layers depend on it:

- **L2 (bidirectional traversal)** — Step 4 will index both `source_id` and `target_id` so anything stored here can be walked in both directions.
- **L3 (query-shaped traversal)** — Step 7's strategy router picks edge types to follow. Sparse or low-quality edges here means the router has nothing to work with.
- **L4 (degree caps)** — Step 4 precomputes per-node degree from the edges produced here. V2.3's density probe sets initial cap thresholds.
- **L5 (annotated context)** — Step 5 renders the edges produced here as inline relationships between sources. Edge *types* (not just existence) are what make the rendering useful.
- **L7 (conflict surfacing)** — Step 8 Verifier looks at sources connected by `interprets` edges and at different `authority_rank`s. No `interprets` edges → no conflict surfacing.
- **L8 (path-aware citations)** — Step 7 records BFS paths over the edges produced here; Step 5 renders them. If the edges are sparse, paths are short and uninteresting.

**Edges are the load-bearing structure of the whole pipeline.** Spend the time here. Anything that's not extracted now must be either re-extracted at query time (slow, expensive) or done without (worse retrieval quality).
