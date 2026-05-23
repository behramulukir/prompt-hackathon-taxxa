"""Synthetic-input tests for the four Track-H agents.

These tests hit the live LLM (Featherless/DeepSeek by default). They are
slow and cost money, so run them when you actually want to calibrate. To
opt in:

    FEATHERLESS_API_KEY=... pytest tests/test_agent_prompts.py -v

Without the API key, every test is skipped (no fake LLM, no recorded
fixtures — Track H is explicitly a calibration track, not a regression
suite).

Coverage:
    Clarifier — 10 medium-tier questions, each with one dimension dropped.
    Planner   — 10 hard-tier compound questions.
    Verifier  — 5 hand-built (claim, supporting, contradicting) triples
                plus 2 negative cases.
    Extractor — 20 real sentences sampled from output/chunks.jsonl
                covering cites / interprets / amends / defines / negatives.
"""

from __future__ import annotations

import os

import pytest

# Skip the entire module if no API key is present.
pytestmark = pytest.mark.skipif(
    not os.environ.get("FEATHERLESS_API_KEY"),
    reason="FEATHERLESS_API_KEY not set; agent calibration tests are live-LLM only.",
)

from src.agents.clarifier import clarifier
from src.agents.extractor import extractor
from src.agents.planner import MAX_SUB_QUESTIONS, planner
from src.agents.verifier import verifier


# ==========================================================================
# Clarifier — 10 questions, one dimension intentionally dropped in each.
# ==========================================================================
#
# Bank source: eval/questions.json, "medium" tier. Each entry below records
# (id, modified_question, dropped_dimension). The Clarifier passes if the
# returned ``missing`` set contains the dropped dimension.

CLARIFIER_CASES: list[tuple[str, str, str]] = [
    (
        "C1-Q11",
        "A Finnish blogger receives free beauty products worth approximately 150 "
        "euros per month from a cosmetics company in exchange for reviews. The "
        "company also occasionally gives her branded tote bags. How is this "
        "income taxed?",
        "year",
    ),
    (
        "C2-Q12",
        "A company purchases electronic meal vouchers through a third-party "
        "voucher platform for its employees. The platform invoices the company "
        "for the vouchers but does not charge VAT on the voucher face value. "
        "How should this be treated for VAT purposes?",
        "year",
    ),
    (
        "C3-Q13",
        "A taxpayer wins 10,000 euros in a licensed lottery in Germany. Another "
        "person wins the same amount from a licensed lottery in Canada (outside "
        "the EEA area). How is each win taxed in 2026?",
        "jurisdiction",
    ),
    (
        "C4-Q15",
        "An employee works in a hospital canteen. The employer's direct cost "
        "per meal is 5.00 euros. Using the standard indirect cost ratio "
        "recognized in Finnish tax guidance, what total cost per meal should "
        "be used to assess the meal benefit?",
        "year",
    ),
    (
        "C5-Q16",
        "A taxpayer has a company-provided benefit car (käyttöetuauto) "
        "available for private use in 2026. They also own their own car. For "
        "commuting (asunto–työpaikka matkat), what per-kilometer deduction "
        "rate applies?",
        "entity_type",
    ),
    (
        "C6-Q17",
        "A taxpayer receives 80,000 euros in dividends from a listed Finnish "
        "company in 2026: (a) what portion, if any, is tax-free; (b) what "
        "portion is taxable as capital income; (c) at what rate(s)?",
        "entity_type",
    ),
    (
        "C7-Q20",
        "An Austrian company owns 28% of a Finnish company and receives a "
        "dividend of 200,000 euros. A separate Austrian company owns 20% of "
        "the same Finnish company and receives a dividend of 100,000 euros. "
        "Under the Finland–Austria tax treaty, how is each dividend taxed at "
        "source?",
        "year",
    ),
    (
        "C8-Q21",
        "A Finnish employee was born in 1958. They are 67 years old and still "
        "in active employment. Are they still required to pay TyEL (statutory "
        "pension insurance) contributions, and until what age does the "
        "obligation continue?",
        "year",
    ),
    (
        "C9-Q22",
        "A food delivery platform worker (primary account holder, lähettitilin "
        "pääkäyttäjä) arranges for a friend to work their shifts on two "
        "occasions in 2026. The friend has no Finnish tax card. What "
        "withholding obligations apply?",
        "entity_type",
    ),
    (
        "C10-Q26",
        "A lottery winner intends to transfer 200,000 euros of their winnings "
        "to their 10-year-old grandchild in 2026: (a) is this transfer "
        "tax-free as a lottery win for the grandchild; (b) what tax category "
        "applies to the gift?",
        "jurisdiction",
    ),
]


