# TO-DO — Step 1: Re-parse Consolidated Laws to Recover SECTION Coverage

**Owner:** Step 1 (ingestion / HTML parsing)
**Discovered by:** Track F V7.2 pilot, 2026-05-23. See `findings/07_pilot_results.md`.
**Priority:** High — blocks SECTION-level retrieval for major statutes.

## Problem

Several of the most important Finnish tax statutes appear in `output/graph.db` as LAW roots with **no SECTION children**, or with only one chapter's worth:

| Statute | Status |
|---|---|
| **TVL** (`tuloverolaki`, income tax) | LAW exists, **0 SECTIONs**. Same in `laki_skk`. |
| **AVL** (`arvonlisaverolaki`, VAT) | LAW exists, **0 SECTIONs** in main. `laki_skk` consolidated copy has **only §222–237** (chapter 23). |
| **PerVL** (`perintö- ja lahjaverolaki`, inheritance & gift) | Main `laki/`: only AMENDMENT_BLOCKs. `laki_skk`: has §38+ (this one is OK). |

Because typed edges (`cites`, `interprets`, `applies`) that name a section (e.g. "TVL §85", "AVL §117") cannot resolve to a SECTION node that doesn't exist, they fall back to the LAW root. This collapses all section-level cross-references into law-level edges — coarse and undifferentiated.

## Hypothesis on cause

The Step 1 parser likely processed *amendment instruments* (HTML files whose URLs match `…/laki/laki-…-muuttamisesta-…`) but didn't process or didn't structurally expand the *consolidated current-version* HTML for TVL and AVL. The PerVL skk version did parse correctly, so the parser CAN handle consolidated HTML — it just may not have been pointed at the right files for TVL/AVL.

## Verification tasks (cheap)

1. Check `data/raw/finlex/Laki/` (or wherever Finlex raw HTML lives) for files matching `Tuloverolaki*.html` and `Arvonlisäverolaki*.html` (consolidated versions, no "muuttamisesta" suffix).
2. If those files exist: open one and confirm whether the HTML has the section structure (e.g. `<a id="…" data-section="85">` or whatever Step 1's parser recognises).
3. Spot-count: do these consolidated HTML files have ~250 `§` markers each? (TVL has roughly 250 sections; AVL roughly 230.)

## Fix tasks

1. Add the consolidated TVL/AVL HTML files to the Step 1 input list (if not already there).
2. If the parser breaks on them (different DOM than amendment instruments), extend the parser.
3. Re-run Step 1 for those laws only — incremental, not a full corpus re-parse.
4. Append the new nodes to `output/nodes.jsonl` / `output/chunks.jsonl`. Step 3 needs to enrich the new nodes; Step 2 needs to re-run citation extraction so the new SECTION ids become resolvable targets; Step 4b re-loads.

## Cascade impact

- Step 2 re-extract (or at minimum re-resolve): hours.
- Step 4a re-embed of new SECTION chunks: minutes (it's incremental — chunks are deduped by chunk_id).
- Step 4b graph re-load: minutes.

This is feasible but not trivial. Don't start mid-hackathon unless the consolidated HTML is already in `data/raw/`.

## Why Track F isn't doing this

Outside Track F's allowed-writes scope (no `src/parsing/`, no `scripts/`). Also outside its read scope of `data/raw/`. Logged for the Step 1 owner.

## Acceptance

- `SELECT COUNT(*) FROM nodes WHERE type='SECTION' AND id LIKE '%tuloverolaki%';` returns ~250.
- `SELECT COUNT(*) FROM nodes WHERE type='SECTION' AND id LIKE '%arvonlisaverolaki%';` returns ~230.
- Re-running V7.2 pilot with a TVL §85 seed produces direct typed-edge neighbors.
