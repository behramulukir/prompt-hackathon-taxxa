"""FastAPI sidecar wrapping ``PipelineV2`` for the Next.js frontend.

Endpoints
---------

``POST /ask``       — Server-Sent Events stream. Body matches the frontend's
                      ``AskBody`` (question, asof, lang, mode, instant).
                      Emits the same ``AgentEvent`` sequence the Q4 fixture
                      in ``app/api/ask/route.ts`` documents, but driven by
                      the real pipeline.

``GET  /excerpt``   — Citation drawer payload. Looks up the chunk in
                      LanceDB and the section in the graph store, returns
                      ``ExcerptResponse``. Synthesizes a Finlex/Vero URL
                      from the node id when no canonical URL is stored.

``GET  /healthz``   — Liveness probe. Returns 200 once the pipeline is loaded.

Run
---

    uvicorn src.api.server:app --reload --port 8000

Set ``AGENT_SIDECAR_URL=http://localhost:8000`` in the frontend's environment
so its ``/api/ask`` and ``/api/excerpt`` routes proxy through. Without it the
frontend silently falls back to its fixture replay.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, AsyncIterator, Callable, Literal, TypeVar

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from src.api.events import (
    build_orbit,
    estimate_cost_cents,
    rewrite_citations,
)
from src.retrieval import GRAPH_DB_PATH, VECTOR_DB_PATH
from src.retrieval.assemble import AssembledContext, assemble
from src.retrieval.filters import infer_as_of_date, infer_filters
from src.retrieval.generate import generate
from src.retrieval.pipeline import Pipeline
from src.retrieval.query_rewrite import ExpandedQuery, expand_query
from src.retrieval.rerank import RerankedHit, rerank

# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------

# Configure the root logger once so uvicorn doesn't strip our formatter.
# ``LEX_ATLAS_LOG_LEVEL`` is the lever for the demo console — set to DEBUG
# when you want per-hit detail and the full assembled context summary.
_LOG_LEVEL = os.environ.get("LEX_ATLAS_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=_LOG_LEVEL,
    format="%(asctime)s.%(msecs)03d  %(levelname)-5s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
# Quiet down uvicorn's per-request access line (we emit our own with timings).
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

logger = logging.getLogger("lex_atlas.api")


class _ReqLogger:
    """Thin wrapper that prefixes every line with a request id.

    Lets concurrent requests stay readable when the demo gets hit with two
    questions in a row. The id is also handed back to the frontend in the
    ``X-Request-Id`` header so a tester can correlate.
    """

    __slots__ = ("rid",)

    def __init__(self, rid: str) -> None:
        self.rid = rid

    def info(self, msg: str, *args: Any) -> None:
        logger.info(f"[{self.rid}] {msg}", *args)

    def warning(self, msg: str, *args: Any) -> None:
        logger.warning(f"[{self.rid}] {msg}", *args)

    def error(self, msg: str, *args: Any) -> None:
        logger.error(f"[{self.rid}] {msg}", *args)

    def exception(self, msg: str, *args: Any) -> None:
        logger.exception(f"[{self.rid}] {msg}", *args)

    def debug(self, msg: str, *args: Any) -> None:
        logger.debug(f"[{self.rid}] {msg}", *args)


def _new_request_id() -> str:
    """8-char hex request id — short enough for a log prefix."""
    return secrets.token_hex(4)


def _trunc(s: str, n: int = 120) -> str:
    """One-line preview for log output."""
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"

# ----------------------------------------------------------------------
# Globals — pipeline is process-singleton; first request pays warmup.
# ----------------------------------------------------------------------

# Default retrieval depth + context size for /ask. Mirrors the CLI command the
# user has validated against: ``python -m scripts.ask -k 50 -n 12 "<q>"``.
DEFAULT_K = 50
DEFAULT_N = 12

# Single-worker executor for all pipeline calls.
#
# Both SQLite (the graph store) and LanceDB pin their connection objects to
# the thread that opened them. ``asyncio.to_thread`` uses the default pool
# which rotates workers between calls, so the second hit explodes with
# "SQLite objects created in a thread can only be used in that same thread."
# Pinning every pipeline op to one worker keeps the connection happy and
# matches the synchronous assumptions ``scripts.ask`` was built around.
_pipeline_executor = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="lex-atlas-pipeline"
)

_pipeline: Pipeline | None = None


def _build_pipeline() -> Pipeline:
    logger.info(
        "Initializing v1 Pipeline (vector=%s, graph=%s)",
        VECTOR_DB_PATH,
        GRAPH_DB_PATH,
    )
    return Pipeline(
        vector_db_path=VECTOR_DB_PATH,
        graph_db_path=GRAPH_DB_PATH,
        query_rewrite=True,
    )


def _get_pipeline_sync() -> Pipeline:
    """Lazy init the pipeline. Must run on the pinned worker thread."""
    global _pipeline
    if _pipeline is None:
        _pipeline = _build_pipeline()
    return _pipeline


def get_pipeline() -> Pipeline:
    """For sync callers (the ``/excerpt`` endpoint runs on the worker thread).

    Use ``await _on_worker(...)`` from async contexts to make sure the call
    lands on the pinned executor.
    """
    return _get_pipeline_sync()


T = TypeVar("T")


async def _on_worker(fn: Callable[[], T]) -> T:
    """Run a zero-arg blocking callable on the pinned pipeline worker.

    Wrap the call site in a lambda so kwargs and bound methods pass through
    cleanly: ``await _on_worker(lambda: pipe.retriever.retrieve(q, k=50))``.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_pipeline_executor, fn)


