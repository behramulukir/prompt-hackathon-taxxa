# V7.2 Pilot — Hand-Walked Graph Expansion on 3 Hard-Tier Questions

> **Verdict: AMBER.** The BFS mechanism works; the graph contains relevant cross-source structure; **but** the edge topology and corpus coverage are not what the brief assumed. The recommended path is to proceed to building `graph_expand.py` / `strategy.py` / `cross_encoder_rerank.py`, **with three mandatory design constraints derived from the pilot** (degree caps + direction-aware edge allowlists + multi-hop minimum).
>
> The cost of stopping is higher than the cost of building under realistic assumptions. Track F's modules are still the right next step; what changes is the strategy configs they wrap.

## Pilot scope

- **Questions** (hard-tier, from `eval/questions.json`):
  - **Q32** Kaisa — perusteoikaisu under PerVL §38/§39 + Vero VH/6511 decision
  - **Q34** Liisa — Finland–Ireland tax treaty + TVL rental income + Vero pääomatulo guidance
  - **Q35** Pekka — toiminimi VAT, AVL vähäisen toiminnan raja + apportionment under AVL §117
- **Edge variants:**
  - **A**: `["parent_of", "cites", "interprets", "applies"]`
  - **B**: A + `"defines"`
- **Seeds:** zero Voyage calls per the agreed pivot. Seeds were located by direct SQLite lookup against `output/graph.db`.
- **BFS hops:** 1 and 2, direction = `both`. Per-run node cap = 500.

Pilot script + raw counts in `/tmp/v72_pilot_results.json` (transient; the data is summarised inline below).

## Corpus-coverage findings discovered during seed-picking

These are upstream issues but they bound what any v2 expansion can possibly do, so they go here for visibility:

| Statute | LAW root present? | SECTION coverage |
|---|---|---|
| **TVL** (`tuloverolaki`)   | yes, main `…tuloverolaki-html-9e9b64a4` | **0 SECTIONs.** Q34, Q13, Q14, Q26 cannot seed at section granularity. |
| **AVL** (`arvonlisaverolaki`) | yes, main `…arvonlisaverolaki-html-ba5d8e0e` | Main law: 0 SECTIONs. `laki_skk` consolidated copy: **only §222–§237** (chapter 23). AVL §117 (the apportionment rule from the running example) is absent. |
| **PerVL** (`perintö- ja lahjaverolaki`) | yes (main + skk) | Main: only AMENDMENT_BLOCK children. `laki_skk` consolidated: has §38 and other sections. |
| **Finland–Ireland tax treaty** | only the 3-section Finnish *implementing-law wrapper*; treaty body absent | Article 16 (Yksityinen palvelus) / Article 7 (Immovable property) not in corpus. |

**Implication:** the running example "§ 102 AVL → § 114 → § 117" from `00_overview.md` is unrealisable against the current graph because the underlying SECTIONs are not ingested. Multi-hop *within* a major statute requires Step 1 to ingest consolidated-law HTML.

## Edge-topology findings (the load-bearing discovery)

A query against `edges` JOIN `nodes` showed where typed edges actually attach:

**Source side (where typed edges START):**

| edge       | dominant source.type    | counts |
|-----------|-------------------------|-------|
| applies    | SUBSECTION              | 18,259 |
| cites      | SUBSECTION              | 5,609 + smaller from LAW/ITEM/DEFINITION |
| interprets | SUBSECTION              | 15,597 + smaller from ITEM/DEFINITION |
| defines    | DEFINITION              | 234,570 (only from DEFINITION) |

**Target side (where typed edges LAND):**

| edge       | dominant target.type | counts |
|-----------|---------------------|-------|
| applies    | CASE (9,445), LAW (8,811)         | only **3** to SECTION |
| cites      | GUIDE (3,648), LAW (2,939)        | 577 to SECTION |
| interprets | LAW (14,412)                       | only **263** to SECTION |
| defines    | SUBSECTION (197,349), ITEM (37,221) | — |

**This is the V7.2 finding.** Two design facts fall out:

1. **Vector retrieval anchors chunks to SECTIONs (per Step 1). Typed edges do not.** A SECTION seed has only `parent_of` edges. The first useful hop is `parent_of`-OUT to its SUBSECTIONs; the second hop is the typed expansion from those SUBSECTIONs. **`max_hops=1` from a SECTION seed is effectively a structural walk only.** v2 needs `max_hops ≥ 2`.