@pytest.mark.parametrize("case_id,question,dropped", CLARIFIER_CASES, ids=[c[0] for c in CLARIFIER_CASES])
def test_clarifier_flags_dropped_dimension(case_id: str, question: str, dropped: str) -> None:
    result = clarifier(question)
    assert dropped in result.missing, (
        f"{case_id}: expected '{dropped}' in missing, got {result.missing}; "
        f"assumptions={result.assumptions}"
    )
    # In batch mode the prompt instructs the Clarifier to fill safe defaults
    # whenever possible. We expect ``clarified=True`` for all 10 of these —
    # they're under-specified but not fundamentally ambiguous.
    assert result.clarified, f"{case_id}: expected clarified=True, got False"
    # And the assumption for the dropped dimension should be populated.
    assert dropped in result.assumptions, (
        f"{case_id}: expected assumption for '{dropped}', got keys "
        f"{list(result.assumptions.keys())}"
    )


# ==========================================================================
# Planner — 10 hard-tier compound questions from eval/questions.json.
# ==========================================================================
#
# (id, question, expected_min_subs, expected_max_subs). The Planner passes
# if 1 <= len(sub_questions) <= 4 AND the count is within the expected
# range AND ``is_compound`` reflects the count.

PLANNER_CASES: list[tuple[str, str, int, int]] = [
    (
        "P-Q32",
        "Kaisa inherited a farm from her father in January 2016. Inheritance tax "
        "was assessed on the estate's total value as declared in the perukirja. "
        "In 2023, Kaisa's family lawyer discovers that the perukirja omitted a "
        "valid farm loan liability of 80,000 euros. (a) Can the original "
        "inheritance tax assessment be reopened? (b) Within what time limit? "
        "(c) What is the refund procedure?",
        2,
        4,
    ),
    (
        "P-Q34",
        "Liisa is a Finnish citizen who lived and worked in Ireland for 5 years. "
        "She earns 95,000 euros/year from an Irish employer and rents a Helsinki "
        "apartment for 14,000 euros/year. She maintained Finnish permanent "
        "residency throughout. (a) Under the Finland–Ireland double tax treaty, "
        "in which country is her employment income taxed? (b) How does Finland "
        "credit the foreign tax? (c) How is her Helsinki rental income taxed?",
        2,
        4,
    ),
    (
        "P-Q35",
        "Pekka runs a sole proprietorship: VAT-taxable IT consulting "
        "(8,500 euros/year) plus VAT-exempt educational training "
        "(4,000 euros/year), total 12,500 euros. He registered for VAT three "
        "years ago. (a) Under the current small-business limit (vähäisen "
        "toiminnan raja), is he still required to be VAT-registered? "
        "(b) How is shared office-equipment VAT apportioned?",
        2,
        4,
    ),
    (
        "P-Q38",
        "A Finnish parent (Oy Pohjoinen Ab) owns 100% of an Austrian subsidiary "
        "(Österreich GmbH). 2025 dividend of 600,000 euros to the Finnish "
        "parent. Held 100% for three consecutive years. (a) Under the "
        "Finland–Austria tax treaty, at what withholding rate is the dividend "
        "taxed in Austria? (b) How much Finnish tax does the parent pay on the "
        "dividend? (c) Does the EU parent–subsidiary directive apply?",
        2,
        4,
    ),
    (
        "P-Q40",
        "Tommi is a food-delivery platform primary account holder. Over six "
        "months in 2025, his brother Juhani (no tax card) regularly works his "
        "shifts. Tommi receives the platform's total compensation of 60,000 "
        "euros and pays Juhani 25,000 euros. (a) Whose income is the entire "
        "60,000 euros for tax reporting purposes? (b) Within how many days "
        "must Tommi register? (c) What withholding rate applies to payments "
        "to Juhani?",
        2,
        4,
    ),
    (
        "P-Q41",
        "A Finnish employer obtained key personnel (avainhenkilö) tax status "
        "for a foreign specialist (Dr. Chen) in Jan 2022. Taxed at 32% "
        "withholding since then. In Jan 2026 the 48-month tax card expires. "
        "Payroll continues 32% withholding for Jan–Apr 2026. In May 2026 the "
        "tax administration notices. (a) What was the correct withholding "
        "rate for Jan–Apr 2026? (b) What corrective procedure applies? "
        "(c) What penalty/interest applies?",
        2,
        4,
    ),
    (
        "P-Q44",
        "Maria runs a restaurant business as a sole trader and filed quarterly "
        "VAT. From 2022–2024 she systematically misclassified restaurant sales "
        "(13.5% rate) as consulting (24% standard rate) to under-report. A "
        "2026 audit uncovers the scheme. Undeclared VAT is 48,000 euros. "
        "(a) For which tax years can the audit reassess VAT? (b) What "
        "additional tax and penalty apply? (c) Is criminal liability "
        "triggered?",
        2,
        4,
    ),
    (
        "P-Q45",
        "A syndicate of six friends has been buying lottery tickets together "
        "since 2022. Only Sirkka is registered as the player. In December "
        "2025 the syndicate wins 3,000,000 euros. Sirkka distributes 500,000 "
        "euros to each of the five other members per a pre-draw agreement. "
        "(a) Is Sirkka's original win tax-free for her? (b) Is the "
        "distribution treated as a gift or as a split of pooled property? "
        "(c) What documentation should the syndicate have?",
        2,
        4,
    ),
    (
        "P-Q49",
        "Ari is a Finnish self-employed person (YEL-insured). 2026 earned "
        "income from self-employment is 28,000 euros. (a) What is the health "
        "insurance daily allowance fee (päivärahamaksu) rate, and does it "
        "apply at this income level? (b) What is the sairausvakuutusmaksu "
        "rate? (c) What is the YEL contribution rate? (d) What is his total "
        "social-insurance contribution burden?",
        2,
        4,
    ),
    (
        "P-Q50",
        "Eeva worked as tax consultant at a large Finnish accounting firm "
        "2019–2024. She advised clients to use 24% standard VAT rate instead "
        "of 13.5% restaurant rate for catering services. Some clients overpaid, "
        "others underpaid. A 2026 audit covers 2020–2023. (a) For which "
        "clients can the audit reassess? (b) What is the period for refund "
        "claims by overpaying clients? (c) Is the consultant personally "
        "liable?",
        2,
        4,
    ),
]


