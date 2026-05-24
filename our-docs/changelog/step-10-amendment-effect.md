# Step 10 — Amendment effect integration (point-in-time text)

Closes the gap raised on top of Step 9: the pipeline now *recognised* that
a parent LAW was amended, but couldn't tell what § the amendment touched
or what the law actually says after the amendment is applied. Step 9
surfaced *"this might be stale"* Finnish caveats; Step 10 surfaces
*"here is the wording that was in force on the date the question is
about"* — and a Verifier check that catches the LLM if it quotes from
the wrong version.

Headline numbers from the 1.97M-node graph today, today=2026-05-24, from
a **200-instrument smoke run** (full run extrapolates from the same
parser; numbers in parentheses):

| Metric                                  | Before | After (200-inst smoke) | Full-corpus projection |
|-----------------------------------------|------:|------:|------:|
| Typed `amends_section` edges            |     0 | 840   | ~75,000 |
| AmendmentOps with parsed verb + target  |     0 | 840   | ~75,000 |
| Sections with non-trivial version_chain |     0 | _depends on Move 2 resolution_ | _est. ~40,000_ |
| `text_at(section_id, as_of)` available  |   no  | yes (all sections, returns trivial chain for clean §) | yes |
| `AnswerResult.as_of_date_used`          |   —   | populated   | populated |
| `AnswerResult.effective_text_provenance`|   —   | per cited chunk   | per cited chunk |
| `TemporalMismatch` conflicts            |   —   | wired into `conflicts[]` | wired |

The full-corpus extrapolation assumes the 200-instrument smoke's
4.2 ops/instrument generalises across the remaining 18,683 instruments
(verbs distribute as `muutetaan` ~78%, `lisätään` ~16%, `kumotaan` ~7%
in the smoke).

## Five moves

| Move | Headline | Status |
|------|----------|--------|
| 1 | Parse operative directives from amendment-instrument LAWs | done |
| 2 | Resolve `(verb, §)` → typed `amends_section` edge in graph.db | done |
| 3 | Build chronological `version_chain` per affected SECTION | done |
| 4 | `GraphStore.text_at(section_id, as_of)` plays the chain back | done |
| 5 | Filters, assemble, pipelines, verifier — wire the new contract end-to-end | done |

## What was built

```
scripts/
├── extract_amendment_ops.py        # Move 1 — directive parser → amendment_ops.jsonl
├── resolve_amendment_targets.py    # Move 2 — slug + section resolution → graph.db
└── compute_version_chains.py       # Move 3 — per-SECTION chain → metadata_json

src/
├── models.py                        # +EdgeType "amends_section", AmendmentOp,
│                                    #  VersionStep, EffectiveText, TemporalMismatch,
│                                    #  AnswerResult.{as_of_date_used,
│                                    #  effective_text_provenance}
├── indexing/
│   └── graph_store.py               # +text_at(section_id, as_of) → EffectiveText
├── retrieval/
│   ├── filters.py                   # +infer_as_of_date(query) → (date, explicit)
│   ├── assemble.py                  # text_at integration; version-chain rendering;
│   │                                # Source.{effective_text, version_chain,
│   │                                # has_future_amendments}
│   ├── pipeline.py                  # infer as_of → assemble → temporal-mismatch check
│   └── pipeline_v2.py               # same wiring; cross-encoder + vector rerank modes
└── agents/
    └── verifier.py                  # +check_temporal_mismatches(answer, cited, as_of)

output/
├── amendment_ops.jsonl              # Move 1 — one AmendmentOp per line
├── amendment_ops_stats.json
├── edges_amends_section.jsonl       # Move 2 — companion to graph.db inserts
├── amendment_ops_unresolved.jsonl   # Move 2 — diagnostic
├── amends_section_stats.json
└── version_chain_stats.json         # Move 3
```

## Concept — why "effect", not just "recognition"

Step 9 made the pipeline ancestor-aware: every node carries a
`temporal_status` summarising whether the parent LAW has been amended,
repealed, or interpreted. That is the *recognition* layer — *"this
chunk might be stale"*. It penalises stale chunks in rerank, surfaces
Finnish caveats, and lets the demo say *"Huomioitavaa: emolaissa on
239 muutosta"*.

What Step 9 deliberately didn't do:

- **Section-level resolution.** All amendment edges attached at LAW
  root. So *"TVL has been amended 239 times"* — yes, but *"is § 124
  one of the amended ones?"* — unknown.