2. **`interprets` lands at LAW-root granularity, not SECTION granularity** — even when `target_ref` preserves the section reference. Example from a Vero pitkäaikaissäästäminen guidance node:
   ```
   interprets  target_ref='TVL 34 a §'  → target_id=finlex/.../tuloverolaki-html-9e9b64a4   (LAW root)
   interprets  target_ref='TVL 54 d §'  → target_id=finlex/.../tuloverolaki-html-9e9b64a4   (LAW root)
   ```
   Step 2's resolver couldn't find the §34a / §54d SECTION nodes (they don't exist — TVL has 0 sections) and fell back to the law root. The `target_ref` string still carries the precise citation, but the graph edge is coarse.

## BFS run summaries

Seeds switched from SECTION (no useful edges) to LAW-root because that's where the inbound `interprets`/`cites`/`applies` traffic lives.

### Q32 — PerVL law roots

| seed | hops | variant | total nodes | by edge type |
|------|------|--------|------------:|--------------|
| `finlex/laki/…perinto-ja-lahjaverolaki-html-bd8ad33b` (main) | 1 | A | 3 | parent_of/2 |
| same | 2 | A | 67 | parent_of/66 |
| same | 1 | B | 3 | parent_of/2 |
| same | 2 | B | 67 | parent_of/66 |

A direct `interprets`-IN query against PerVL main and PerVL `laki_skk` returns **zero rows for both**. No Vero guidance / KVL / KHO node in the corpus has an `interprets` edge into PerVL. **defines variant is identical to A — defines doesn't fire here** (PerVL has no DEFINITION nodes with outgoing defines into PerVL).

**Verdict for Q32: FAIL.** Multi-hop expansion would not surface a single Vero source for an inheritance/gift-tax question. The graph offers only `parent_of` neighbours. Either Step 2 missed PerVL-citation extraction entirely, or Vero's PerVL guidance documents weren't in the parsed corpus.

### Q34 — TVL law root

| seed | hops | variant | total nodes | by edge type |
|------|------|--------|------------:|--------------|
| `finlex/laki/…tuloverolaki-html-9e9b64a4` | 1 | A | **500 (cap hit)** | applies/497, parent_of/2 |
| same | 2 | A | 500 (cap hit) | applies/497, parent_of/2 |
| same | 1 | B | 500 (cap hit) | applies/497, parent_of/2 |

`applies`-IN dominates entirely. The 6,934 `interprets`-IN edges into TVL are visible in a direct query but never get explored — BFS's frontier fills with `applies`-IN edges from KHO/KVL case SUBSECTIONs first. Spot-check of the first 20 `interprets`-IN edges: all from KVL (keskusverolautakunta) ennakkoratkaisu case SUBSECTIONs — relevant cross-source nodes are present, but drowned.

**Verdict for Q34: AMBER.** The right neighbours exist (KVL case sections that interpret TVL provisions). Without `applies_in` degree cap and `interprets_in` priority, BFS never reaches them.

### Q35 — AVL law root

| seed | hops | variant | total nodes | by edge type |
|------|------|--------|------------:|--------------|
| `finlex/laki/…arvonlisaverolaki-html-ba5d8e0e` | 1 | A | 500 (cap hit) | applies/497, parent_of/2 |
| same | 2 | A | 500 (cap hit) | applies/497, parent_of/2 |
| same | 1 | B | 500 (cap hit) | applies/497, parent_of/2 |

Same shape as Q34. 3,284 `interprets`-IN edges into AVL exist; they are masked by `applies`-IN flooding.

**Verdict for Q35: AMBER.** Same diagnosis as Q34.

### `defines` test (variant B vs A)

For every seed and every hop count, **variant B was numerically identical to variant A**. From LAW roots, `defines` doesn't fire (defines edges emanate from DEFINITION nodes, not LAW). So **`defines` is not noise from these seeds** — but it also is not contributing signal. Real test of `defines` requires a seed that is or is adjacent to a DEFINITION node; that test is deferred to the full module's strategy router (definition lookup category).

## Three design constraints the full module must respect

These are derived directly from the BFS runs above. Without them, v2 will underperform v1 on most questions.

1. **`applies_in` degree cap is mandatory** (not in the original brief).
   - Threshold: start at **25**. A `applies_in` value above this means the node is being applied-to by many KHO/KVL cases; following all of them is rarely useful for a question that isn't case-law-specific.
   - The brief's existing caps (`interprets_in=30`, `cites_out=15`, `parent_of_in=50`) stay; we are *adding* `applies_in=25`.
   - Also add a per-edge-type frontier-limit (not just per-node degree) so a single edge type cannot exhaust the node budget mid-BFS, as `applies` did in this pilot.

2. **Direction-aware edge allowlists, keyed on seed node type.**
   - From a Finlex LAW or SECTION seed: traverse `interprets`-IN (find guidance), `cites`-OUT (find what it cites), `parent_of`-OUT (drill into subsections). Do **not** traverse `applies`-IN unless the question is recency/precedent-shaped.
   - From a Vero GUIDE / SUBSECTION seed: traverse `cites`-OUT (find statutes), `interprets`-OUT (find what it interprets), `parent_of`-IN (find the parent guide).
   - From a DEFINITION seed: `defines`-OUT (find usage sites), `parent_of`-IN (find the defining section).
   - From a KHO/KVL CASE seed: `applies`-OUT (find statutes applied), `interprets`-OUT (find statutes interpreted).
   - The strategy router (B7.2) becomes the single point where these mappings live.

3. **`max_hops` minimum is 2 for SECTION seeds; 1 is acceptable only for LAW or SUBSECTION seeds.**
   - Reason: SECTIONs have no typed edges (only `parent_of`); you must descend one structural hop before the typed edges become reachable.
   - The strategy config carries `max_hops` per category, but the router should also auto-bump it when the seed type doesn't match the expected edge-bearing type.

## Recommended Step 2 follow-ups (for the Step 2 owner)

These are out of Track F's scope; documenting them so they don't get lost:

1. **PerVL has zero `interprets` edges in.** Investigate whether (a) the corpus contains Vero guidance about PerVL (e.g., the perusteoikaisu kannanotto), and (b) Step 2's extractor recognised PerVL citation forms. If both are true, the loader is dropping these edges silently.
2. **`interprets` resolution falls back to LAW root too aggressively.** When `target_ref` is "TVL 34 a §" and the §34a SECTION exists in the corpus, the edge should target it. Today it targets the LAW root unconditionally. (Mitigated when SECTION nodes don't exist — see point 3.)
3. **Major laws (TVL, AVL) have no SECTION children.** The HTML for the consolidated TVL/AVL didn't expand into the per-section node hierarchy. Step 1's parser may have only treated amendment instruments. Without SECTION nodes, no amount of edge fixing will let v2 retrieve at section granularity.
4. **The brief's edge counts (`cites: 67,834`, `transposes: 8,453`) are wrong by ≥10× / missing entirely** — captured in `our-docs/edge_count_discrepancies.md`.

## Defines verdict

**Default `defines` to OFF in the strategy router**, with one exception: the `definition` category turns it ON. Reasoning:
- From LAW or SECTION seeds, `defines` never fires (no DEFINITION node is the source of those edges from those seeds).
- From a SUBSECTION or ITEM that mentions a defined term, the inbound `defines` edge points to a DEFINITION node — useful, but only when the question is term-definition-shaped.
- The 234k volume of `defines` edges makes "always-on" untenable; per-query degree caps would have to be very tight, defeating the point.

## Go/no-go decision

**GO**, with caveats:

- The graph mechanism is sound — BFS works, edges have the expected types, ordering is sensible.
- The cross-source structure exists where the brief said it should (interprets-IN into AVL/TVL, applies-IN into AVL/TVL from KHO/KVL cases). It just lives at LAW-root granularity, not SECTION.
- The three design constraints above are sufficient to extract usable signal from the existing graph; we do not need Step 2 to be re-run before building Track F's modules.
- **PerVL is a known dead spot.** Inheritance/gift-tax questions (Q32, Q26 medium, Q14 medium) will degrade to vector-only retrieval until Step 2 fixes the PerVL interprets gap. Track F should not block on this — it is one statute among many.

## Next steps (paused for review)

Build order if approved:

1. `findings/07_expansion_strategies.md` — codify the per-category strategy configs (edge-type allowlists, direction, max_hops, caps) discovered above.
2. `src/retrieval/graph_expand.py` — wraps `GraphStore.bfs()` with `ExpansionStrategy` config + adds `applies_in` cap + per-edge-type frontier limit.
3. `src/retrieval/strategy.py` — keyword router → `ExpansionStrategy`. Seed-type-aware (auto-bumps `max_hops` for SECTION seeds).
4. `src/retrieval/cross_encoder_rerank.py` — `BAAI/bge-reranker-v2-m3` wrapper.
5. `tests/test_graph_expand.py` — synthetic-seed unit tests on a tiny in-memory graph (no `output/graph.db` dependency in tests).

**Standing instruction holds: no code in `src/retrieval/` until this writeup is reviewed and approved.**