@pytest.mark.parametrize(
    "case_id,question,exp_min,exp_max",
    PLANNER_CASES,
    ids=[c[0] for c in PLANNER_CASES],
)
def test_planner_decomposes_compound_questions(
    case_id: str, question: str, exp_min: int, exp_max: int
) -> None:
    plan = planner(question)
    n = len(plan.sub_questions)
    assert 1 <= n <= MAX_SUB_QUESTIONS, f"{case_id}: {n} sub-questions exceeds cap"
    assert exp_min <= n <= exp_max, (
        f"{case_id}: expected {exp_min}..{exp_max} sub-questions, got {n}: "
        f"{[s.text for s in plan.sub_questions]}"
    )
    assert plan.is_compound, f"{case_id}: expected is_compound=True for a multi-part question"
    # Every sub-question must be non-empty.
    for i, s in enumerate(plan.sub_questions):
        assert s.text.strip(), f"{case_id}: sub-question {i} is empty"


def test_planner_atomic_question_passthrough() -> None:
    """A single-fact question should NOT be over-decomposed."""
    plan = planner("What is the standard VAT rate in Finland in 2026?")
    assert len(plan.sub_questions) == 1
    assert plan.sub_questions[0].category == "single"
    assert plan.is_compound is False


# ==========================================================================
# Verifier — 5 hand-built conflicts + 2 negative cases.
# ==========================================================================
#
# Authority ranks per Step 3 plan: Finlex=100, Vero=60.
# Each case below is a (case_id, answer, sources, expected_status,
# expected_prevailing_id_for_first_conflict).