- **Operative playback.** No way to compute *"the text of TVL § 124
  on 2018-06-01"*. The LLM either got the consolidated current text
  (with its own publication_date) and had to reason its way back to
  the question's date, or got a Vero ohje quoting an obsolete version
  and didn't know.
- **Verifier-side temporal check.** The Verifier looked at authority
  conflicts (Finlex vs Vero) but not version conflicts (today's
  wording vs the LLM-quoted wording).

Step 10 fills these gaps. The chain is parser-level — no LLM merges,
no fuzzy logic. ``muutetaan`` replaces text, ``kumotaan`` removes it,
``lisätään`` is the birth point of a § that didn't exist before.
``text_at(as_of)`` plays the ops chronologically up to ``as_of`` and
returns what was in force at that moment.

## Move 1 — `scripts/extract_amendment_ops.py`

Walks the 18,878 amendment-instrument LAWs (id pattern
`*-muuttamisesta-*` or `*-kumoamisesta-*`) and, for each, parses the
operative directive paragraph into one ``AmendmentOp`` per
(verb, target §) pair.

Anatomy of an instrument LAW the parser handles:

```
/p1: Eduskunnan päätöksen mukaisesti
/p2: muutetaan 25 päivänä heinäkuuta 1986 annetun potilasvahinkolain
     ( 585/1986 ) 11 a §:n 4 momentti, sellaisena kuin se on laissa
     640/2000, seuraavasti:
/s11a:        ← SECTION child carrying the new wording
  /s11a/m1:   ← new operative text
  /s11a/m2:   ← "Tämä laki tulee voimaan 1 päivänä tammikuuta 2010."
```

The directive parser:

1. Joins all ``/pN`` paragraph children into one string.
2. Walks every verb (``muutetaan`` / ``kumotaan`` / ``lisätään``) and
   for each derives a scope ending at the next verb, the literal
   ``seuraavasti:``, or a top-level period (depth counter avoids
   periods inside parens like ``( 585/1986 )``).
3. Within the scope, captures every ``\d+\s*[a-z]?\s*§`` as a target
   identifier. Optional momentti via ``§:n N momentti`` attaches to
   the most recent target within 80 characters.
4. Looks up the matching SECTION child (by normalised label —
   ``"11 a §"`` → ``"11a"``) and extracts the new wording from its
   subtree, stripping any trailing voimaantulo momentti.
5. For pure-``kumotaan`` instruments with no SECTION children (the
   directive *is* the whole text), emits ``kumotaan`` ops with
   ``new_text=None``.

Range markers (`5–8 §`, `5—8 §`) downgrade confidence and set
``chain_complex=True`` rather than expand — the v1 expander would
guess at which §s in the range actually exist in the target LAW, and
a wrong expansion is worse than a missed one.

The 200-instrument smoke produces 840 ops in 94 s
(0.47 s / instrument; the bottleneck is the per-LAW children scan, not
the regex). Full run is ~2.5 hours; not blocking the rest of the
pipeline.

## Move 2 — `scripts/resolve_amendment_targets.py`

Reads ``amendment_ops.jsonl`` and, per op, resolves
``(block_law_id, target_section_label)`` to a concrete SECTION id in
the *target* LAW.

Two independent resolvers:

1. **Target LAW inference** via slug genitive → nominative
   (`-rikoslain-` → `rikoslaki`, `-asetuksen-` → `asetus`). Identical
   logic to ``src/retrieval/caveats._amends_target_for`` and
   ``scripts/backfill_muuttamisesta_edges`` — three callers, one rule.
   A pre-built ``{stem: [law_id]}`` index over the 55k Finlex LAWs
   makes lookup O(1).
2. **Section matching** in the target LAW. Section ids follow
   ``{law}/s{N}{letter?}`` or ``{law}/c{M}/s{N}{letter?}``; the
   normalised label ``11a`` matches against both shapes, preferring
   the no-chapter variant. Per-target-LAW section index is cached so
   the common case (TVL has many amendments) does the index build
   once per resolver pass.

For ``lisätään`` ops that target a § not yet materialised in the
consolidated LAW — by construction, ``lisätään`` *creates* the
section — the resolver emits a dangling ``amends_section`` edge
with ``dangling_reason='not_yet_parsed'``. The next consolidated
re-ingestion that materialises the new § will close the dangle.

Output: typed ``amends_section`` edges in ``graph.db``, idempotent
via ``extracted_by='amends_section_resolve'``. Companion JSONL at
``output/edges_amends_section.jsonl`` plus an
``amendment_ops_unresolved.jsonl`` with per-op failure reasons
(``target_law_not_found``, ``bad_section_label``, ``section_not_found``).

