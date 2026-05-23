# Step 8 — Agentic Workflow

> Wrap the v2 GraphRAG pipeline in the four agents from slide 6 of the brief — Planner, Extractor, Verifier, Clarifier. Each agent solves a specific failure mode v2 still has.
>
> Do this last. Agents on top of a weak retriever amplify weaknesses. Agents on top of a strong retriever close the remaining gap.

## Inputs

- v2 pipeline beating v1 (Step 7 complete)
- `findings/07_v2_eval.md` — which categories still underperform and why

## Verification task

### V8.1 — Map remaining failures to agents

For each category still below target after Step 7, write which agent addresses it:

| Failure mode in v2 | Agent that should help |
|--------------------|------------------------|
| Question is ambiguous (jurisdiction, year, entity type missing) | **Clarifier** |
| Question needs decomposition into sub-questions | **Planner** |
| Citation in a retrieved chunk was missed by regex/anchor extraction | **Extractor** (on-demand) |
| Sources conflict (Finlex vs Vero) and v2 picked one without acknowledging | **Verifier** |

**Output:** `findings/08_agent_targets.md`. **Only build agents that address documented failures.** Building all four because the slide shows four wastes time on agents that don't move metrics.

## Build tasks

> Each subsection below is a self-contained mini-phase. Skip any whose target failure mode doesn't show up in your v2 results.

### B8.1 — Clarifier agent

**Triggers when:** the question is missing jurisdiction, tax year, or entity type (private person / yritys / yhdistys / public body).

`src/agents/clarifier.py`:
```python
def clarify(question: str, conversation: list[Msg] | None = None) -> ClarifyResult:
    """Returns either:
    - clarified=False, missing=[...] → ask back to the user
    - clarified=True, assumptions={...} → run with stated assumptions surfaced in the answer"""
```

For interactive use, ask back. For batch evaluation, run with explicit defaults (current year, Finnish tax-resident company) and have the final answer state the assumption.

### B8.2 — Planner agent

**Triggers when:** the question is compound or multi-step.

`src/agents/planner.py`:
```python
def plan(question: str) -> Plan:
    """Decompose into sub-questions, each tagged with category → strategy.
    Single-sub-question plans pass through unchanged."""
```

The Planner replaces the keyword router from Step 7 only for compound questions. Each sub-question runs through `answer_v2`. The Planner synthesizes a final answer from sub-answers.

Cost guard: cap sub-questions at 4. More than that is usually a sign of wrong decomposition.

### B8.3 — Extractor agent (on-demand)

**Triggers when:** a retrieved chunk contains citation-like phrasing that the Step 2 extraction missed.

Same logic as `extract_citations_llm` from Step 2, but invoked at **query time** on the retrieved chunks. The newly extracted edges:

1. Are walked immediately for this query (expand the context)
2. Are written back to `data/edges.jsonl` for future queries

This is a learning loop. Over time, the graph fills in citations the initial regex pass missed.

`src/agents/extractor.py` — wraps the Step 2 LLM extractor with query-time invocation and write-back.

### B8.4 — Verifier agent

**Triggers when:** the assembled context contains sources from different authority tiers covering the same question (e.g. Finlex SECTION + Vero guidance both addressing deduction rules).

`src/agents/verifier.py`:
```python
def verify(answer: str, sources: list[Node]) -> VerifyResult:
    """For each claim in the answer:
    - find supporting source(s)
    - check for contradicting sources in the retrieved set
    - if contradiction exists, return conflict_report with the paths
    Returns OK, conflicts=[...], or unsupported_claims=[...]."""
```

The Verifier knows the authority hierarchy from Step 3 (Finlex > Vero). When conflicts surface it doesn't silently pick — it asks the generator to revise with the conflict explicitly stated.

Output is fed back to the generator. One re-revision pass max.

### B8.5 — Orchestrator

`src/agents/orchestrator.py`:

```python
def answer_agentic(question: str) -> AnswerResult:
    # 1. Clarify
    clarified = clarify(question)
    if clarified.needs_user_input:
        return AskBack(clarified.missing)

    # 2. Plan
    plan = planner.plan(clarified.normalized_question)

    # 3. Execute sub-plans (each calls answer_v2; extractor invoked on-demand)
    sub_results = [answer_v2(sub) for sub in plan.sub_questions]

    # 4. Synthesize
    draft = synthesize(plan, sub_results)

    # 5. Verify
    verified = verify(draft.answer, draft.sources)
    if verified.has_conflicts:
        draft = regenerate_with_conflict_acknowledgment(draft, verified)

    return draft
```

Keep the orchestrator boring and explicit. No autonomous loops. Each agent has a single responsibility in a deterministic flow.

### B8.6 — Run the evaluation

Same harness as Steps 6 and 7. Compare v2 → v2+agents per category.

Expected wins:
- Statute-vs-guidance category jumps (Verifier)
- Compound / multi-hop questions improve further (Planner)
- Ambiguous questions get clarified or run with explicit assumptions (Clarifier)

Expected costs:
- Higher latency (4 agents = at least 4x LLM calls)
- 3–10x v2 LLM spend per query

Both acceptable for the hackathon, but worth measuring and reporting.

**Output:** `findings/08_agentic_eval.md` — agent-by-agent contribution analysis.

## Done when

- The orchestrator answers eval questions end-to-end
- Statute-vs-guidance and compound-question metrics improve over v2
- For at least one question, the Verifier visibly catches a Finlex-vs-Vero conflict v2 missed
- For at least one question, the Clarifier asks back (interactively) or surfaces an explicit assumption (batch)
- The on-demand Extractor has written at least a few new edges back to `data/edges.jsonl`

## After the hackathon — out of scope but worth noting in the writeup

- **KKO case law.** Adding a third source with `applies` / `overrides` edge types extends the Verifier's authority logic naturally.
- **EU-lex conflict handling.** `transposes` edges to EU directives and EU-vs-Finland conflict rules in the Verifier.
- **Temporal queries.** "What was the rule on X in 2019?" requires versioned retrieval — the current `usable` flag doesn't fully support point-in-time queries.
- **Active learning.** Surface low-confidence LLM extractions to a human reviewer; promote confirmed ones to confidence=1.0.
- **Caching.** Sub-questions repeat across queries; cache `answer_v2` by normalized question.