VERIFIER_CASES: list[tuple[str, str, list[dict], str, str | None]] = [
    (
        "V1-meals-VAT",
        "VAT on business meals (representation expenses for clients) is fully "
        "deductible by the company.",
        [
            {
                "id": "vero-ohje-meals-2023",
                "text": "Liikeneuvotteluihin liittyvien tarjoiluiden arvonlisäveron voi "
                "vähentää, jos kustannukset liittyvät liiketoimintaan.",
                "authority_rank": 60,
                "source": "vero",
                "source_subcorpus": "vero_ohje",
            },
            {
                "id": "avl-114",
                "text": "Arvonlisäverolain 114 §:n mukaan edustuskuluihin sisältyvää "
                "arvonlisäveroa ei saa vähentää.",
                "authority_rank": 100,
                "source": "finlex",
                "source_subcorpus": "laki",
            },
        ],
        "conflicts",
        "avl-114",
    ),
    (
        "V2-avainhenkilo-rate",
        "In 2026 the avainhenkilö withholding tax rate is 32%.",
        [
            {
                "id": "vero-ohje-avainh-2024",
                "text": "Avainhenkilölain mukainen lähdevero on 32 prosenttia "
                "ulkomaalaisen erityisasiantuntijan palkasta.",
                "authority_rank": 60,
                "source": "vero",
                "source_subcorpus": "vero_ohje",
            },
            {
                "id": "avainhenkilolaki-2025-amendment",
                "text": "Avainhenkilölain (1551/1995) muutoksen mukaan 1.1.2026 alkaen "
                "maksetuista palkoista lähdevero on 25 prosenttia.",
                "authority_rank": 100,
                "source": "finlex",
                "source_subcorpus": "laki",
            },
        ],
        "conflicts",
        "avainhenkilolaki-2025-amendment",
    ),
    (
        "V3-capital-income-rate",
        "Capital income above 30,000 euros is taxed at 30%.",
        [
            {
                "id": "vero-old-kannanotto",
                "text": "Pääomatulosta menevä vero on 30 prosenttia (vanhempi kannanotto).",
                "authority_rank": 60,
                "source": "vero",
                "source_subcorpus": "vero_kannanotto",
            },
            {
                "id": "tvl-124-current",
                "text": "Tuloverolain 124 §:n mukaan pääomatulosta menevä vero on 30 "
                "prosenttia ja siltä osin kuin verovelvollisen verotettavan "
                "pääomatulon määrä ylittää 30 000 euroa, 34 prosenttia.",
                "authority_rank": 100,
                "source": "finlex",
                "source_subcorpus": "laki",
            },
        ],
        "conflicts",
        "tvl-124-current",
    ),
    (
        "V4-eea-lottery",
        "Lottery winnings from a licensed EEA-area lottery are tax-free for a "
        "Finnish tax resident.",
        [
            {
                "id": "arpajaisverolaki-2",
                "text": "Arpajaisverolain 2 §:n mukaan ETA-alueella toimeenpannuista "
                "arpajaisista saadut voitot ovat saajalleen verovapaita.",
                "authority_rank": 100,
                "source": "finlex",
                "source_subcorpus": "laki",
            },
            {
                "id": "vero-old-foreign-winnings-ohje",
                "text": "Ulkomailta saadut arpajaisvoitot katsotaan saajan veronalaiseksi "
                "pääomatuloksi (vanha ohje).",
                "authority_rank": 60,
                "source": "vero",
                "source_subcorpus": "vero_ohje",
            },
        ],
        "conflicts",
        "arpajaisverolaki-2",
    ),
    (
        "V5-vat-threshold",
        "From 2025, the Finnish small-business VAT threshold (vähäisen toiminnan "
        "raja) is 20,000 euros of annual turnover.",
        [
            {
                "id": "vero-pre2025-threshold-ohje",
                "text": "Vähäisen toiminnan raja on 15 000 euroa tilikauden liikevaihdosta.",
                "authority_rank": 60,
                "source": "vero",
                "source_subcorpus": "vero_ohje",
            },
            {
                "id": "avl-3-2025-amendment",
                "text": "Arvonlisäverolain 3 §:n mukaan 1.1.2025 alkaen vähäisen toiminnan "
                "raja on 20 000 euroa tilikauden liikevaihdosta.",
                "authority_rank": 100,
                "source": "finlex",
                "source_subcorpus": "laki",
            },
        ],
        "conflicts",
        "avl-3-2025-amendment",
    ),
    (
        "V6-negative-agreement",
        "The standard Finnish VAT rate is 25.5%.",
        [
            {
                "id": "vero-ohje-vat-rate",
                "text": "Yleinen arvonlisäverokanta Suomessa on 25,5 prosenttia "
                "1.9.2024 alkaen.",
                "authority_rank": 60,
                "source": "vero",
                "source_subcorpus": "vero_ohje",
            },
            {
                "id": "avl-84",
                "text": "Arvonlisäverolain 84 §:n mukaan suoritettava vero on 25,5 "
                "prosenttia veron perusteesta.",
                "authority_rank": 100,
                "source": "finlex",
                "source_subcorpus": "laki",
            },
        ],
        "ok",
        None,
    ),
    (
        "V7-negative-unsupported",
        "The Finnish inheritance tax rate on a 1,000,000 euro estate is 19%.",
        [
            {
                "id": "tvl-124-current",
                "text": "Tuloverolain 124 §:n mukaan pääomatulosta menevä vero on 30 "
                "prosenttia ja yli 30 000 euron ylittävältä osalta 34 prosenttia.",
                "authority_rank": 100,
                "source": "finlex",
                "source_subcorpus": "laki",
            },
            {
                "id": "avl-84",
                "text": "Yleinen arvonlisäverokanta Suomessa on 25,5 prosenttia.",
                "authority_rank": 100,
                "source": "finlex",
                "source_subcorpus": "laki",
            },
        ],
        "unsupported_claims",
        None,
    ),
]


