"""Eval harness reporter — aggregates grade JSONL files into a dashboard.

Reads ``eval/runs/<config_id>.jsonl`` and ``eval/grades/<config_id>.jsonl``,
joins on ``question_id``, and writes under ``findings/06_eval_harness/``:
``summary.csv``, ``summary.md``, ``per_question.csv``, ``stage_latency.csv``.

    python -m scripts.report_eval [--runs-dir eval/runs] [--grades-dir eval/grades]
                                  [--out-dir findings/06_eval_harness]
                                  [--configs v1-current,v2-cross,...] [--no-judge]

Stdlib-only. See ``eval/SCHEMA.md`` for the row contracts this consumes.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNS_DIR = REPO_ROOT / "eval" / "runs"
DEFAULT_GRADES_DIR = REPO_ROOT / "eval" / "grades"
DEFAULT_OUT_DIR = REPO_ROOT / "findings" / "06_eval_harness"

KNOWN_CONFIGS = ["v1-current", "v1-bare", "v2-cross", "v2-vector", "v2-no-rewrite", "v2-no-hybrid"]
TIER_GROUPS = ["all", "Q-set", "N-set", "basic", "medium", "hard",
               "difficulty_1", "difficulty_2", "difficulty_3", "difficulty_4", "difficulty_5"]
STAGE_KEYS = ["filter_infer", "query_rewrite", "vector_retrieve", "rerank", "graph_expand",
              "cross_encoder", "vector_rerank", "assemble", "generate", "total"]
# Below this abs delta on judge_correctness / key_fact_recall we call (config vs v1) a tie.
WIN_LOSS_TOLERANCE = 0.02
_STRATEGY_PREFIX = "Expansion strategy:"
SUMMARY_CSV_COLS = ["config_id", "tier_group", "n_questions", "n_errors", "n_refusals",
    "key_fact_recall_mean", "numeric_recall_mean",
    "citation_publisher_precision_mean", "citation_publisher_recall_mean",
    "judge_correctness_mean", "judge_grounding_mean", "judge_completeness_mean",
    "latency_p50_ms", "latency_p95_ms",
    "total_latency_ms_sum", "generate_ms_mean", "retrieve_ms_mean", "rerank_ms_mean"]
# (display, source-key, higher-is-better, decimals); config row is special-cased.
_SCOREBOARD_SPEC = [
    ("config", "config_id", None, None),
    ("key_fact_recall", "key_fact_recall_mean", True, 2), ("numeric_recall", "numeric_recall_mean", True, 2),
    ("refusal_rate", "_refusal_rate", False, 2),
    ("cite_prec", "citation_publisher_precision_mean", True, 2),
    ("cite_recall", "citation_publisher_recall_mean", True, 2),
    ("judge_correctness", "judge_correctness_mean", True, 2),
    ("judge_grounding", "judge_grounding_mean", True, 2),
    ("judge_completeness", "judge_completeness_mean", True, 2),
    ("latency_p50", "latency_p50_ms", False, 0), ("latency_p95", "latency_p95_ms", False, 0),
]

def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows

def _git_commit() -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                      cwd=REPO_ROOT, stderr=subprocess.DEVNULL)
        return out.decode("ascii", errors="ignore").strip()
    except Exception:
        return "unknown"

def _load_config_data(config_id: str, runs_dir: Path, grades_dir: Path) -> list[dict[str, Any]]:
    """Join run+grade rows on question_id. Grades with no matching run are dropped."""
    runs = _read_jsonl(runs_dir / f"{config_id}.jsonl")
    grades = _read_jsonl(grades_dir / f"{config_id}.jsonl")
    runs_by_qid = {r.get("question_id"): r for r in runs if isinstance(r.get("question_id"), str)}
    grades_by_qid: dict[str, dict[str, Any]] = {}
    for g in grades:
        qid = g.get("question_id")
        if not isinstance(qid, str):
            continue
        if qid not in runs_by_qid:
            print(f"[report_eval] WARN: grade for {config_id}/{qid} has no matching run; skipping",
                  file=sys.stderr)
            continue
        grades_by_qid[qid] = g
    return [{"question_id": qid, "tier": run.get("tier"), "run": run,
             "grade": grades_by_qid.get(qid)} for qid, run in runs_by_qid.items()]

def _tier_matches(tg: str, tier: str | None, qid: str) -> bool:
    if tg == "all":
        return True
    if tg == "Q-set":
        return isinstance(qid, str) and qid.startswith("Q")
    if tg == "N-set":
        return isinstance(qid, str) and qid.startswith("N")
    return tier == tg

def _mean(vals: list[float]) -> float | None:
    return statistics.fmean(vals) if vals else None

def _quantile(vals: list[float], q: float) -> float | None:
    # Hand-rolled to stay stable on tiny samples where statistics.quantiles errors.
    if not vals:
        return None
    if len(vals) == 1:
        return float(vals[0])
    s = sorted(vals); pos = (len(s) - 1) * q
    lo = int(pos); hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)

_DET_KEYS = ("key_fact_recall", "numeric_recall",
             "citation_publisher_precision", "citation_publisher_recall")
_JUDGE_KEYS = ("correctness", "grounding", "completeness")

def _aggregate(rows: list[dict[str, Any]], tier_group: str, *, include_judge: bool) -> dict[str, Any] | None:
    sel = [r for r in rows if _tier_matches(tier_group, r["tier"], r["question_id"])]
    if not sel:
        return None
    n = len(sel)
    n_errors = sum(1 for r in sel if (r["run"] or {}).get("error"))
    series: dict[str, list[float]] = defaultdict(list)
    refusals = 0
    elapsed: list[float] = []
    stages: dict[str, list[float]] = defaultdict(list)
    for r in sel:
        run, grade = r["run"] or {}, r["grade"] or {}
        if run.get("error"):
            continue
        det = grade.get("deterministic") or {}
        for k in _DET_KEYS:
            v = det.get(k)
            if isinstance(v, (int, float)):
                series[k].append(float(v))
        if det.get("refusal_detected"):
            refusals += 1
        if include_judge:
            j = grade.get("judge") or {}
            for k in _JUDGE_KEYS:
                v = j.get(k)
                if isinstance(v, (int, float)):
                    series["judge_" + k].append(float(v))
        e = run.get("elapsed_ms")
        if isinstance(e, (int, float)):
            elapsed.append(float(e))
        for k, v in (((run.get("answer_result") or {}).get("timing_ms")) or {}).items():
            if isinstance(v, (int, float)):
                stages[k].append(float(v))
    # elapsed_ms is wall-clock from the driver; timing_ms.total is the pipeline's
    # own sum-of-stages — they should agree to within a few ms but aren't identical.
    return {
        "tier_group": tier_group, "n_questions": n, "n_errors": n_errors, "n_refusals": refusals,
        "key_fact_recall_mean": _mean(series["key_fact_recall"]),
        "numeric_recall_mean": _mean(series["numeric_recall"]),
        "citation_publisher_precision_mean": _mean(series["citation_publisher_precision"]),
        "citation_publisher_recall_mean": _mean(series["citation_publisher_recall"]),
        "judge_correctness_mean": _mean(series["judge_correctness"]) if include_judge else None,
        "judge_grounding_mean": _mean(series["judge_grounding"]) if include_judge else None,
        "judge_completeness_mean": _mean(series["judge_completeness"]) if include_judge else None,
        "latency_p50_ms": _quantile(elapsed, 0.5), "latency_p95_ms": _quantile(elapsed, 0.95),
        "total_latency_ms_sum": sum(elapsed) if elapsed else None,
        "generate_ms_mean": _mean(stages.get("generate", [])),
        "retrieve_ms_mean": _mean(stages.get("vector_retrieve", [])),
        "rerank_ms_mean": (_mean(stages.get("rerank", [])) or _mean(stages.get("cross_encoder", []))
                           or _mean(stages.get("vector_rerank", []))),
        "_stage_means": {k: _mean(v) for k, v in stages.items()},
        "_refusal_rate": (refusals / n) if n else None,
    }

def _fmt(val: Any, decimals: int = 2) -> str:
    if val is None:
        return ""
    return f"{val:.{decimals}f}" if isinstance(val, float) else str(val)

def _fmt_csv(val: Any) -> str:
    if val is None:
        return ""
    return f"{val:.4f}" if isinstance(val, float) else str(val)

def _bold_best(rows: list[dict[str, Any]], col: str, *, higher: bool, dec: int = 2) -> dict[str, str]:
    valued = [(r["config_id"], r.get(col)) for r in rows if r.get(col) is not None]
    if not valued:
        return {r["config_id"]: "" for r in rows}
    best = (max if higher else min)(v for _, v in valued)
    return {cid: ("" if v is None else (f"**{_fmt(v, dec)}**" if v == best else _fmt(v, dec)))
            for cid, v in [(r["config_id"], r.get(col)) for r in rows]}

def _scoreboard_table(summaries: list[dict[str, Any]], *, include_judge: bool) -> str:
    if not summaries:
        return "_(no data)_\n"
    sort_key = "judge_correctness_mean" if include_judge else "key_fact_recall_mean"
    if not any(r.get(sort_key) is not None for r in summaries):
        sort_key = "key_fact_recall_mean"
    summaries = sorted(summaries, key=lambda r: (r.get(sort_key) is None, -(r.get(sort_key) or 0)))
    spec = _SCOREBOARD_SPEC if include_judge else [s for s in _SCOREBOARD_SPEC if not s[0].startswith("judge_")]
    bolded = {disp: _bold_best(summaries, src, higher=hib, dec=dec)
              for disp, src, hib, dec in spec if disp != "config"}
    headers = [s[0] for s in spec]
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in summaries:
        cells = [r["config_id"] if disp == "config" else bolded[disp][r["config_id"]]
                 for disp, _, _, _ in spec]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"

def _stage_latency_table(summaries_all: dict[str, dict[str, Any]]) -> str:
    headers = ["config"] + STAGE_KEYS
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join(["---"] * len(headers)) + "|"]
    for cid, s in summaries_all.items():
        means = s.get("_stage_means", {})
        cells = [cid] + [(_fmt(means.get(k), 0) if means.get(k) is not None else "") for k in STAGE_KEYS]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"

def _pivot_metric(grade: dict[str, Any] | None, include_judge: bool) -> float | None:
    if not grade:
        return None
    if include_judge:
        c = (grade.get("judge") or {}).get("correctness")
        if isinstance(c, (int, float)):
            return float(c)
    v = (grade.get("deterministic") or {}).get("key_fact_recall")
    return float(v) if isinstance(v, (int, float)) else None

def _qid_sort_key(qid: str) -> tuple[int, int, str]:
    # Q1..Q35 first, then N1..N48; numeric suffixes sort numerically.
    if not qid:
        return (2, 0, "")
    prefix_rank = 0 if qid.startswith("Q") else (1 if qid.startswith("N") else 2)
    num_part = "".join(c for c in qid[1:] if c.isdigit())
    n = int(num_part) if num_part else 0
    return (prefix_rank, n, qid)

def _build_per_question(data: dict[str, list[dict[str, Any]]], configs: list[str],
                        include_judge: bool) -> list[dict[str, Any]]:
    qids: set[str] = set()
    tier_by_qid: dict[str, str] = {}
    gold_by_qid: dict[str, list[str]] = {}
    by_cid_qid: dict[tuple[str, str], dict[str, Any]] = {}
    for cid in configs:
        for r in data.get(cid, []):
            qid = r["question_id"]
            qids.add(qid); by_cid_qid[(cid, qid)] = r
            if qid not in tier_by_qid and r.get("tier"):
                tier_by_qid[qid] = r["tier"]
            gp = (r.get("run") or {}).get("gold_citation_publishers") or []
            if qid not in gold_by_qid and gp:
                gold_by_qid[qid] = list(gp)
    rows: list[dict[str, Any]] = []
    for qid in sorted(qids, key=_qid_sort_key):
        row: dict[str, Any] = {"question_id": qid, "tier": tier_by_qid.get(qid, ""),
                               "gold_publishers": "|".join(gold_by_qid.get(qid, []))}
        for cid in configs:
            entry = by_cid_qid.get((cid, qid))
            grade = (entry or {}).get("grade") if entry else None
            det = (grade or {}).get("deterministic") or {}
            j = (grade or {}).get("judge") or {}
            row[f"{cid}_error"] = "1" if (entry and ((entry.get("run") or {}).get("error"))) else ""
            row[f"{cid}_key_fact_recall"] = det.get("key_fact_recall")
            row[f"{cid}_numeric_recall"] = det.get("numeric_recall")
            row[f"{cid}_cite_prec"] = det.get("citation_publisher_precision")
            row[f"{cid}_cite_recall"] = det.get("citation_publisher_recall")
            if include_judge:
                row[f"{cid}_judge_correctness"] = j.get("correctness")
                row[f"{cid}_judge_grounding"] = j.get("grounding")
                row[f"{cid}_judge_completeness"] = j.get("completeness")
        rows.append(row)
    return rows

def _winloss_pivot_table(per_q: list[dict[str, Any]], other_configs: list[str], include_judge: bool,
                         data: dict[str, list[dict[str, Any]]], cap: int = 30) -> str:
    if not other_configs:
        return "_(only v1-current is present)_\n"
    v1_by_qid = {r["question_id"]: r for r in data.get("v1-current", [])}
    by_cid_qid: dict[tuple[str, str], dict[str, Any]] = {
        (cid, r["question_id"]): r for cid in other_configs for r in data.get(cid, [])
    }
    headers = ["question_id", "tier"] + other_configs
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join(["---"] * len(headers)) + "|"]
    shown = 0
    for row in per_q:
        if shown >= cap:
            break
        qid = row["question_id"]
        v1_entry = v1_by_qid.get(qid)
        if not v1_entry:
            continue
        v1_metric = _pivot_metric(v1_entry.get("grade"), include_judge)
        v1_err = (v1_entry.get("run") or {}).get("error")
        cells = [qid, row.get("tier", "")]
        for cid in other_configs:
            other = by_cid_qid.get((cid, qid))
            if not other:
                cells.append("?"); continue
            if (other.get("run") or {}).get("error"):
                cells.append("e"); continue
            other_metric = _pivot_metric(other.get("grade"), include_judge)
            if other_metric is None or v1_metric is None or v1_err:
                cells.append("?"); continue
            delta = other_metric - v1_metric
            cells.append("=" if abs(delta) <= WIN_LOSS_TOLERANCE else ("+" if delta > 0 else "-"))
        lines.append("| " + " | ".join(cells) + " |")
        shown += 1
    total = sum(1 for r in per_q if r["question_id"] in v1_by_qid)
    if total > shown:
        lines.append(f"\n… ({total - shown} more rows omitted, see per_question.csv)")
    return "\n".join(lines) + "\n"

def _strategy_for_run(run: dict[str, Any]) -> str | None:
    for a in (run.get("answer_result") or {}).get("assumptions") or []:
        if isinstance(a, str) and a.startswith(_STRATEGY_PREFIX):
            return a[len(_STRATEGY_PREFIX):].strip()
    return None

def _strategy_tables(data: dict[str, list[dict[str, Any]]]) -> str:
    parts: list[str] = []
    for cid in sorted(c for c in data if c.startswith("v2")):
        counter: Counter[str] = Counter()
        for r in data[cid]:
            run = r.get("run") or {}
            if run.get("error"):
                continue
            strat = _strategy_for_run(run)
            if strat:
                counter[strat] += 1
        if not counter:
            continue
        parts += [f"**{cid}**\n", "| strategy | count |", "|---|---|"]
        parts += [f"| {strat} | {count} |" for strat, count in counter.most_common()]
        parts.append("")
    return ("\n".join(parts) + "\n") if parts else "_(no v2 configs with strategy assumptions)_\n"

def _write_csv(path: Path, cols: list[str], data_rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for row in data_rows:
            w.writerow([_fmt_csv(v) for v in row])

def _per_question_cols(configs: list[str], include_judge: bool) -> list[str]:
    cols = ["question_id", "tier", "gold_publishers"]
    for cid in configs:
        cols += [f"{cid}_error", f"{cid}_key_fact_recall", f"{cid}_numeric_recall",
                 f"{cid}_cite_prec", f"{cid}_cite_recall"]
        if include_judge:
            cols += [f"{cid}_judge_correctness", f"{cid}_judge_grounding", f"{cid}_judge_completeness"]
    return cols

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    p.add_argument("--grades-dir", default=str(DEFAULT_GRADES_DIR))
    p.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    p.add_argument("--configs", default=None,
                   help="Comma-separated config_ids to report on (default: all known).")
    p.add_argument("--no-judge", action="store_true", help="Omit judge columns from outputs.")
    args = p.parse_args()
    runs_dir, grades_dir, out_dir = Path(args.runs_dir), Path(args.grades_dir), Path(args.out_dir)
    include_judge = not args.no_judge

    if args.configs:
        configs = [c.strip() for c in args.configs.split(",") if c.strip()]
    else:
        configs = [c for c in KNOWN_CONFIGS if (runs_dir / f"{c}.jsonl").exists()] or list(KNOWN_CONFIGS)

    data: dict[str, list[dict[str, Any]]] = {}
    for cid in configs:
        rows = _load_config_data(cid, runs_dir, grades_dir)
        data[cid] = rows
        print(f"[report_eval] loaded {cid}: {len(rows)} rows", file=sys.stderr)
    configs = [c for c in configs if data.get(c)]
    if not configs:
        print("[report_eval] no data found; nothing to report.", file=sys.stderr)
        return 1

    summary_rows: list[dict[str, Any]] = []
    overall_by_config: dict[str, dict[str, Any]] = {}
    per_tier: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cid in configs:
        for tg in TIER_GROUPS:
            s = _aggregate(data[cid], tg, include_judge=include_judge)
            if s is None:
                continue
            s["config_id"] = cid
            summary_rows.append(s)
            if tg == "all":
                overall_by_config[cid] = s
            else:
                per_tier[tg].append(s)

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(out_dir / "summary.csv", SUMMARY_CSV_COLS,
               [[r.get(c) for c in SUMMARY_CSV_COLS] for r in summary_rows])
    per_q = _build_per_question(data, configs, include_judge)
    pq_cols = _per_question_cols(configs, include_judge)
    _write_csv(out_dir / "per_question.csv", pq_cols, [[r.get(c) for c in pq_cols] for r in per_q])
    sl_cols = ["config_id"] + STAGE_KEYS
    _write_csv(out_dir / "stage_latency.csv", sl_cols,
               [[cid] + [s.get("_stage_means", {}).get(k) for k in STAGE_KEYS]
                for cid, s in overall_by_config.items()])

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    commit = _git_commit()
    n_qids_seen = len({r["question_id"] for cid in configs for r in data[cid]})
    md = [
        "# Eval harness — dashboard\n",
        f"_Generated: {now} · commit `{commit}` · configs: {len(configs)} · questions seen: {n_qids_seen}_\n",
        "## Overall scoreboard\n",
        _scoreboard_table([overall_by_config[c] for c in configs if c in overall_by_config],
                          include_judge=include_judge),
        "\n## Per-tier breakdown\n",
    ]
    for tg in [t for t in TIER_GROUPS if t != "all" and per_tier.get(t)]:
        md += [f"### {tg}\n", _scoreboard_table(per_tier[tg], include_judge=include_judge), ""]
    md += ["\n## Stage-latency profile (mean ms)\n", _stage_latency_table(overall_by_config),
           "\n## Per-question pivot — wins/losses vs v1-current\n",
           "Legend: `+` better, `-` worse, `=` within ±0.02, `e` errored, `?` missing/unscored.\n"]
    md.append(_winloss_pivot_table(per_q, [c for c in configs if c != "v1-current"], include_judge, data)
              if "v1-current" in configs else "_v1-current not present; pivot skipped._\n")
    md += ["\n## v2 strategy distribution\n", _strategy_tables(data), "\n## Known limitations\n",
        ("- The gold may have stale facts (e.g., Q35 €10k → €20k).\n"
         "- Hand-labeled section-level recall is not measured.\n"
         "- Refusals on answerable questions count as misses; refusal_rate is reported separately.\n"
         "- N-prefix `answer_key_facts` may be a strict subset of the full answer.\n"),
        "\n## Footer\n",
        ("Source data: `eval/runs/` (driver output), `eval/grades/` (grader output).\n\n"
         "Reproduce:\n\n```bash\n"
         "python -m scripts.run_eval --tier A && \\\n"
         "python -m scripts.grade_eval && \\\n"
         "python -m scripts.report_eval\n```\n")]
    (out_dir / "summary.md").write_text("\n".join(md), encoding="utf-8")
    print(f"[report_eval] wrote outputs to {out_dir}", file=sys.stderr)
    return 0

if __name__ == "__main__":
    sys.exit(main())
