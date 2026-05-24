# Step 10 — Eval-driven retrieval fixes (filter, router, hybrid, encoding, edges)

A single failing eval question — *"What is the maximum daily withholding
tax percentage (ennakonpidätys) that can be applied to a taxpayer's
income under Finnish law?"* — surfaced five independent issues that had
been silently degrading retrieval quality across the corpus. Step 10
fixes each one, then re-runs the temporal-status layer built in
[step-9](./step-9-temporal-awareness.md) so the resulting
`amendment_caveats` reflect the newly-discovered amendment chains.

The user's expected answer cites a Verohallinto päätös for 2026 saying
the withholding rate is capped at **60.0 %**. Pre-fix, the päätös was
in the corpus but unreachable; the LLM fell back to a 1980 amendment
law's **50 %** rule and produced a wrong answer.

## Five fixes

| Fix | Issue | File(s) |
|-----|-------|---------|
| **A** | Filter inference shipped `source=finlex` for any query containing the bare token `"law"` — catastrophically broad: "Finnish **law**" / "act of Parliament" silently excluded every Vero document. | `src/retrieval/filters.py` |
| **B.1** | Strategy router had no signal for Verohallinto-päätös queries; they routed to `default` (vector-only), never expanding through the `interprets` edges connecting päätökset to their statutory framework. | `src/retrieval/strategy.py` |
| **B.2** | Pure cosine retrieval struggled on cross-lingual queries where the answer lives in dense Finnish administrative prose. No sparse / lexical fallback existed. | `src/indexing/vector_store.py`, `src/retrieval/vector_retriever.py`, `scripts/build_fts_index.py` |
| **C** | The Step-2 regex extractor resolved only ~24 outbound `amends` edges from "Laki X muuttamisesta" instrument acts. Hundreds of amendment instruments sat as graph orphans, and their target consolidated laws (ennakkoperintälaki, sairausvakuutuslaki, …) reported 0 amendments — so the temporal-status layer rated them `ok` when they were heavily amended. | `scripts/backfill_muuttamisesta_edges.py`, `scripts/compute_temporal_status.py` |
| **D** | BeautifulSoup's encoding sniffer mis-detected the encoding of Vero / amendment HTML files (no `<!DOCTYPE>` / `<meta charset>`) and produced double-encoded chunks (`päätös` → `pรครคtรถs`) in **~6,638 chunks (1.7 %)** including every chunk of the 2026 päätös. Both vector embedding and BM25 operated on mojibake. | `pipeline/html_utils.py`, `scripts/reingest_corrupted_chunks.py` |

## What was built

```
scripts/
├── backfill_muuttamisesta_edges.py   # Fix C: slug-inferred amends edges
├── build_fts_index.py                # Fix B.2: one-time FTS index builder
└── reingest_corrupted_chunks.py      # Fix D: targeted re-ingest for mojibake'd files

src/
├── retrieval/
│   ├── filters.py                    # Fix A: trigger list narrowed
│   ├── strategy.py                   # Fix B.1: päätös → CROSS_SOURCE
│   ├── vector_retriever.py           # Fix B.2: hybrid toggle (default ON)
│   └── ...                           # downstream callers unchanged
├── indexing/
│   └── vector_store.py               # Fix B.2: search_fts + search_hybrid (RRF)
pipeline/
└── html_utils.py                     # Fix D: explicit UTF-8 decode

scripts/compute_temporal_status.py    # extended to fold in Fix C edges +
                                      # fall back to source-LAW publication
                                      # date when edge effective_date absent
```

## Fix A — filter inference

`src/retrieval/filters.py:60`. The pre-fix list was:

```python
_FINLEX_TRIGGERS = ("finlex", "statute", "law", "act", "laki",
                    "säädös", "asetus")
```

`"law"` matches as a substring in any English sentence about Finnish
law, and `"act"` similarly matches "act of Parliament" / "in this act".
Both were removed. Compensation on the Vero side:

```python
_VERO_TRIGGERS = ("vero guidance", "vero ohje", "vero päätös",
                  "tax administration", "verohallinto",
                  "verohallinnon päätös", "ohje", "syventävä")
```

