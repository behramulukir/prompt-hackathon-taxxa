"""Grader for the Finnish-tax-law RAG eval harness.

Reads ``eval/runs/<config_id>.jsonl`` rows produced by ``run_eval.py`` and
writes ``eval/grades/<config_id>.jsonl`` with deterministic metrics plus an
optional LLM-judge score. See ``eval/SCHEMA.md`` for the on-disk shape. The
CLI is resumable: a (config, question_id) already graded is skipped, except
that ``--judge`` will backfill missing judge blocks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.agents._llm import LLMError, chat, parse_json_object

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_DIR = REPO_ROOT / "eval" / "runs"
DEFAULT_OUT_DIR = REPO_ROOT / "eval" / "grades"
DEFAULT_VECTOR_DB = REPO_ROOT / "output" / "lancedb"
JUDGE_CACHE_PATH_NAME = ".judge_cache.json"
DEFAULT_JUDGE_MODEL = "deepseek-ai/DeepSeek-V4-Pro"
VECTOR_TABLE = "chunks"

# --- text/number normalization ----------------------------------------------

_PUNCT_STRIP_RE = re.compile(r"[^\wäöåÄÖÅ%€]+", re.UNICODE)
_WS_RE = re.compile(r"\s+")
# Captures numbers like "30 000", "30.000", "30,5", "1.5". Trailing unit is
# matched but unused — only the number group is normalized.
_NUMBER_RE = re.compile(
    # Longer alternative first: thousand-separated form requires at least one
    # separator group, so a bare "30000" falls through to the simple \d+ form.
    r"(?<![\w])(\d{1,3}(?:[  .,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"\s*(%|€|EUR|km|prosenttia|euroa|kuukauden|kk|kuukautta|vuotta)?",
    re.IGNORECASE,
)
_REFUSAL_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"do(?: not| n.t) (?:contain|provide|have|find|include)",
        r"cannot answer",
        r"provided sources? (?:do not|don.t)",
        r"ei sis[äa]ll[äa]",
        r"l[äa]hde(?:t)? eiv[äa]t sis[äa]ll[äa]",
        r"ei voida vastat",
        r"not (?:enough|sufficient) (?:information|context)",
    ]
]


def _normalize_text(text: str) -> str:
    s = _PUNCT_STRIP_RE.sub(" ", (text or "").lower())
    return _WS_RE.sub(" ", s).strip()


def _normalize_number(raw: str) -> str:
    """Canonical form: strip thousand-seps, ',' decimal -> '.', drop leading zeros.

    Heuristics: a single comma + 1-3 digit tail (not exactly 3) is a decimal;
    a single dot + exactly-3-digit tail is a Finnish thousand separator.
    """
    s = raw.strip().replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and 1 <= len(parts[1]) <= 3 and len(parts[1]) != 3:
            s = parts[0] + "." + parts[1]
        else:
            s = s.replace(",", "")
    elif "." in s:
        parts = s.split(".")
        if len(parts) == 2 and len(parts[1]) == 3:
            s = "".join(parts)
    s = s.replace(" ", "")
    if "." in s:
        whole, frac = s.split(".", 1)
        whole = whole.lstrip("0") or "0"
        frac = frac.rstrip("0")
        s = whole if not frac else f"{whole}.{frac}"
    else:
        s = s.lstrip("0") or "0"
    return s


def _is_year(num: str) -> bool:
    """4-digit years 1900-2099 are context, not numeric facts — skip for matching."""
    if "." in num or len(num) != 4 or not num.isdigit():
        return False
    return 1900 <= int(num) <= 2099


def _extract_numbers(text: str) -> list[str]:
    return [_normalize_number(m.group(1)) for m in _NUMBER_RE.finditer(text or "")]


def _unique(seq: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _refusal(answer: str) -> bool:
    return any(p.search(answer or "") for p in _REFUSAL_PATTERNS)


def _fact_matches(fact: str, answer: str) -> bool:
    """Match if >= 60% of the fact's content-words (len>=4) appear in the
    normalized answer AND every numeric value in the fact also appears among
    the answer's numbers. The 60% heuristic tolerates Finnish paraphrase
    (e.g. "kuukauden" vs "kuukautta") while still catching missing nouns.
    """
    answer_words = set(_normalize_text(answer).split())
    words = [t for t in _normalize_text(fact).split() if len(t) >= 4]
    if not words:
        return False
    if sum(1 for w in words if w in answer_words) / len(words) < 0.6:
        return False
    fact_numbers = [n for n in _extract_numbers(fact) if not _is_year(n)]
    if fact_numbers:
        answer_numbers = set(_extract_numbers(answer))
        if not all(n in answer_numbers for n in fact_numbers):
            return False
    return True


# --- LanceDB chunk resolver --------------------------------------------------


class ChunkResolver:
    """Lazy LanceDB connection: chunk_id -> {source, embedded_text}.

    Unknown ids (e.g. graph-node ids from BFS expansion) are flagged once per
    config in stderr instead of crashing.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._cache: dict[str, dict[str, Any] | None] = {}
        self._table = None
        self._init_err: str | None = None
        self._unresolved_reported: set[str] = set()

    def _ensure_table(self) -> None:
        if self._table is not None or self._init_err is not None:
            return
        try:
            import lancedb
            db = lancedb.connect(str(self.db_path))
            if VECTOR_TABLE not in db.table_names():
                self._init_err = f"table {VECTOR_TABLE!r} not in {self.db_path}"
                return
            self._table = db.open_table(VECTOR_TABLE)
        except Exception as e:  # noqa: BLE001
            self._init_err = f"lancedb open failed: {e}"

    def _fetch(self, chunk_ids: list[str]) -> None:
        self._ensure_table()
        missing = [c for c in chunk_ids if c not in self._cache]
        if not missing or self._table is None:
            for c in missing:
                self._cache.setdefault(c, None)
            return
        quoted = ", ".join("'" + c.replace("'", "''") + "'" for c in missing)
        try:
            rows = (
                self._table.search()
                .where(f"chunk_id IN ({quoted})")
                .select(["chunk_id", "source", "embedded_text"])
                .limit(len(missing))
                .to_list()
            )
        except Exception as e:  # noqa: BLE001
            print(f"[grade_eval] lancedb query failed: {e}", file=sys.stderr)
            for c in missing:
                self._cache.setdefault(c, None)
            return
        found: set[str] = set()
        for row in rows:
            cid = row.get("chunk_id")
            if not cid:
                continue
            self._cache[cid] = {
                "source": row.get("source"),
                "embedded_text": row.get("embedded_text") or "",
            }
            found.add(cid)
        for c in missing:
            if c not in found:
                self._cache[c] = None

    def get(self, chunk_id: str) -> dict[str, Any] | None:
        if chunk_id not in self._cache:
            self._fetch([chunk_id])
        return self._cache.get(chunk_id)

    def prefetch(self, chunk_ids: list[str]) -> None:
        uniq = [c for c in _unique(chunk_ids) if c not in self._cache]
        if uniq:
            self._fetch(uniq)

    def note_unresolved(self, chunk_id: str, config_id: str) -> None:
        key = f"{config_id}::{chunk_id}"
        if key in self._unresolved_reported:
            return
        self._unresolved_reported.add(key)
        reason = self._init_err or "not in vector store"
        print(f"[grade_eval] {config_id}: unresolved {chunk_id!r} ({reason})", file=sys.stderr)


