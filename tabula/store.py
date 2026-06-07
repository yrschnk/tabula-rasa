"""Канонический стор SQLite: facts + edges + concepts + FTS5 (+ vec). SPEC 5.5."""
from __future__ import annotations

from tabula.models import FactCandidate


def init_schema(namespace: str = "personal") -> None:
    """Создать таблицы facts, edges, concepts, facts_fts, facts_vec + триггеры."""
    raise NotImplementedError


def reset_store(namespace: str) -> None:
    """Очистить namespace (для изоляции бенч-инстансов). SPEC 6."""
    raise NotImplementedError


def add_fact(c: FactCandidate, namespace: str) -> str:
    raise NotImplementedError


def reinforce(fact_id: str) -> None:
    raise NotImplementedError


def supersede(old_fact_id: str, ts: str) -> None:
    raise NotImplementedError


def archive(fact_id: str, ts: str) -> None:
    raise NotImplementedError


def get_fact(fact_id: str):
    raise NotImplementedError


def upsert_edge(src: str, dst: str, edge_type: str, dweight: float, namespace: str) -> None:
    raise NotImplementedError


def collect_facts(concepts: list[str], namespace: str, as_of: str | None = None) -> list:
    """Актуальные факты концептов (valid_to IS NULL или > as_of)."""
    raise NotImplementedError
