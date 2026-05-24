# Eval harness file schemas

Contract between `scripts/run_eval.py`, `scripts/grade_eval.py`, and
`scripts/report_eval.py`. All files are JSONL (one object per line). Each
field is required unless marked optional.

## `eval/runs/<config_id>.jsonl` — produced by run_eval.py

One row per (config, question) attempt.

```json
{
  "config_id": "v1-current",
  "question_id": "Q1",
  "tier": "basic",
  "question": "What is the capital income tax rate ...",
  "gold_answer": "The capital income tax rate ...",
  "gold_key_facts": ["The capital income tax rate ... is 34%.", "..."],
  "gold_citation_publishers": ["vero"],
  "answer_result": { "...full AnswerResult.model_dump(mode='json')..." },
  "error": null,
  "elapsed_ms": 12345,
  "run_started_at": "2026-05-24T10:00:00Z"
}
```

- On error, set `error` to a short string and leave `answer_result` as `null`.
- `gold_citation_publishers` is the deduplicated list of `citations[].publisher` from `eval/questions.json`.
- `tier` is the raw `tier` field (e.g. `basic`, `medium`, `hard`, `difficulty_1`..`difficulty_5`).
- The file is append-only and resumable: skip a (config, question) if already present.

## `eval/grades/<config_id>.jsonl` — produced by grade_eval.py

One row per graded (config, question).

```json
{
  "config_id": "v1-current",
  "question_id": "Q1",
  "tier": "basic",
  "deterministic": {
    "key_fact_recall": 0.75,
    "key_facts_total": 4,
    "key_facts_matched": 3,
    "matched_facts": ["..."],
    "missed_facts": ["..."],
    "numeric_recall": 1.0,
    "gold_numbers": ["30000", "34", "30"],
    "answer_numbers": ["30000", "34", "30"],
    "missing_numbers": [],
    "refusal_detected": false,
    "citation_publisher_precision": 1.0,
    "citation_publisher_recall": 1.0,
    "cited_publishers": ["vero"],
    "gold_publishers": ["vero"],
    "citation_count": 2,
    "citation_inflation_flag": false,
    "hallucinated_numbers": [],
    "answer_length_words": 87
  },
  "judge": {
    "correctness": 4,
    "grounding": 5,
    "completeness": 4,
    "comment": "Covered all key facts; minor paraphrase on threshold.",
    "model": "deepseek-ai/DeepSeek-V4-Pro",
    "cached": false
  },
  "graded_at": "2026-05-24T11:00:00Z"
}
```

- `judge` may be `null` if `--no-judge` was passed.
- `key_fact_recall = key_facts_matched / max(key_facts_total, 1)`.
- `citation_publisher_precision = |cited ∩ gold| / |cited|` (1.0 if cited is empty AND gold is empty; 0.0 if cited empty but gold non-empty).
- `citation_publisher_recall = |cited ∩ gold| / |gold|`.

## `eval/configs.json` — read by all three scripts

See file. Shape:

```json
{
  "configs": [{"id": "...", "pipeline": "v1|v2", "rerank": "metadata|cross_encoder|vector", "query_rewrite": bool, "hybrid": bool, "k": 20, "n": 8, "notes": "..."}],
  "tiers": {"A": ["...config ids..."], "B": ["..."]},
  "defaults": {"vector_db_path": "...", "graph_db_path": "...", "judge_model": "..."}
}
```
