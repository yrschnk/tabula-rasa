"""A.U.D.N: разрешение операции при похожих фактах. SPEC 5.4."""
from __future__ import annotations

from tabula.models import FactCandidate, Op


def find_similar(candidate: FactCandidate, namespace: str, k: int = 5) -> list:
    """Векторный поиск похожих (sqlite-vec) ИЛИ concept-scoped."""
    raise NotImplementedError


def resolve_operation(candidate: FactCandidate, similar: list) -> tuple[Op, str | None]:
    """LLM A.U.D.N. Промпт: prompts/audn.md. -> (op, target_fact_id)."""
    raise NotImplementedError


def apply_candidate(candidate: FactCandidate, namespace: str) -> None:
    """hash-дедуп → similar → resolve → применить операцию (atomic)."""
    raise NotImplementedError
