# Demo question picks — Track G

Three questions from `eval/questions.json` preloaded in the UI dropdown.
They cover one basic, one medium, and one hard tier; the trio is designed so
the live demo arc moves from "here's a clean fact" → "here's a cross-source
nuance" → "here's where GraphRAG actually earns its keep."

Each pick is hand-crafted into a deterministic `AnswerResult` in
`web/data/demo_overrides.py`, with **real chunk IDs** sourced from
`output/chunks.jsonl` via `web/data/build_source_meta.py`.

---

## Q1 · Basic — Capital income tax rate above €30k

> "What is the capital income tax rate (pääomatulovero) applicable to the
> portion of capital income that exceeds 30,000 euros in a tax year?"

**Why it leads the demo.** Single statute, single citation, no conflict, no
assumption — the simplest possible request. It proves the baseline pipeline
works end-to-end and gives the audience a calibration point for what
"simple" looks like before the next two questions escalate. The cinematic on
this question is intentionally short (~2.5 s) — only the Retriever row
activates, no Verifier moment.

**Expected reasoning path.** Vector hit on TVL § 124 (capital income tax
brackets). No graph expansion — the answer is fully present in the seed
chunk.

**Real chunk used.**
- `[Source 1]` Finlex · Laki tuloverolain muuttamisesta — **§ 124** ·
  *Veron määräytyminen* (rank 100, binding)

**Choreography beats.** Strategy badge → "Single-hop". Retriever row
activates. Seed node pulses, no edges drawn. Memo renders one paragraph and
one citation pill.

---

## Q12 · Medium — Meal voucher VAT deduction (cross-source)

> "A company purchases electronic meal vouchers through a third-party
> voucher platform (app) for its employees… Can the company claim a VAT
> deduction on the invoice? How does the answer change if the company
> instead contracts directly with a restaurant for catering services?"

**Why it's the middle slot.** It exercises **cross-source retrieval** —
the answer requires (a) the binding KHO precedent KHO:2025:46, (b) the
underlying KVL ennakkoratkaisu KVL:004/2024 that KHO confirmed, and (c) the
Vero guidance *Henkilöstöruokailun arvonlisäverotuksesta* that operationalises
the rule. The Clarifier surfaces an assumption (Finnish VAT-registered
employer, tax year 2026). No authority-rank conflict — KHO and Vero
guidance are aligned post-2025 — so the Verifier row stays dark and the
demo viewer can see the difference between "agents collaborated" and
"agents disagreed."

**Expected reasoning path.** Vector hit on KHO:2025:46. Graph walk along
`cites` to KVL:004/2024 (the case KHO ruled on), and `interprets` to the
Vero guidance section 5 (deductions for direct catering). Extractor writes
one new `interprets` edge back to the graph.

**Real chunks used.**
- `[Source 1]` Finlex · KHO — **KHO 2025:46** (rank 85, binding)
- `[Source 2]` Vero · KVL — **KVL:004/2024** (rank 50, interpretive)
- `[Source 3]` Vero · Ohje — *Henkilöstöruokailun ALV* § 5 (rank 60, interpretive)

**Choreography beats.** Strategy badge flips to "Multi-hop". Assumption
chip slides into the memo. Clarifier + Planner + Retriever + Extractor all
activate. Memo renders two paragraphs separated by the structural distinction
between the voucher case and the direct-catering case.

---

## Q41 · Hard — Avainhenkilö specialist's expired tax card (conflict)

> "A Finnish employer obtained key personnel (avainhenkilö) tax status for
> a foreign specialist (Dr. Chen) in Jan 2022. He has been taxed at 32%
> withholding since then. In Jan 2026 the 48-month tax card expires.
> Payroll fails to notice and continues 32% withholding for Jan-Apr 2026…
> (a) progressive rate from Jan 2026? (b) correction procedure? (c) can he
> apply for a new key personnel card after acquiring Finnish residency?"

**Why it closes the demo — the showpiece.** Three things happen here that
none of the other questions exercise:

1. **Temporal reasoning across two statutes** — the 2025 amendment to the
   avainhenkilölaki extended the validity period from 48 to **84 months**,
   so the chunk dated 2025 contradicts the older Vero kannanotto from 2020.
2. **An authority-rank conflict** — the binding statute (Finlex, rank 100)
   says 84 months; the interpretive Vero kannanotto (rank 55) still
   references the older 48-month cap. The Verifier surfaces this and
   resolves it via `authority_rank`. **This is the V3.2 moment.**
3. **Multi-hop reasoning** — three retrieval paths (one vector seed, two
   `interprets` neighbours, one `parent_of` second-hop expansion).

**Expected reasoning path.** Vector hit on Avainhenkilölaki § 2 (the
amendment chunk). Graph walks `interprets` to the Vero kannanotto background
and the Vero deepening guidance; `parent_of` to the kannanotto's section
sibling. Extractor writes a new `interprets` edge from kannanotto →
statute § 2. Verifier compares ranks: Finlex 100 > Vero 55 → statute prevails.

**Real chunks used.**
- `[Source 1]` Finlex · Laki ulkomailta tulevan palkansaajan lähdeverosta —
  **§ 2** (84-month amendment) (rank 100, binding)
- `[Source 2]` Vero · Kannanotto — *Avainhenkilöltä perittävä lähdevero
  vuodesta 2020 alkaen · Taustaa* (rank 55, interpretive)
- `[Source 3]` Vero · Ohje — *Avainhenkilöiden verotus § 2.1* (rank 60, interpretive)
- (Retrieved-only, not cited) Vero · Kannanotto · *Kannanotto* section (the
  rule-statement sibling of [Source 2])

**Choreography beats.** Full pipeline runs. Strategy badge → "Multi-hop".
Assumption chip with 3 lines (residency, salary, no treaty). Conflict
callout slides in between the (a) and (b) paragraphs of the memo, surfacing
the 84-vs-48-month divergence and stating the resolution rule explicitly:
*"Finlex statute (rank 100, binding) prevails over Vero kannanotto
(rank 55, interpretive)."* Edges-added counter ticks 0 → 1, conflicts
counter ticks 0 → 1.

---

## Why not the other obvious candidates

- **Q16** (company car vs own car commuting) — almost identical structure
  to Q3, both single-source Vero rate lookups. Less narratively rich than
  Q12's KHO/KVL/Ohje triangle.
- **Q35** (sole proprietorship VAT threshold) — exercises a similar
  conflict shape to Q41 (old kannanotto vs current law), but the avainhenkilö
  scenario is more legible to a non-Finnish audience and the personal-
  story framing of "Dr. Chen" reads better on stage than "Pekka's IT
  consulting + educational training."
- **Q32** (inheritance tax correction) — strong procedural multi-step but
  no authority-rank conflict; doesn't exercise the Verifier.

## When the real pipeline ships

The override layer (`USE_DEMO_OVERRIDES = True` in `web/app.py`) stays in
place as long as we want stage-demo reliability. To run the full pipeline
end-to-end on these three questions, flip the flag to `False` and the
dispatch falls through to `ANSWER_FN(question)`. Useful for catching
divergences between the curated answer and what the real system produces.
