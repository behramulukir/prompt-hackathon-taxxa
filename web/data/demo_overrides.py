"""Hand-crafted AnswerResult objects for the 3 preloaded demo questions.

Why this exists: MockPipeline.answer() ignores the question and returns one of
three random canned variants. Live stage demos need deterministic, well-
choreographed answers — so we shortcut the pipeline for the 3 questions a
viewer can pick from the dropdown.

Each override:
  - Uses REAL chunk IDs from output/chunks.jsonl (cached in source_meta.json)
  - Encodes the cinematic beats the animation script expects
    (assumption chip ↔ assumptions != []; conflict callout ↔ conflicts != [];
     edge-write moment ↔ a "graph"-via path with hops>=1)
  - Maps cleanly to the publisher/rank dichotomy in styles.css

The dispatch lookup is keyed by EXACT question text from eval/questions.json.
If the question text in eval changes, update DEMO_OVERRIDES here. The mapping
from short ID (Q1/Q12/Q41) to question text is exposed via DEMO_PICKS for the
dropdown.

When Track D ships, this file stays in place — it remains the source of truth
for stage demos regardless of pipeline version. To disable overrides for a
particular demo run, set USE_OVERRIDES=False in web/app.py.
"""

from __future__ import annotations

from src.models import AnswerResult, RetrievalPath


# --------------------------------------------------------------------------
# Q1 — Basic — Capital income tax rate
# Single-source, no conflict, no assumption. Demonstrates the baseline:
# vector hit, clean answer, one citation.
# --------------------------------------------------------------------------

_Q1_QUESTION = (
    "What is the capital income tax rate (pääomatulovero) applicable to the "
    "portion of capital income that exceeds 30,000 euros in a tax year?"
)

_Q1_ANSWER = (
    "Under the Income Tax Act (tuloverolaki) § 124, capital income is taxed "
    "at 30% up to €30,000 per tax year; the portion of capital income "
    "exceeding €30,000 is taxed at **34%** [Source 1]. The two-bracket "
    "structure has been in force since the 2024 amendment to TVL § 124."
)

_Q1_CHUNKS = [
    "finlex/laki/finlex-laki-laki-tuloverolain-muuttamisesta-62-html-22049862/s124#0",
]

Q1_RESULT = AnswerResult(
    question=_Q1_QUESTION,
    answer=_Q1_ANSWER,
    cited_source_ids=_Q1_CHUNKS,
    retrieved_chunks=_Q1_CHUNKS,
    retrieval_paths={
        _Q1_CHUNKS[0]: RetrievalPath(via="vector", score=0.92, hops=0),
    },
    timing_ms={"vector": 48, "rerank": 9, "generate": 980},
    assumptions=[],
    conflicts=[],
)


# --------------------------------------------------------------------------
# Q12 — Medium — Meal voucher VAT deduction
# Cross-source: KHO precedent + Vero kannanotto + Vero guidance. Surfaces an
# assumption (tax year 2026) but no rank conflict — KHO is binding and Vero
# guidance is consistent with it post-2025.
# --------------------------------------------------------------------------

_Q12_QUESTION = (
    "A company purchases electronic meal vouchers through a third-party "
    "voucher platform (app) for its employees. The platform invoices the "
    "company for the vouchers but does not charge VAT on the voucher face "
    "value. Can the company claim a VAT deduction on the invoice? How does "
    "the answer change if the company instead contracts directly with a "
    "restaurant for catering services?"
)

_Q12_ANSWER = (
    "**Electronic meal voucher via third-party platform — no VAT deduction.** "
    "Per KHO:2025:46 [Source 1] (incorporated into the Vero guidance "
    "*Henkilöstöruokailun arvonlisäverotuksesta* [Source 3]), an app-based "
    "meal benefit administered by an external platform constitutes a voucher "
    "in the VAT sense — no taxable supply occurs at invoicing, so the "
    "employer has no input VAT to deduct. The Keskusverolautakunta ruling "
    "KVL:004/2024 [Source 2] reached the same conclusion before being "
    "confirmed by KHO.\n\n"
    "**Direct catering contract — deduction allowed.** When the employer "
    "contracts directly with a restaurant for henkilöstöruokailupalvelua, "
    "input VAT on the goods and services used to provide the canteen meals "
    "*is* deductible under § 5 of the Vero guidance [Source 3], because the "
    "supply is taxable at the point of provision rather than at the issuance "
    "of a voucher."
)

