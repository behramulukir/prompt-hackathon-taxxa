# Track G — Demo UI

Streamlit-based demo frontend for the Taxxa GraphRAG hackathon project.
Mirrors `our-docs/hybrid_cinematic_concept.md` — chat shell + inline memo
on the left, cinematic reasoning panel (graph traversal + agent timeline) on
the right.

## Run it

Streamlit is installed inside the project venv (`.venv/`), not globally.
From the repo root, either:

```bash
# Option A — full path (no activation needed)
.venv/bin/streamlit run web/app.py

# Option B — activate the venv first, then run normally
source .venv/bin/activate
streamlit run web/app.py
```

Streamlit will print a `http://localhost:8501` URL. Open it.

> First-time setup (if the venv is empty): `.venv/bin/python -m pip install streamlit playwright pydantic`
> — Playwright is only needed if you want to re-run the screenshot tests.

## Files

```
web/
├── app.py                       # Streamlit entry. ANSWER_FN swap point at top.
├── cinematic.py                 # Builds the right-column animation HTML
├── cinematic_template.html      # HTML/CSS/JS for the cinematic component
├── components/
│   ├── memo.py                  # Inline memo (the answer-as-document, left column)
│   └── source_pill.py           # Citation pills with hover excerpts + rank labels
├── data/
│   ├── build_source_meta.py     # One-shot: scans chunks.jsonl → source_meta.json
│   ├── source_meta.py           # Lookup interface used at request time
│   ├── source_meta.json         # Generated cache (committed)
│   └── demo_overrides.py        # 3 hand-crafted AnswerResults for Q1, Q12, Q41
├── DEMO_QUESTIONS.md            # Which 3 questions and why
└── README.md                    # this file
```

## Pipeline swap (when Track D ships)

Two lines at the top of `web/app.py`:

```python
ANSWER_FN = MockPipeline().answer
# from src.retrieval.pipeline import Pipeline
# ANSWER_FN = Pipeline().answer
```

Comment the first line, uncomment the second pair. Nothing else changes.

## Demo behaviour

- **The 3 preloaded questions** dispatch to deterministic, hand-crafted
  `AnswerResult` objects in `web/data/demo_overrides.py`. Stage demo never
  re-rolls — same animation every time. See `DEMO_QUESTIONS.md`.
- **Free-text input** falls through to `ANSWER_FN(question)` (MockPipeline
  for now). The dispatch seeds `random` by the question hash, so a given
  typed question produces the same `MockPipeline` variant on every Replay
  click.

To disable the override layer (e.g. to test the real pipeline against
the demo questions once Track D ships), set `USE_DEMO_OVERRIDES = False`
in `web/app.py`.

## Regenerating the source-meta cache

If `output/chunks.jsonl` changes or you add a new chunk ID to
`demo_overrides.py`:

```bash
python -m web.data.build_source_meta
```

The script reads `output/chunks.jsonl` once and writes
`web/data/source_meta.json`. Hover tooltips on citation pills read from
this cache.

## Notes for the demo narrator

- Show **Q1** first (single citation, short cinematic). Calibrates the
  audience on what the baseline does.
- Show **Q12** next. Narrate: "Watch the graph — the vector hit lands on the
  KHO precedent, then the BFS walks the citation edges to pull in the
  KVL ruling and the Vero guidance." Edges-added counter ticks 0 → 1.
- Close with **Q41**. Narrate: "The Extractor just wrote a new edge back
  to the graph — it'll be there next time someone asks about avainhenkilö."
  Then: "The Verifier surfaced a conflict — the Vero kannanotto from 2020
  still references the old 48-month cap, the statute from 2025 says 84.
  The system picks the higher authority rank and tells you that's what
  it did." Edges-added 0 → 1, conflicts 0 → 1.
- Skip/Replay are wired. Use Replay on the third question to give the
  judges a second look at the graph walk.
- The "V3.2 provisional" pill in the header is hover-targeted at any
  Finnish tax expert in the audience — it advertises that the rank values
  are unsigned and invites feedback.

## Known limitations

- The cinematic animation timeline is **narratively ordered**, not
  algorithmically faithful — agents activate sequentially even though a
  real pipeline would interleave them. Documented in
  `hybrid_cinematic_concept.md` under "Honest caveats."
- The `3.4 s` displayed total time is a simulated placeholder. The real
  pipeline will be closer to 5–15 s.
- Free-text composer input runs `MockPipeline`, so the **answer text will
  not correspond to the question**. The pre-loaded dropdown questions are
  what to demo. Free-text exists to prove the UI handles variant shapes.
