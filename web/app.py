"""Streamlit entry point for the GraphRAG demo UI (Track G).

Layout (mirrors our-docs/hybrid_cinematic_concept.md):
  ┌────────────────────────────────────────────────────────────────┐
  │ Header · brand · jurisdiction context · V3.2 provisional pill  │
  ├────────────────────────────────────────────────────────────────┤
  │ "Try a question" dropdown + composer                           │
  ├──────────────────────────────────┬─────────────────────────────┤
  │ Inline memo (left column)        │ Cinematic reasoning panel   │
  │  - assumption chip               │  - reasoning strip          │
  │  - body sections                 │  - graph traversal SVG      │
  │  - inline conflict callout       │  - agent timeline           │
  │  - citation pills                │  - run budget               │
  └──────────────────────────────────┴─────────────────────────────┘

# ─── Pipeline swap point ──────────────────────────────────────────
# Change ANSWER_FN below when Track D's real pipeline ships. The rest
# of the app is pipeline-agnostic — it only calls ANSWER_FN(question)
# and treats the AnswerResult as opaque.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

# Make `streamlit run web/app.py` work from any cwd: ensure the repo root
# (the parent of web/) is on sys.path so `src.*` imports resolve.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import streamlit as st

from src.models import AnswerResult
from src.retrieval.mock_pipeline import MockPipeline
from web.cinematic import render_html as render_cinematic_html
from web.components.memo import render_html as render_memo_html
from web.data.demo_overrides import DEMO_OVERRIDES, DEMO_PICKS


def _safe(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

# ─────────────────────────────────────────────────────────────────────
# SWAP POINT — change these two lines when Track D ships pipeline.py
# ─────────────────────────────────────────────────────────────────────
ANSWER_FN = MockPipeline().answer
# from src.retrieval.pipeline import Pipeline
# ANSWER_FN = Pipeline().answer
# ─────────────────────────────────────────────────────────────────────

USE_DEMO_OVERRIDES = True  # Stage-demo reliability. Flip to False to
                           # test the wrapped pipeline end-to-end.


def get_answer(question: str) -> AnswerResult:
    """Two-tier dispatch.

    1. Curated demo picks → hand-crafted, deterministic, choreographed
       answer with real chunk IDs. Stage demo never re-rolls.
    2. Free-text input → seed random by question hash so the same typed
       question always produces the same MockPipeline variant on Replay.
       MockPipeline still fuzzes the UI against varied AnswerResult
       shapes (single/multi-source/empty/conflict) — just deterministically.
    """
    if USE_DEMO_OVERRIDES and question in DEMO_OVERRIDES:
        return DEMO_OVERRIDES[question]
    random.seed(hash(question) & 0xFFFFFFFF)
    return ANSWER_FN(question)


# ─────────────────────────────────────────────────────────────────────
# Streamlit chrome
# ─────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="GraphRAG · Finnish Tax",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Inject our own theme over Streamlit's defaults. Iframe components have
# their own isolated styles, so this only affects the chat shell.
st.markdown(
    """
    <style>
      .stApp { background: #0e1117; }
      .block-container { padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1500px; }

      /* Header bar */
      .taxxa-header {
        display: flex; align-items: center; gap: 14px;
        padding: 10px 16px; background: #161b22;
        border: 1px solid #2a3340; border-radius: 12px;
        margin-bottom: 14px;
      }
      .taxxa-brand {
        display: inline-flex; align-items: center; gap: 8px;
        font-weight: 800; font-size: 15px; color: #e6e8ec;
        letter-spacing: 0.01em;
      }
      .taxxa-brand-mark {
        display: inline-block; width: 16px; height: 16px;
        background: linear-gradient(135deg, #6ea8ff 0%, #f5a524 100%);
        border-radius: 4px;
      }
      .taxxa-ctx {
        display: inline-flex; gap: 10px; align-items: center;
        color: #8a96a8; font-size: 12px; font-family: ui-monospace, "SF Mono", Menlo, monospace;
      }
      .taxxa-ctx-chip {
        background: #1f2630; color: #e6e8ec; padding: 3px 9px; border-radius: 6px;
        border: 1px solid #2a3340; font-weight: 600;
      }
      .taxxa-spacer { flex: 1; }
      .taxxa-provisional {
        display: inline-flex; align-items: center; gap: 6px;
        padding: 4px 10px; border-radius: 999px;
        background: rgba(245, 165, 36, 0.13); color: #f5a524;
        border: 1px solid rgba(245, 165, 36, 0.45);
        font-size: 11px; font-weight: 700; letter-spacing: 0.03em;
        cursor: help;
      }
      .taxxa-provisional::before { content: "⚠"; font-size: 12px; }

      /* Question composer */
      .stSelectbox label, .stTextInput label, .stTextArea label {
        color: #8a96a8 !important; font-size: 11px !important;
        text-transform: uppercase; letter-spacing: 0.06em; font-weight: 700;
      }
      div[data-baseweb="select"] > div {
        background: #161b22 !important; border-color: #2a3340 !important;
      }
      .stTextInput input, .stTextArea textarea {
        background: #161b22 !important; color: #e6e8ec !important;
        border-color: #2a3340 !important;
      }
      .stButton button {
        background: #1f2630; color: #e6e8ec; border: 1px solid #2a3340;
        font-weight: 700; padding: 6px 16px;
      }
      .stButton button:hover { background: #2a3340; border-color: #3a4452; }

      /* Tighten column gaps */
      div[data-testid="column"] { padding: 0 6px !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="taxxa-header">
      <div class="taxxa-brand">
        <span class="taxxa-brand-mark"></span>
        Taxxa GraphRAG
      </div>
      <div class="taxxa-ctx">
        <span class="taxxa-ctx-chip">Finland</span>
        <span class="taxxa-ctx-chip">Tax year 2026</span>
        <span class="taxxa-ctx-chip">Finlex + Vero</span>
      </div>
      <div class="taxxa-spacer"></div>
      <span class="taxxa-provisional"
            title="Step 3 authority_rank values are provisional pending V3.2 sign-off (findings/03_authority_ranks.md). Surface any apparent rank errors to the Step 3 owner.">
        V3.2 provisional ranks
      </span>
    </div>
    """,
    unsafe_allow_html=True,
)

# ─── Question picker + composer ───────────────────────────────────────

with st.container():
    col_q, col_btn = st.columns([5, 1], gap="small")
    with col_q:
        pick_labels = ["— Type your own question —"] + [p["label"] for p in DEMO_PICKS]
        pick_choice = st.selectbox(
            "Try a curated demo question",
            pick_labels,
            index=1,  # default to Q1 (basic) so the first load runs the simplest path
            key="pick_choice",
        )
    with col_btn:
        st.write("")  # spacer to align with the selectbox
        st.write("")
        run_clicked = st.button("Run", use_container_width=True)

    if pick_choice == "— Type your own question —":
        composer_value = st.text_area(
            "Or ask your own question",
            value=st.session_state.get("composer_value", ""),
            placeholder="e.g. Mikä on yleinen arvonlisäverokanta vuonna 2026?",
            height=80,
            key="composer_value",
        )
        active_question = composer_value
    else:
        # Show the question text under the dropdown for context
        picked = next(p for p in DEMO_PICKS if p["label"] == pick_choice)
        active_question = picked["question"]
        st.markdown(
            f'<div style="background:#161b22;border:1px solid #2a3340;border-radius:8px;'
            f'padding:10px 14px;margin-top:4px;color:#e6e8ec;font-size:13px;">'
            f'<span style="color:#8a96a8;font-size:11px;text-transform:uppercase;letter-spacing:0.06em;'
            f'font-weight:700;">Question</span><br/>{_safe(picked["question"])}</div>',
            unsafe_allow_html=True,
        )

# Build the answer when the user clicks Run, OR auto-run on first visit so
# the cinematic plays without requiring a click.
auto_first_run = "result" not in st.session_state
if run_clicked or auto_first_run:
    if active_question.strip():
        st.session_state["result"] = get_answer(active_question.strip())
        st.session_state["last_question"] = active_question.strip()

result: AnswerResult | None = st.session_state.get("result")

# ─── Two-column body ──────────────────────────────────────────────────

if result is None:
    st.info("Pick a question or type one, then click **Run**.")
else:
    left, right = st.columns([1, 1], gap="medium")
    with left:
        st.iframe(render_memo_html(result), height=720)
    with right:
        st.iframe(render_cinematic_html(result), height=720)