_Q12_CHUNKS = [
    # [Source 1] — KHO 2025:46 (binding, rank 85)
    "finlex/kho/finlex-korkein-hallinto-oikeus-ennakkopaatokset-kho-2025-46-html-048ea0e9#0",
    # [Source 2] — KVL 004/2024 (interpretive, rank 50)
    "vero/vero_kvl/vero-syventavat-vero-ohjeet-keskusverolautakunnan-ennakkoratkaisut-kvl-004-2024-773dbff8#0",
    # [Source 3] — Vero henkilöstöruokailu ALV guidance (interpretive, rank 60)
    "vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-henkilostoruokailun-arvonlisaverotuksesta-hen-eb9e4b68/c5#0",
]

Q12_RESULT = AnswerResult(
    question=_Q12_QUESTION,
    answer=_Q12_ANSWER,
    cited_source_ids=_Q12_CHUNKS,
    retrieved_chunks=_Q12_CHUNKS,
    retrieval_paths={
        _Q12_CHUNKS[0]: RetrievalPath(via="vector", score=0.88, hops=0),
        _Q12_CHUNKS[1]: RetrievalPath(
            via="graph",
            score=0.76,
            from_node_id=_Q12_CHUNKS[0],
            edge_type="cites",
            hops=1,
        ),
        _Q12_CHUNKS[2]: RetrievalPath(
            via="graph",
            score=0.71,
            from_node_id=_Q12_CHUNKS[0],
            edge_type="interprets",
            hops=1,
        ),
    },
    timing_ms={"vector": 52, "graph": 38, "rerank": 14, "generate": 1340},
    assumptions=[
        "Finnish VAT-registered corporate employer, tax year 2026.",
        "Voucher face value does not exceed the Verohallinto luontoisetupäätös limit.",
    ],
    conflicts=[],
)


# --------------------------------------------------------------------------
# Q41 — Hard — Avainhenkilö expired tax card → wrong withholding
# Multi-hop across statute + Vero kannanotto + Vero ohje. Includes an
# authority-rank CONFLICT: the Vero 2020 kannanotto codifies the 32% rate
# in force pre-2026, but the statute (§ 2 of the avainhenkilölaki, amended
# 2025) extends the validity period to 84 months and the 2026 päätös
# lowers the rate to 25%. Surfaces as Finlex (100) > Vero (55).
# --------------------------------------------------------------------------

_Q41_QUESTION = (
    "A Finnish employer obtained key personnel (avainhenkilö) tax status for "
    "a foreign specialist (Dr. Chen) in Jan 2022. He has been taxed at 32% "
    "withholding since then. In Jan 2026 the 48-month tax card expires. "
    "Payroll fails to notice and continues 32% withholding for Jan-Apr 2026. "
    "In May 2026 the tax authority's system flags it. (a) What standard "
    "progressive withholding rate should have applied from Jan 2026 (identify "
    "the applicable income bracket for 90,000 euros/yr)? (b) What is the "
    "procedure for correcting the under-withholding for those four months? "
    "(c) Can Dr. Chen apply for a new key personnel tax card if he has by "
    "now acquired Finnish tax residency?"
)

_Q41_ANSWER = (
    "**(a) Applicable progressive rate from Jan 2026.** Once Dr. Chen's "
    "avainhenkilö tax card expires, his salary is taxed under the ordinary "
    "progressive system (verotusmenettelylaki). For €90,000/yr in 2026, the "
    "applicable bracket is the second-highest band of the Verohallinnon "
    "päätös ennakonpidätysprosenttien laskentaperusteista, yielding a "
    "marginal rate of approximately 42–44% plus the municipal surtax.\n\n"
    "**(b) Correction procedure.** The under-withholding for Jan–Apr 2026 is "
    "corrected via *ennakonpidätyksen oikaisu* (advance withholding "
    "correction) under the verotusmenettelylaki. The employer files a "
    "corrected oma-aloitteinen vero return for the affected months and "
    "remits the shortfall plus interest.\n\n"
    "**(c) New key personnel card after residency.** Under the avainhenkilölaki "
    "(1551/1995) § 2 as amended [Source 1], the maximum validity has been "
    "extended from 48 to **84 months** from the start of employment — "
    "Dr. Chen may request an extension within 30 days of the previous "
    "card's expiry. The Vero kannanotto of 2020 [Source 2] still references "
    "the older 48-month cap; the statute prevails. The Vero deepening "
    "guidance [Source 3] confirms the applicability conditions but does not "
    "yet reflect the 84-month extension."
)

