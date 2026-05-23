# Step 9 — Ancestor-aware temporal awareness (amendments, repeals, interpretations)

Closes the gap raised in the audit: the v1/v2 pipelines did fine semantic
matching but were blind to whether a semantically-related chunk was
outdated by a downstream amendment, repeal, or higher-court interpretation.
Worse, they only consulted each chunk's own `usable` flag — a SUBSECTION
sitting under an amended SECTION inherited no signal from its ancestor.

This step makes both pipelines (v1 + v2) ancestor-aware end-to-end:
typed amendment edges are backfilled into the graph, every node gets a
graded `temporal_status`, the reranker uses a four-bucket penalty, the
assembled LLM context surfaces amendment + interpretation history per
source, and `AnswerResult` carries a new `amendment_caveats` list ready
for the UI to render as a "Huomioitavaa:" block.

Headline numbers from the existing 1.97M-node graph, today=2026-05-24:

| Metric                                  | Before | After |
|-----------------------------------------|------:|------:|
| Typed `amends` edges                    |    24 | 14,032 |
| Typed `repeals` edges                   |    24 |    161 |
| Nodes with `temporal_status` field      |     0 | 1,967,776 |
| Nodes graded `suspect`                  |     — |  62,467 |
| Nodes graded `stale`                    |     — |    203 |
| Nodes graded `repealed`                 |     — |  50,830 |

## Five moves

| Move | Headline | Status |
|------|----------|--------|
| 1 | Backfill `AMENDMENT_BLOCK → LAW` typed amends/repeals edges | done |
| 2 | Compute ancestor-aware `temporal_status` for every node | done (priority) |
| 3 | Reranker uses graded temporal penalty | done |
| 4 | Surface amendment + interpretation history in the assembled prompt | done |
| 5 | `AmendmentCaveat` list on every `AnswerResult` | done |

## What was built

```
scripts/
├── backfill_amendment_edges.py        # Move 1: AMENDMENT_BLOCK → LAW edges
└── compute_temporal_status.py         # Move 2: per-node temporal_status writer

src/
├── models.py                          # +AmendmentCaveat, +AnswerResult.amendment_caveats
├── indexing/
│   └── graph_store.py                 # +get_temporal_status_map(node_ids) — bulk lookup
└── retrieval/
    ├── rerank.py                      # graded W_TEMPORAL_PENALTY, accepts temporal_status_map
    ├── assemble.py                    # _temporal_lines() per source block; status= flag in header
    ├── caveats.py                     # NEW — build_amendment_caveats(...) with 3-tier fallback
    ├── pipeline.py                    # v1: bulk lookup → rerank → caveats
    ├── pipeline_v2.py                 # v2: bulk lookup → rerank (CE + vector) → caveats
    └── generate.py                    # +SYSTEM_PROMPT instructions for "Huomioitavaa:"

output/
├── edges_amendments.jsonl             # Move 1 companion (14,145 records)
├── temporal_status_stats.json         # Move 2 counts per grade
└── graph.db                           # nodes.metadata_json now carries temporal_status
```

## Concept — why ancestor-aware

The user's brief framed it: *"even if a section is not outdated based on
the edges immediately connected to it, edges connected to its parent
might indicate such situations."*

The v1/v2 pipelines previously asked one question per chunk: *"is this
chunk's `usable` flag True?"* That flag is set from the chunk's own
metadata. So a SUBSECTION of TVL would inherit TVL-root metadata once at
ingestion time and be done with it. If TVL gained a 240th amendment after
the chunk was indexed, the chunk had no way to know.

The new `temporal_status` answers a richer question: *"given the chunk's
LAW root, every amendment ever applied to that LAW, every direct repeal
edge, and every KHO/KVL interpretation on file, what is the chunk's
**effective** temporal grade?"* Four buckets:

- **ok** — clean ancestor history.
- **suspect** — the parent LAW has amendments with effective dates after
  this chunk's publication. Consolidated text usually reflects them, so
  the penalty is light (0.10).
- **stale** — the parent LAW is superseded by a successor act (not a
  "muuttamisesta annetun lain kumoamisesta" meta-repeal — see below).
- **repealed** — the chunk or its LAW root has been explicitly repealed
  or marked `in_force=false`.

Each grade maps directly to a `W_TEMPORAL_PENALTY` value the reranker
subtracts from the composite score.

## Move 1 — `scripts/backfill_amendment_edges.py`

