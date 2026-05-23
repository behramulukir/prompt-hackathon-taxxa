# Edge Count Discrepancies — Brief vs. `output/graph.db`

> Flagged during Track F kick-off (V7.2 pilot prep). The numbers in the parallel-execution brief do not match what the loaded graph store actually contains.
>
> This is a **brief-vs-reality** report, not a fix. Track F continues working against the real numbers below; Step 2 owner should triage whether the gaps are extractor losses or loader filters.

## Source of the figures

- **Brief numbers**: edge counts listed in the Track F kickoff prompt (also referenced in `our-docs/parallel_execution_after_step4.md` adjacent context).
- **Actual numbers**: `SELECT type, COUNT(*) FROM edges GROUP BY type` against `output/graph.db` (3.2 GB SQLite, Step 4b load complete).

## The gap

| Edge type   | Brief        | Actual        | Δ                          | Notes |
|-------------|-------------:|--------------:|----------------------------|-------|
| parent_of   | 1,904,115    | 1,904,115     | match                      | Structural; loader-faithful as expected. |
| defines     |   234,570    |   234,570     | match                      | Confirmed dominant non-structural type. |
| applies     |    18,259    |    18,259     | match                      | — |
| interprets  |    16,613    |    16,613     | match                      | — |
| **cites**   |  **67,834**  |   **7,164**   | **−60,670 (≈10× fewer)**   | **Material.** v2's `cites` traversal is much thinner than planned. |
| **transposes** | **8,453** |       **0**   | **completely absent**      | No `transposes` rows in the edge table. |
| amends      |        75    |        24     | −51                        | Already small; impact minor. |
| repeals     |       102    |        24     | −78                        | Already small; impact minor. |

## Why this matters for Step 7

1. **`cites` is a primary multi-hop lever.** The Step 7 strategy table assigns `cites` to *multi-hop (rule + exception)* and *cross-reference* categories. With 10× less material, those expansions will surface fewer neighbors than the brief assumed. Multi-hop quality on v2 is therefore at higher risk than the plan implied.
2. **`transposes` is gone.** EU-law transposition is out of corpus scope per `00_overview.md`, so the missing `transposes` edges do not block any in-scope question. Worth confirming whether Step 2 emitted them at all or whether the loader dropped them — if the former, no action; if the latter, the loader has a silent filter.
3. **`amends` / `repeals` smaller but still functional** for the recency strategy (1 hop is enough to find the superseding instrument). Less worry.

## Track F response

- **Include `applies` in the V7.2 pilot edge set** (alongside `parent_of`, `cites`, `interprets`) as a partial compensation for the thinner `cites`. 18k `applies` edges may carry some of the rule-chain signal we would otherwise have hoped to get from `cites`.
- **Test `defines` IN vs OUT** as already planned — the 234k count was correct and is the main noise risk.
- **Lower expectations for `cites`-driven gains.** If V7.2's cross-reference question (Q34 candidate, treaty Art 16 → Art 17/19/20/21) surfaces few or no expected neighbors, the diagnosis is upstream (Step 2 extractor missed citation forms), not Track F's expansion logic.
- **Do not chase the gap from Track F.** Re-running Step 2 is out of this track's scope. If the pilot fails because of edge sparsity, the finding goes back to Step 2's owner with a concrete failing-example list.

## Open questions for Step 2 / loader owners

1. Did Step 2 emit ~67k `cites` edges and the loader keep only 7k? Or did the extractor only produce 7k?
2. Same question for `transposes`, `amends`, `repeals`.
3. If the loader is dropping edges, on what criterion? (Dangling target? Low confidence? Type-mismatch with the strict EdgeType literal?)

Answers to (1)–(3) determine whether a re-load can recover the gap cheaply, or whether Step 2 needs a re-run.
