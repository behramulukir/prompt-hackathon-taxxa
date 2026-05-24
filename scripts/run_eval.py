"""Eval harness driver — runs configs from ``eval/configs.json`` against the
question bank in ``eval/questions.json`` and writes one JSONL row per
(config, question) to ``eval/runs/<config_id>.jsonl``.

    python -m scripts.run_eval                              # default: tier A
    python -m scripts.run_eval --config v2-cross --limit 3  # smoke test
    python -m scripts.run_eval --config v1-current,v2-cross --tier-filter basic

Append-only / resumable: a (config, question) already present in the file is
skipped. Each pipeline is built once and reused across its questions so
LanceDB open + cross-encoder warmup happen at most once per config. See
``eval/SCHEMA.md`` for the row contract.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_FILE = REPO_ROOT / "eval" / "configs.json"
DEFAULT_QUESTIONS_FILE = REPO_ROOT / "eval" / "questions.json"
RUNS_DIR = REPO_ROOT / "eval" / "runs"


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _completed_pairs(out_path: Path) -> set[str]:
    """Question_ids already written to this config's JSONL (for resumability)."""
    if not out_path.exists():
        return set()
    done: set[str] = set()
    with out_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            qid = row.get("question_id")
            if isinstance(qid, str):
                done.add(qid)
    return done


def _append_row(out_path: Path, row: dict[str, Any]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # ensure_ascii=False keeps Finnish characters readable in the JSONL.
    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False))
        f.write("\n")


def _select_config_ids(args: argparse.Namespace, configs_doc: dict[str, Any]) -> list[str]:
    if args.config:
        return [c.strip() for c in args.config.split(",") if c.strip()]
    tiers = configs_doc.get("tiers", {})
    if args.tier == "all":
        seen: set[str] = set()
        out: list[str] = []
        for group in tiers.values():
            for cid in group:
                if cid not in seen:
                    seen.add(cid)
                    out.append(cid)
        return out
    return list(tiers.get(args.tier, []))


