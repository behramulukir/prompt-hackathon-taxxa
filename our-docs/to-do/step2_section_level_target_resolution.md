# TO-DO — Step 2: `interprets` Falls Back to LAW Root When SECTION Exists

**Owner:** Step 2 (edge extraction, specifically target-id resolution)
**Discovered by:** Track F V7.2 pilot, 2026-05-23. See `findings/07_pilot_results.md`.
**Priority:** Medium — bounded by `step1_consolidated_law_section_parsing.md`. Only worth fixing once Step 1 produces the SECTION nodes to resolve into.

## Problem

Spot-check from a high-degree Vero guidance SUBSECTION (`0a3be5bd/c4/s4-3/pmisc-1`):

```
edge_type   target_ref      target_id
interprets  'TVL 34 a §'    finlex/laki/finlex-laki-tuloverolaki-html-9e9b64a4   (LAW root)
interprets  'TVL 34 b §'    finlex/laki/finlex-laki-tuloverolaki-html-9e9b64a4   (LAW root)
interprets  'TVL 54 d §'    finlex/laki/finlex-laki-tuloverolaki-html-9e9b64a4   (LAW root)
```

`target_ref` preserves the precise section reference, but `target_id` resolves to the LAW root in every case. The aggregate counts confirm this is universal:

| edge type | target = LAW | target = SECTION |
|---|---:|---:|
| interprets | 14,412 | 263 |
| cites      | 2,939  | 577 |

Section-level resolution is the exception, not the rule.

## Why it matters

When v2 walks `interprets`-IN from a statute seed, *every* result is "some guidance interprets the entire law" rather than "some guidance interprets §34a specifically." The graph effectively flattens section-level structure into law-level structure for cross-source traversal.

For questions about specific sections (most hard-tier ones), this means:
- Retrieval can find that *some* guidance interprets TVL, but not *which sections* it focuses on.
- The LLM has to re-read all returned guidance to figure out which one is relevant.
- The cross-encoder reranker partially compensates but doesn't fully recover the lost specificity.

## Hypothesis on cause

The resolver tries (in order):
1. Exact match of `target_ref` → existing node id.
2. Fall back to LAW root if no SECTION-level match.

Step (2) fires unconditionally when SECTION nodes are missing — which is true for almost all of TVL (0 SECTIONs in corpus) and most of AVL.

## Why this is gated by Step 1

If TVL has 0 SECTIONs in `output/nodes.jsonl`, there's nothing for the resolver to target. **Don't fix this in isolation; fix it after `step1_consolidated_law_section_parsing.md` lands.** Otherwise step (1) of the resolver always misses and step (2) always fires.

## Fix tasks (after Step 1 fix)

1. Add a verification check in the resolver: when target_ref names a specific section AND the SECTION node exists, resolve to it. When the SECTION doesn't exist, log a `dangling_reason='not_yet_parsed'` rather than silently resolving to LAW.
2. Decide whether existing law-root edges should be re-resolved (probably yes; one-pass re-walk over `edges.jsonl`).
3. After re-resolution, re-load Step 4b graph.

## Stretch goal — preserve coarse-grained edges too

Some downstream queries genuinely want "what guidance is about this law overall" rather than "what guidance interprets §85 specifically." Consider emitting both:
- `interprets target_id=<SECTION>` (specific)
- `interprets target_id=<LAW>` (coarse, with `properties.coarse=true`)

Or accept that walking `parent_of`-IN from a SECTION's interprets-IN sources implicitly recovers the law-level set.

## Acceptance

- Spot-check the same `0a3be5bd/c4/s4-3/pmisc-1` SUBSECTION: its `TVL 34 a §` `interprets` edge now targets a `…/tuloverolaki/s34a` (or similar) SECTION node.
- Aggregate: `interprets target.type=SECTION` count rises from 263 to at least 5,000.