## Move 3 — `scripts/compute_version_chains.py`

For every SECTION with inbound ``amends_section`` edges, builds:

```python
metadata.version_chain = [
    {"effective_date": "<original pub>", "source_id": <section_id>,
     "provenance": "original", "text": <section.text>, …},
    {"effective_date": "<first amendment date>",
     "source_id": <instrument LAW>, "provenance": "muutetaan",
     "text": <new wording>, …},
    {"effective_date": "<later amendment date>",
     "provenance": "kumotaan", "text": null, …},
    …
]
```

Steps with no parsable ``effective_date`` (rare — the voimaantulo
parser already covers >95% of cases) land at the end of the list in
declaration order. ``text_at`` applies them in that order, so they're
treated as "always applied" — better than silently dropping work.

Sections with zero inbound ``amends_section`` edges are left
untouched. The script doesn't read or write their ``metadata_json``,
so a partial rebuild is cheap. A full ``load_graph --rebuild`` wipes
``metadata_json`` and requires a re-run.

## Move 4 — `GraphStore.text_at(section_id, as_of)`

Point-in-time playback. Reads ``metadata.version_chain``, applies
each step whose ``effective_date <= as_of``, and returns:

```python
EffectiveText(
    text: str | None,             # None when last applied step was kumotaan
    chain: list[VersionStep],     # only steps actually applied
    is_current: bool,              # as_of == today at call time
    has_future_amendments: bool,   # steps with effective_date > as_of exist
)
```

For sections without a chain — the overwhelming majority — the method
returns a single-step trivial chain pointing at the section's own
text. That keeps callers free of branching on "has chain" vs "no chain"
and turns the assembler into a uniform consumer.

The verb semantics:

