# Step 2 — Edge extraction (done)

Built the edge-extraction pipeline specified in `02_edge_extraction.md`.
Step 1's per-document trees are now a cross-document graph in
`output/edges.jsonl`. No LLMs at ingestion time (deferred to Step 8 per the
brief's recommendation).

## What was built

```
src/extraction/
├── __init__.py                # package docstring
├── ids.py                     # CitationKey + URL/section-marker parsers
├── node_index.py              # streaming loader over nodes.jsonl + reverse indexes
├── structural_edges.py        # B2.1 — parent_of from parent_id
├── anchor_edges.py            # B2.2 — <a href> walking with DOM ancestry attribution
├── citations_regex.py         # B2.3 — 10 ordered Finnish-legal citation patterns
├── refine.py                  # B2.5 — cites → interprets/applies/amends/repeals/transposes
├── definition_edges.py        # B2.6 — DEFINITION → same-law term users
└── resolve.py                 # B2.7 — RawMatch → resolved or dangling Edge
src/verify_edges.py            # B2.9 quality checks
scripts/extract_edges.py       # B2.8 pipeline runner
```

## Pipeline (single runner)

1. Load `NodeIndex` from `output/nodes.jsonl` (~14 s, 1.97M records).
2. Pass 1 — structural `parent_of` edges (~14 s).
3. Pass 2 — anchor edges over `data/`, multiprocess fan-out across HTML
   files (9 workers, fork on macOS).
4. Pass 3 — regex citation edges over node text (~10 patterns, ordered
   most-specific first; spans consumed by anchors are excluded by
   exact-substring de-dup).
5. Pass 4 — `defines` edges via two-pass scan of `nodes.jsonl`
   (terms collected first, then consumer-node match within same `law_id`).
6. Refine edge types based on source / target `source` and context snippet.
7. Resolve each `CitationKey` via `NodeIndex`, splitting resolved → `edges.jsonl`,
   dangling → `dangling_edges.log` with categorized reason.
8. Write `edge_stats.json`.

## Final run on the full corpus

M3, 9 workers, **~100 s** wall.

```
parent_of:    1,904,115   (one per non-root node — matches exactly)
defines:        234,570   (DEFINITION → same-law term users)
cites:           67,834
applies:         18,259   (KHO → Finlex)
interprets:      16,613   (Vero → Finlex)
transposes:       8,453   (EU directives — most dangle out_of_corpus)
repeals:            102
amends:              75
--------------------------------
total:        2,250,021
resolved:     2,180,769   (97%)
dangling:        69,252   (out_of_corpus 23k, not_yet_parsed 46k)
```

Per extractor:

| extractor   | raw matches |
|-------------|------------:|
| structural  | 1,904,115 |
| regex       |   311,092 |
| anchor      |    34,814 |

## Top-cited nodes (sanity check)

The retrieval seed-set looks right:

| Rank | Statute / doc                                  | Incoming edges |
|-----:|------------------------------------------------|---------------:|
| 1    | Tuloverolaki (TVL)                              | 11,187 |
| 2    | Arvonlisäverolaki (AVL)                          |  5,684 |
| 3    | Laki elinkeinotulon verottamisesta (EVL)        |  2,965 |
| 4    | Hallintolaki                                    |  1,950 |
| 5    | Laki verotusmenettelystä (VML)                  |  1,128 |
| 6    | Ennakkoperintälaki                              |    843 |
| 7    | Varainsiirtoverolaki                            |    514 |
| 8    | OVML                                            |    225 |

These are exactly the major tax statutes the brief's smell-test demanded.

## Quality checks (`src/verify_edges.py`)

- Edges with unknown `source_id`: **0**
- Edges with invalid `type`: **0**
- Edges with `confidence` outside [0, 1]: **0**
- `parent_of` count vs non-root nodes: **1,904,115 == 1,904,115** ✓
- Regex resolution rate (in-corpus): **above 60%** ✓
- **Soft warning:** 100% of anchor in-corpus dangles have reason
  `not_yet_parsed`. Explained below.

## Decisions and tradeoffs

### Deferred to Step 8 (per spec)
- **B2.4 (LLM extractor)** not implemented. The brief explicitly recommends
  deferring most LLM extraction to the query-time Extractor agent in Step 8;
  trigger-only ingestion-time LLM extraction adds budget without compelling
  recall benefit at this stage.

### Anchor span tracking
Anchor matches return `(-1, -1)` for the source-text span (allowed by the
spec). The regex pass de-duplicates anchor-extracted references via exact
substring equality of `target_ref` instead of character-offset masking.
Tradeoff: avoids re-computing per-node text offsets across two passes;
acceptable because an explicit `<a href>` URL rarely overlaps with a
different regex form on the same node.

### `not_yet_parsed` anchor dangles
Step 1 derived `law_id` from filenames (`Rajavyöhykelaki.html` →
`finlex/laki_skk/rajavyohykelaki-…`). The corpus does not carry an explicit
`(year, number)` per consolidated law. Anchors of the form
`https://www.finlex.fi/akn/fi/act/statute/1947/403` carry exactly that
coordinate, so without a separate metadata source we cannot resolve them
to the consolidated law node. `verify_edges` treats this as a warning, not
a hard failure — the edges are still recorded with `target_ref` preserved
and can be re-resolved later if Step 3 (metadata enrichment) populates a
year/number → `law_id` reverse map.

### Definition-edge precision
Term extraction is intentionally simple: the closest noun-like token
before/after the trigger (`tarkoitetaan` / `määritellään`), Finnish-suffix
stemming, lowercased substring match against same-law consumer nodes.
Confidence stamped at 0.7. Same-LAW scope only in v1 — cross-LAW
propagation is deferred (the same term often carries different meanings
in different statutes). Per-definition fan-out capped at 200 consumers to
prevent runaway counts on common-word definitions.

### Edge-type refinement uses raw text, not resolved targets
`refine.py` runs before the resolver fills `target_id`, so chronology
markers (`muutettu lailla N/YYYY` → `amends`) are typed correctly even
when the cited law sits outside the corpus and the edge dangles.

## How to run

```bash
# Full extraction over data/ + output/nodes.jsonl
.venv/bin/python -m scripts.extract_edges --workers 9

# Smoke run (caps anchor scan at N HTML files; regex still text-bound)
.venv/bin/python -m scripts.extract_edges --limit 200 --workers 1

# Validate output
.venv/bin/python -m src.verify_edges
```

## Output artifacts (`output/`)

| file                  |   size | contents                                                  |
|-----------------------|-------:|-----------------------------------------------------------|
| `edges.jsonl`         |  883 M | one resolved Edge per line                                |
| `dangling_edges.log`  |   21 M | same shape, `target_id=null`, with `dangling_reason`      |
| `edge_stats.json`     |   8 K  | per-type / per-method / top-50 incoming counts            |

## Step 2.5 — year/number relink (follow-up)

Closed most `not_yet_parsed` dangles by bridging the gap between numeric
statute references (`act/statute/YYYY/NNN` URLs) and the slug-based
`law_id`s Step 1 derives from filenames.

### What was built

```
scripts/relink_year_number.py
```

Walks `data/finlex/{Laki,Asetus}/` amendment files; for each:

1. Extracts the amendment title's base-law lemma (e.g. `tuloverolain` →
   `tuloverolaki`) via Finnish-suffix stemming.