Verification cases now behave correctly:

| Query | Pre-fix | Post-fix |
|-------|---------|---------|
| "What is the maximum daily withholding tax percentage under **Finnish law**?" | `source=finlex` | `{}` (no filter) |
| "Verohallinnon päätös ennakonpidätyksestä" | `{}` | `source=vero` |
| "TVL 124 § soveltaminen" | `source=finlex` | `{}` (no filter — "TVL" not a trigger) |

## Fix B.1 — router for päätös queries

`src/retrieval/strategy.py`. Added `_PAATOS_PAT` covering both Finnish
päätös vocabulary and English withholding-percentage framings, and
extended `_is_cross_source()` to fire whenever this pattern alone
matches (the previous rule required *both* a Finlex citation form *and*
a guidance marker — too restrictive for päätös-only queries).

A Finnish-morphology subtlety landed mid-development: the bare stem
`ennakonpidätys` (nominative) doesn't match `ennakonpidätyksen`
(genitive) because Finnish consonant doubling turns `s` → `ks` before
the genitive marker. The fix:

```python
r"ennakonpid[äa]ty(?:s|ks)"
```

— matches both forms via the trailing `(?:s|ks)` alternation. Without
this the stem would have missed every inflected reference.

Routing now picks `CROSS_SOURCE` for:

- "What is the maximum daily withholding tax percentage (ennakonpidätys)?"
- "Verohallinnon päätös ennakonpidätyksestä vuodelle 2026"
- "Mikä on ennakonpidätyksen enimmäismäärä?"
- "AVL 102 § soveltaminen vero ohje" (unchanged from before)

— and leaves these on `default`:

- "Mikä on pääomatulon verokanta?"
- "TVL 124 § soveltaminen"
- "Rikoslain virkamiehen lahjominen"

## Fix B.2 — hybrid retrieval

LanceDB supports both vector and inverted (BM25-style) indices.
Pre-fix we used only the former. Add a one-time FTS builder + a
`search_hybrid` method that runs both searches in parallel and fuses
the rankings with **Reciprocal Rank Fusion (Cormack et al. 2009)**:

```
score(d) = sum over rankings of  1 / (rrf_k + rank(d))
```

with `rrf_k = 60` (the standard constant — robust to score-scale
differences between vector and BM25). Each backend retrieves
`k * oversample = 60` candidates; top-`k` from the fused ranking is
returned.

`VectorRetriever` now defaults to `hybrid=True`; falls back gracefully
to pure vector when the FTS index hasn't been built yet (the
`search_hybrid` body catches that exception). No call-site changes
needed in `pipeline.py` / `pipeline_v2.py`.

Building the FTS index over 402,088 rows took ~1 hour on local
hardware. Re-runnable via `scripts.build_fts_index --rebuild` after
re-ingestion.

## Fix C — backfill amends from `…lain-muuttamisesta` LAWs

The slug-inference logic from `src/retrieval/caveats._amends_target_for`
already mapped amendment-instrument LAW ids to their consolidated
target at query time. Step 10 promotes that same logic into the graph
data layer as proper `amends` edges, so the temporal-status layer can
count amendments and pick the latest effective date.

`scripts/backfill_muuttamisesta_edges.py` builds an in-memory
`{nominative_stem: [law_id, ...]}` index over all 21,054 Finlex LAW
roots (0.2 s) and uses it for O(1) target lookup per candidate. The
first version did a SQL `LIKE` per candidate against a 1.97 M-row
table and stalled at 99 % CPU with no output; the index moves the
inner loop from O(N) to O(1).

Counts:

| Step | Value |
|------|------:|
| Amendment-instrument LAWs scanned | 18,283 |
| Targets resolved via slug | **12,848** |
| `no_target` (slug stem didn't map to any LAW) | 5,421 |
| Already had outbound amends (Step 2 / Move 1) | 14 |

`compute_temporal_status` was extended in two places:

1. Step B now selects edges with `extracted_by IN ('backfill_amendment',
   'backfill_muuttamisesta')` so Fix C edges count toward
   `amendment_count_in_law`.
2. When an edge's `properties_json.effective_date` is null (the common
   case for Fix C edges — the title carries no date), fall back to the
   source LAW's own `publication_date` / `effective_date` from its
   root metadata. This lets `ancestor_amended_after` populate even
   when the slug doesn't encode a date.

