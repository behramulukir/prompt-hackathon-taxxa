# Step 8 — Agentic workflow (Track H: agent prompts done)

Built the four agent modules specified in `08_agentic_workflow.md` and
`parallel_execution_after_step4.md` (Track H). Each agent is a standalone,
synchronous callable that wraps one LLM call against an OpenAI-compatible
HTTP endpoint. No retrieval-pipeline coupling — the orchestrator
(convergence step 2, not in this track) wires them together later.

## What was built

```
src/agents/
├── __init__.py            # result dataclasses (frozen): ClarifyResult, Plan,
│                          # SubQuestion, ClaimVerification, VerifyResult
├── _llm.py                # stdlib-only OpenAI-compatible HTTP client +
│                          # forgiving JSON-object parser (fences/preamble safe)
├── _prompts.py            # tiny loader that reads prompts/*.txt at import
├── clarifier.py           # B8.1 — missing year / entity_type / jurisdiction
├── planner.py             # B8.2 — decompose into 1–4 tagged sub-questions
├── verifier.py            # B8.4 — conflict surfacing with explicit authority_rank
├── extractor.py           # B8.3 — query-time citation extraction (dangling edges)
└── prompts/
    ├── clarifier.txt
    ├── planner.txt
    ├── verifier.txt
    └── extractor.txt

tests/
└── test_agent_prompts.py  # 48 parametrized live-LLM cases (skipped without API key)

findings/
└── 08_agent_prompts.md    # calibration template; filled after first live run
```

The orchestrator (`src/agents/orchestrator.py`) and Step 8.6 evaluation
are explicitly out of scope for this track per the parallel-execution
plan; they are convergence work that runs after Track D delivers
`pipeline.answer()`.

## Agent contracts

Each agent is one callable. Result types live in `src/agents/__init__.py`
as frozen `dataclass`es — `src/models.py` is the locked Step 1–4 schema
and was not touched.

```python
clarifier(question: str) -> ClarifyResult
planner(question: str)   -> Plan
verifier(answer: str, sources: list[dict]) -> VerifyResult
extractor(text: str, source_node_meta: dict) -> list[Edge]    # models.Edge
```

`verifier`'s `sources` is a list of dicts with at least:

```python
{"id": str, "text": str, "authority_rank": int,
 "source": "finlex"|"vero", "source_subcorpus": str}
```

`authority_rank` is an **explicit input** (validated at the Python
boundary before the LLM is called); the prompt forbids inferring
authority from text. This is load-bearing for the L7 conflict-surfacing
path described in `00_overview.md`.

`extractor`'s `source_node_meta` must carry `node_id` (becomes
`Edge.source_id`); `source` and `source_subcorpus` are hints that help
the LLM choose between `cites` and `interprets`.

Every emitted `Edge` is dangling: `target_id=None`,
`dangling_reason="not_yet_parsed"`, `extracted_by="llm"`. Step 2's
resolver (`scripts/extract_edges.py`) picks them up at write-back time
exactly as it does for the ingestion-time regex/anchor passes.

## LLM client

`src/agents/_llm.py` is pure stdlib (no `openai`/`anthropic` SDK
dependency) so the team can swap providers by flipping environment
variables:

```
FEATHERLESS_API_KEY    — required at call time
FEATHERLESS_BASE_URL   — default https://api.featherless.ai/v1
AGENT_MODEL            — default deepseek-ai/DeepSeek-V3
AGENT_TIMEOUT_S        — default 60
```

JSON mode is requested via `response_format={"type":"json_object"}`. For
providers that ignore the flag, `parse_json_object` falls back to
stripping ```json fences and balanced-brace extraction. Each agent
module also re-declares `MODEL = "deepseek-ai/DeepSeek-V3"` at the top of
the file so model selection is visible per-agent and overridable without
touching the shared client.

## Test suite

`tests/test_agent_prompts.py` is **live-LLM only** — calibration, not
regression. The whole module skips unless `FEATHERLESS_API_KEY` is set.
No recorded fixtures by design (Track H is explicitly a prompt-iteration
track; fixtures would freeze whatever the prompt did on first run).

### Case counts

| Agent     | Cases | Source |
|-----------|------:|--------|
| Clarifier | 10    | medium-tier questions from `eval/questions.json` with one dimension dropped per case |
| Planner   | 11    | 10 hard-tier `(a)/(b)/(c)` questions + 1 atomic pass-through |
| Verifier  | 7     | 5 hand-built conflict triples + 2 negative (agreement / unsupported) |
| Extractor | 20    | Real sentences sampled from `output/chunks.jsonl` — 8 cites / 4 interprets / 4 amends / 2 defines / 2 negative-control prose |

Per-case assertions enforce the agent's invariants:

- Clarifier: dropped dimension must appear in `missing` AND a value must
  be filled into `assumptions` (batch-mode safe-defaults behaviour).
- Planner: `1 ≤ |sub_questions| ≤ 4`; `is_compound` reflects count;
  atomic case must have category `single` and `is_compound=False`.
- Verifier: status matches expected (`conflicts` / `ok` /
  `unsupported_claims`); for conflicts the prevailing source id is the
  Finlex one (rank 100 beats Vero rank 60).
- Extractor: emitted edges respect the closed `EdgeType` literal; each
  edge is dangling with `extracted_by="llm"`; negative controls produce
  zero edges (the prompt's "do not invent citations" instruction must
  land).

### Sampling note (chunks.jsonl)

`output/chunks.jsonl` is 808 MB. Sampling 20 sentences once at
plan-time and inlining them as literals in the test file keeps tests
fast and reproducible without depending on the chunks file at runtime.
The sample was drawn by random byte-offset seeks (binary mode to dodge
mid-UTF-8 splits) targeting Vero subcorpora for `interprets`-style
content; Finlex amendment laws surfaced the `cites` / `amends` /
`defines` examples.

## Verifier authority hierarchy

Test sources use the rank values established in
`findings/03_authority_ranks.md`:

| Source         | `authority_rank` |
|----------------|-----------------:|
| Finlex statute |              100 |
| Vero guidance  |               60 |

If Step 3's rank values shift, only the inlined sources in the test
file need updating — the Verifier code reads ranks as an input and
makes no assumptions about specific values beyond "integer, higher
wins, equal → no prevailing".

## Decisions and tradeoffs

### Result types in `src/agents/__init__.py`, not `src/models.py`

`models.py` is the locked schema contract for Steps 1–4 and three
parallel tracks read it. Polluting it with agent-layer types
(`ClarifyResult`, `Plan`, `VerifyResult`) would create cross-track
write contention for zero benefit — the orchestrator converts these to
`AnswerResult`'s loose `conflicts: list[dict]` / `assumptions:
list[str]` shape at the boundary.

### Frozen dataclasses, not Pydantic models

Agent result types are pure data with no validation requirements beyond
what the parsing code already does. `@dataclass(frozen=True)` keeps
them hash-able, immutable, and free of the Pydantic import that
`models.py` already pays for elsewhere.

### Stdlib HTTP, no SDK

Featherless exposes an OpenAI-compatible endpoint. `urllib.request` is
~80 lines of glue and avoids dragging in the `openai` package (which
would shadow the team's later decision on provider). Trade: no
streaming support and no automatic retry on transient 5xx — the
Verifier/Extractor calls are short and a hard fail is preferable to a
silent retry that doubles token cost.

### JSON-object response format + forgiving parser

Every agent's output is structured. JSON mode handles most providers.
The fallback parser (`parse_json_object`) strips ```json fences and
extracts the first balanced `{...}` span — DeepSeek-V3 occasionally
preambles its output even in JSON mode, and this keeps the agents
robust to that without retries.

