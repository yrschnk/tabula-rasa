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
    """Векторный поиск через sqlite-vec. SPEC 5.8.
    Возвращает [(concept, score)] отсортировано по убыванию score.
    """
    from tabula.embeddings import embed_one
    from tabula.store import vector_knn
    import sqlite3

    k = k or CONFIG.top_seed
    try:
        q_vec = embed_one(query)
        knn = vector_knn(q_vec, namespace, k=k)
    except Exception:
        return []

    if not knn:
        return []

    # Получаем concept для каждого fact_id
    from tabula.store import _conn
    fact_ids = [fid for fid, _ in knn]
    dist_map = {fid: d for fid, d in knn}

    ph = ",".join("?" * len(fact_ids))
    with _conn(namespace) as con:
        rows = con.execute(
            f"SELECT fact_id, concept FROM facts WHERE fact_id IN ({ph})",
            fact_ids,
        ).fetchall()

    results = []
    for row in rows:
        fid = row["fact_id"]
        concept = row["concept"]
        d = dist_map.get(fid, 1.0)
        score = 1.0 / (1.0 + d)
        results.append((concept, score))

    return sorted(results, key=lambda x: x[1], reverse=True)


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
