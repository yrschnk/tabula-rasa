"""Поиск: FTS5 baseline + векторы + RRF-fusion. SPEC 5.8."""
from __future__ import annotations


def fts_search(query: str, namespace: str, k: int) -> list[tuple[str, float]]:
    raise NotImplementedError


def vector_search(query: str, namespace: str, k: int) -> list[tuple[str, float]]:
    raise NotImplementedError


def rrf_fuse(*result_lists) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion."""
    raise NotImplementedError