# --- deterministic grading ---------------------------------------------------


def grade_deterministic(row: dict[str, Any], resolver: ChunkResolver) -> dict[str, Any]:
    ar = row.get("answer_result") or {}
    answer = ar.get("answer") or ""
    cited = list(ar.get("cited_source_ids") or [])
    retrieved = list(ar.get("retrieved_chunks") or [])
    gold_facts = list(row.get("gold_key_facts") or [])
    gold_pubs = list(row.get("gold_citation_publishers") or [])
    config_id = row.get("config_id", "?")

    matched_facts: list[str] = []
    missed_facts: list[str] = []
    for fact in gold_facts:
        (matched_facts if _fact_matches(fact, answer) else missed_facts).append(fact)
    key_fact_recall = (len(matched_facts) / len(gold_facts)) if gold_facts else None

    gold_numbers_all = _unique(n for fact in gold_facts for n in _extract_numbers(fact))
    answer_numbers_all = _unique(_extract_numbers(answer))
    gold_for_match = [n for n in gold_numbers_all if not _is_year(n)]
    answer_for_match = {n for n in answer_numbers_all if not _is_year(n)}
    missing_numbers = [n for n in gold_for_match if n not in answer_for_match]
    if not gold_numbers_all:
        numeric_recall: float | None = None
    elif not gold_for_match:
        numeric_recall = 1.0
    else:
        numeric_recall = 1.0 - len(missing_numbers) / len(gold_for_match)

    refusal = _refusal(answer)

    resolver.prefetch(cited + retrieved)
    cited_pubs_list: list[str] = []
    for cid in cited:
        info = resolver.get(cid)
        if info is None:
            resolver.note_unresolved(cid, config_id)
            continue
        if info.get("source"):
            cited_pubs_list.append(info["source"])
    cited_pubs_unique = _unique(cited_pubs_list)
    gold_pubs_set = set(gold_pubs)
    cited_pubs_set = set(cited_pubs_unique)
    overlap = cited_pubs_set & gold_pubs_set
    if not cited_pubs_set and not gold_pubs_set:
        cit_precision = 1.0
    elif not cited_pubs_set:
        cit_precision = 0.0
    else:
        cit_precision = len(overlap) / len(cited_pubs_set)
    cit_recall = (len(overlap) / len(gold_pubs_set)) if gold_pubs_set else None

    citation_count = len(cited)
    citation_inflation_flag = (
        citation_count > 0 and citation_count == len(retrieved) and refusal
    )

    # Hallucinated numbers: appear in answer but not in any retrieved chunk's
    # embedded_text. Also accept the comma-decimal form ("30,5" <-> "30.5").
    retrieved_text_blob = "\n".join(
        (resolver.get(cid) or {}).get("embedded_text") or "" for cid in retrieved
    )
    hallucinated: list[str] = []
    for n in answer_numbers_all:
        if _is_year(n):
            continue
        if n in retrieved_text_blob:
            continue
        if "." in n and n.replace(".", ",") in retrieved_text_blob:
            continue
        hallucinated.append(n)
    hallucinated = hallucinated[:20]

    return {
        "key_fact_recall": key_fact_recall,
        "key_facts_total": len(gold_facts),
        "key_facts_matched": len(matched_facts),
        "matched_facts": matched_facts,
        "missed_facts": missed_facts,
        "numeric_recall": numeric_recall,
        "gold_numbers": gold_numbers_all,
        "answer_numbers": answer_numbers_all,
        "missing_numbers": missing_numbers,
        "refusal_detected": refusal,
        "citation_publisher_precision": cit_precision,
        "citation_publisher_recall": cit_recall,
        "cited_publishers": cited_pubs_unique,
        "gold_publishers": sorted(gold_pubs_set),
        "citation_count": citation_count,
        "citation_inflation_flag": citation_inflation_flag,
        "hallucinated_numbers": hallucinated,
        "answer_length_words": len(answer.split()),
    }


