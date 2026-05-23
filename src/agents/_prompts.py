"""Prompt loader. Each agent imports ``load("clarifier")`` at module import
time so the prompt text is resolved once and surfaced as a module-level
constant for inspection/diffing.
"""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def load(name: str) -> str:
    path = _PROMPTS_DIR / f"{name}.txt"
    return path.read_text(encoding="utf-8")
