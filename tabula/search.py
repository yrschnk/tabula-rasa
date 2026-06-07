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


def vector_search_facts(query: str, namespace: str,
                        k: int | None = None) -> list[tuple[str, float]]:
    """Векторный поиск фактов. Возвращает [(fact_id, score)]."""
    from tabula.embeddings import embed_one
    from tabula.store import vector_knn

    k = k or CONFIG.top_seed
    try:
        q_vec = embed_one(query)
        knn = vector_knn(q_vec, namespace, k=k)
    except Exception:
        return []

    return [(fid, 1.0 / (1.0 + dist)) for fid, dist in knn]


def search_facts_hybrid(query: str, namespace: str,
                        k: int | None = None) -> list:
    """Hybrid search: RRF(FTS5 facts + vector facts). Возвращает list[Fact]."""
    from tabula.store import get_fact, search_facts

    k = k or CONFIG.top_seed
    fts_facts = search_facts(query, namespace, k=k * 2)
    vec_hits = vector_search_facts(query, namespace, k=k * 2)

    ranked_lists: list[list[tuple[str, float]]] = []
    if fts_facts:
        ranked_lists.append([(f.fact_id, float(len(fts_facts) - i)) for i, f in enumerate(fts_facts)])
    if vec_hits:
        ranked_lists.append(vec_hits)

    if not ranked_lists:
        return []

    if len(ranked_lists) == 1:
        ids = [item[0] for item in ranked_lists[0][:k]]
    else:
        fused = rrf_fuse(*ranked_lists)
        ids = [fid for fid, _ in fused[:k]]

    seen: set[str] = set()
    facts = []
    for fid in ids:
        if fid in seen:
            continue
        seen.add(fid)
        f = get_fact(fid, namespace)
        if f and f.status == "active" and f.valid_to is None:
            facts.append(f)
    return facts


def search_facts_reranked(
    query: str,
    namespace: str,
    k: int | None = None,
    *,
    use_activation: bool = True,
) -> list:
    """Hybrid FTS+vector search с rerank по spreading activation (веса рёбер графа)."""
    from tabula.activation import activate
    from tabula.retrieval import activation_map, collect_facts_ranked

    k = k or CONFIG.top_seed
    hybrid = search_facts_hybrid(query, namespace, k=k * 3)
    if not hybrid or not use_activation:
        return hybrid[:k]

    activated = activate(query, namespace, mode="activation")
    if not activated:
        return hybrid[:k]

    scores = activation_map(activated)
    hybrid.sort(
        key=lambda f: (scores.get(f.concept, 0.0) * f.strength, scores.get(f.concept, 0.0)),
        reverse=True,
    )
    seen: set[str] = set()
    result = []
    for f in hybrid:
        if f.fact_id in seen:
            continue
        seen.add(f.fact_id)
        result.append(f)
        if len(result) >= k:
            break

    # Добавить факты с сильно активированных соседних концептов (graph spread)
    extra = collect_facts_ranked(activated, namespace)
    for f in extra:
        if f.fact_id in seen:
            continue
        if scores.get(f.concept, 0.0) < CONFIG.act_threshold:
            continue
        seen.add(f.fact_id)
        result.append(f)
        if len(result) >= k * 2:
            break

    result.sort(
        key=lambda f: (scores.get(f.concept, 0.0) * f.strength, scores.get(f.concept, 0.0)),
        reverse=True,
    )
    return result[:k]


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
