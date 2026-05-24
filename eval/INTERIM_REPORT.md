# Eval — Interim Report

**Status:** evaluation in flight · **Snapshot:** 2026-05-24

---

## Current state

Tier A is barely off the ground. 83 questions × 3 configs (`v1-current`,
`v2-cross`, `v2-vector`) = 249 runs planned. Completed so far:

| config           | rows  | successes | errors                         | remaining |
| ---------------- | ----- | --------- | ------------------------------ | --------- |
| `v1-current`     | 15/83 | 14        | 1                              | 68        |
| `v2-cross`       | 0/83  | —         | 2 attempted, both 429          | 83        |
| `v2-vector`      | 0/83  | —         | 2 attempted, 1 success unsaved | 83        |
| `v1-bare`        | not started (Tier B) |
| `v2-no-rewrite`  | not started (Tier B) |
| `v2-no-hybrid`   | not started (Tier B) |

### Two distinct failure modes in the logs

1. **Featherless concurrency limit** (`HTTP 429`). The plan caps at **4
   concurrent units**; DeepSeek-V4-Pro costs **4 units per request**, so any
   parallelism whatsoever blows the limit. Most `v2-cross` / `v2-vector`
   errors are this. The query-rewrite step soft-fails to the original
   question (good — pipeline keeps moving), but the final generation step
   then 429s and the whole row fails.
2. **`Edge ValidationError`**. The graph DB contains
   `extracted_by='backfill_amendment'`, but it isn't in the
   `ExtractionMethod` literal (`structural | anchor | regex | llm`). Killed
   `v1-current Q4`. Real bug between `src/models.py` and ingest.

### What we can see from the 14 `v1-current` successes (basic + medium mix)

- **Citations**: avg 3.2 sources cited, range 0–6; 1/14 returned no citations.
- **Retrieved chunks**: 8 per query (matches `n=8` config).
- **Conflicts surfaced**: 0 across all 14 — none of the questions hit the
  authority lattice, or the Verifier isn't triggering.
- **Amendment caveats**: 19 total across 10/14 rows — temporal awareness is
  firing.
- **Latency**: median **21.8s**, p90 **25.7s**, outlier **153.5s on Q15**
  (generation took 146s — likely a token-stream stall, worth investigating).

Nothing is graded yet — `eval/grades/v1-current.jsonl` is empty. No
key-fact recall / citation-publisher precision / judge scores to compare
configs on.

## Recommendations (now)

- The 429s won't clear by waiting — pipeline parallelism × 4-unit cost =
  guaranteed conflict. Either (a) serialize the runner to 1 in-flight call,
  (b) upgrade the Featherless plan, or (c) drop the agent calls
  (planner/verifier) for the eval runs since they aren't load-bearing for
  retrieval quality.
- Fix the `backfill_amendment` literal in `ExtractionMethod` — that's a
  30-second edit that unblocks any rows whose graph expansion lands on a
  backfilled amendment edge.
- Investigate Q15 — 146s in generate suggests the model is looping; not a 429.

---

## How the eval is architected

Three-stage pipeline, all file-based, all resumable. Designed so you can
crash, restart, and pick up exactly where you stopped.

### 1. Question bank — `eval/questions.json`

83 entries, one per question. Each has:

- `question_id` (`Q1`..`Q83`), `tier` (basic / medium / hard / etc.),
  `question` text
- `gold_answer` — the human-written reference answer
- `gold_key_facts` — atomic claims the answer must contain (drives the
  recall metric)
- `gold_citation_publishers` — which publishers (`vero`, `finlex`, `kho`, …)
  the answer should cite (drives precision/recall on sourcing)

Top-level metadata also splits questions into tiers and counts existing vs.
additional Q&A.

### 2. Config matrix — `eval/configs.json`

Six configs, paired into two ablation tiers:

- **Tier A** — current baselines you'd actually ship: `v1-current`,
  `v2-cross`, `v2-vector`. Three different rerank strategies on top of the
  same hybrid + query-rewrite stack.
- **Tier B** — Plan-A / Plan-B attribution: `v1-bare`, `v2-no-rewrite`,
  `v2-no-hybrid`. Each ablates exactly one feature so its contribution is
  measurable.

Each config row carries: `pipeline` (v1/v2), `rerank` strategy,
`query_rewrite` on/off, `hybrid` on/off, `k`, `n`. The defaults section
pins vector / graph DB paths and the judge model.

### 3. Stage 1 — `scripts/run_eval.py` → `eval/runs/<config_id>.jsonl`

- One row per (config, question) attempt.
- Builds each pipeline **once** per config — LanceDB open + cross-encoder
  warmup happen at most once per config, not 83×.
- Append-only; completed `question_id`s are skipped on restart
  (`_completed_pairs`).
- On error: writes a row with `error` set and `answer_result=null`. The bad
  row still counts as "done" for resume purposes — debatable, since a
  transient 429 burns that slot.
- Persists the full `AnswerResult` dump: question, answer,
  `cited_source_ids`, `retrieved_chunks` (with paths), `timing_ms`,
  `conflicts`, `amendment_caveats`, `as_of_date_used`, etc.

### 4. Stage 2 — `scripts/grade_eval.py` → `eval/grades/<config_id>.jsonl`

Two scorers per row.

**Deterministic** (no LLM, reproducible):

- `key_fact_recall` — fuzzy-match each `gold_key_fact` against the answer text.
- `numeric_recall` — extract all numbers (handles Finnish "30 000" /
  "30,5" / "30.000" thousand-separator forms via `_NUMBER_RE` +
  `_normalize_number`) and check gold numbers appear in the answer.
- `refusal_detected` — regex bank in `_REFUSAL_PATTERNS` (English + Finnish).
- `citation_publisher_precision` and `_recall` — set-overlap on cited vs.
  gold publishers.
- `citation_inflation_flag` — citations way above gold-key-fact count.
- `hallucinated_numbers` — numbers in the answer that aren't in gold.

**LLM judge** (DeepSeek-V4-Pro, optional via `--no-judge`):

- 1–5 scores on `correctness` / `grounding` / `completeness` + free-text
  comment.
- Disk-cached by content hash (`.judge_cache.json`) so re-runs don't re-pay.

### 5. Stage 3 — `scripts/report_eval.py`

Rolls the grades up into a comparison table across configs. Hasn't run yet
because grades are empty.

### Why it's shaped this way

- **JSONL + append + resume** — eval is a long-tail operation with flaky
  upstreams (Featherless 429, transient LanceDB locks, etc.); restartability
  is more valuable than fancy storage.
- **Deterministic + judge scoring side-by-side** — the deterministic side
  gives you a regression signal that doesn't drift; the judge gives you the
  "is this actually a good answer" signal that deterministic can't see.
- **Configs as data, not code** — adding a 7th ablation is a `configs.json`
  edit, not a code change; the pipeline router reads
  `pipeline` / `rerank` / `query_rewrite` / `hybrid` at runtime.
- **Build-pipeline-once** — for a 249-cell matrix, paying LanceDB +
  rerank warmup per question would blow the budget; the runner is
  structured around "outer loop = config, inner loop = questions".