_Q41_CHUNKS = [
    # [Source 1] — Avainhenkilölaki § 2 amendment (binding, rank 100)
    "finlex/laki/finlex-laki-laki-ulkomailta-tulevan-palkansaajan-lahdeverosta-annetun-lain-2-ja-4852b24c/s2#0",
    # [Source 2] — Vero kannanotto background (interpretive, rank 55)
    "vero/vero_kannanotto/vero-syventavat-vero-ohjeet-kannanotot-avainhenkilolta-perittava-lahdevero-vuode-df57db44/ctaustaa#0",
    # [Source 3] — Vero avainhenkilöiden verotus guidance (interpretive, rank 60)
    "vero/vero_ohje/vero-syventavat-vero-ohjeet-ohjeet-avainhenkiloiden-verotus-avainhenkiloiden-ver-87e04865/c2/s2-1#0",
    # Retrieved-only (not directly cited but surfaced by graph walk)
    "vero/vero_kannanotto/vero-syventavat-vero-ohjeet-kannanotot-avainhenkilolta-perittava-lahdevero-vuode-df57db44/ckannanotto#0",
]

Q41_RESULT = AnswerResult(
    question=_Q41_QUESTION,
    answer=_Q41_ANSWER,
    cited_source_ids=_Q41_CHUNKS[:3],
    retrieved_chunks=_Q41_CHUNKS,
    retrieval_paths={
        _Q41_CHUNKS[0]: RetrievalPath(via="vector", score=0.91, hops=0),
        _Q41_CHUNKS[1]: RetrievalPath(
            via="graph",
            score=0.79,
            from_node_id=_Q41_CHUNKS[0],
            edge_type="interprets",
            hops=1,
        ),
        _Q41_CHUNKS[2]: RetrievalPath(
            via="graph",
            score=0.74,
            from_node_id=_Q41_CHUNKS[0],
            edge_type="interprets",
            hops=1,
        ),
        _Q41_CHUNKS[3]: RetrievalPath(
            via="graph",
            score=0.68,
            from_node_id=_Q41_CHUNKS[1],
            edge_type="parent_of",
            hops=2,
        ),
    },
    timing_ms={"vector": 54, "graph": 102, "rerank": 22, "generate": 1820},
    assumptions=[
        "Finnish tax resident from 2026 onward (Dr. Chen).",
        "Annual gross salary €90,000; tax year 2026.",
        "No applicable double-tax treaty modifier.",
    ],
    conflicts=[
        {
            "sources": [_Q41_CHUNKS[0], _Q41_CHUNKS[1]],
            "topic": "Maximum validity of avainhenkilö tax card",
            "statute_position": "84 months from start of employment (post-2025 amendment).",
            "guidance_position": "48 months (Vero kannanotto issued 2020, not yet updated).",
            "resolution": "Finlex statute (rank 100, binding) prevails over Vero kannanotto (rank 55, interpretive).",
        }
    ],
)


# --------------------------------------------------------------------------
# Dispatch table — keyed by exact question text
# --------------------------------------------------------------------------

DEMO_PICKS: list[dict] = [
    {
        "id": "Q1",
        "tier": "basic",
        "label": "Q1 · Basic — Capital income tax rate above €30k",
        "question": _Q1_QUESTION,
    },
    {
        "id": "Q12",
        "tier": "medium",
        "label": "Q12 · Medium — Meal voucher VAT (cross-source)",
        "question": _Q12_QUESTION,
    },
    {
        "id": "Q41",
        "tier": "hard",
        "label": "Q41 · Hard — Avainhenkilö expired tax card (conflict)",
        "question": _Q41_QUESTION,
    },
]

DEMO_OVERRIDES: dict[str, AnswerResult] = {
    _Q1_QUESTION: Q1_RESULT,
    _Q12_QUESTION: Q12_RESULT,
    _Q41_QUESTION: Q41_RESULT,
}
