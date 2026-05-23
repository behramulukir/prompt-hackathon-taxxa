# TO-DO — Audit Step 2 / Loader for Missing Edges (cites 10×, transposes missing)

**Owner:** Step 2 owner + Step 4b loader owner (one or both, depending on diagnosis)
**Discovered by:** Track F kickoff scan vs. brief, 2026-05-23. Full numbers in `our-docs/edge_count_discrepancies.md`.
**Priority:** Medium for `cites`; low for `transposes`/`amends`/`repeals`.

## Problem

| Edge type | Brief said | Actual in graph.db | Gap |
|---|---:|---:|---|
| **cites** | 67,834 | **7,164** | ~10× fewer |
| **transposes** | 8,453 | **0** | missing entirely |
| amends    | 75 | 24 | smaller (low priority) |
| repeals   | 102 | 24 | smaller (low priority) |

## Why it matters

- `cites` is one of the main multi-hop levers in `findings/07_expansion_strategies.md`. 10× fewer edges → much thinner cross-reference recall.
- `transposes` was meant to be the EU-law transposition link. Its absence is fine for in-scope questions (EU-lex is out of scope per `00_overview.md`), but if those edges *were* produced by Step 2 and silently dropped by the loader, the loader has a bug worth fixing for symmetric reasons.

## Diagnosis path

The discrepancy could live in either layer:

### A. Step 2 emitted fewer edges than expected.

Check the raw edge artifact:

```bash
wc -l output/edges.jsonl    # actual extraction output
```

If the line count matches the graph.db count (~265k total resolved + dangling), Step 2 simply didn't extract as many `cites` as the brief assumed. The brief's number may have been a planning estimate, not a measurement.

Sub-check: count by extracted_by method (`structural`, `anchor`, `regex`, `llm`). If `llm` is unusually low, the LLM extractor was throttled / failed silently on many docs and the gap is recoverable by re-running the LLM extractor on the failed docs.

### B. Loader dropped edges.

Compare `output/edges.jsonl` count to `SELECT COUNT(*) FROM edges` in `output/graph.db`. If the file has more rows than the DB has, the loader is filtering.

If the loader does filter (e.g., by confidence threshold, type validity, dangling status), check whether the filter is documented. Step 4b's reload report (`findings/04b_load_report.md`) may already note this.

### C. Loader dropped `transposes` specifically.

`transposes` is a valid `EdgeType` literal in `src/models.py`. If `edges.jsonl` contains rows of `type='transposes'` but `graph.db` has zero, the loader has a type filter. Quick check:

```bash
grep -c '"type":"transposes"' output/edges.jsonl
```

Non-zero count + zero in DB = loader bug.

## Fix tasks (depending on diagnosis)

**If Step 2 under-extracted `cites`:**
- Identify documents where `cites` extraction failed (likely the LLM-fallback docs).
- Re-run the LLM extractor on just those documents.
- Append to `edges.jsonl`, re-load.

**If loader dropped edges:**
- Find the filter, document the intent (or remove the filter), re-load.
- Verify counts post-load.

**If brief was wrong:**
- Update the brief. The pilot already proceeded against actual numbers; downstream design has accounted for the gap. Nothing further to fix.

## Cascade impact

- Step 2 incremental re-extract on missing docs: hours.
- Loader fix + reload: minutes.

## Why Track F isn't doing this

Out of allowed-writes scope (no `src/extraction/`, no `src/indexing/`, no `scripts/load_graph.py`). Track F already updated its design to work against the *actual* numbers; this to-do is for whoever wants to close the gap.

## Acceptance

- `cites` count is either explained ("brief was wrong") or recovered to within 50% of the brief's number.
- `transposes` either confirmed to be zero by design (Step 2 didn't generate them) or recovered.
