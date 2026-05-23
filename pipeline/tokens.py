"""Token counting. Uses tiktoken cl100k_base; falls back to a word/char heuristic."""
from __future__ import annotations

import functools

try:
    import tiktoken  # type: ignore

    @functools.lru_cache(maxsize=1)
    def _enc():
        return tiktoken.get_encoding("cl100k_base")

    def count_tokens(text: str) -> int:
        if not text:
            return 0
        return len(_enc().encode(text, disallowed_special=()))

except ImportError:  # pragma: no cover - fallback only
    def count_tokens(text: str) -> int:
        if not text:
            return 0
        # Rough: ~1 token per 3.5 chars for mixed Finnish/English.
        return max(1, len(text) // 3)