# --- judge -------------------------------------------------------------------

JUDGE_SYSTEM = (
    "You are a strict grader of Finnish-tax-law RAG answers. Given a question, "
    "a gold reference answer, the gold key facts that MUST appear, and a system "
    "answer, produce a JSON object with integer scores 1-5 for:\n"
    "- correctness: are the facts the system asserts correct (matched against the gold)?\n"
    "- grounding: do the facts match the gold, or did the system invent things?\n"
    "- completeness: how many of the gold key facts are present in the system answer?\n"
    "Also a short \"comment\" (<= 30 words). Return ONLY the JSON object, no prose."
)


def _judge_hash(config_id: str, question_id: str, answer: str) -> str:
    h = hashlib.sha256()
    for part in (config_id, question_id, answer or ""):
        h.update(part.encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def load_judge_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"[grade_eval] judge cache unreadable ({e}); starting fresh", file=sys.stderr)
        return {}


def save_judge_cache(path: Path, cache: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def call_judge(row: dict[str, Any], model: str, cache: dict[str, Any]) -> dict[str, Any]:
    answer = (row.get("answer_result") or {}).get("answer") or ""
    key = _judge_hash(row["config_id"], row["question_id"], answer)
    if key in cache:
        return {**cache[key], "cached": True}
    payload = {
        "question": row.get("question", ""),
        "gold_answer": row.get("gold_answer", ""),
        "gold_key_facts": list(row.get("gold_key_facts") or []),
        "system_answer": answer,
    }
    try:
        resp = chat(
            JUDGE_SYSTEM,
            json.dumps(payload, ensure_ascii=False),
            model=model,
            temperature=0.0,
            max_tokens=400,
        )
        obj = parse_json_object(resp.text)
        out = {
            "correctness": int(obj.get("correctness", 0)) or None,
            "grounding": int(obj.get("grounding", 0)) or None,
            "completeness": int(obj.get("completeness", 0)) or None,
            "comment": (obj.get("comment") or "")[:400],
            "model": model,
            "cached": False,
        }
        cache[key] = {k: v for k, v in out.items() if k != "cached"}
        return out
    except (LLMError, ValueError, KeyError, TypeError) as e:
        return {
            "correctness": None,
            "grounding": None,
            "completeness": None,
            "comment": None,
            "model": model,
            "cached": False,
            "error": str(e),
        }


# --- IO + CLI ----------------------------------------------------------------


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                print(f"[grade_eval] bad JSONL in {path.name}: {e}", file=sys.stderr)


def _read_existing_grades(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(path):
        qid = row.get("question_id")
        if qid:
            out[qid] = row
    return out


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _mean(xs: list[float | None]) -> float:
    vals = [x for x in xs if x is not None]
    return sum(vals) / len(vals) if vals else 0.0


def grade_config(
    config_id: str,
    runs_dir: Path,
    out_dir: Path,
    resolver: ChunkResolver,
    judge_enabled: bool,
    judge_model: str,
    judge_cache: dict[str, Any],
    judge_cache_path: Path,
    limit: int | None,
) -> None:
    runs_path = runs_dir / f"{config_id}.jsonl"
    if not runs_path.exists():
        print(f"[grade_eval] no runs file: {runs_path}", file=sys.stderr)
        return
    out_path = out_dir / f"{config_id}.jsonl"
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = _read_existing_grades(out_path)

    written: list[dict[str, Any]] = []
    n_seen = n_graded = n_judged = 0
    judge_dirty = False

    for row in _read_jsonl(runs_path):
        if limit is not None and n_seen >= limit:
            break
        n_seen += 1
        qid = row.get("question_id")
        if not qid:
            print(f"[grade_eval] {config_id}: row without question_id, skipping", file=sys.stderr)
            continue
        if row.get("error") or not row.get("answer_result"):
            written.append(existing.get(qid) or {
                "config_id": config_id,
                "question_id": qid,
                "tier": row.get("tier"),
                "deterministic": None,
                "judge": None,
                "graded_at": _utcnow(),
                "error": row.get("error") or "missing answer_result",
            })
            continue

        prior = existing.get(qid)
        needs_grade = prior is None or prior.get("deterministic") is None
        needs_judge = judge_enabled and (
            prior is None
            or prior.get("judge") is None
            or (prior.get("judge") or {}).get("correctness") is None
        )
        if not needs_grade and not needs_judge:
            written.append(prior)
            continue

        try:
            det = grade_deterministic(row, resolver) if needs_grade else prior.get("deterministic")
            if needs_grade:
                n_graded += 1
            if judge_enabled and needs_judge:
                judge_block: dict[str, Any] | None = call_judge(row, judge_model, judge_cache)
                if "error" not in judge_block and not judge_block.get("cached", False):
                    judge_dirty = True
                n_judged += 1
            elif judge_enabled:
                judge_block = (prior or {}).get("judge")
            else:
                judge_block = None
            written.append({
                "config_id": config_id,
                "question_id": qid,
                "tier": row.get("tier"),
                "deterministic": det,
                "judge": judge_block,
                "graded_at": _utcnow(),
            })
        except Exception as e:  # noqa: BLE001 — never crash on a single row
            print(f"[grade_eval] {config_id}/{qid}: failed: {e}", file=sys.stderr)
            written.append({
                "config_id": config_id,
                "question_id": qid,
                "tier": row.get("tier"),
                "deterministic": None,
                "judge": None,
                "graded_at": _utcnow(),
                "error": f"grader error: {e}",
            })

    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in written:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(out_path)
    if judge_dirty:
        save_judge_cache(judge_cache_path, judge_cache)

    det_rows = [r["deterministic"] for r in written if r.get("deterministic")]
    mean_kfr = _mean([r.get("key_fact_recall") for r in det_rows])
    mean_nr = _mean([r.get("numeric_recall") for r in det_rows])
    mean_cp = _mean([r.get("citation_publisher_precision") for r in det_rows])
    judge_rows = [r["judge"] for r in written if r.get("judge") and (r["judge"] or {}).get("correctness")]
    mean_corr = _mean([j.get("correctness") for j in judge_rows]) if judge_rows else None
    extra = f" judgeCorr={mean_corr:.2f}" if mean_corr is not None else ""
    print(
        f"[grade_eval] {config_id}: seen={n_seen} graded={n_graded} judged={n_judged} "
        f"kfr={mean_kfr:.2f} numr={mean_nr:.2f} citP={mean_cp:.2f}{extra}",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Grade eval runs.")
    p.add_argument("--config", help="Comma-separated config_ids (default: all).")
    p.add_argument("--all", action="store_true", help="Grade every config in runs-dir (default).")
    p.add_argument("--judge", dest="judge", action="store_true", help="Run LLM judge.")
    p.add_argument("--no-judge", dest="judge", action="store_false", help="Skip judge (default).")
    p.set_defaults(judge=False)
    p.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    p.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument(
        "--vector-db",
        type=Path,
        default=Path(os.environ.get("LEX_ATLAS_VECTOR_DB", str(DEFAULT_VECTOR_DB))),
    )
    p.add_argument("--limit", type=int, default=None, help="Max rows per config.")
    args = p.parse_args(argv)

    runs_dir: Path = args.runs_dir
    out_dir: Path = args.out_dir
    if not runs_dir.exists():
        print(f"[grade_eval] runs dir missing: {runs_dir}", file=sys.stderr)
        return 2

    if args.config:
        config_ids = [c.strip() for c in args.config.split(",") if c.strip()]
    else:
        config_ids = sorted(pp.stem for pp in runs_dir.glob("*.jsonl"))
    if not config_ids:
        print("[grade_eval] no configs to grade", file=sys.stderr)
        return 1

    resolver = ChunkResolver(args.vector_db)
    judge_cache_path = out_dir / JUDGE_CACHE_PATH_NAME
    judge_cache = load_judge_cache(judge_cache_path) if args.judge else {}

    t0 = time.time()
    for cid in config_ids:
        grade_config(
            config_id=cid,
            runs_dir=runs_dir,
            out_dir=out_dir,
            resolver=resolver,
            judge_enabled=args.judge,
            judge_model=args.judge_model,
            judge_cache=judge_cache,
            judge_cache_path=judge_cache_path,
            limit=args.limit,
        )
    print(f"[grade_eval] done in {time.time() - t0:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