# ----------------------------------------------------------------------
# Request / response models
# ----------------------------------------------------------------------


class ChatMessage(BaseModel):
    """One prior conversation turn — OpenAI-format role/content pair.

    The frontend builds this list from completed turns and sends it on every
    follow-up. The current question is sent separately as ``question``; this
    history is everything BEFORE it.
    """

    role: Literal["user", "assistant"]
    content: str


class AskBody(BaseModel):
    """Body of POST /ask.

    Mirrors the frontend's ``AskBody`` interface in ``app/api/ask/route.ts``.
    Stays permissive on extras so a future frontend field (e.g. ``mode_args``)
    doesn't 422 the request before we've had a chance to handle it here.
    """

    question: str = Field(min_length=4)
    asof: str | None = None
    lang: Literal["fi", "sv", "en"] = "en"
    mode: Literal["ask", "draft_email", "debate_only"] = "ask"
    instant: bool = False

    # Prior conversation turns for multi-turn chat. Empty for the first turn.
    # Each follow-up retrieves fresh sources against the current question;
    # history feeds the LLM context for pronouns / referential follow-ups
    # ("and what about asetus 1535/1992?", "explain that exception again").
    history: list[ChatMessage] = Field(default_factory=list)

    # Optional per-request overrides for the retrieval depth + context size.
    # Defaults mirror ``python -m scripts.ask -k 50 -n 12`` — the command the
    # frontend's /ask path is meant to be a streaming wrapper around.
    k: int | None = None
    n: int | None = None

    model_config = {"extra": "allow"}


# ----------------------------------------------------------------------
# App
# ----------------------------------------------------------------------


app = FastAPI(title="Lex Atlas Sidecar", version="0.1.0")

# Allow the Next.js dev server (default :3000) to talk to us directly when
# the rewrite isn't in place. In production the rewrite handles it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id"],
)


@app.middleware("http")
async def access_log(request: Request, call_next) -> Any:
    """One INFO line per request with method, path, status, and duration.

    Skips ``/healthz`` so polling doesn't drown the console. Adds an
    ``X-Request-Id`` header to the response so log lines correlate with
    whatever the frontend captures in DevTools.

    For ``/ask`` we let the streaming handler do its own staged logging
    (start banner, per-stage line, done summary). We still log the entry
    here so a request that dies before the first stage event is visible.
    """
    rid = request.headers.get("x-request-id") or _new_request_id()
    request.state.request_id = rid

    if request.url.path == "/healthz":
        return await call_next(request)

    t0 = time.perf_counter()
    method = request.method
    path = request.url.path
    logger.info("[%s] → %s %s", rid, method, path)
    try:
        response = await call_next(request)
    except Exception:
        ms = _ms_since(t0)
        logger.exception("[%s] ✗ %s %s — crashed after %d ms", rid, method, path, ms)
        raise
    ms = _ms_since(t0)
    response.headers["X-Request-Id"] = rid
    glyph = "✓" if response.status_code < 400 else "✗"
    logger.info(
        "[%s] %s %s %s — %d in %d ms",
        rid, glyph, method, path, response.status_code, ms,
    )
    return response


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    """Lightweight liveness probe.

    The pipeline is lazy by default; we don't force-load it here so the probe
    stays fast and the first ``/ask`` is the one that pays warmup.
    """
    return {"status": "ok", "pipeline_loaded": _pipeline is not None}


