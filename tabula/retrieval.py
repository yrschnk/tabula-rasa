"""Query: collect -> abstention -> build_context -> one-shot reconstruct. SPEC 5.10."""
from __future__ import annotations

from tabula.models import QueryResult


def build_context(facts: list, token_budget: int) -> str:
    raise NotImplementedError


def llm_reconstruct(question: str, context: str, as_of: str | None):
    """One-shot ответ. Промпт: prompts/reconstruct.md. Разрешён abstention."""
    raise NotImplementedError


def query(question: str, namespace: str = "personal",
          as_of: str | None = None, mode: str = "activation") -> QueryResult:
    raise NotImplementedError