End-to-end impact on a representative LAW:

| Field | Pre-Fix-C | Post-Fix-C |
|-------|----------:|-----------:|
| ennakkoperintälaki `amendment_count_in_law` | 0 | **85** |
| ennakkoperintälaki `effective_usable` | ok | **suspect** |
| ennakkoperintälaki `ancestor_amended_after` | null | **2026-05-01** |
| Whole graph `suspect` count | 62,467 | **97,340** (+56 %) |

## Fix D — UTF-8 decoding

`pipeline/html_utils.parse_html` now decodes bytes to `str` with
`utf-8 / errors="replace"` before handing off to BeautifulSoup. Pre-fix
BS4's encoding sniffer fell back to Latin-1 / Windows-1252 for files
without `<!DOCTYPE>` or `<meta charset>` declarations (most Vero
päätös files and a long tail of finlex amendment instruments) and
internally re-encoded the result as UTF-8 — producing the classic
double-encoded artifact:

```
input  bytes:  c3 a4              (ä in UTF-8)
sniffer says:  Latin-1 → Ã ¤
re-encoded:    c3 83 c2 a4        (Ã¤ in UTF-8)
displays as:   รค
```

Affected: **6,638 chunks (~1.7 %)** across **1,152 LAW roots**.
Breakdown by subcorpus:

| Subcorpus | Bad | Total | % |
|-----------|----:|------:|--:|
| vero_paatos | 86 | 1,744 | **4.9** |
| laki | 2,522 | 129,893 | 1.9 |
| asetus | 1,927 | 106,335 | 1.8 |
| asetus_skk | 818 | 48,126 | 1.7 |
| laki_skk | 971 | 64,701 | 1.5 |
| kho | 301 | 29,132 | 1.0 |
| vero_kvl | 11 | 1,209 | 0.9 |
| vero_ohje | 2 | 15,947 | 0.0 |

`scripts/reingest_corrupted_chunks.py` handles targeted re-ingestion:

1. Scan LanceDB for chunks whose `embedded_text` contains the mojibake
   marker `รค`.
2. Map each affected chunk to its source file via `nodes.jsonl`.
3. Re-parse with the fixed `parse_html`, re-pack with `pack_sections`.
4. Re-embed via Voyage (input_type=`document`).
5. `merge_insert("chunk_id")` upserts — chunk IDs are stable because
   the ID inputs (filename hash, sequential chapter/section indices)
   don't touch the text-encoding pathway.

Step 10 ran this **only against the 2026 päätös** (47 chunks, 156
nodes) to validate the fix end-to-end. The remaining ~6,591 corrupted
chunks were left in place pending an explicit decision on the broader
re-ingest (~$0.60 of Voyage credit + 1 hour for FTS rebuild).

## Verification

The eval question after all five fixes:

```
[suspect] finlex-laki-laki-ennakkoperintalain-muuttamisesta-27 / s2
   Emolaissa on 85 muutosta, joista uusin on voimassa 2026-05-01 alkaen
   ja saattaa olla tuoreempi kuin tämä teksti.

[suspect] finlex-asetus-asetus-ennakkoperintaasetuksen-muuttamisesta-1 / s38
   Emolaissa on 32 muutosta, joista uusin on voimassa 2019-01-01 alkaen
   ja saattaa olla tuoreempi kuin tämä teksti.
```

— two ancestor-aware caveats fire, naming the parent LAWs and the
latest amendment effective dates. The temporal-awareness payoff from
step-9 is now genuinely useful instead of silent.

The **2026 päätös chunks themselves still don't surface in the top-15
retrieved chunks** — even though they are now clean, indexed, and
FTS-searchable, they rank ~138 in pure vector search for this English
query. The semantic gap is documented in
[step-11-semantic-translation-gap.md](./step-11-semantic-translation-gap.md).