# ----------------------------------------------------------------------
# /ask — SSE driven by a real PipelineV2 run
# ----------------------------------------------------------------------


def _sse(event: dict[str, Any]) -> bytes:
    """Frame one event for the SSE wire format the frontend expects.

    The frontend's parser splits on ``\\n\\n`` (LF or CRLF) and grabs the
    first ``data:`` line. We keep the message single-line JSON so a single
    ``data:`` is enough.
    """
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")


# Tokenization for the draft stream — chunk on whitespace + cite boundaries
# so the cite tokens stay intact (the AnswerStream regex needs them whole).
_DRAFT_SPLIT_RE = re.compile(r"(\[cite:node:[^\]]+\][^\[]*\[/cite\]|\S+\s*)")


def _draft_chunks(answer: str) -> list[str]:
    """Split a rewritten answer into ~word-sized fragments for streaming.

    Cite tokens are always one chunk so the regex on the client side never
    sees them broken in half.
    """
    out: list[str] = []
    for m in _DRAFT_SPLIT_RE.finditer(answer):
        chunk = m.group(0)
        if chunk:
            out.append(chunk)
    return out


async def _ask_stream(body: AskBody, request: Request) -> AsyncIterator[bytes]:
    """Async generator that drives the pipeline and emits SSE events.

    Mirrors ``python -m scripts.ask -k {k} -n {n} "<question>"`` — the v1
    Pipeline (vector + rerank + assemble + generate, no graph expansion).
    Each blocking step runs inside ``_on_worker`` (a single-thread executor)
    so the SQLite/LanceDB connections stay bound to one thread and the
    event loop can still interleave SSE writes.

    Observability: every stage logs one INFO line tagged with the request
    id. Set ``LEX_ATLAS_LOG_LEVEL=DEBUG`` to also dump the top-5 retrieved
    chunks and the assembled-source summary.
    """
    rid = getattr(request.state, "request_id", None) or _new_request_id()
    log = _ReqLogger(rid)

    # Pipeline lazy-init runs on the worker so its SQLite/LanceDB connections
    # are bound to the same thread we'll use for every subsequent op.
    cold_start = _pipeline is None
    if cold_start:
        log.info("pipeline cold start — loading vector + graph stores")
    pipe = await _on_worker(_get_pipeline_sync)
    k = body.k or DEFAULT_K
    n = body.n or DEFAULT_N
    timings: dict[str, int] = {}
    t_total = time.perf_counter()

    log.info(
        "ask · lang=%s mode=%s k=%d n=%d instant=%s",
        body.lang, body.mode, k, n, body.instant,
    )
    log.info("ask · question: %s", _trunc(body.question, 160))

    # Stage 1 — filters + as-of date. Cheap, inline.
    filters = infer_filters(body.question)
    as_of, _as_of_explicit = infer_as_of_date(body.question)
    filter_summary = ", ".join(f"{k_}={v_}" for k_, v_ in filters.items()) or "none"
    log.info(
        "plan · filters=%s · asof=%s",
        filter_summary, as_of.isoformat() if as_of else "today",
    )

    # Stage 1.5 — emit a starter pulse so the empty state animates immediately.
    # We don't have real NER here; ship the inferred filter keys as the
    # entity ids so the UI's pulse fires (the AnswerStream uses any
    # ner_pulse to flip phase=planning).
    yield _sse({
        "type": "ner_pulse",
        "entityNodeIds": list(filters.keys()) or ["query"],
    })

    # Stage 2 — query rewrite (LLM, can take 1-3 s on cold).
    t = time.perf_counter()
    try:
        expanded: ExpandedQuery = await _on_worker(lambda: expand_query(body.question))
        log.info(
            "query_rewrite · %d ms · cached=%s · finnish=%s",
            _ms_since(t),
            expanded.cached,
            ",".join(expanded.finnish_keywords[:4]) or "(none)",
        )
    except Exception as e:  # soft-fail to original question
        log.warning("query_rewrite FAILED (%s) — falling back to original", e)
        expanded = ExpandedQuery(
            original=body.question, expanded=body.question,
            finnish_keywords=(), year=None, cached=False,
        )
    timings["query_rewrite"] = _ms_since(t)
    retrieval_query = expanded.expanded

    # Plan event — subQuestions surface the k/n + filters so the UI's
    # planning panel reads like a debugger trace. entityNodeIds becomes
    # the Finnish keyword chips the OrbitGraph pulses on.
    yield _sse({
        "type": "plan",
        "subQuestions": [
            f"Retrieve k={k}, assemble n={n}",
            f"Filters: {filter_summary}",
            f"As of: {as_of.isoformat() if as_of else 'today'}",
        ],
        "entityNodeIds": list(expanded.finnish_keywords or [])[:6],
    })

    # Stage 3 — vector retrieve (k as supplied; default 50).
    t = time.perf_counter()
    hits = await _on_worker(
        lambda: pipe.retriever.retrieve(
            retrieval_query, k=k, filters=filters or None
        )
    )
    timings["vector_retrieve"] = _ms_since(t)
    log.info(
        "retrieve · k=%d · returned=%d · best_cos=%.3f · %d ms",
        k, len(hits),
        max((h.cosine_sim for h in hits), default=0.0),
        timings["vector_retrieve"],
    )
    if log.debug and logger.isEnabledFor(logging.DEBUG):
        for i, h in enumerate(hits[:5], start=1):
            log.debug(
                "  hit %d  cos=%.3f  sub=%-14s  %s",
                i, h.cosine_sim, h.source_subcorpus, h.chunk_id,
            )

    # Emit a walked event per top hit so the orbit's "wiring" animation
    # has something to chew on while rerank runs.
    for i, h in enumerate(hits[:8], start=1):
        if await request.is_disconnected():
            log.warning("client disconnected during walked events — aborting")
            return
        yield _sse({
            "type": "walked",
            "nodeId": h.chunk_id,
            "score": float(h.cosine_sim),
            "step": i,
        })

    # Stage 4 — rerank (cosine + authority + recency + term + repealed).
    t = time.perf_counter()
    unique_section_ids = list({h.section_id for h in hits})
    temporal_status_map = await _on_worker(
        lambda: pipe.graph.get_temporal_status_map(unique_section_ids)
    )
    reranked: list[RerankedHit] = await _on_worker(
        lambda: rerank(
            body.question, hits, temporal_status_map=temporal_status_map
        )
    )
    timings["rerank"] = _ms_since(t)
    log.info(
        "rerank · candidates=%d · top_score=%.3f · %d ms",
        len(reranked),
        reranked[0].score if reranked else 0.0,
        timings["rerank"],
    )

    # Stage 5 — assemble (n as supplied; default 12).
    t = time.perf_counter()
    context: AssembledContext = await _on_worker(
        lambda: assemble(reranked, graph=pipe.graph, n=n, as_of=as_of)
    )
    timings["assemble"] = _ms_since(t)
    log.info(
        "assemble · sources=%d · context_chars=%d · %d ms",
        len(context.sources), len(context.text), timings["assemble"],
    )
    if logger.isEnabledFor(logging.DEBUG):
        for s in context.sources[:5]:
            log.debug(
                "  src %d  rerank=%.3f  %s",
                s.index, s.rerank_score, s.chunk_id,
            )

    if not context.sources:
        log.warning("no sources matched the question — emitting error event")
        yield _sse({"type": "error", "message": "No sources matched the question."})
        yield _sse({"type": "done"})
        return

    # Build + emit the orbit subgraph BEFORE the LLM call so the UI has the
    # context visible while the answer streams in. ``build_orbit`` calls
    # ``graph.get_node`` + ``graph.get_neighbors`` per source, so it has to
    # run on the pinned worker too.
    orbit_nodes, orbit_edges, _src_by_chunk = await _on_worker(
        lambda: build_orbit(context, graph=pipe.graph, cited_chunk_ids=[])
    )
    log.info(
        "orbit · nodes=%d · edges=%d",
        len(orbit_nodes), len(orbit_edges),
    )
    yield _sse({
        "type": "subgraph_ready",
        "orbitNodes": orbit_nodes,
        "orbitEdges": orbit_edges,
    })

    # Pre-warm the /excerpt cache for every orbit node. The frontend
    # CitationDrawer aborts the request after 2 s; LanceDB's first cold
    # scan per chunk can blow that budget. We do them all in one bulk
    # ``IN (...)`` query, then stuff the rows into the per-id cache so
    # subsequent /excerpt calls are O(1) dict reads.
    orbit_chunk_ids = [n["id"] for n in orbit_nodes]
    if orbit_chunk_ids:
        t = time.perf_counter()
        prefetched = await _on_worker(
            lambda: _prefetch_chunk_rows(pipe, orbit_chunk_ids)
        )
        log.info(
            "excerpt_prefetch · warmed=%d/%d · %d ms",
            prefetched, len(orbit_chunk_ids), _ms_since(t),
        )

    # Stage 6 — generate.
    t = time.perf_counter()
    history_payload = [
        {"role": m.role, "content": m.content} for m in body.history
    ]
    if history_payload:
        log.info(
            "generate · prior turns=%d (user/assistant pairs)",
            len(history_payload) // 2,
        )
    try:
        gen = await _on_worker(
            lambda: generate(body.question, context, history=history_payload)
        )
    except Exception as e:
        log.exception("generate FAILED")
        yield _sse({"type": "error", "message": f"Generation failed: {e}"})
        yield _sse({"type": "done"})
        return
    timings["generate"] = _ms_since(t)
    log.info(
        "generate · answer_chars=%d · cited=%s · %d ms",
        len(gen.answer),
        ",".join(str(i) for i in gen.cited_indices) or "(none)",
        timings["generate"],
    )

    # Rewrite [Source N] → [cite:node:<chunk_id>]Source N[/cite] before
    # streaming so the frontend's render path attaches hover handlers.
    answer_with_cites = rewrite_citations(gen.answer, context)
    chunks = _draft_chunks(answer_with_cites)

    # Per-chunk delay so the typewriter effect is visible. The frontend
    # passes ``instant: true`` for screenshots / e2e — honor that.
    delay = 0.0 if body.instant else 0.025
    aborted = False
    for i, chunk in enumerate(chunks):
        if await request.is_disconnected():
            aborted = True
            log.warning(
                "client disconnected mid-stream after %d/%d draft chunks",
                i, len(chunks),
            )
            return
        yield _sse({"type": "draft_token", "text": chunk})
        if delay:
            await asyncio.sleep(delay)

    timings["total"] = _ms_since(t_total)
    cents = estimate_cost_cents(gen.answer, context, question=body.question)

    # Cost meter + done.
    yield _sse({"type": "cost", "cents": cents})
    yield _sse({"type": "done"})

    # End-of-request banner with the timing breakdown — one line per stage
    # ordered so it reads like the pipeline diagram.
    log.info(
        "done · total=%d ms · breakdown=%s · cost~%.3f¢",
        timings.get("total", 0),
        " ".join(
            f"{label}={timings[label]}ms"
            for label in (
                "query_rewrite", "vector_retrieve", "rerank",
                "assemble", "generate",
            )
            if label in timings
        ),
        cents,
    )
    if aborted:
        log.warning("stream aborted before completion")