@pytest.mark.parametrize(
    "case_id,answer,sources,exp_status,exp_prevailing",
    VERIFIER_CASES,
    ids=[c[0] for c in VERIFIER_CASES],
)
def test_verifier_resolves_against_authority_rank(
    case_id: str,
    answer: str,
    sources: list[dict],
    exp_status: str,
    exp_prevailing: str | None,
) -> None:
    result = verifier(answer, sources)
    assert result.status == exp_status, (
        f"{case_id}: expected status={exp_status}, got {result.status}; "
        f"claims={result.claims}"
    )
    if exp_prevailing is not None:
        # Exactly one of the claims should be a conflict with the expected
        # prevailing source id (the Finlex one).
        conflicts = [c for c in result.claims if c.resolution == "conflict"]
        assert conflicts, f"{case_id}: expected at least one conflict claim"
        prevailing_ids = {c.prevailing_source_id for c in conflicts}
        assert exp_prevailing in prevailing_ids, (
            f"{case_id}: expected prevailing={exp_prevailing}, got {prevailing_ids}"
        )


# ==========================================================================
# Extractor — 20 sentences sampled from output/chunks.jsonl.
# ==========================================================================
#
# Sampled at planning time; inlined here so the test does not depend on the
# 800 MB chunks file. Fields per case:
#   case_id, source_node_meta, text, expected_min_edges, allowed_types
# A test passes if:
#   - the returned edge count is >= expected_min_edges
#   - every emitted edge has a type ∈ allowed_types (closed-vocab adherence)
#   - every emitted edge is dangling (target_id is None,
#     dangling_reason == "not_yet_parsed", extracted_by == "llm")
#   - source_id matches metadata['node_id']

