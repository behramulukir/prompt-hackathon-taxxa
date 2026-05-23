# Step 1 pipeline — HTML → nodes → chunks

Implements `our-docs/step-1-plan.md` for the Finnish legal corpus
(Finlex + Vero) under `data/`.

## Run

```bash
# one-time setup
python3 -m venv .venv && .venv/bin/pip install beautifulsoup4 lxml tiktoken

# full corpus (≈60s on M3, 9 workers)
.venv/bin/python -m pipeline.ingest --workers 9

# smaller smoke run
.venv/bin/python -m pipeline.ingest --limit 100 --workers 8

# quality checks
.venv/bin/python -m pipeline.verify output
```

## Layout

```
pipeline/
├── ingest.py                       # entry point — walks data/, dispatches, writes JSONL
├── nodes.py                        # Node dataclass + deterministic id helpers
├── chunks.py                       # SECTION-first packing + sentence-split fallback
├── tokens.py                       # tiktoken cl100k_base counter
├── output.py                       # JSONL writers + hierarchy index builder
├── html_utils.py                   # BS4 helpers (heading detection, § parsing)
├── verify.py                       # post-run quality checks (spec §9)
└── parsers/
    ├── finlex_konsolidoitu.py      # Laki/Asetus (säädöskokoelma) — clean h1/h2/h3
    ├── finlex_amendments.py        # Laki/, Asetus/ — h1 + h4 amendment blocks
    ├── vero.py                     # Verohallinto guidance (Ohjeet/Päätökset/…)
    ├── kho.py                      # KHO case-law precedents
    └── treaty.py                   # Tuloverosopimukset (tax treaties)
```

## Outputs (in `output/`)

| file              | shape                                                                                                                                                                                            |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `nodes.jsonl`     | one Node per line: `{id, type, text, parent_id, order, label, title, source, source_subcorpus, source_file, source_html_id, law_id, metadata}`                                                  |
| `chunks.jsonl`    | one Chunk per line: `{chunk_id, section_id, law_id, node_ids[], text, token_count, source, source_subcorpus, source_file, oversized}`                                                            |
| `hierarchy.json`  | `{law_id: {title, source, chapters[], sections[], subsections[], items[], amendments[], definitions[]}}` — fast lookup for any root document                                                     |
| `stats.json`      | run summary: timings, counts, per-subcorpus breakdown                                                                                                                                            |
| `errors.log`      | parser exceptions (one block per failed file). Should be empty.                                                                                                                                  |

## Node types

Hierarchical: `LAW`, `CHAPTER`, `SECTION` (§), `SUBSECTION` (momentti), `ITEM` (kohta).
Semantic: `DEFINITION` (only when the text matches `tarkoitetaan` / `määritellään` / `defined as`).
Metadata: `TITLE`, `AMENDMENT_BLOCK`.
Per-corpus roots: `GUIDE` (vero), `CASE` (KHO), `TREATY` (Tuloverosopimukset).

## ID scheme

Every id is deterministic and reproducible:

```
{source}/{subcorpus}/{slug-of-rel-path}-{4-byte-hash}/c{n}/s{n}/m{n}/i{n}
                     ^^^ collision-free at the document level
```

A `disambiguate()` counter is applied at the chapter/section/item level so
that legal markers that repeat under the same parent (e.g. an amendment
file that restates `1 §` twice) still produce unique IDs (`s1`, `s1-2`).

## Chunking

`pack_section` in `chunks.py`:
- one SectionBundle per § (or per heading-equivalent in vero/kho/treaty),
- target 800–1500 tokens, hard cap 2000,
- never splits an `ITEM` node (spec §6.4),
- for non-ITEM nodes that individually exceed the hard cap, falls back to
  sentence-level packing (Finnish-aware abbreviation handling in
  `_split_sentences`),
- if a single sentence is itself > 2000 tokens, emits it alone with
  `oversized: true` so downstream filters can flag it.

## Last full run (M3, 9 workers)

```
files:    63,661  (0 errors)
nodes:    1,967,776  (0 duplicates, 0 missing parents)
chunks:   402,098    (avg 365 tok, p50 233, p90 937, p99 1465, 10 oversized)
elapsed:  ~57s
output:   2.1 GB across nodes.jsonl + chunks.jsonl + hierarchy.json
```