@app.post("/ask")
async def ask(body: AskBody, request: Request) -> StreamingResponse:
    # Ensure middleware has stamped a request id (defensive — middleware
    # always runs first, but the stream pulls from request.state).
    rid = getattr(request.state, "request_id", None) or _new_request_id()
    request.state.request_id = rid
    return StreamingResponse(
        _ask_stream(body, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Request-Id": rid,
        },
    )


# ----------------------------------------------------------------------
# /excerpt — citation drawer payload
# ----------------------------------------------------------------------


def _embedded_body(embedded_text: str | None) -> str:
    """Strip the ``[Path:…]``/``[Title:…]`` prefix off ``embedded_text``."""
    if not embedded_text:
        return ""
    parts = embedded_text.split("\n\n", 1)
    return parts[1] if len(parts) == 2 else parts[0]


def _excerpt_publisher(source: str | None, subcorpus: str | None) -> str:
    """``ExcerptResponse.publisher`` is a fixed enum on the TS side."""
    if (source or "").lower() == "vero":
        return "vero"
    if (subcorpus or "").lower() == "treaty":
        return "eur-lex"
    return "finlex"


def _excerpt_url(chunk_id: str, source: str | None, subcorpus: str | None) -> str:
    """Best-effort canonical URL from the chunk_id structure.

    Falls back to the publisher's landing page. The frontend's synthesize
    helper covers the same shape; we mirror it here so direct callers get
    a useful link even without the frontend proxy.
    """
    parts = chunk_id.split("/")
    src = (source or (parts[0] if parts else "")).lower()
    sub = (subcorpus or (parts[1] if len(parts) > 1 else "")).lower()
    if src == "vero":
        return "https://www.vero.fi/syventavat-vero-ohjeet/"
    if sub == "kho":
        return "https://www.finlex.fi/fi/oikeus/kho/"
    if sub in {"laki", "asetus", "laki_skk", "asetus_skk"} and len(parts) >= 3:
        # Pull the slug between the "finlex-<sub>-" prefix and the "-html-<hash>"
        # suffix and shove it through Finlex's search page.
        slug = parts[2]
        slug = re.sub(r"^finlex-(?:laki|asetus|kho|laki_skk|asetus_skk|treaty)-", "", slug)
        slug = re.sub(r"-html-[0-9a-f]{6,}$", "", slug, flags=re.IGNORECASE)
        terms = "+".join(slug.split("-")[:4]) or slug
        return f"https://www.finlex.fi/fi/laki/ajantasa/?search%5Btype%5D=pika&search%5Bpika%5D={terms}"
    return "https://www.finlex.fi/"