## Decisions and tradeoffs

### Filter triggers — keep `"statute"`, drop `"law"`/`"act"`

`"statute"` is rare in casual English about Finnish tax and unambiguously
references a Finlex source when used. `"law"` and `"act"` are too
generic. The Finnish vocabulary (`laki`, `säädös`, `asetus`) stays
because a Finnish-language user typing those literally is gesturing
at a Finlex search.

### RRF `rrf_k = 60`, oversample = 3

The Cormack et al. paper showed `60` is a sweet spot that resists
score-scale skew across retrievers. Each backend retrieves
`k * 3 = 60` candidates so the fusion has enough material; smaller
oversamples drop documents that one backend ranked moderately and the
other strongly. The total LanceDB work is two ~60-candidate queries
— negligible.

### Hybrid default-on, with graceful fallback

`VectorRetriever.__init__` defaults to `hybrid=True`. Callers that
don't have an FTS index see `search_hybrid` silently fall back to pure
vector via the `try / except`. This avoids forcing a one-shot
ingestion script to know whether the index exists, at the cost of one
swallowed exception on cold starts.

### `_law_root_index` in-memory, not a SQL index

Fix C's first version did one `LIKE %-stem-html-%` query per candidate
× 18 k candidates × 1.97 M-row scan — predictably hung. Building a
Python dict of all 21 k LAW roots up front is 0.2 s and lets every
candidate resolve in O(1). The dict fits comfortably in memory.

### Date fallback via source LAW's publication_date

Fix C edges rarely carry a parseable `effective_date` (the slug
contains the act number but not its voimaantulo). When the edge
property is null, `compute_temporal_status` now falls back to the
amending LAW's own `publication_date` — a lower-bound proxy for when
the amendment took effect. This isn't strictly correct (laws can
specify a voimaantulo months or years after enactment) but it's
strictly better than null for the freshness comparison.

### Targeted re-ingest, not corpus-wide

A full re-ingest of the 6,638 corrupted chunks costs ~$0.60 of Voyage
credit + 1 hour for FTS rebuild. The blast radius is 1.7 % of the
corpus and very few of those chunks are likely answer-source material
on a Finnish tax question. The 2026 päätös was the one chunk that
mattered for the live eval; the rest is documented and gated behind
an explicit run of `scripts.reingest_corrupted_chunks`.

### Mojibake marker — `รค` (U+0E23 + U+0E04 + U+0E27)

The substring `รค` (Thai-script-looking-but-isn't) is the unique
fingerprint of a double-encoded `ä`. Other Finnish letters double-encode
to other Thai-shaped substrings; checking for `รค` alone catches every
file with mojibake because any Finnish text contains an `ä` with very
high probability. Cheap, deterministic, no false positives observed.

## How to run

```bash
# Build the FTS index (first time only — ~1 hour for 402k rows)
.venv/bin/python -m scripts.build_fts_index

# Backfill the muuttamisesta edges
.venv/bin/python -m scripts.backfill_muuttamisesta_edges

# Refresh temporal_status to fold in the new edges + date fallbacks
.venv/bin/python -m scripts.compute_temporal_status

# Targeted re-ingest for the päätös (or any subset)
.venv/bin/python -m scripts.reingest_corrupted_chunks \
    --only-paths "vero/Syventävät vero-ohjeet/Päätökset/"
.venv/bin/python -m scripts.build_fts_index --rebuild   # if chunks changed
```

## Open items

- [ ] Broader re-ingest of the remaining 6,591 mojibake chunks
      (1,151 files outside the päätös). User-gated; script is ready.
- [ ] **Semantic translation gap** — English questions about Finnish
      tax don't surface the most-authoritative Finnish administrative
      sources. Plan: see [step-11-semantic-translation-gap.md](./step-11-semantic-translation-gap.md).
- [ ] FTS index rebuild after each broader re-ingest (~1 hour). Could
      be made incremental but LanceDB's API doesn't expose that cleanly
      yet.
