# Step 8 — Agent Prompt Calibration (Track H)

**Status:** Code shipped. Prompt calibration pending live-LLM runs.

This document is the agreed shape of the calibration report. Each agent
section has three slots for working test cases (`PASS_1..3`) and 1–2 slots
for failures / marginal cases (`FAIL_*`). The slots are filled after the
first live run (`FEATHERLESS_API_KEY=... pytest tests/test_agent_prompts.py -v`).

Per Step 8 brief:
> Honest reporting beats inflated claims.

If an agent never produces a marginal/failing case across the full suite,
that itself is a finding worth noting — usually it means the test set
isn't adversarial enough yet.

---

## Configuration

| Setting | Value |
|---|---|
| LLM provider | Featherless (OpenAI-compatible HTTP) |
| Default model | `deepseek-ai/DeepSeek-V3` (per-file `MODEL = ...`, override per agent if needed) |
| Temperature | 0.0 |
| Response format | JSON object (provider-side, plus forgiving fallback parser) |
| Per-agent prompt budget | 2 (Clarifier) / 3 (Planner) / 3 (Verifier) / 2 (Extractor) |

All four agents share `src/agents/_llm.py` — a pure-stdlib HTTP wrapper
that reads `FEATHERLESS_API_KEY`, `FEATHERLESS_BASE_URL`, `AGENT_MODEL`
from env.

---

## Clarifier

**Job.** Detect missing context dimensions (year / entity_type / jurisdiction) in a Finnish tax question; fill with safe defaults in batch mode, ask back in interactive mode.

**Test set.** 10 medium-tier questions from `eval/questions.json`, each with one dimension intentionally dropped. The Clarifier passes if the dropped dimension appears in `result.missing` AND a default for it appears in `result.assumptions`.

### PASS_1 — TBD
### PASS_2 — TBD
### PASS_3 — TBD
### FAIL_1 — TBD

**Known calibration risk.** Questions like Q21 (TyEL for a 67-year-old) hint at "current rules" without naming a year. If Clarifier over-reads context it may decide year is *not* missing. The prompt explicitly tells it that "current rules" still requires a year assumption.

---

## Planner

**Job.** Decompose compound Finnish-tax questions into 1–4 sub-questions tagged with retrieval-strategy categories. Pass-through atomic questions unchanged.

**Test set.** 10 hard-tier questions (`Q32, Q34, Q35, Q38, Q40, Q41, Q44, Q45, Q49, Q50`) with explicit `(a)/(b)/(c)` structure. Pass if `1 ≤ |sub_questions| ≤ 4` and the question is flagged compound. Plus one negative — a single-fact VAT-rate question that must pass through as `category=single, is_compound=false`.

### PASS_1 — TBD
### PASS_2 — TBD
### PASS_3 — TBD
### FAIL_1 — TBD

**Known calibration risk.** Q49 has four sub-parts (a/b/c/d). The 4-question cap is exactly enough — but if the Planner merges or over-splits, this will fail. Q44 has interleaved tax-period reasoning that may resist clean decomposition. If multiple cases fail, the fix is to add an explicit "merge sibling sub-parts that share the same statute" instruction.

---

## Verifier

**Job.** For each claim in a draft answer, check supporting and contradicting sources; surface conflicts and pick the prevailing source by `authority_rank` (Finlex=100 > Vero=60). `authority_rank` is an EXPLICIT input — never inferred from text.

**Test set.** 5 hand-built conflict triples (V1–V5) + 2 negative cases (V6 agreement, V7 unsupported claim with off-topic sources).

| Case | Topic | Expected status | Prevailing |
|---|---|---|---|
| V1 | VAT deduction on representation meals | conflicts | `avl-114` (Finlex) |
| V2 | Avainhenkilö rate in 2026 | conflicts | `avainhenkilolaki-2025-amendment` (Finlex) |
| V3 | Capital income rate > 30k | conflicts | `tvl-124-current` (Finlex) |
| V4 | EEA lottery winnings tax-free | conflicts | `arpajaisverolaki-2` (Finlex) |
| V5 | VAT small-business threshold | conflicts | `avl-3-2025-amendment` (Finlex) |
| V6 | Standard VAT 25.5% (both sources agree) | ok | — |
| V7 | Inheritance tax 19% (no supporting source) | unsupported_claims | — |

### PASS_1 — TBD
### PASS_2 — TBD
### PASS_3 — TBD
### FAIL_1 — TBD

**Known calibration risk.** V4 mixes a clear conflict (Finlex says tax-free, Vero says taxable as capital income) with subtle target alignment — the Finlex source is about EEA winnings, the Vero source is about "foreign" winnings. If the Verifier treats "EEA" and "foreign-outside-EEA" as different targets, it may classify V4 as `ok`. The prompt instructs that same-target means same subject matter, but this case is the most likely to slip.

---

## Extractor

**Job.** Given one passage of Finnish legal text and source-node metadata, emit every cross-reference as a typed dangling edge. Closed edge-type vocabulary; `target_id=None, dangling_reason="not_yet_parsed", extracted_by="llm"` mandatory.

**Test set.** 20 real sentences (inlined in `tests/test_agent_prompts.py`):
- 8 `cites`-leaning (Finlex amendment laws with `§`/`momentti`/`kohta`)
- 4 `interprets`-leaning (Vero ohje paraphrasing a statute)
- 4 `amends` (amendment titles + cross-statute references)
- 2 `defines` ("Tässä laissa tarkoitetaan…")
- 2 negative controls (prose with no references → empty edges list)

### PASS_1 — TBD
### PASS_2 — TBD
### PASS_3 — TBD
### FAIL_1 — TBD

**Known calibration risk.** The hardest distinction is `cites` vs `amends` on amendment-law titles ("Laki X:n muuttamisesta"). The prompt says to use `amends` when the language is unambiguously about modifying a prior law, but the bare title alone is borderline. E3/E4 ("Tämä laki tulee voimaan…") are pure voimaantulosäännöksiä with no real reference — they're set to `exp_min=0` so the Extractor may legitimately emit nothing.

Negative controls (E19/E20) have `exp_max=0`. If the Extractor produces edges here, the prompt's "do not invent citations" instruction is not landing and needs tightening.

---

## Cost notes

Per single full-suite run (45 test cases, one LLM call each):

| Agent | Calls | Approx. tokens / call | Notes |
|---|---|---|---|
| Clarifier | 10 | ~600 in + 200 out | shortest |
| Planner | 11 | ~700 in + 400 out | |
| Verifier | 7 | ~900 in + 500 out | sources inlined |
| Extractor | 20 | ~700 in + 300 out | most volume |

Roughly 48 LLM calls per suite run, dominated by Extractor. DeepSeek-V3 via Featherless should put the full suite around $0.05–$0.20 depending on plan.

---

## Open questions for the team

1. **Model choice.** Defaulted to `deepseek-ai/DeepSeek-V3`. Switch via the `AGENT_MODEL` env var or per-file `MODEL` constant. If DeepSeek-V3 underperforms on Finnish, escalate to a larger model only for the agent that fails — not the whole suite.
2. **Authority ranks.** Per `findings/03_authority_ranks.md` (Track B output, not in scope here), the rank values are provisional. Verifier test cases use Finlex=100, Vero=60 to match Step 3's plan. If those rank values shift, only the inlined test sources need updating — the Verifier code reads ranks as input.
3. **Live-run pass rates.** This file will be amended with concrete PASS/FAIL slots after the first full-suite run.