def _select_questions(args: argparse.Namespace, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if args.questions:
        wanted = {q.strip() for q in args.questions.split(",") if q.strip()}
        entries = [e for e in entries if e.get("id") in wanted]
    if args.tier_filter:
        wanted_tiers = {t.strip() for t in args.tier_filter.split(",") if t.strip()}
        entries = [e for e in entries if e.get("tier") in wanted_tiers]
    if args.limit is not None:
        entries = entries[: args.limit]
    return entries


def _gold_citation_publishers(entry: dict[str, Any]) -> list[str]:
    pubs: set[str] = set()
    for c in entry.get("citations") or []:
        p = c.get("publisher") if isinstance(c, dict) else None
        if isinstance(p, str) and p:
            pubs.add(p)
    return sorted(pubs)


def _build_pipeline(config: dict[str, Any], defaults: dict[str, Any]):
    """Construct a fresh pipeline. We bypass the module-level singletons in
    ``src.retrieval.pipeline`` / ``pipeline_v2`` because they cache by path
    only — successive configs with different flags would silently reuse a
    stale instance.
    """
    vector_db_path = defaults["vector_db_path"]
    graph_db_path = defaults["graph_db_path"]

    if config["pipeline"] == "v1":
        from src.retrieval.pipeline import Pipeline

        pipe = Pipeline(
            vector_db_path=vector_db_path,
            graph_db_path=graph_db_path,
            query_rewrite=bool(config.get("query_rewrite", True)),
        )
    elif config["pipeline"] == "v2":
        from src.retrieval.pipeline_v2 import PipelineV2

        rerank_mode = config.get("rerank", "cross_encoder")
        if rerank_mode not in ("cross_encoder", "vector"):
            raise ValueError(
                f"config {config['id']}: rerank={rerank_mode!r} is invalid for "
                "pipeline=v2 (use 'cross_encoder' or 'vector')"
            )
        pipe = PipelineV2(
            vector_db_path=vector_db_path,
            graph_db_path=graph_db_path,
            rerank_mode=rerank_mode,
            query_rewrite=bool(config.get("query_rewrite", True)),
        )
    else:
        raise ValueError(f"unknown pipeline {config['pipeline']!r}")

    # ``hybrid`` (BM25+vector RRF) is decided inside VectorRetriever, which the
    # pipeline constructs internally with hybrid=True. Monkey-patch the live
    # retriever to honor the config flag.
    pipe.retriever.hybrid = bool(config.get("hybrid", True))
    return pipe


def _call_answer(pipe, config: dict[str, Any], question: str):
    n = int(config.get("n", 8))
    if config["pipeline"] == "v1":
        return pipe.answer(question, k=int(config.get("k", 20)), n=n)
    return pipe.answer(question, n=n)


def _format_progress(config_id: str, qid: str, tier: str, elapsed_ms: int, result, error: str | None) -> str:
    elapsed_s = elapsed_ms / 1000.0
    if error is not None:
        return f"[{config_id}] {qid} ({tier}) ... {elapsed_s:.1f}s | ERROR: {error[:120]}"
    cited = len(result.cited_source_ids) if result is not None else 0
    timings = result.timing_ms if result is not None else {}
    # Pipelines emit ``vector_retrieve``; fall back to ``retrieve`` for safety.
    retr = timings.get("vector_retrieve") or timings.get("retrieve") or 0
    gen = timings.get("generate", 0)
    return (
        f"[{config_id}] {qid} ({tier}) ... {elapsed_s:.1f}s "
        f"| cited {cited} | timing: retrieve={retr} generate={gen}"
    )


def _run_one_config(
    config: dict[str, Any],
    questions: list[dict[str, Any]],
    defaults: dict[str, Any],
    *,
    dry_run: bool,
) -> dict[str, int]:
    config_id = config["id"]
    out_path = RUNS_DIR / f"{config_id}.jsonl"
    done = _completed_pairs(out_path)
    pending = [e for e in questions if e.get("id") not in done]
    stats = {"ok": 0, "err": 0, "skipped": len(questions) - len(pending), "total": len(questions)}

    print(
        f"[{config_id}] {len(pending)} to run ({stats['skipped']} already in "
        f"{out_path.name}); pipeline={config['pipeline']} rerank={config.get('rerank')} "
        f"query_rewrite={config.get('query_rewrite')} hybrid={config.get('hybrid')}",
        file=sys.stderr,
    )
    if dry_run or not pending:
        return stats

    run_started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    pipe = _build_pipeline(config, defaults)
    try:
        for entry in pending:
            qid = entry["id"]
            tier = entry.get("tier", "")
            question = entry["question"]
            t0 = time.perf_counter()
            result = None
            error: str | None = None
            try:
                result = _call_answer(pipe, config, question)
            except Exception as exc:  # noqa: BLE001 — record and continue
                error = f"{type(exc).__name__}: {exc}"[:200]
                traceback.print_exc(file=sys.stderr)
            elapsed_ms = int((time.perf_counter() - t0) * 1000)

            _append_row(out_path, {
                "config_id": config_id,
                "question_id": qid,
                "tier": tier,
                "question": question,
                "gold_answer": entry.get("answer", ""),
                "gold_key_facts": list(entry.get("answer_key_facts") or []),
                "gold_citation_publishers": _gold_citation_publishers(entry),
                "answer_result": result.model_dump(mode="json") if result is not None else None,
                "error": error,
                "elapsed_ms": elapsed_ms,
                "run_started_at": run_started_at,
            })
            print(_format_progress(config_id, qid, tier, elapsed_ms, result, error), file=sys.stderr)
            stats["ok" if error is None else "err"] += 1
    finally:
        try:
            pipe.close()
        except Exception:  # noqa: BLE001 — close best-effort
            traceback.print_exc(file=sys.stderr)
    return stats


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the Taxxa retrieval pipelines against the question bank.")
    p.add_argument("--config", help="Comma-separated config IDs. Overrides --tier when set.")
    p.add_argument("--tier", choices=("A", "B", "all"), default="A", help="Which configs.json:tiers group. Default: A.")
    p.add_argument("--questions", help="Comma-separated question IDs (e.g. Q1,Q3).")
    p.add_argument("--tier-filter", help="Comma-separated question tiers to keep (basic,medium,hard,...).")
    p.add_argument("--limit", type=int, help="Cap on questions per config (applied after filters).")
    p.add_argument("--questions-file", type=Path, default=DEFAULT_QUESTIONS_FILE)
    p.add_argument("--config-file", type=Path, default=DEFAULT_CONFIG_FILE)
    p.add_argument("--dry-run", action="store_true", help="Print plan, skip pipeline calls and writes.")
    return p.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    configs_doc = _load_json(args.config_file)
    questions_doc = _load_json(args.questions_file)

    configs_by_id = {c["id"]: c for c in configs_doc.get("configs", [])}
    defaults = configs_doc.get("defaults", {})
    if "vector_db_path" not in defaults or "graph_db_path" not in defaults:
        print("config file is missing defaults.vector_db_path / defaults.graph_db_path", file=sys.stderr)
        return 2

    config_ids = _select_config_ids(args, configs_doc)
    unknown = [cid for cid in config_ids if cid not in configs_by_id]
    if unknown:
        print(f"unknown config id(s): {unknown}", file=sys.stderr)
        return 2
    if not config_ids:
        print("no configs selected (try --tier A / --config ...).", file=sys.stderr)
        return 2

    selected_questions = _select_questions(args, list(questions_doc.get("entries", [])))
    if not selected_questions:
        print("no questions selected after filters.", file=sys.stderr)
        return 2

    print(
        f"plan: configs={config_ids} questions={len(selected_questions)} dry_run={args.dry_run}",
        file=sys.stderr,
    )

    summary: list[tuple[str, dict[str, int]]] = []
    for cid in config_ids:
        summary.append((cid, _run_one_config(configs_by_id[cid], selected_questions, defaults, dry_run=args.dry_run)))

    print("\n=== run_eval summary ===", file=sys.stderr)
    for cid, stats in summary:
        print(
            f"[{cid}] ok={stats['ok']} err={stats['err']} skipped={stats['skipped']} total={stats['total']}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
