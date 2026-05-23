"""Track F — Cross-encoder reranker (Step 7, B7.4).

Wraps ``BAAI/bge-reranker-v2-m3`` (multilingual, handles Finnish) for the
post-graph-expansion rerank step. Pilot finding (``findings/07_pilot_results.md``)
elevated this from "quality lever" to "damage control": graph expansion can
add 50-100 candidates, many plausible-but-not-on-point; vector cosine alone
cannot discriminate them; the cross-encoder reads ``(query, candidate)``
jointly and can.

Heavyweight dependencies (``torch``, ``sentence-transformers``) are imported
lazily inside ``CrossEncoderReranker.__init__`` so this module can be
imported in environments where the deps are missing (CI lint, tests that
only need the combine-weights helper, etc.). Calling ``score()`` without
the deps installed raises a clear ``RuntimeError``.

Model cache: ``~/.cache/huggingface/`` by default. The first ``score()``
call downloads ~1.1 GB.

Offline mode: any ``HF_*`` or ``TRANSFORMERS_OFFLINE`` keys present in the
project's ``.env`` file are loaded into ``os.environ`` at import time, before
``sentence_transformers`` is imported. Setting ``HF_HUB_OFFLINE=1`` in
``.env`` therefore makes this module run fully offline against the cached
model (silences the "set HF_TOKEN" warning, blocks cache-validation HEAD
requests).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


# ---------------------------------------------------------------------------
# .env loader for HF offline flags
#
# The project's .env file is not auto-loaded by anything global; voyage_client
# hand-parses one specific key (VOYAGE_API_KEY). We do the same here, narrowly
# scoped to HF_* / TRANSFORMERS_OFFLINE so we don't shadow other keys. Must
# run *before* ``sentence_transformers`` imports below — those imports read
# the env vars on their first call.
# ---------------------------------------------------------------------------


def _load_hf_offline_env() -> None:
    project_root = Path(__file__).resolve().parents[2]
    env_path = project_root / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("HF_") or key == "TRANSFORMERS_OFFLINE":
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


_load_hf_offline_env()

# Default model picked per the Step 7 brief — multilingual cross-encoder,
# 568M parameters, supports Finnish well alongside the other 100+ languages
# in its training mix.
DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"

_INSTALL_HINT = (
    "Cross-encoder rerank requires `sentence-transformers` (and `torch`). "
    "Install with `uv pip install sentence-transformers` (pulls torch). "
    "Model `BAAI/bge-reranker-v2-m3` will download ~1.1 GB to "
    "`~/.cache/huggingface/` on first use."
)


@dataclass
class ScoredCandidate:
    """One reranked candidate."""

    chunk_id: str
    text: str
    cross_score: float
    cosine: float | None = None
    metadata_score: float | None = None
    final_score: float | None = None


class CrossEncoderReranker:
    """Thin wrapper around ``sentence_transformers.CrossEncoder``.

    Usage::

        rr = CrossEncoderReranker()
        scored = rr.score(query, [(cid, text), ...])
        # ScoredCandidate.cross_score populated.

    The model is loaded on construction. If the heavyweight deps are not
    installed, raises ``RuntimeError`` with install instructions.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL, max_length: int = 512) -> None:
        try:
            from sentence_transformers import CrossEncoder  # type: ignore
        except ImportError as exc:  # pragma: no cover — import-guard test below
            raise RuntimeError(_INSTALL_HINT) from exc
        self.model_name = model_name
        self.max_length = max_length
        # ``activation_fn`` left at default (sigmoid for bge-reranker family),
        # which produces scores roughly in (0, 1). Good for weight-combining
        # with cosine without re-normalising.
        self._model = CrossEncoder(model_name, max_length=max_length)

    def score(
        self,
        query: str,
        candidates: Sequence[tuple[str, str]],
        batch_size: int = 32,
    ) -> list[ScoredCandidate]:
        """Score each candidate against the query.

        Parameters
        ----------
        query
            The user's question. Finnish or English (or mixed).
        candidates
            ``[(chunk_id, text), ...]`` — chunk_id is opaque; text is what
            the cross-encoder reads.
        batch_size
            Forwarded to the cross-encoder. 32 fits in CPU RAM comfortably;
            increase to 64+ on GPU.

        Returns
        -------
        list[ScoredCandidate]
            Sorted by ``cross_score`` descending.
        """
        if not candidates:
            return []
        pairs = [(query, text) for _, text in candidates]
        raw = self._model.predict(pairs, batch_size=batch_size, show_progress_bar=False)
        scored = [
            ScoredCandidate(chunk_id=cid, text=text, cross_score=float(s))
            for (cid, text), s in zip(candidates, raw)
        ]
        scored.sort(key=lambda c: c.cross_score, reverse=True)
        return scored