The Step-1 parser emits ~14k `AMENDMENT_BLOCK` nodes (one per
`14.5.2010/409`-style h4 heading) but Step 2's regex extractor only
resolved ~48 typed amends/repeals edges from the small "Laki X
muuttamisesta" instrument files. The bulk of the amendment graph was
structurally present (under the consolidated LAW's parent_of chain) but
typeless.

This script closes the gap. For each AMENDMENT_BLOCK:

1. Parses the label (`14.5.2010/409`) → `enactment_date`, `act_number`.
2. Parses the body's `tulee voimaan ...` clause → `effective_date`.
   The scoping regex (`_VOIMAAN_WINDOW_RE`) matches the *first date
   within the voimaantulo window* — without that, blocks that mention an
   older asetus they repeal ("kumotaan ... 24 päivänä helmikuuta 1873")
   would grab the 1873 date as the new law's effective date. (This bug
   was caught at dry-run stage on the 1947/623 block.)
3. Detects pure-repeal vs amendment via verb presence
   (`kumotaan` / `muutetaan` / `lisätään`).
4. Emits one `amends` (or `repeals`) edge to the LAW root, with the
   parsed dates in `properties_json`.

Idempotent via `extracted_by='backfill_amendment'` — re-runs delete the
previous backfill before inserting fresh edges. Companion JSONL at
`output/edges_amendments.jsonl` for inclusion in a future
`load_graph --rebuild`. Also refreshes the per-node `degree` map for
affected ids so the v2 expansion's degree caps stay accurate.

The script targets WAL-mode SQLite via `timeout=30s` (the demo UI is a
concurrent reader) and stays in WAL throughout — `journal_mode=OFF`
needs an exclusive lock we can't get while the UI is open.

## Move 2 — `scripts/compute_temporal_status.py` (priority)

Three-pass streaming computation:

1. **Per-LAW summary**. Scan all 54,678 LAW nodes; for each, collect own
   publication/effective/repeal dates, in_force, superseded_by. Then
   walk Move-1 edges to count amendments + repeals per LAW and record
   the latest `effective_date` + the AMENDMENT_BLOCK id that carries it.
2. **Per-target interprets aggregation**. Build
   `{target_node_id: (count, latest_interpretation_date)}` from all
   16,613 `interprets` edges, joined against each source's
   `publication_date`.
3. **Stream every node**. For each node:
   - Derive its LAW root from the id (`first 3 path segments`).
   - Inherit the LAW summary; fold in the node's own repeal_date /
     in_force.
   - `ancestor_amended = (LAW's latest_amendment_date > node's
     publication_date)` — for consolidated Finlex children whose
     publication_date matches the latest amendment, this is False (no
     surprise: their text already reflects the amendment). For external
     citing chunks (KHO/Vero with older publication_date), this fires.
   - Severity priority: repealed > stale > suspect > ok.
   - Write `temporal_status` into `metadata_json`.

The whole graph (1.97M nodes) updates in ~42s on a warm SQLite.

### Meta-repeal correction (the TVL bug)

Step 3's `enrich_metadata.walk_amendment_chains` greedily fills
`superseded_by` from any inbound amends/repeals edge. That made TVL
appear superseded by
`finlex-laki-laki-tuloverolain-53-n-muuttamisesta-annetun-lain-kumoamisesta-html-…`
— a "law repealing the law about amending TVL § 53". It's a one-shot
meta-repeal of a stray amendment instrument, not a real successor act.

`_is_meta_repeal_id()` detects this with a single-line heuristic:

```python
def _is_meta_repeal_id(law_id: str) -> bool:
    lower = law_id.lower()
    return "muuttamisesta" in lower and "kumoamisesta" in lower
```

When a LAW's `superseded_by` matches that pattern, the law_status stays
`ok` instead of flipping to `stale`. After the run, TVL's
`effective_usable` is `suspect` (it has 239 real amendments, latest
effective 2027-07-01) rather than the previous wrong `usable=false`.

## Move 3 — graded reranker penalty

`src/retrieval/rerank.py` now takes an optional `temporal_status_map:
dict[str, dict|None]` keyed by `section_id`. When supplied, the legacy
binary `W_NOT_USABLE` penalty is replaced by:

```python
W_TEMPORAL_PENALTY = {
    "ok":       0.00,
    "suspect":  0.10,
    "stale":    0.25,
    "repealed": 0.50,
}
```

