# Eval harness — dashboard

_Generated: 2026-05-24T16:43:01+00:00 · commit `cd976577` · configs: 3 · questions seen: 42_

## Overall scoreboard

| config | key_fact_recall | numeric_recall | refusal_rate | cite_prec | cite_recall | latency_p50 | latency_p95 |
|---|---|---|---|---|---|---|---|
| v1-current | **0.25** | 0.59 | 0.28 | 0.59 | 0.74 | 22435 | 105506 |
| v2-no-hybrid | 0.19 | **0.73** | 0.50 | **0.67** | **0.83** | 29757 | 111798 |
| v1-bare | 0.19 | 0.48 | **0.17** | 0.62 | 0.69 | **16323** | **28123** |


## Per-tier breakdown

### Q-set

| config | key_fact_recall | numeric_recall | refusal_rate | cite_prec | cite_recall | latency_p50 | latency_p95 |
|---|---|---|---|---|---|---|---|
| v1-current | **0.22** | **0.59** | 0.29 | 0.58 | **0.73** | 22156 | 110168 |
| v1-bare | 0.19 | 0.48 | **0.17** | **0.62** | 0.69 | **16323** | **28123** |


### N-set

| config | key_fact_recall | numeric_recall | refusal_rate | cite_prec | cite_recall | latency_p50 | latency_p95 |
|---|---|---|---|---|---|---|---|
| v1-current | **1.00** |  | **0.00** | **1.00** | **1.00** | **27870** | **27870** |
| v2-no-hybrid | 0.19 | **0.73** | 0.50 | 0.67 | 0.83 | 29757 | 111798 |


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
| v1-bare | **0.17** | 0.33 | **0.14** | **0.67** | **0.67** | **17319** | **21565** |
| v1-current | 0.14 | **0.55** | 0.31 | 0.50 | 0.57 | 24370 | 37333 |


### difficulty_2

| config | key_fact_recall | numeric_recall | refusal_rate | cite_prec | cite_recall | latency_p50 | latency_p95 |
|---|---|---|---|---|---|---|---|
| v2-no-hybrid | **0.00** | **1.00** | **1.00** | **0.00** | **0.00** | **13505** | **13505** |


### difficulty_3

| config | key_fact_recall | numeric_recall | refusal_rate | cite_prec | cite_recall | latency_p50 | latency_p95 |
|---|---|---|---|---|---|---|---|
| v2-no-hybrid | **0.22** | **0.60** | **0.33** | **0.83** | **1.00** | **52916** | **123575** |


### difficulty_4

| config | key_fact_recall | numeric_recall | refusal_rate | cite_prec | cite_recall | latency_p50 | latency_p95 |
|---|---|---|---|---|---|---|---|
| v2-no-hybrid | **0.00** |  | **1.00** | **0.50** | **1.00** | **19112** | **19112** |


### difficulty_5

| config | key_fact_recall | numeric_recall | refusal_rate | cite_prec | cite_recall | latency_p50 | latency_p95 |
|---|---|---|---|---|---|---|---|
| v1-current | **1.00** |  | **0.00** | **1.00** | **1.00** | 27870 | 27870 |
| v2-no-hybrid | 0.50 |  | **0.00** | **1.00** | **1.00** | **27491** | **27491** |



## Stage-latency profile (mean ms)

| config | filter_infer | query_rewrite | vector_retrieve | rerank | graph_expand | cross_encoder | vector_rerank | assemble | generate | total |
|---|---|---|---|---|---|---|---|---|---|---|
| v1-current | 0 | 11060 | 851 | 14 |  |  |  | 7 | 19557 | 31524 |
| v1-bare | 0 |  | 753 | 5 |  |  |  | 2 | 16071 | 16863 |
| v2-no-hybrid | 0 | 18226 | 740 |  | 0 | 2288 |  | 13 | 24763 | 46079 |


## Per-question pivot — wins/losses vs v1-current

Legend: `+` better, `-` worse, `=` within ±0.02, `e` errored, `?` missing/unscored.

| question_id | tier | v1-bare | v2-no-hybrid |
|---|---|---|---|
| Q1 | basic | e | ? |
| Q3 | basic | e | ? |
| Q4 | basic | e | ? |
| Q6 | basic | e | ? |
| Q7 | basic | = | ? |
| Q8 | basic | e | ? |
| Q9 | basic | = | ? |
| Q11 | medium | e | ? |
| Q12 | medium | = | ? |
| Q13 | medium | e | ? |
| Q14 | medium | = | ? |
| Q15 | medium | = | ? |
| Q16 | medium | e | ? |
| Q17 | medium | = | ? |
| Q20 | medium | e | ? |
| Q21 | medium | = | ? |
| Q22 | medium | = | ? |
| Q23 | medium | = | ? |
| Q24 | medium | ? | ? |
| Q26 | medium | e | ? |
| Q27 | medium | e | ? |
| Q28 | medium | e | ? |
| Q32 | hard | e | ? |
| Q34 | hard | = | ? |
| Q35 | hard | e | ? |
| Q38 | hard | e | ? |
| Q40 | hard | = | ? |
| Q41 | hard | ? | ? |
| Q42 | hard | e | ? |
| Q43 | hard | ? | ? |

… (6 more rows omitted, see per_question.csv)


## v2 strategy distribution

**v2-no-hybrid**

| strategy | count |
|---|---|
| default (seed_k=20, edges=[], hops=0). | 6 |



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
