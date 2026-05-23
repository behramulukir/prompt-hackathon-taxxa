"""One-shot script: scan output/chunks.jsonl and write web/data/source_meta.json.

The cache holds publisher, label, authority rank, and a short excerpt for every
chunk ID we cite in demo_overrides + MockPipeline. Citation hover previews read
from this file at request time (cheap json load), not from the 691 MB
chunks.jsonl.

When Track D ships, the real pipeline will fetch chunk text via GraphStore at
query time — this static cache becomes dead code and can be deleted.

Run:
    python -m web.data.build_source_meta
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHUNKS_PATH = REPO_ROOT / "output" / "chunks.jsonl"
CACHE_PATH = Path(__file__).parent / "source_meta.json"

# Chunk IDs we know we'll cite. Real IDs from chunks.jsonl, located by keyword
# search against the corpus on 2026-05-23. Demo overrides reference these by
# the human-friendly key on the left.
DEMO_CHUNK_IDS: dict[str, str] = {
    # --- Q1: Capital income tax rate ---
    "tvl_s124_current": (
        "finlex/laki/finlex-laki-laki-tuloverolain-muuttamisesta-62-html-22049862/s124#0"
    ),
    "tvl_s124_superseded_33pct": (
        "finlex/laki/finlex-laki-laki-tuloverolain-muuttamisesta-ja-"
        "valiaikaisesta-muuttamisesta-12-h-1bb21c04/s124#0"
    ),
    # --- Q12: Meal voucher VAT ---
    "kho_2025_46": (
        "finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-"
        "kho-2025-46-html-048ea0e9#0"
    ),
    "kvl_004_2024": (
        "vero/vero_kvl/vero-syventavat-vero-ohjeet-keskusverolautakunnan-"
        "ennakkoratkaisut-kvl-004-2024-773dbff8#0"
    ),
    "vero_henkilostoruokailu_alv_c5": (
        "vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-"
        "henkilostoruokailun-arvonlisaverotuksesta-hen-eb9e4b68/c5#0"
    ),
    # --- Q41: Avainhenkilö expired tax card ---
    "avainhenkilolaki_s2_84kk": (
        "finlex/laki/finlex-laki-laki-ulkomailta-tulevan-palkansaajan-"
        "lahdeverosta-annetun-lain-2-ja-4852b24c/s2#0"
    ),
    "vero_kannanotto_avainhenkilo_taustaa": (
        "vero/vero_kannanotto/vero-syventavat-vero-ohjeet-kannanotot-"
        "avainhenkilolta-perittava-lahdevero-vuode-df57db44/ctaustaa#0"
    ),
    "vero_kannanotto_avainhenkilo_kannanotto": (
        "vero/vero_kannanotto/vero-syventavat-vero-ohjeet-kannanotot-"
        "avainhenkilolta-perittava-lahdevero-vuode-df57db44/ckannanotto#0"
    ),
    "vero_avainhenkilo_ohje_2_1": (
        "vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-"
        "avainhenkiloiden-verotus-avainhenkiloiden-ver-87e04865/c2/s2-1#0"
    ),
}

# MockPipeline returns synthetic IDs that won't be in chunks.jsonl. We provide
# fallback metadata so hover previews still work when MockPipeline rolls a
# variant for free-text input.
MOCK_FALLBACK: dict[str, dict] = {
    "finlex_laki/avl/s114": {
        "publisher": "finlex",
        "subcorpus": "laki",
        "label": "AVL § 114",
        "authority_rank": 100,
        "authority_tier": "binding",
        "excerpt": (
            "Entertainment-expense input VAT is non-deductible. The statute "
            "governs the general rule; exceptions are listed in § 114(2)."
        ),
        "synthetic": True,
    },
    "finlex_laki/avl/s114-2": {
        "publisher": "finlex",
        "subcorpus": "laki",
        "label": "AVL § 114(2)",
        "authority_rank": 100,
        "authority_tier": "binding",
        "excerpt": (
            "Promotional gifts of low unit value are exempt from the "
            "entertainment-expense restriction in § 114(1)."
        ),
        "synthetic": True,
    },
    "vero/2019-mainoslahjat": {
        "publisher": "vero",
        "subcorpus": "vero_ohje",
        "label": "Vero 2019 · Mainoslahjat",
        "authority_rank": 60,
        "authority_tier": "interpretive",
        "excerpt": (
            "Vero guidance applies a stricter unit-value threshold for "
            "promotional gifts than the statute literally requires."
        ),
        "synthetic": True,
    },
    "finlex_laki/avl/s117": {
        "publisher": "finlex",
        "subcorpus": "laki",
        "label": "AVL § 117",
        "authority_rank": 100,
        "authority_tier": "binding",
        "excerpt": (
            "Apportionment rule for goods or services used partly for "
            "non-deductible purposes."
        ),
        "synthetic": True,
    },
    "finlex_laki/avl/s84": {
        "publisher": "finlex",
        "subcorpus": "laki",
        "label": "AVL § 84",
        "authority_rank": 100,
        "authority_tier": "binding",
        "excerpt": "Standard VAT rate as defined in the Value Added Tax Act.",
        "synthetic": True,
    },
    "finlex_laki/tvl/s1": {
        "publisher": "finlex",
        "subcorpus": "laki",
        "label": "TVL § 1",
        "authority_rank": 100,
        "authority_tier": "binding",
        "excerpt": "General scope of the Income Tax Act.",
        "synthetic": True,
    },
    "vero/yleinen-info": {
        "publisher": "vero",
        "subcorpus": "vero_ohje",
        "label": "Vero · General Information",
        "authority_rank": 60,
        "authority_tier": "interpretive",
        "excerpt": "Generic Vero introductory material.",
        "synthetic": True,
    },
}


# Authority rank provisional values per findings/03_authority_ranks.md (V3.2,
# unsigned). Keyed by source_subcorpus. Higher = more binding.
RANK_BY_SUBCORPUS: dict[str, tuple[int, str]] = {
    "laki": (100, "binding"),
    "asetus": (90, "binding"),
    "laki_skk": (80, "binding"),
    "asetus_skk": (80, "binding"),
    "kho": (85, "binding"),
    "treaty": (95, "binding"),
    "vero_paatos": (75, "binding"),
    "vero_ohje": (60, "interpretive"),
    "vero_kannanotto": (55, "interpretive"),
    "vero_kvl": (50, "interpretive"),
    "vero_other": (40, "interpretive"),
}


def _derive_label(chunk: dict) -> str:
    """Compose a short human label from chunk fields.

    Pulls section number and (for KHO) the case identifier from the chunk text.
    """
    text = chunk.get("text", "")
    # KHO case label: "KHO:2025:46  kappale 1" → "KHO 2025:46"
    m = re.match(r"^(KHO[:\-]?\s*\d{4}[:\-]\w+)", text)
    if m:
        return m.group(1).replace(":", " ", 1).replace("-", " ")

    # Generic: "Law title — N § Subtitle" → "N § · Law title".
    # The section number lives in the LAST em-dash segment (the law title may
    # itself contain "N § something" — e.g. "lain 2 ja 4 §:n muuttamisesta").
    head = text.split("\n", 1)[0]
    if " — " in head:
        parts = [p.strip() for p in head.split(" — ")]
        # Section header is in the middle segment if there are 3+ parts,
        # otherwise the last segment.
        section_part = parts[1] if len(parts) >= 3 else parts[-1]
        law_title = parts[0]
        sec = re.match(r"(\d+\s*[a-z]?\s*§)", section_part)
        if sec:
            if len(law_title) > 52:
                law_title = law_title[:52].rsplit(" ", 1)[0] + "…"
            return f"{sec.group(1).strip()} · {law_title.strip()}"
    # No em-dash structure: grab the first §-form anywhere.
    sec = re.search(r"(\d+\s*[a-z]?\s*§)", head)
    if sec:
        return sec.group(1).strip()
    # Vero guidance: "Title — section.id — Heading" → "Heading · Title"
    if " — " in head:
        parts = [p.strip() for p in head.split(" — ")]
        if len(parts) >= 3:
            return f"{parts[-1]} · {parts[0]}"
        if len(parts) == 2:
            return parts[0]
    return head[:80]


def _excerpt(chunk: dict, max_chars: int = 260) -> str:
    """Two- to three-line excerpt suitable for a hover tooltip."""
    text = chunk.get("text", "")
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Drop the leading "Title — N § Subtitle" head if it's long
    # (the label already shows it).
    if " kappale 1 " in text:
        text = text.split(" kappale 1 ", 1)[-1]
    elif " 1 momentti " in text:
        text = text.split(" 1 momentti ", 1)[-1]
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "…"
    return text


def build():
    target_ids = set(DEMO_CHUNK_IDS.values())
    found: dict[str, dict] = {}

    print(f"Scanning {CHUNKS_PATH} for {len(target_ids)} demo chunk IDs…")
    with CHUNKS_PATH.open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            cid = d["chunk_id"]
            if cid not in target_ids:
                continue
            subc = d.get("source_subcorpus", "")
            rank, tier = RANK_BY_SUBCORPUS.get(subc, (50, "interpretive"))
            found[cid] = {
                "publisher": d.get("source"),
                "subcorpus": subc,
                "label": _derive_label(d),
                "authority_rank": rank,
                "authority_tier": tier,
                "excerpt": _excerpt(d),
                "law_id": d.get("law_id"),
                "section_id": d.get("section_id"),
                "synthetic": False,
            }
            if len(found) == len(target_ids):
                break

    missing = target_ids - found.keys()
    if missing:
        print(f"WARNING: {len(missing)} demo chunk IDs not found:")
        for m in missing:
            print(f"  - {m}")

    # Merge in synthetic fallbacks for MockPipeline-style IDs
    found.update(MOCK_FALLBACK)

    CACHE_PATH.write_text(json.dumps(found, ensure_ascii=False, indent=2))
    print(f"Wrote {len(found)} entries to {CACHE_PATH}")


if __name__ == "__main__":
    build()