Both pipelines fetch the map once per `answer()` call via the new
`GraphStore.get_temporal_status_map(node_ids)` — one SQL roundtrip
regardless of `k`. Hits without a status entry fall back to the legacy
`hit.usable` check inside `rerank()` so callers without graph-store
access keep working (e.g. the v1 unit-test path that constructs synthetic
`RetrievedHit` instances).

v2's cross-encoder reranker reads the same map through `_metadata_signal`
so the combined score is ancestor-aware whether the cross-encoder or the
vector reranker is in charge. The v2 vector path (`_rerank_vector`)
forwards the map to `metadata_rerank` directly.

The diagnostic component name `not_usable_penalty` was kept so `--verbose`
output and any dashboards reading it don't break — the value is now
graded. An additional `temporal_grade` debug component (0/1/2/3/-1)
exposes which bucket fired per hit.

## Move 4 — temporal lines in the assembled prompt

`src/retrieval/assemble.py` now adds `_temporal_lines(temporal_status)`
under each `[Source N]` block. Lines are emitted only when there's
something to say, so clean sources stay compact:

```
[Source 3] Finlex laki · Tuloverolaki — 124 § (in force, authority_rank=100, 2026-04-24, status=suspect)
  Path: Tuloverolaki > Luku 4 > § 124
  Amendments to parent LAW: 239 (latest effective 2027-07-01 — may post-date this text)
  Interpretations on file: 6934 (latest 2024-…)

  ...body...
```

The header line gained `status=suspect|stale|repealed` (silent for `ok`)
so the LLM sees the ancestor-aware grade alongside the binary `in force`
flag. One graph roundtrip per `assemble()` call (same map shape as
rerank uses — could be deduped in a future pass).

## Move 5 — `AmendmentCaveat` on `AnswerResult`

`src/models.py` gains `AmendmentCaveat` and
`AnswerResult.amendment_caveats: list[AmendmentCaveat]`. Empty list =
every citation rests on clean ancestor history; non-empty = the UI
should render a "Huomioitavaa:" block.

Caveats are built in `src/retrieval/caveats.py:build_amendment_caveats`
from the actually-cited chunks (post-generation) via a **three-tier
fallback**, picked per cited section:

1. **The section's own `temporal_status`** if flagged.
2. **Amendment-instrument target lookup** — when the citation lives in
   a `…-muuttamisesta-…` LAW (single-shot amendment act whose own status
   is `ok` because the act itself has no further amendments), follow
   outbound `amends` edges; if there are none (the common case — Step 2
   covered only a few dozen), infer the target by Finnish-genitive→
   nominative slug transformation:
   `rikoslain` → `rikoslaki`, `tuloverolain` → `tuloverolaki`,
   `arvonlisäverolain` → `arvonlisäverolaki`, `asetuksen` → `asetus`.
   Search the LAW table by id-suffix (`%-<nominative>-html-%`),
   preferring the consolidated Laki edition over Säädöskokoelma.
3. **Cross-source interprets/cites lookup** — for citations from Vero
   ohjeet and KHO cases, walk outbound `interprets`/`cites` edges on the
   section *and its leaf descendants* (most typed edges live one
   structural hop down from the chunk-anchoring SECTION). Pick the
   most-amended flagged target as the representative caveat.

Each caveat carries `chunk_id`, `section_id`, `kind`,
`nearest_amendment_id`, `amendment_effective_date`,
`amendment_count_in_law`, `interpreted_count`,
`latest_interpretation_date`, and a Finnish `explanation_fi` produced by
`_format_explanation_fi` — a small templating function that selects
phrasing by grade and folds in the amendment/interpretation counts when
available.

The LLM system prompt in `generate.py` was extended with a "Temporal
awareness" section instructing the model to read the new context lines
and write a short "Huomioitavaa:" / "Note:" block when a cited source is
suspect/stale/repealed. The pipeline still populates
`amendment_caveats` independently of whether the LLM mentions them —
the UI is the authoritative renderer for caveats; the prompt change is a
best-effort nudge.

## Live evidence

Five queries through `scripts.ask --json` against the full corpus:

