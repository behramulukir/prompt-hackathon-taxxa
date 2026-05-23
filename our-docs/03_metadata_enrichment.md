# Step 3 — Metadata Enrichment

> Step 1 produced nodes with structural fields. Step 2 produced edges. This step adds the **filterable signals** retrieval needs: dates, in-force status, authority, version.
>
> Lower priority than edges. Do this only after Step 2 produces a usable graph.

## Inputs

- `data/nodes.jsonl` from Step 1
- `data/edges.jsonl` from Step 2 (used to detect `amends` / `repeals` chains)
- Original HTML in `data/raw/` (some metadata is in HTML structure, not in node text)

## Annotations added to nodes

Annotations live in a new field `node.metadata = {...}` — the Step 1 schema is not modified.

| Field | Type | Why |
|-------|------|-----|
| `publication_date` | ISO date | Sort by recency |
| `effective_date` | ISO date | Temporal filtering |
| `repeal_date` | ISO date or null | Filter out repealed law |
| `in_force` | bool | Direct ranking signal |
| `authority` | str | "Finlex" / "Vero" (one of a small fixed set) |
| `authority_rank` | int | Numeric tier — used by reranker |
| `superseded_by` | str or null | Canonical ID of newer version |
| `language` | "fi" / "sv" / "en" | Language filter |
| `usable` | bool | Composite: in_force AND not superseded |

## Verification tasks

### V3.1 — Metadata coverage audit

For each source, run a script that counts how often each field can be populated from parsed HTML:

| Field | Expected coverage in Finlex | Expected coverage in Vero |
|-------|------------------------------|----------------------------|
| `publication_date` | high (in document metadata) | high (page header) |
| `effective_date` | high | medium |
| `repeal_date` | medium (only for repealed laws) | rare |
| `in_force` | high (Finlex marks status) | usually true (current guidance only) |

Anything below 80% coverage in its source needs either a better extractor or a documented gap. Write to `findings/03_metadata_coverage.md`.

### V3.2 — Authority hierarchy sanity check

Confirm the hierarchy the system will rely on:

```
finlex_statute  →  authority_rank = 100
vero_guidance   →  authority_rank = 60
```

For 20 hand-picked queries where both sources address the same topic, verify by inspection that this ordering matches expert intuition (Finlex statute is binding; Vero is an interpreter). If a team member with tax expertise can review, get sign-off.

**Output:** `findings/03_authority_ranks.md` — the numeric assignments and the rationale.

## Build tasks

### B3.1 — Metadata extractor (per source)

`src/extraction/metadata_finlex.py`:
- Publication / effective / repeal dates from Finlex document headers
- Status flag from Finlex's explicit "in force" / "repealed" markup
- Amendment chain from `amends` / `repeals` edges in Step 2 — set `superseded_by` to the latest amender

`src/extraction/metadata_vero.py`:
- Publication date from page header
- Vero guidance is generally assumed in force unless explicitly marked obsolete
- Older guidance superseded by newer guidance on the same topic — detected via Vero's own "tämä ohje korvaa" markers when present

### B3.2 — Authority tagging

`src/extraction/authority.py` — applies fixed `authority` and `authority_rank` based on `source`:

```python
AUTHORITY_RANK = {
    "finlex": 100,
    "vero":    60,
}
```

Trivial code; the point is keeping the table in one place so retrieval can import it directly.

### B3.3 — Composite `usable` flag

For every node compute:

```python
usable = (
    in_force is True
    and (repeal_date is None or repeal_date > today)
    and superseded_by is None
)
```

This is what the default retrieval filter checks. Repealed nodes aren't deleted — historical queries may still need them — but they're filtered out by default.

### B3.4 — Pipeline runner

`scripts/enrich_metadata.py`:

1. Iterate over `data/nodes.jsonl`
2. Dispatch to the right extractor per source
3. Walk amendment edges to compute `superseded_by`
4. Compute `authority_rank` and `usable`
5. Write back to `data/nodes.jsonl` (or to a parallel `data/nodes_enriched.jsonl` if you want a clean separation)

## Quality checks

`scripts/qa_check_metadata.py` rejects if:
- More than 5% of nodes per source are missing `publication_date`
- More than 5% are missing `authority` (this is a fixed mapping — should be ~0%)
- An `amends` / `repeals` edge exists but `superseded_by` was not propagated to the source
- `usable` is true for a node with `repeal_date < today`

## Done when

- All nodes have `authority`, `authority_rank`, `language`, `in_force`, `usable` populated
- ≥95% of nodes have `publication_date`
- Amendment chains are correctly propagated — a hand-picked example of an amended statute shows `superseded_by` pointing to the amender
- A spot-check query "find all SECTION nodes about ALV deductions currently in force" returns only `usable=true` results
