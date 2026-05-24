# Eval harness — dashboard

_Generated: 2026-05-24T11:45:26+00:00 · commit `8bef14cf` · configs: 2 · questions seen: 35_

## Overall scoreboard

| config | key_fact_recall | numeric_recall | refusal_rate | cite_prec | cite_recall | latency_p50 | latency_p95 |
|---|---|---|---|---|---|---|---|
| v1-current | **0.22** | **0.59** | 0.29 | 0.58 | **0.73** | 22156 | 110168 |
| v1-bare | 0.21 | 0.52 | **0.19** | **0.58** | 0.67 | **15436** | **28161** |


## Per-tier breakdown

### Q-set

| config | key_fact_recall | numeric_recall | refusal_rate | cite_prec | cite_recall | latency_p50 | latency_p95 |
|---|---|---|---|---|---|---|---|
| v1-current | **0.22** | **0.59** | 0.29 | 0.58 | **0.73** | 22156 | 110168 |
| v1-bare | 0.21 | 0.52 | **0.19** | **0.58** | 0.67 | **15436** | **28161** |


### basic

| config | key_fact_recall | numeric_recall | refusal_rate | cite_prec | cite_recall | latency_p50 | latency_p95 |
|---|---|---|---|---|---|---|---|
| v1-current | **0.36** | **0.71** | **0.14** | **0.42** | **0.83** | 19435 | **24822** |
| v1-bare | 0.00 | 0.64 | **0.14** | 0.25 | 0.50 | **18845** | 27599 |


### medium

| config | key_fact_recall | numeric_recall | refusal_rate | cite_prec | cite_recall | latency_p50 | latency_p95 |
|---|---|---|---|---|---|---|---|
| v1-bare | **0.25** | 0.49 | **0.20** | 0.69 | 0.75 | **12988** | **25818** |
| v1-current | 0.19 | **0.54** | 0.33 | **0.69** | **0.77** | 22435 | 141484 |


### hard

| config | key_fact_recall | numeric_recall | refusal_rate | cite_prec | cite_recall | latency_p50 | latency_p95 |
|---|---|---|---|---|---|---|---|
| v1-bare | **0.25** | 0.50 | **0.20** | **0.50** | 0.50 | **19678** | **21801** |
| v1-current | 0.14 | **0.55** | 0.31 | **0.50** | **0.57** | 24370 | 37333 |



## Stage-latency profile (mean ms)

| config | filter_infer | query_rewrite | vector_retrieve | rerank | graph_expand | cross_encoder | vector_rerank | assemble | generate | total |
|---|---|---|---|---|---|---|---|---|---|---|
| v1-current | 0 | 11408 | 859 | 14 |  |  |  | 7 | 19342 | 31665 |
| v1-bare | 0 |  | 734 | 5 |  |  |  | 2 | 16134 | 16908 |


## Per-question pivot — wins/losses vs v1-current

Legend: `+` better, `-` worse, `=` within ±0.02, `e` errored, `?` missing/unscored.

| question_id | tier | v1-bare |
|---|---|---|
| Q1 | basic | e |
| Q3 | basic | e |
| Q4 | basic | e |
| Q6 | basic | e |
| Q7 | basic | = |
| Q8 | basic | e |
| Q9 | basic | = |
| Q11 | medium | e |
| Q12 | medium | = |
| Q13 | medium | e |
| Q14 | medium | = |
| Q15 | medium | = |
| Q16 | medium | e |
| Q17 | medium | = |
| Q20 | medium | e |
| Q21 | medium | = |
| Q22 | medium | = |
| Q23 | medium | = |
| Q24 | medium | ? |
| Q26 | medium | e |
| Q27 | medium | e |
| Q28 | medium | e |
| Q32 | hard | e |
| Q34 | hard | = |
| Q35 | hard | e |
| Q38 | hard | e |
| Q40 | hard | = |
| Q41 | hard | ? |
| Q42 | hard | ? |
| Q43 | hard | ? |

… (5 more rows omitted, see per_question.csv)


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
