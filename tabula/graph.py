"""Граф: LLM-links + record/session co-occurrence. SPEC 5.6."""
from __future__ import annotations

import itertools
import math

import networkx as nx

from tabula.config import CONFIG
from tabula.store import get_edges, upsert_edge


def update_edges_for_turn(concepts: list[str],
                           links: list[tuple[str, str]],
                           namespace: str) -> None:
    """record-рёбра (сильные) + LLM-links при ingest реплики. SPEC 5.6."""
    # LLM-links: явные связи (weight += w_link)
    for src, dst in links:
        if src != dst:
            upsert_edge(src, dst, "link", CONFIG.w_link, namespace)
            upsert_edge(dst, src, "link", CONFIG.w_link, namespace)

    # record co-occurrence: концепты в одной реплике (weight += w_rec)
    for a, b in itertools.combinations(set(concepts), 2):
        upsert_edge(a, b, "cooccur_rec", CONFIG.w_rec, namespace)
        upsert_edge(b, a, "cooccur_rec", CONFIG.w_rec, namespace)


def update_session_edges(session_concepts: list[str], namespace: str) -> None:
    """session-рёбра (слабые ×0.3) в конце сессии. SPEC 5.6."""
    for a, b in itertools.combinations(set(session_concepts), 2):
        upsert_edge(a, b, "cooccur_sess", CONFIG.w_sess, namespace)
        upsert_edge(b, a, "cooccur_sess", CONFIG.w_sess, namespace)


def load_graph(namespace: str) -> nx.Graph:
    """Строит NetworkX граф из SQLite edges. SPEC 5.6 формула weight(A,B)."""
    G = nx.Graph()
    edges_raw = get_edges(namespace)

    # Группируем по паре (src, dst) — суммируем по типам с разными коэффициентами
    from collections import defaultdict
    pairs: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: {"link": 0.0, "cooccur_rec": 0.0, "cooccur_sess": 0.0}
    )
    for e in edges_raw:
        key = (e["src_concept"], e["dst_concept"])
        pairs[key][e["type"]] = e["weight"]

    for (src, dst), weights in pairs.items():
        # weight = link + log1p(rec)*w_rec + log1p(sess)*w_sess
        # weight уже накоплен в SQLite, просто суммируем
        w = min(
            weights.get("link", 0.0)
            + math.log1p(weights.get("cooccur_rec", 0.0)) * CONFIG.w_rec
            + math.log1p(weights.get("cooccur_sess", 0.0)) * CONFIG.w_sess,
            1.0,
        )
        if w > 0:
            G.add_edge(src, dst, weight=w)

    return G
