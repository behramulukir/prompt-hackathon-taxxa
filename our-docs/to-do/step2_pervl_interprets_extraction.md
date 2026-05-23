# TO-DO — Step 2: Diagnose Zero `interprets`-IN Edges into PerVL

**Owner:** Step 2 (edge extraction)
**Discovered by:** Track F V7.2 pilot, 2026-05-23. See `findings/07_pilot_results.md`.
**Priority:** Medium — affects all inheritance/gift-tax questions in the eval set (Q14, Q26, Q32, Q42, Q45). Doesn't block Track F.

## Problem

```sql
SELECT COUNT(*) FROM edges
WHERE type = 'interprets'
  AND target_id LIKE '%perinto-ja-lahjaverolaki%';
-- returns 0
```

Both PerVL main and PerVL `laki_skk` have **zero inbound `interprets` edges**. For comparison:

| LAW | interprets-IN |
|---|---:|
| TVL    | 6,934 |
| AVL    | 3,284 |
| EVL    | 2,364 |
| Verotusmenettelylaki | 1,057 |
| **PerVL** | **0** |

Yet inheritance/gift-tax is one of the most-litigated parts of Finnish tax law, and Vero publishes multiple kannanotto / syventävä ohje documents about it (perusteoikaisu, lahjaverotus, perukirja, etc.). At least *some* of those should produce `interprets` edges into PerVL.

## Two possible causes (need to disambiguate)

### Cause A — corpus gap (Vero PerVL guidance not in `data/raw/`)

Check whether files like these exist in the Vero ingestion:
- "Perusteoikaisu perintö- ja lahjaverotuksessa" kannanotto
- "Perukirja ja verotus" syventävä ohje
- Any document containing "lahjavero" or "perintövero" in the title

If none exist: this is an ingestion gap, not an extractor gap.

### Cause B — extractor regex missed PerVL citation forms

The Finnish citation conventions for PerVL are:
- `PerVL 18 §`
- `Perintö- ja lahjaverolain 38 §`
- `perintö- ja lahjaverolain (378/1940) 38 §:n 3 momentti`
- `PerVL 38 § 3 mom.`

Compare with TVL forms (`TVL 85 §`, `Tuloverolain 34 a §`) which clearly work — what regex/anchor handling differs for PerVL?

Likely suspects:
- The abbreviation `PerVL` may not be in the extractor's law-abbreviation dictionary.
- The composite form `perintö- ja lahjaverolain` (with hyphen + dash + "ja") may not match a citation pattern designed for single-word law names like `tuloverolain` or `arvonlisäverolain`.

## Verification tasks

1. List Vero documents in the corpus whose title contains `perint`, `lahjavero`, or `lahja-`:
   ```sql
   SELECT id, title FROM nodes
   WHERE source='vero' AND type='GUIDE'
     AND (title LIKE '%perint%' OR title LIKE '%lahja%');
   ```
   Count and inspect — is the corpus carrying these docs?

2. If yes: search the raw text of one of those Vero guides for PerVL citation strings. Did Step 2's extractor see them? Spot-check the LLM extraction prompt with one paragraph.

3. If no: this is Step 1 ingestion's problem, not Step 2's. Re-route.

## Fix tasks (if Cause B)

1. Add `PerVL` to the law-abbreviation dictionary in the extractor.
2. Extend the citation-pattern regex to recognise multi-word law names with internal hyphens and "ja" (broader fix that may help other composite-name laws too: ennakkoperintälaki, kiinteistöverolaki, etc.).
3. Re-run Step 2 on Vero guidance corpus (incremental; only re-extract on Vero subcorpus).
4. Re-load Step 4b graph.

## Cascade impact

- Step 2 re-extract on Vero guidance: ~1 hour (smaller subcorpus).
- Step 4b reload: ~minutes.

## Why Track F isn't doing this

Out of allowed-writes scope (no `src/extraction/`). The pilot found this; the fix needs Step 2's owner.

## Acceptance

PerVL has at least 100 inbound `interprets` edges from Vero guidance nodes after the fix.