### Live-LLM tests, no recorded fixtures

Recorded fixtures freeze in whatever the prompt did on the first run
and silently rot when prompts are tuned. Track H's whole purpose is
prompt iteration, so the suite hits the live LLM by design. Without
the API key the whole module skips — no false signal from a never-run
test.

### `target_id=None` everywhere from Extractor

The on-demand Extractor runs on retrieved chunks at query time with no
node-resolution context. Even when the LLM produces an obvious "this is
AVL §114", it would be wrong to claim resolution without checking the
graph. Every edge dangles; the existing Step 2 resolver picks them up
at write-back. The `@model_validator` on `Edge` enforces this — a
resolved edge with `dangling_reason` set raises, and vice versa, so the
Extractor's contract is mechanically enforced.

### Per-agent prompt-revision budget

Documented up front in `findings/08_agent_prompts.md`: 2 (Clarifier) /
3 (Planner) / 3 (Verifier) / 2 (Extractor). If an agent needs more
than its budget after the first live run, the next call is to escalate
to the team — not to silently burn more tokens. Honest reporting per
the Step 8 brief.

### Two-tier negative cases for the Extractor

E19/E20 are pure prose with no legal references. They explicitly
require `len(edges) == 0`. If the Extractor produces output here, the
"do not invent citations" instruction is not landing and the prompt
needs tightening before the suite is trustworthy. Without these
controls the suite would only measure recall, not precision.

## How to run

```bash
# One-time: set up the provider creds
export FEATHERLESS_API_KEY=<your key>
# optional overrides
export AGENT_MODEL=deepseek-ai/DeepSeek-V3
export FEATHERLESS_BASE_URL=https://api.featherless.ai/v1

# Run the full calibration suite (~48 LLM calls, ~$0.05–$0.20)
.venv/bin/python -m pytest tests/test_agent_prompts.py -v

# Run a single agent's cases
.venv/bin/python -m pytest tests/test_agent_prompts.py -k clarifier -v
.venv/bin/python -m pytest tests/test_agent_prompts.py -k planner   -v
.venv/bin/python -m pytest tests/test_agent_prompts.py -k verifier  -v
.venv/bin/python -m pytest tests/test_agent_prompts.py -k extractor -v
```

Without `FEATHERLESS_API_KEY` set, the whole module is `skipped` —
intentional, since no fake-LLM fixtures exist.

## Output artifacts

This track produces no `output/` artifacts. Everything lives under
`src/agents/`, `tests/`, and `findings/`. The Extractor's actual edge
write-back to `output/edges.jsonl` happens at orchestrator wire-up time,
not here.

## Sequencing notes

- **Convergence step 1 (v2 pipeline assembly)** does not need this
  track. v2 = vector + graph + reranker, no agents.
- **Convergence step 2 (orchestrator)** wires `clarifier → planner →
  answer_v2 (per sub-question) → synthesize → verifier` per the
  pseudocode in `08_agentic_workflow.md §B8.5`. All four agents are
  callable now.
- **Convergence step 3 (UI integration)** consumes the orchestrator's
  `AnswerResult.conflicts` and `assumptions` fields — both are
  populated from Verifier and Clarifier outputs respectively via the
  orchestrator's dict-conversion at the boundary.
- **Step 8.6 evaluation** runs after the orchestrator is wired. Not
  part of Track H.

## Open items (will close at convergence)

- [ ] First live-LLM run — fill PASS/FAIL slots in
      `findings/08_agent_prompts.md`
- [ ] Per-agent prompt revisions within the documented budget if any
      case fails
- [ ] Orchestrator (`src/agents/orchestrator.py`) — convergence work,
      not Track H
- [ ] Extractor edge write-back to `output/edges.jsonl` — wired by the
      orchestrator, not Track H