# Negative controls have expected_min_edges=0 and allowed_types=() — i.e.
# the prompt should NOT invent edges. We require the count be exactly 0 by
# expressing it as expected_max_edges=0 in a separate field.

EXTRACTOR_CASES: list[tuple[str, dict, str, int, int, tuple[str, ...]]] = [
    # ---- cites (8) --------------------------------------------------------
    (
        "E1-cites-cybersec",
        {"node_id": "n-cites-1", "source": "finlex", "source_subcorpus": "laki"},
        "Laki vaarallisten kemikaalien ja räjähteiden käsittelyn turvallisuudesta "
        "annetun lain muuttamisesta — 5 § Suhde muuhun lainsäädäntöön. "
        "Kyberturvallisuuden riskienhallinta- ja raportointivelvoitteista sekä "
        "viranomaisten yhteistyöstä kyberturvallisuuspoikkeamien ja -riskien "
        "osalta säädetään erikseen.",
        1,
        4,
        ("cites", "amends", "applies"),
    ),
    (
        "E2-cites-kumotaan",
        {"node_id": "n-cites-2", "source": "finlex", "source_subcorpus": "laki"},
        "Laki koiraverosta annetun lain kumoamisesta — 1 §. Tällä lailla kumotaan "
        "koiraverosta annettu laki (590/1979).",
        1,
        3,
        ("cites", "amends", "repeals"),
    ),
    (
        "E3-cites-voimaan",
        {"node_id": "n-cites-3", "source": "finlex", "source_subcorpus": "laki"},
        "Tämä laki tulee voimaan 15 päivänä kesäkuuta 2018.",
        0,
        2,
        ("cites", "amends"),
    ),
    (
        "E4-cites-tyott",
        {"node_id": "n-cites-4", "source": "finlex", "source_subcorpus": "laki"},
        "Tämä laki tulee voimaan 1 päivänä elokuuta 2018.",
        0,
        2,
        ("cites", "amends"),
    ),
    (
        "E5-cites-erityishuolto",
        {"node_id": "n-cites-5", "source": "finlex", "source_subcorpus": "laki"},
        "Laki kehitysvammaisten erityishuollosta annetun lain muuttamisesta — 28 §. "
        "Jos lapsen kehitys tai henkinen toiminta on siinä määrin estynyt tai "
        "häiriintynyt, ettei lapsi voi saada opetusta peruskoululain (476/83) "
        "mukaisesti, hänellä on oikeus saada 2 §:n 3 kohdassa tarkoitettua opetusta.",
        2,
        5,
        ("cites", "amends"),
    ),
    (
        "E6-cites-edella-momentti",
        {"node_id": "n-cites-6", "source": "finlex", "source_subcorpus": "laki"},
        "Edellä 1 momentin 4 kohdassa tarkoitettuun tiedoksisaantiin sovelletaan "
        "vastaavasti, mitä tapaturmavakuutuslain 53 c §:n 6 momentissa säädetään.",
        1,
        4,
        ("cites",),
    ),
    (
        "E7-cites-tyovoima",
        {"node_id": "n-cites-7", "source": "finlex", "source_subcorpus": "laki"},
        "Edellä 14 a §:ssä tarkoitetussa neuvottelukunnassa on viisi jäsentä sekä "
        "kullakin henkilökohtainen varajäsen.",
        1,
        2,
        ("cites",),
    ),
    (
        "E8-cites-elake",
        {"node_id": "n-cites-8", "source": "finlex", "source_subcorpus": "laki"},
        "Asianomistaja saa itse nostaa syytteen rikoksesta vain, jos syyttäjä on "
        "päättänyt jättää syytteen nostamatta tai esitutkintaviranomainen "
        "taikka syyttäjä on päättänyt, ettei esitutkintaa toimiteta tai että "
        "se keskeytetään tahi lopetetaan.",
        0,
        2,
        ("cites",),
    ),
    # ---- interprets (4) ---------------------------------------------------
    (
        "E9-interprets-vat-meals",
        {"node_id": "n-interp-1", "source": "vero", "source_subcorpus": "vero_ohje"},
        "Arvonlisäverolain 102 §:n mukaan elinkeinonharjoittaja saa vähentää "
        "verollista liiketoimintaa varten toiselta elinkeinonharjoittajalta "
        "ostamansa palvelun arvonlisäveron. Lain 114 §:ssä on kuitenkin "
        "edustuskuluja koskeva poikkeus.",
        1,
        4,
        ("cites", "interprets"),
    ),
    (
        "E10-interprets-minverotus",
        {"node_id": "n-interp-2", "source": "vero", "source_subcorpus": "vero_ohje"},
        "Suurten konsernien vähimmäisverotus — Vähimmäisverolain 6 luvussa "
        "säännellään muun muassa eräistä konsernirakenteiden muutostilanteista. "
        "Vähimmäisverolain yritysten uudelleenjärjestelyjä koskevat säännökset "
        "eivät rajaudu esimerkiksi sulautumisiin.",
        1,
        3,
        ("cites", "interprets"),
    ),
    (
        "E11-interprets-vml-22a",
        {"node_id": "n-interp-3", "source": "vero", "source_subcorpus": "vero_ohje"},
        "Sivullisilmoittajan laiminlyöntimaksu — VML 22 a § sääntelee "
        "laiminlyöntimaksun määräämistä erityisesti finanssitilitietoihin "
        "liittyvien huolellisuusvelvoitteiden laiminlyönnistä.",
        1,
        3,
        ("cites", "interprets"),
    ),
    (
        "E12-interprets-treaty-art4",
        {"node_id": "n-interp-4", "source": "vero", "source_subcorpus": "vero_ohje"},
        "Verosopimusten artiklat — Artikla 4, Verosopimuksen mukainen kotipaikka. "
        "Edellä mainitun esimerkin kaksoisasuja voi antaa Ruotsissa oleskelun "
        "ajaksi asuntonsa Suomesta vuokralle. Kun hänellä tällöin on asunto "
        "käytettävänään vain Ruotsissa, Ruotsi on hänen asuinvaltionsa.",
        1,
        3,
        ("cites", "interprets"),
    ),
    # ---- amends / repeals (4) --------------------------------------------
    (
        "E13-amends-rikos",
        {"node_id": "n-amend-1", "source": "finlex", "source_subcorpus": "laki"},
        "Laki oikeudenkäynnistä rikosasioissa annetun lain 1 luvun 14 §:n "
        "muuttamisesta — 14 §.",
        1,
        3,
        ("cites", "amends"),
    ),
    (
        "E14-amends-potilas",
        {"node_id": "n-amend-2", "source": "finlex", "source_subcorpus": "laki"},
        "Laki potilasvahinkolain 11 a §:n muuttamisesta — 11 a § "
        "Potilasvahinkolautakunnan tehtävät.",
        1,
        3,
        ("cites", "amends"),
    ),
    (
        "E15-amends-kalastus",
        {"node_id": "n-amend-3", "source": "finlex", "source_subcorpus": "laki"},
        "Laki kalastuslain muuttamisesta — 14 b §. Edellä 14 a §:ssä "
        "tarkoitetussa neuvottelukunnassa on viisi jäsentä sekä kullakin "
        "henkilökohtainen varajäsen.",
        2,
        4,
        ("cites", "amends"),
    ),
    (
        "E16-amends-mata",
        {"node_id": "n-amend-4", "source": "finlex", "source_subcorpus": "laki"},
        "Laki maatalousyrittäjien tapaturmavakuutuslain muuttamisesta — 22 §. "
        "Jollei tästä laista muuta seuraa, on soveltuvin osin lisäksi voimassa, "
        "mitä työntekijäin eläkelain 16 ja 19 §:ssä, maatalousyrittäjien "
        "eläkelain 16 ja 17 §:ssä ja tapaturmavakuutuslain 30 a ja 30 b §:ssä "
        "säädetään.",
        3,
        7,
        ("cites", "amends"),
    ),
    # ---- defines (2) ------------------------------------------------------
    (
        "E17-defines-uusiutuva",
        {"node_id": "n-def-1", "source": "finlex", "source_subcorpus": "laki"},
        "Laki uusiutuvilla energialähteillä tuotetun sähkön tuotantotuesta "
        "annetun lain muuttamisesta — 5 § Määritelmät. Tässä laissa "
        "tarkoitetaan: 1) verkonhaltijalla sähkömarkkinalaissa (588/2013) "
        "tarkoitettua verkonhaltijaa; 11) päästöoikeudella päästökauppalaissa "
        "tarkoitettua oikeutta.",
        2,
        6,
        ("defines", "cites", "amends"),
    ),
    (
        "E18-defines-pelastus",
        {"node_id": "n-def-2", "source": "finlex", "source_subcorpus": "laki"},
        "Laki pelastuslain muuttamisesta — 2 a § Määritelmät. Tässä laissa "
        "tarkoitetaan: 1) pelastustoimella tehtäväalaa, joka koostuu "
        "tulipalojen ja muiden onnettomuuksien ehkäisystä sekä "
        "pelastustoiminnasta; 2) pelastustoiminnalla kiireellisiä tehtäviä.",
        2,
        5,
        ("defines", "cites", "amends"),
    ),
    # ---- negative controls (2) -------------------------------------------
    (
        "E19-neg-prose",
        {"node_id": "n-neg-1", "source": "vero", "source_subcorpus": "vero_ohje"},
        "Verohallinto neuvoo asiakkaita useilla eri kielillä. Asiakaspalvelu on "
        "avoinna arkisin kello 9–16.",
        0,
        0,
        (),
    ),
    (
        "E20-neg-procedure",
        {"node_id": "n-neg-2", "source": "vero", "source_subcorpus": "vero_ohje"},
        "Esimerkki: Asiakas täyttää lomakkeen huolellisesti ja toimittaa sen "
        "määräaikaan mennessä.",
        0,
        0,
        (),
    ),
]


