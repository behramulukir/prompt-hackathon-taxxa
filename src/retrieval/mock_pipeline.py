"""MockPipeline — returns canned AnswerResult objects with VARIED shapes.

Used during the parallel-build phase. Swap for the real pipeline when ready.
Returns different shapes per call to prevent downstream tracks from growing
assumptions about uniform structure.
"""

import random

from src.models import AnswerResult, RetrievalPath

_VARIANTS = [
    # Multi-source with conflict
    {
        "answer": (
            "Entertainment expenses are non-deductible under [Source 1]. "
            "Promotional gifts are an exception per [Source 2]. Vero's "
            "interpretation in [Source 3] applies a stricter threshold than "
            "the statute requires."
        ),
        "cited_source_ids": [
            "finlex_laki/avl/s114",
            "finlex_laki/avl/s114-2",
            "vero/2019-mainoslahjat",
        ],
        "retrieved_chunks": [
            "finlex_laki/avl/s114",
            "finlex_laki/avl/s114-2",
            "vero/2019-mainoslahjat",
            "finlex_laki/avl/s117",
        ],
        "assumptions": ["Finnish corporate taxpayer, tax year 2025"],
        "conflicts": [
            {
                "sources": [
                    "finlex_laki/avl/s114-2",
                    "vero/2019-mainoslahjat",
                ],
                "resolution": "Finlex (rank 100) prevails over Vero (rank 60)",
            }
        ],
    },
    # Simple single-hop
    {
        "answer": "The standard VAT rate in Finland is 25.5% as of 2024 [Source 1].",
        "cited_source_ids": ["finlex_laki/avl/s84"],
        "retrieved_chunks": ["finlex_laki/avl/s84"],
        "assumptions": [],
        "conflicts": [],
    },
    # Unanswerable
    {
        "answer": (
            "The sources don't address this question. The question may be "
            "outside the corpus's scope (Finlex + Vero only)."
        ),
        "cited_source_ids": [],
        "retrieved_chunks": ["finlex_laki/tvl/s1", "vero/yleinen-info"],
        "assumptions": [],
        "conflicts": [],
    },
]


class MockPipeline:
    def answer(self, question: str) -> AnswerResult:
        v = random.choice(_VARIANTS)
        seed = v["cited_source_ids"][0] if v["cited_source_ids"] else None
        return AnswerResult(
            question=question,
            answer=v["answer"],
            cited_source_ids=v["cited_source_ids"],
            retrieved_chunks=v["retrieved_chunks"],
            retrieval_paths={
                cid: RetrievalPath(
                    via="vector" if i == 0 else "graph",
                    score=0.85 - 0.1 * i,
                    from_node_id=seed if i > 0 else None,
                    edge_type="cites" if i > 0 else None,
                    hops=1 if i > 0 else 0,
                )
                for i, cid in enumerate(v["retrieved_chunks"])
            },
            timing_ms={"vector": 50, "rerank": 10, "generate": 1200},
            assumptions=v["assumptions"],
            conflicts=v["conflicts"],
        )