_CHUNK_LOOKUP_BY_ID: dict[str, dict[str, Any]] = {}


def _lookup_chunk_row(chunk_id: str) -> dict[str, Any] | None:
    """Read one chunk row from LanceDB by chunk_id, cached.

    LanceDB doesn't expose ``get_by_id``, so we use a ``where`` scan. Cache
    locally because excerpt requests cluster around the same handful of
    cited nodes per question.
    """
    if chunk_id in _CHUNK_LOOKUP_BY_ID:
        return _CHUNK_LOOKUP_BY_ID[chunk_id]
    pipe = get_pipeline()
    # v1 ``Pipeline`` exposes the LanceDB connection via ``retriever.store``.
    # (PipelineV2 had a convenience ``vector_store`` alias; v1 doesn't.)
    store = pipe.retriever.store
    if store.table is None:
        return None
    quoted = chunk_id.replace("'", "''")
    try:
        arrow = (
            store.table.search()
            .where(f"chunk_id = '{quoted}'", prefilter=True)
            .limit(1)
            .to_arrow()
        )
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("lancedb scan for %s failed: %s", chunk_id, e)
        return None
    rows = arrow.to_pylist()
    row = rows[0] if rows else None
    if row is not None:
        _CHUNK_LOOKUP_BY_ID[chunk_id] = row
    return row