@pytest.mark.parametrize(
    "case_id,meta,text,exp_min,exp_max,allowed_types",
    EXTRACTOR_CASES,
    ids=[c[0] for c in EXTRACTOR_CASES],
)
def test_extractor_produces_typed_dangling_edges(
    case_id: str,
    meta: dict,
    text: str,
    exp_min: int,
    exp_max: int,
    allowed_types: tuple[str, ...],
) -> None:
    edges = extractor(text, meta)
    n = len(edges)
    assert exp_min <= n <= exp_max, (
        f"{case_id}: expected {exp_min}..{exp_max} edges, got {n}: "
        f"{[(e.type, e.target_ref) for e in edges]}"
    )
    for i, e in enumerate(edges):
        assert e.source_id == meta["node_id"], (
            f"{case_id}: edges[{i}].source_id={e.source_id!r}, expected {meta['node_id']!r}"
        )
        assert e.target_id is None, f"{case_id}: edges[{i}] must be dangling"
        assert e.dangling_reason == "not_yet_parsed", (
            f"{case_id}: edges[{i}].dangling_reason={e.dangling_reason!r}"
        )
        assert e.extracted_by == "llm", (
            f"{case_id}: edges[{i}].extracted_by={e.extracted_by!r}"
        )
        if allowed_types:
            assert e.type in allowed_types, (
                f"{case_id}: edges[{i}].type={e.type!r} not in {allowed_types}"
            )
        assert 0.0 <= e.confidence <= 1.0
        assert e.target_ref.strip(), f"{case_id}: edges[{i}].target_ref empty"