| Query | Caveats fired | Driven by |
|-------|--------------:|-----------|
| `Mikä on pääomatulon verokanta?` | 2 | suspect — rajoitetusti-verovelvollisen tulon law, 60 amendments |
| `Rikoslain virkamiehen lahjominen` | 4 | suspect — rikoslaki, **467 amendments** (via slug inference from `rikoslain-muuttamisesta-14`) |
| `Yleishyödyllisen yhteisön verovapauden edellytykset` | 2 | suspect — TVL, **239 amendments**, 6,934 interpretations |
| `Mikä on arvonlisäveron vähennysoikeus?` | 1 | stale — AVL (via cross-source from Vero ohje's outbound interprets) |
| `Mikä on pääomatulon verokanta?` (specific § 124 amendment law) | 0 | the cited amendment act is itself a one-shot — own status `ok`, no flagged target to fall back on |

Example Finnish explanation produced by Move 5 for the rikoslaki case:

> Emolaissa on 467 muutosta, joista uusin on voimassa 2027-07-01 alkaen
> ja saattaa olla tuoreempi kuin tämä teksti.

## Decisions and tradeoffs

### `temporal_status` written to graph.db, not nodes_enriched.jsonl

Both routes were viable. Writing to `metadata_json` in-place means the
field is available the moment the script finishes — no
`load_graph --rebuild` needed, which matters because the demo UI is
holding a read connection. The jsonl is the authoritative source-of-truth
for a full rebuild; users should re-run `compute_temporal_status` after
any rebuild. Documented at the bottom of the README.

### Severity priority repealed > stale > suspect > ok, never additive

A node could plausibly be both "in a stale parent LAW" and "with
amendments after publication" — additive penalties would compound. The
priority ladder picks the strongest signal so penalties stay capped at
0.50. The lighter signals are still recorded in the status dict
(`law_stale`, `ancestor_amended` are independent bools) so a future
verifier agent could differentiate.

### Suspect penalty is gentle (0.10), not punitive

Consolidated Finlex chunks have `publication_date = latest amendment
date` by construction (Step 3's `_extract_publication` picks the last
`<h4>` amendment header). So for consolidated text,
`ancestor_amended = False` and the chunk stays `ok`. `suspect` mostly
fires on:

- External citing chunks (KHO, Vero) whose `publication_date` is older
  than the parent LAW's latest amendment.
- Future-effective amendments that have not yet been folded into the
  consolidated text but are dated > now (rikoslaki / TVL both have
  2027-07-01 amendments today).

0.10 is enough to break ties between two semantically-equal chunks
without dropping the chunk out of the top-N. The user still sees the
caveat in `amendment_caveats`.

### Slug-based amendment-target inference (the genitive→nominative trick)

Step 2's regex extractor resolved only a few dozen outbound `amends`
edges from instrument laws. Rebuilding Step 2 with a better extractor
was out of scope. Instead Move 5 leans on a Finnish morphological
regularity: amendment laws are always titled "Laki X:n muuttamisesta"
where `X:n` is the target law in the genitive. The id slug preserves
this verbatim (`-rikoslain-muuttamisesta-`, `-tuloverolain-77-n-`).

`_genitive_to_nominative`:
- `-lain` → strip 2 chars, append `ki` → `-laki`
- `-uksen` → strip 4 chars, append `s` → `-us`

Then a `LIKE '%-<nominative>-html-%'` LAW lookup, preferring
`finlex/laki/` over `finlex/laki_skk/`. This recovers the target for
the entire `…-muuttamisesta-…` family without rebuilding edges.

### Three-tier caveat fallback, not a single union

Building the union of all three sources would surface noise (every Vero
ohje cites dozens of statutes; many of those are clean). The fallback
ladder picks the most relevant single caveat per cited section: own
status if flagged, else the law it amends, else the most-amended law it
interprets/cites. One caveat per cited section keeps the
`amendment_caveats` list small and the UI's "Huomioitavaa:" block
readable.

### Two GraphStore lookups per answer, not one shared cache

Move 3 (rerank) and Move 4 (assemble) each call
`get_temporal_status_map` for the section ids they handle. They could
share a cache, but rerank's set is `k`-sized (~20) and assemble's is
`n`-sized (~8) — both small, both already issued in a single roundtrip.
Premature consolidation would couple two modules that should stay
independent. The cost is two ~1ms queries instead of one.

### Caveats built post-generation, not pre

Caveats fire from `gen.cited_chunk_ids` — the chunks the LLM actually
cited, not everything in the candidate pool. This makes the caveat list
strictly relevant to the answer the user sees. A pre-generation alternative
(caveat every retrieved chunk) would dump 8+ caveats on every query.

### Keeping the binary `usable` flag

`usable` is read by enrich_metadata, by LanceDB column scans, by older
eval scripts, and by the v1 metadata signal. Moving them all to read
`effective_usable` would have been a wide refactor. The cleaner path was
to add `temporal_status` as a parallel, richer field and have the new
penalty take precedence when present. `usable` remains a useful binary
default for callers that don't have graph-store access.

### LLM prompt change is best-effort, not load-bearing

The added "Temporal awareness" section in `SYSTEM_PROMPT` asks the LLM
to render a "Huomioitavaa:" block. DeepSeek doesn't always comply — and
that's fine. The authoritative source of caveats is the
`AnswerResult.amendment_caveats` field, populated independently of
generation. The prompt is a nudge for inline prose; the structured field
is the contract for the UI.

## Known limits (data-coverage, not architecture)

- **The koiravero case**: the dog tax law was repealed in 2010 by `Laki
  koiraverosta annetun lain kumoamisesta`. The kumoamisesta act emits no
  outbound `repeals` edge to the koiraverosta law — Step 2's regex
  didn't catch it. A query about `Koiravero verovapaus` therefore
  produces zero caveats because every cited section's status reads
  `ok`. The architecture is sound; the missing data is one `repeals`
  edge.
- **Future-effective amendments inflate the `suspect` count**.
  Rikoslaki's `nearest_amendment_date = 2027-07-01` makes the `suspect`
  bucket ~62k chunks today. This is signal, not noise: those chunks
  really do precede an upcoming amendment. The UI can choose to suppress
  caveats for `effective_date > today` if it wants strict
  "what-was-the-law-on-date-X" semantics — the data to do so is in the
  status dict.
- **Per-section amendment tracking is unchanged**. Move 1 attaches
  amendment edges at LAW-root granularity. The known SECTION-parsing
  gaps on AVL/TVL (see `our-docs/to-do/step1_consolidated_law_section_parsing.md`)
  mean we still can't say *which §* of TVL was amended by a particular
  block. Section-level resolution needs a Step-2 extractor refresh,
  out of scope here.
- **Some KHO publication dates are wildly out of range** (one chunk's
  inherited `publication_date` is `2073-01-01`). This is an upstream
  Step-3 extractor bug, not a Move-2 bug. The downstream effect on
  `latest_interpretation_date` is cosmetic — the caveat phrasing
  surfaces the bad date but doesn't act on it.

## How to run

```bash
# After any graph rebuild (scripts.load_graph --rebuild):
.venv/bin/python -m scripts.backfill_amendment_edges
.venv/bin/python -m scripts.compute_temporal_status

# Smoke test
.venv/bin/python -m scripts.ask --json "Rikoslain virkamiehen lahjominen" | jq '.amendment_caveats'
.venv/bin/python -m scripts.ask --v2 --json "Mikä on AVL:n vähennysoikeus?" | jq '.amendment_caveats'
```

Both scripts accept `--dry-run` for fast iteration without writes.
`compute_temporal_status --today YYYY-MM-DD` overrides `date.today()` for
reproducible runs (the script's repeal-by-date logic depends on it).

## Sequencing notes

- **No CLI flags changed**. Both pipelines pick up the new behavior
  automatically as long as `compute_temporal_status` has been run on
  the graph the retriever points at.
- **Existing tests still pass** (`19 passed, 48 skipped`). The rerank's
  fallback path was specifically preserved for tests that construct
  synthetic `RetrievedHit` objects without a graph store.
- **v2 / GraphRAG benefits the same as v1**. Both rerank modes
  (cross-encoder + vector) plumb the temporal_status map through.
- **The Verifier agent** (`src/agents/verifier.py`, Step 8) is unchanged
  but is the natural next consumer of `amendment_caveats` — a future
  pass could have it cross-check the LLM's prose against the caveat
  list and surface unhandled caveats in `conflicts`.

## Open items

- [ ] Backfill `repeals` edges from `Laki X annetun lain kumoamisesta`
      acts whose titles encode the target (parallel to Move 5's
      slug-inference for amendments). Would unblock the koiravero case.
- [ ] Section-level amendment resolution — requires a Step-2 refresh on
      "Laki X muuttamisesta" body parsing.
- [ ] UI: render `amendment_caveats` as a styled "Huomioitavaa:" block
      under the answer, with each caveat's `nearest_amendment_id`
      linking to the amendment block node.
- [ ] Optional: caveat suppression when
      `amendment_effective_date > today` and the user query has no
      explicit "current" / "voimassa" marker.