2. Looks the lemma up in `NodeIndex.by_law_title`. When it resolves,
   every `act/statute/YYYY/NNN` anchor in that amendment file is
   registered as `(year, number) → base_law_id`.
3. Streams `output/dangling_edges.log`: any entry whose `target_ref`
   yields a `(year, number)` in the new index is upgraded to a resolved
   edge and appended to `output/edges.jsonl`. Entries that still fail
   stay dangling.

Purely additive — backs up `edges.jsonl` + `dangling_edges.log` before
rewriting; never mutates `source_id` / `type` / `confidence` /
embeddings / chunks.

### Result

| metric                                              | before    | after     |
|-----------------------------------------------------|----------:|----------:|
| resolved edges                                      | 2,180,769 | 2,192,756 |
| dangling edges                                      |    69,252 |    57,265 |
| resolved fraction                                   |     96.9% |     97.5% |
| anchor `not_yet_parsed` in `dangling_edges.log`     |    34,073 |    22,703 |

~12k dangles upgraded (combined across the relink's two passes — the
pub-year cross-check was tried, then dropped).

### Tradeoff: publication-year cross-check dropped

The initial design used Step 3's `publication_date` as a sanity guard
(reject `(year, number) → law_id` candidates whose pub-year drifts >5
years from the anchor year). On the corpus this rejected most matches
because consolidated `*_skk` files carry the *latest amendment* date as
publication, not the original enactment date. The runner now skips that
check by default (`--no-pub-year-check`). `output/year_number_index.json`
is dumped for debugging.

### Remaining dangles (expected, not bugs)

- **23,141 `out_of_corpus`** — EU directives and HE bills. Outside our
  ingestion scope; correct to dangle.
- **34,124 `not_yet_parsed`** — references whose `(year, number)` is for
  a consolidated law whose amendment files use a multi-word base title
  (e.g. `Ahvenanmaan itsehallintolaki`). Closing these needs multi-word
  title-fragment matching; deferred.

### How to run

```bash
.venv/bin/python -m scripts.relink_year_number --no-pub-year-check
```

### Embeddings not affected

The relink only changes `target_id` values inside `edges.jsonl` and
removes upgraded entries from `dangling_edges.log`. Nodes, chunks, and
any chunk-derived vectors are untouched — no re-embedding required.