def _prefetch_chunk_rows(pipe: Pipeline, chunk_ids: list[str]) -> int:
    """Bulk-warm ``_CHUNK_LOOKUP_BY_ID`` for a list of chunk_ids.

    One ``IN (...)`` scan instead of N point lookups. The default frontend
    timeout on ``/api/excerpt`` is 2 s; one bulk scan against a few-thousand-
    row prefilter is well under that even cold, and the per-id cache
    immediately picks up hits from there.

    Returns the number of rows actually written into the cache.
    """
    # v1 ``Pipeline`` exposes the LanceDB connection via ``retriever.store``.
    # (PipelineV2 had a convenience ``vector_store`` alias; v1 doesn't.)
    store = pipe.retriever.store
    if store.table is None or not chunk_ids:
        return 0
    todo = [cid for cid in chunk_ids if cid not in _CHUNK_LOOKUP_BY_ID]
    if not todo:
        return 0
    quoted = ",".join("'" + cid.replace("'", "''") + "'" for cid in todo)
    try:
        arrow = (
            store.table.search()
            .where(f"chunk_id IN ({quoted})", prefilter=True)
            .limit(len(todo) + 8)
            .to_arrow()
        )
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("lancedb prefetch failed: %s", e)
        return 0
    warmed = 0
    for row in arrow.to_pylist():
        cid = row.get("chunk_id")
        if cid and cid not in _CHUNK_LOOKUP_BY_ID:
            _CHUNK_LOOKUP_BY_ID[cid] = row
            warmed += 1
    return warmed


