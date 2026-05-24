# Eval harness — dashboard

_Generated: 2026-05-24T11:25:09+00:00 · commit `8fc4f84a` · configs: 1 · questions seen: 1_

## Overall scoreboard

| config | key_fact_recall | numeric_recall | refusal_rate | cite_prec | cite_recall | judge_correctness | judge_grounding | judge_completeness | latency_p50 | latency_p95 |
|---|---|---|---|---|---|---|---|---|---|---|
| v1-current | **1.00** | **1.00** | **0.00** | **0.50** | **1.00** |  |  |  | **29409** | **29409** |


## Per-tier breakdown

### Q-set

| config | key_fact_recall | numeric_recall | refusal_rate | cite_prec | cite_recall | judge_correctness | judge_grounding | judge_completeness | latency_p50 | latency_p95 |
|---|---|---|---|---|---|---|---|---|---|---|
| v1-current | **1.00** | **1.00** | **0.00** | **0.50** | **1.00** |  |  |  | **29409** | **29409** |


### basic

| config | key_fact_recall | numeric_recall | refusal_rate | cite_prec | cite_recall | judge_correctness | judge_grounding | judge_completeness | latency_p50 | latency_p95 |
|---|---|---|---|---|---|---|---|---|---|---|
| v1-current | **1.00** | **1.00** | **0.00** | **0.50** | **1.00** |  |  |  | **29409** | **29409** |



## Stage-latency profile (mean ms)

| config | filter_infer | query_rewrite | vector_retrieve | rerank | graph_expand | cross_encoder | vector_rerank | assemble | generate | total |
|---|---|---|---|---|---|---|---|---|---|---|
| v1-current | 0 | 6153 | 1712 | 17 |  |  |  | 7 | 21341 | 29409 |


## Per-question pivot — wins/losses vs v1-current

Legend: `+` better, `-` worse, `=` within ±0.02, `e` errored, `?` missing/unscored.

_(only v1-current is present)_


## v2 strategy distribution

_(no v2 configs with strategy assumptions)_


## Known limitations

- The gold may have stale facts (e.g., Q35 €10k → €20k).
- Hand-labeled section-level recall is not measured.
- Refusals on answerable questions count as misses; refusal_rate is reported separately.
- N-prefix `answer_key_facts` may be a strict subset of the full answer.


## Footer

Source data: `eval/runs/` (driver output), `eval/grades/` (grader output).

Reproduce:

```bash
python -m scripts.run_eval --tier A && \
python -m scripts.grade_eval && \
python -m scripts.report_eval
```
