# Step 1 — HTML → nodes → chunks (done)

Built the deterministic ingestion pipeline specified in `step-1-plan.md`.
HTML in `data/` is now parsed into a legal-structure node graph and packed
into token-bounded chunks. No LLMs in this stage.

## What was built

```
pipeline/
├── ingest.py                       # entry point — walks data/, dispatches, writes JSONL
├── nodes.py                        # Node dataclass + deterministic id helpers
├── chunks.py                       # SECTION-first packing + sentence-split fallback
├── tokens.py                       # tiktoken cl100k_base counter
├── output.py                       # JSONL writers + hierarchy index builder
├── html_utils.py                   # BeautifulSoup helpers (heading detection, § parsing)
├── verify.py                       # post-run quality checks (spec §9)
└── parsers/
    ├── finlex_konsolidoitu.py      # Laki/Asetus (säädöskokoelma) — clean h1/h2/h3
    ├── finlex_amendments.py        # Laki/, Asetus/ — h1 + h4 amendment blocks
    ├── vero.py                     # Verohallinto guidance (Ohjeet/Päätökset/…)
    ├── kho.py                      # KHO case-law precedents
    └── treaty.py                   # Tuloverosopimukset (tax treaties)
```

## Node taxonomy (as implemented)

- Hierarchical: `LAW`, `CHAPTER`, `SECTION` (§), `SUBSECTION` (momentti), `ITEM` (kohta)
- Semantic: `DEFINITION` — only when `tarkoitetaan` / `määritellään` / `defined as` is
  explicit in the text (never inferred)
- Metadata: `TITLE`, `AMENDMENT_BLOCK`
- Per-corpus roots: `GUIDE` (vero), `CASE` (KHO), `TREATY`

## ID scheme

Every id is deterministic, ASCII-safe, and collision-free:

```
{source}/{subcorpus}/{slug-of-rel-path}-{4-byte-hash}/c{n}/s{n}/m{n}/i{n}
                     ^^^ blake2b suffix prevents 80-char-prefix collisions
```

A `disambiguate()` counter handles cases where legal markers repeat under
the same parent (e.g. amendment files that restate `1 §` across multiple
luvut without a fresh `<h2>` — second one becomes `s1-2`).

## Chunking strategy

`chunks.pack_section()`:

- one `SectionBundle` per § (or per heading-equivalent in vero/kho/treaty)
- target 800–1500 tokens, hard cap 2000
- never splits an `ITEM` node (spec §6.4)
- non-ITEM nodes exceeding the cap fall back to sentence-level packing
  with Finnish-aware abbreviation handling (`esim.`, `ks.`, `yms.`, etc.)
- a single sentence > 2000 tokens is emitted alone with `oversized: true`

## Outputs (`output/`)

| file              | size  | contents                                                                                                   |
| ----------------- | -----:| ---------------------------------------------------------------------------------------------------------- |
| `nodes.jsonl`     | 1.3 G | one Node per line                                                                                          |
| `chunks.jsonl`    | 691 M | one Chunk per line                                                                                         |
| `hierarchy.json`  | 159 M | `{law_id: {title, source, chapters[], sections[], subsections[], items[], amendments[], definitions[]}}` |
| `stats.json`      | <1 K  | run summary                                                                                                |
| `errors.log`      | 0 B   | parser exceptions — empty                                                                                  |

## Final run on the full corpus

M3, 9 workers, **56.9 s**.

```
files:    63,661   (0 errors)
nodes:    1,967,776
chunks:   402,098   avg 365 tok · p50 233 · p90 937 · p99 1465 · 10 oversized
```

Per-subcorpus breakdown:

| subcorpus    | files  | nodes     | chunks  |
|--------------|-------:|----------:|--------:|
| finlex_laki  | 47,226 | 1,103,137 | 236,236 |
| finlex_skk   |  7,452 |   517,891 | 112,827 |
| kho          |  7,040 |   228,432 |  29,132 |
| vero (all)   |  1,826 |    91,356 |  19,240 |
| treaty       |    117 |    26,960 |   4,663 |

## Quality checks (`pipeline.verify`)

- duplicate node ids: **0**
- nodes with missing parent: **0**
- nodes without source_file: **0**
- chunks referencing a non-existent node: **0**
- ITEM nodes split across chunks: **0**
- UUID-like node ids: **0**
- oversized chunks (single unsplittable sentence): **10** (flagged, not fatal)

## Bugs found and fixed during integration

1. **Doc-slug truncation collisions** — many Finnish asetus filenames share
   80-char prefixes; the same slug ended up referring to 100+ different
   documents. Fixed by appending a 4-byte BLAKE2b hash of the full relative
   path.
2. **Vero preamble paragraphs colliding on `m1`** — paragraphs before the
   first heading were not added to `current_members`, so the momentti
   counter reset to 1 on every preamble paragraph. Fixed with a per-parent
   counter dict.
3. **ITEM-marker reuse across multiple lists** — `looks_like_item_prefix()`
   returned the same `"1"` / `"a"` marker for every list under a section,
   colliding when sections had multiple lists. Fixed by using position-based
   IDs and keeping the natural marker on `label`.
4. **Repeated `§ N` markers under the same chapter** in amendment files
   (where chapter switches aren't always wrapped in `<h2>`) — fixed with
   the same `disambiguate()` counter applied at all heading levels.
5. **Treaty preambles producing 10k-token single-paragraph chunks** —
   added sentence-level packing fallback inside `pack_section`.

## How to run

```bash
python3 -m venv .venv && .venv/bin/pip install beautifulsoup4 lxml tiktoken
.venv/bin/python -m pipeline.ingest --workers 9         # full corpus
.venv/bin/python -m pipeline.ingest --limit 100         # smoke run
.venv/bin/python -m pipeline.verify output              # quality checks
```