# ---------------------------------------------------------------------------
# Weight combination — pure-Python, no ML deps required
# ---------------------------------------------------------------------------


def combine_scores(
    candidates: Iterable[ScoredCandidate],
    weights: tuple[float, float, float] = (0.6, 0.3, 0.1),
) -> list[ScoredCandidate]:
    """Apply the strategy's ``rerank_weights`` to populate ``final_score``.

    ``weights`` is ``(cross_encoder, cosine, metadata)``. Missing components
    (None) are treated as 0 and their weight is redistributed onto the
    components that are present, so a candidate with only ``cross_score``
    still gets a sensible final score.

    Returns the candidates sorted by ``final_score`` descending. Does not
    modify the input list ordering.
    """
    w_cross, w_cos, w_meta = weights
    out: list[ScoredCandidate] = []
    for c in candidates:
        present_weight = 0.0
        accum = 0.0
        if c.cross_score is not None:
            accum += w_cross * c.cross_score
            present_weight += w_cross
        if c.cosine is not None:
            # Cosine in LanceDB is distance (lower is closer). Convert to
            # similarity in [0, 1] under the assumption that distances stay
            # in [0, 2] for normalised embeddings.
            sim = max(0.0, 1.0 - c.cosine / 2.0)
            accum += w_cos * sim
            present_weight += w_cos
        if c.metadata_score is not None:
            accum += w_meta * c.metadata_score
            present_weight += w_meta
        c.final_score = accum / present_weight if present_weight > 0 else 0.0
        out.append(c)
    out.sort(key=lambda c: c.final_score or 0.0, reverse=True)
    return out


# ---------------------------------------------------------------------------
# Module-level factory + smoke check
# ---------------------------------------------------------------------------


_cached_reranker: CrossEncoderReranker | None = None


def get_reranker(model_name: str = DEFAULT_MODEL) -> CrossEncoderReranker:
    """Lazily construct and cache a single reranker for the process.

    Re-uses the loaded model across queries — the first call pays the
    ~5-10s load cost; subsequent calls are free.
    """
    global _cached_reranker
    if _cached_reranker is None or _cached_reranker.model_name != model_name:
        _cached_reranker = CrossEncoderReranker(model_name=model_name)
    return _cached_reranker


def finnish_smoke_check() -> bool:
    """Sanity-check that the model discriminates on Finnish text.

    Returns True iff a known-relevant Finnish candidate outranks a
    known-irrelevant one. Designed to be run once after the model
    downloads, to catch silent multilingual-model regressions on Finnish.
    """
    rr = get_reranker()
    query = "Mikä on pääomatulon veroprosentti?"
    candidates = [
        ("rel", "Pääomatulon veroprosentti on 30 prosenttia 30 000 euroon asti."),
        ("irrel", "Suomen mestaruussarjan ottelut pelataan viikonloppuisin."),
    ]
    scored = rr.score(query, candidates)
    # The relevant candidate must be ranked first.
    return scored[0].chunk_id == "rel" and scored[0].cross_score > scored[1].cross_score
