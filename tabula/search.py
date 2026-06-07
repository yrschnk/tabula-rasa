"""Поиск: FTS5 baseline + векторы + RRF-fusion. SPEC 5.8."""
from __future__ import annotations

from tabula.config import CONFIG
from tabula.store import search_fts as _store_fts


def fts_search(query: str, namespace: str,
               k: int | None = None) -> list[tuple[str, float]]:
    """FTS5 baseline. Возвращает [(concept, score)]."""
    return _store_fts(query, namespace, k or CONFIG.top_seed)


def vector_search(query: str, namespace: str,
                  k: int | None = None) -> list[tuple[str, float]]:
    """Векторный поиск (sqlite-vec). Реализуется в вехе 5."""
    raise NotImplementedError("vector_search реализуется в вехе 5")


def rrf_fuse(*result_lists: list[tuple[str, float]],
             k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion по нескольким ранкинг-спискам.
    k — константа сглаживания (обычно 60).
    """
    scores: dict[str, float] = {}
    for ranked in result_lists:
        for rank, (concept, _score) in enumerate(ranked, start=1):
            scores[concept] = scores.get(concept, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
