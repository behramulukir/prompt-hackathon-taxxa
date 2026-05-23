"""Thin wrapper around the Voyage SDK.

Centralizes:
- API key loading from .env (we deliberately don't depend on python-dotenv)
- Model/dimension defaults (locked in 04_embedding_and_indexing.md)
- Retry/back-off for transient 429/5xx so the long-running embed pass survives
  hiccups without dropping work.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Literal

import voyageai

MODEL = "voyage-3-large"
OUTPUT_DIMENSION = 1024
# Per-request timeout for Voyage. Long enough to handle big batches (large KHO
# / treaty chunks at ~120k tokens take a few seconds server-side), short enough
# to fail-fast on network hangs rather than stalling the whole pass indefinitely.
REQUEST_TIMEOUT_SECONDS = 120.0
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_api_key() -> str:
    """Pick VOYAGE_API_KEY from the process env, falling back to .env."""
    key = os.environ.get("VOYAGE_API_KEY")
    if key:
        return key
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("VOYAGE_API_KEY="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    os.environ["VOYAGE_API_KEY"] = val
                    return val
    raise RuntimeError(
        "VOYAGE_API_KEY not set in environment or .env at project root"
    )


def get_client() -> voyageai.Client:
    _load_api_key()
    return voyageai.Client(timeout=REQUEST_TIMEOUT_SECONDS)


def _embed_once(
    client: voyageai.Client,
    texts: list[str],
    input_type: Literal["document", "query"],
    max_retries: int,
) -> tuple[list[list[float]], int]:
    """Single Voyage call with retry on transient errors. Caller handles
    InvalidRequestError (over-cap batches)."""
    delay = 2.0
    for attempt in range(max_retries):
        try:
            resp = client.embed(
                texts,
                model=MODEL,
                input_type=input_type,
                output_dimension=OUTPUT_DIMENSION,
            )
            return resp.embeddings, resp.total_tokens
        except voyageai.error.RateLimitError:
            if attempt == max_retries - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 60.0)
        except (voyageai.error.ServiceUnavailableError, voyageai.error.Timeout):
            if attempt == max_retries - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 60.0)
    raise RuntimeError("unreachable")


def embed_batch(
    client: voyageai.Client,
    texts: list[str],
    *,
    input_type: Literal["document", "query"],
    max_retries: int = 5,
) -> tuple[list[list[float]], int]:
    """Embed a batch, returning (embeddings, total_tokens).

    - Retries 429/503/timeout up to max_retries.
    - On InvalidRequestError (most often per-batch token cap), splits the batch
      in half and recurses. Caller's accounting still sums correctly because
      results are concatenated in order. Single-text batches are not split —
      they re-raise so the caller can decide whether to drop the chunk.
    """
    try:
        return _embed_once(client, texts, input_type, max_retries)
    except voyageai.error.InvalidRequestError:
        if len(texts) <= 1:
            raise
        mid = len(texts) // 2
        left_emb, left_tok = embed_batch(
            client, texts[:mid], input_type=input_type, max_retries=max_retries
        )
        right_emb, right_tok = embed_batch(
            client, texts[mid:], input_type=input_type, max_retries=max_retries
        )
        return left_emb + right_emb, left_tok + right_tok