def _highlight(body: str) -> str:
    """Wrap an obvious quotable fragment in ``<mark class="claim-match">``.

    Cheapest useful highlight: the first sentence under ~280 chars. The UI
    will look fine without one when this misses; the mark is a hint, not a
    contract.
    """
    if not body:
        return ""
    # Escape HTML first; the frontend renders this with dangerouslySetInnerHTML.
    escaped = (
        body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    # First sentence-ish chunk.
    m = re.match(r"(.{20,280}?[\.!\?])(\s|$)", escaped, flags=re.DOTALL)
    if m:
        prefix = escaped[: m.start()]
        sent = m.group(1)
        rest = escaped[m.end() :]
        return f'{prefix}<mark class="claim-match">{sent}</mark>{rest}'
    return escaped


def _excerpt_payload(node_id: str) -> dict[str, Any] | None:
    """Synchronous excerpt lookup. Must run on the pinned worker thread."""
    pipe = _get_pipeline_sync()
    row = _lookup_chunk_row(node_id)

    if row is not None:
        section_id = row.get("section_id", node_id)
        body = _embedded_body(row.get("embedded_text"))
        node = pipe.graph.get_node(section_id)
        title = (getattr(node, "title", None) if node else None) or node_id
        publisher = _excerpt_publisher(row.get("source"), row.get("source_subcorpus"))
        language = row.get("language") or "fi"
        return {
            "nodeId": node_id,
            "sourceUrl": _excerpt_url(
                node_id, row.get("source"), row.get("source_subcorpus")
            ),
            "publisher": publisher,
            "docTitle": title,
            "excerptHtml": _highlight(body),
            "contextHtml": "",
            "lang": language,
            "tValid": row.get("publication_date"),
            "tInvalid": None,
        }

    # No chunk row — maybe ``node_id`` is a graph node. Render its text.
    node = pipe.graph.get_node(node_id)
    if node is None:
        return None

    title = node.title or node.label or node_id
    publisher = _excerpt_publisher(node.source, getattr(node, "source_subcorpus", None))
    return {
        "nodeId": node_id,
        "sourceUrl": _excerpt_url(node_id, node.source, None),
        "publisher": publisher,
        "docTitle": title,
        "excerptHtml": _highlight(node.text or ""),
        "contextHtml": "",
        "lang": getattr(node.metadata, "language", None) or "fi",
    }


@app.get("/excerpt")
async def excerpt(node_id: str) -> JSONResponse:
    """Citation drawer payload for the frontend's `<CitationDrawer>`.

    Accepts either a chunk_id (the values we send as cite anchors) or a
    section_id (LRMoo work / component handles). The chunk path is the
    common case — every ``[cite:node:X]`` token holds a chunk_id.
    """
    if not node_id:
        raise HTTPException(status_code=400, detail="missing node_id")
    payload = await _on_worker(lambda: _excerpt_payload(node_id))
    if payload is None:
        # Let the frontend synthesize via its own fallback by 404-ing.
        raise HTTPException(status_code=404, detail=f"unknown node: {node_id}")
    return JSONResponse(payload)


# ----------------------------------------------------------------------
# Utility
# ----------------------------------------------------------------------


def _ms_since(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)