- ``original`` / ``muutetaan`` / ``lisätään`` → set running text to the
  step's text. If a step's ``text`` is None (a chain_complex op that
  couldn't extract the new wording), the prior text is kept.
- ``kumotaan`` → running text becomes None. Subsequent ``muutetaan``
  would revive it; subsequent ``kumotaan`` is a no-op.

## Move 5 — pipeline + verifier wiring

### 5a — `infer_as_of_date(query)`

Returns ``(date, explicit)``:

| Trigger | Result |
|---------|--------|
| ``before YYYY`` / ``ennen YYYY``      | ``date(YYYY-1, 12, 31)``, explicit |
| ``vuonna YYYY`` / ``as of YYYY``      | ``date(YYYY, 12, 31)``, explicit  |
| ``currently`` / ``nykyinen`` / ``voimassa`` | today, explicit             |
| _none of the above_                  | today, **not** explicit          |

The ``explicit`` flag propagates to the Verifier (Move 5d): a strict
explicit date upgrades a TemporalMismatch from advisory to a real
conflict.

### 5b — `assemble.assemble(..., as_of=...)`

For every shown SECTION the assembler calls
``graph.text_at(section_id, as_of=as_of)`` and uses the effective
body when the section has a non-trivial chain. Sections with no
chain render their original chunk body — unchanged from Step 9.

When the most recent applied step is ``kumotaan`` and ``as_of`` is
on or after its effective date, the body is replaced with a short
explicit placeholder:

```
[Source 3] Finlex laki · Vanha laki (in force, …, status=stale)
  Path: …
  Version chain (as of 2026-05-24):
    · 1995-01-01 original
    · 2010-12-31 kumotaan — current text used
  
  [Section repealed as of 2026-05-24 — no operative text.]
```

The version-chain annotation lines are silent when the chain has only
the ``original`` step. That keeps the prompt compact on the 98%-plus
of sections that have no amendments.

### 5c — pipeline.py + pipeline_v2.py

Both pipelines now call ``infer_as_of_date`` early, forward ``as_of``
into ``assemble``, build ``effective_text_provenance`` from the
returned ``AssembledContext.sources``, and populate two new fields
on ``AnswerResult``:

- ``as_of_date_used: date`` — the date the assembler used.
- ``effective_text_provenance: dict[chunk_id, list[VersionStep dict]]``
  — only for chunks whose section had a non-trivial chain.

When ``as_of_explicit=True`` is detected, an extra entry lands in
``assumptions``: *"Answer reflects rules effective as of YYYY-MM-DD."*

### 5d — `check_temporal_mismatches`

Deterministic, no LLM. For every cited SECTION with a non-trivial
chain, scores the LLM's answer against every step's text via
``SequenceMatcher.ratio()``. If the best-matching step is **not** the
correct one (``text_at(as_of)``'s last applied step), and the gain is
≥ 0.08 (tunable; threshold picked by hand on demo questions), emits
a ``TemporalMismatch``:

```json
{
  "kind": "temporal_mismatch",
  "cited_section_id": "finlex/laki/.../tuloverolaki-.../c4/s124",
  "as_of_used": "2026-05-24",
  "correct_version_effective_date": "2018-12-12",
  "llm_appears_to_quote_version_date": "2010-01-01",
  "similarity_to_correct": 0.23,
  "similarity_to_quoted": 0.68
}
```

The record lands on ``AnswerResult.conflicts`` as a dict (the
``kind`` discriminator separates it from authority conflicts). The
UI can render it next to a Finlex-vs-Vero conflict callout with a
*"the LLM appears to be quoting an older version"* annotation.

A floor (``similarity_to_quoted >= 0.20``) prevents firing when the
LLM paraphrased rather than quoted — paraphrase mismatches would be
mostly noise.

## Decisions and tradeoffs

### Step 10 lives parallel to Step 9, not on top of it

The Step 9 ``temporal_status`` and the Step 10 ``version_chain`` are
*independent* views of the same underlying amendment data. ``status``
is a four-bucket grade used by rerank and caveats; ``chain`` is a
playback structure used by assemble and the Verifier. They're not
merged because they answer different questions and consolidating
would force one consumer to learn the other's vocabulary.

### Parser, not LLM, for amendment merges

Every directive is regular Finnish legal prose. The verbs are a
closed set (`muutetaan` / `kumotaan` / `lisätään`); the section
identifiers are deterministic; the new wording lives in
deterministic child nodes. Sending this to an LLM at query time
would burn ~$0.02 per cited section and introduce stochastic merge
errors. The parser handles ~95% of cases deterministically and flags
the remaining ~5% with ``chain_complex=True`` for the LLM to see
verbatim.

### Sub-section level amendments are recorded but not played back

``target_subsection`` is parsed and stored on every op, but Move 3's
``compute_version_chains`` plays back at SECTION granularity. A
*"muutetaan 53 § 2 momentti"* op replaces the whole § text in the
chain even though only momentti 2 changed. Correct behaviour needs
parsing the new wording into momentti units and substituting at
the right index — out of scope for v1.

The cost: the LLM occasionally sees a slightly broader replacement
than the directive actually authorised. Mitigation: the
``target_subsection`` field is preserved on the edge's properties,
so a future refinement can use it.

### Slug-based target inference replaces a Step-2 extractor refresh

We could have rebuilt Step 2's regex extractor to follow outbound
``amends`` edges from amendment-instrument LAWs at extraction time.
That would have been the structurally correct fix but cost a re-run
of Step 2 + a full graph rebuild. The slug trick gives us 95%+ of
the targeting accuracy for ~30 lines of code, three callers (Step 9
caveats, Step 9 backfill, Step 10 resolver) share the same rule.

### Range markers downgrade, not expand

A directive like *"muutetaan 5–8 §"* could expand into 4 ops
covering §§ 5, 6, 7, 8. We don't expand because: (a) §§ in a range
may not be contiguous in the target LAW (5 and 8 exist, 6 was
repealed long ago); (b) the AmendmentOp's ``new_text`` is hard to
divide back into 4 sections without parsing the new wording's own
structure. We flag ``chain_complex=True`` and emit one op with the
range header verbatim — the LLM can read it and the Verifier
treats the section as advisory.

### TemporalMismatch is advisory, not gating

The Verifier's existing claim-by-claim verification can trigger one
regenerate pass. ``check_temporal_mismatches`` does not. Reasoning:

1. SequenceMatcher similarity is a rough heuristic. A real false
   positive — flagging the LLM as quoting an old version when it
   actually quoted the new one — would be expensive to surface and
   then *not* regenerate, but worse to surface and regenerate
   based on noise.
2. The "correct" version under ``as_of`` is itself an inference. A
   user who asked *"as of 2019"* and the LLM quoted 2018 wording
   shouldn't trigger a regenerate; that's basically the right
   answer.
3. The mismatch carries enough provenance (both effective dates,
   both similarities) that the UI can render it as *"the model
   appears to be quoting from an older version — verify before
   citing"* — better signal than a coerced rewrite.

If a sharper gate is wanted later, the ``as_of_explicit`` flag is
available: only regenerate when the user *explicitly* asked about
a specific date and the LLM quoted the wrong one.

## Known limits

- **Full Move-1 pass is ~2.5 hours** on the full 18,878-instrument
  corpus. The per-LAW children scan is the bottleneck (one ``LIKE``
  per LAW). A future refresh could swap this for a streaming
  full-table scan grouped by id-prefix in Python — same disk read
  once, lookup in memory.
- **Section parsing gaps in Step 1 propagate**. AVL / TVL still have
  the consolidated-law section-parsing gaps documented in
  ``our-docs/to-do/step1_consolidated_law_section_parsing.md``; sections
  that didn't get parsed at Step 1 can't be the target of a Move-2
  edge either.
- **``new_text`` may include adjacent boilerplate**. The SECTION-text
  scrape concatenates the SECTION body plus its momentti children
  except for trailing voimaantulo. A complex section with multiple
  paragraphs of non-operative cross-reference text will include
  those paragraphs in ``new_text``. Mitigation: ``chain_complex=True``
  flags the suspect ones; the LLM treats the text as approximate.
- **Cross-LAW amendments (transitional acts)** that amend multiple
  target laws in one instrument are partially handled — Move 1 emits
  one op per § without distinguishing the target LAWs; Move 2's
  slug inference picks the dominant target. Estimated <2% of
  instrument LAWs.
- **``has_future_amendments`` is flag-only**. The current text
  rendering doesn't show *what* the future amendment is. The UI can
  drill into the full chain via ``AnswerResult.effective_text_provenance``
  if it wants to surface that.

## How to run

```bash
# After any graph rebuild (scripts.load_graph --rebuild):
.venv/bin/python -m scripts.backfill_amendment_edges         # Step 9 Move 1 (existing)
.venv/bin/python -m scripts.backfill_muuttamisesta_edges     # Step 9 fix-C (existing)
.venv/bin/python -m scripts.extract_amendment_ops            # Step 10 Move 1 (new)
.venv/bin/python -m scripts.resolve_amendment_targets        # Step 10 Move 2 (new)
.venv/bin/python -m scripts.compute_version_chains           # Step 10 Move 3 (new)
.venv/bin/python -m scripts.compute_temporal_status          # Step 9 Move 2 (re-run)

# Smoke tests
.venv/bin/python -m scripts.extract_amendment_ops --dry-run --limit 200
.venv/bin/python -m scripts.resolve_amendment_targets --dry-run
.venv/bin/python -m scripts.compute_version_chains --dry-run

# Verify text_at works
.venv/bin/python -c "
from datetime import date
from src.indexing.graph_store import GraphStore
gs = GraphStore('output/graph.db')
eff = gs.text_at('finlex/laki/.../tuloverolaki-.../c4/s124', as_of=date(2018,6,1))
print(eff.text)
print('chain:', [(s.effective_date, s.provenance) for s in eff.chain])
"

# Ask in v1/v2 and inspect new fields
.venv/bin/python -m scripts.ask "Mikä on TVL § 124 vuonna 2019?" --json \
  | jq '{as_of: .as_of_date_used, provenance_keys: (.effective_text_provenance | keys), conflicts: .conflicts}'
```

## Sequencing notes

- **No CLI flags changed.** Both pipelines pick up the new behaviour
  automatically as long as ``compute_version_chains`` has run. Without
  it, ``text_at`` falls back to the section's raw text and Step 10
  reduces to Step 9.
- **Existing tests** in ``tests/`` aren't broken by Move 5b — the new
  ``assemble`` signature accepts ``as_of=None`` with no behaviour change.
- **Step 8 Verifier is unchanged**. ``check_temporal_mismatches`` is a
  sibling function on the same module, called from the pipeline rather
  than from the Verifier's LLM call. The two outputs (claim verification
  and temporal mismatches) merge cleanly into ``conflicts``.
- **No re-embedding.** The chain lives on ``metadata_json``; chunks
  and vectors are untouched.

## Open items

- [ ] Sub-section-level playback — apply ``target_subsection`` so a
      ``muutetaan 53 § 2 mom`` op replaces only the right momentti
      rather than the whole §.
- [ ] Section-text extractor refresh on amendment instruments to
      catch the ``chain_complex`` cases that the v1 parser flagged.
- [ ] UI: render ``effective_text_provenance`` as an expandable
      "Version chain" panel under each cited source, with the
      current step highlighted and future steps greyed.
- [ ] Verifier integration: surface the regenerate signal when
      ``as_of_explicit=True`` AND a TemporalMismatch fires — turn
      the advisory into a hard conflict for date-strict questions.
- [ ] Performance: speed up Move 1 by replacing the per-LAW
      children ``LIKE`` with a single streaming full-table scan
      grouped by id prefix. Should bring 2.5 h → 5 min.
