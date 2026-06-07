"""LLM-судья (config: claude | gpt-4o). SPEC 6, Приложение A.4."""
from __future__ import annotations


def judge(question: str, gold: str, pred: str, qtype: str) -> bool:
    raise NotImplementedError
