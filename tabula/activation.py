"""Spreading activation. SPEC 5.9.
seeds (FTS5) -> распространение по графу с decay -> top_nodes.
Веха 5: seeds из RRF(FTS5+vector).
"""
from __future__ import annotations

from tabula.config import CONFIG
from tabula.graph import load_graph
from tabula.search import fts_search


def activate(question: str, namespace: str,
             mode: str = "activation") -> list[tuple[str, float]]:
    """Spreading activation.
    mode='fts5'      → только FTS5 seeds, без распространения
    mode='activation' → FTS5 seeds + spreading по графу
    Возвращает [(concept, activation_score)], отсортировано по убыванию.
    """
    seeds = fts_search(question, namespace, k=CONFIG.top_seed)
    if not seeds:
        return []

    if mode == "fts5":
        return seeds[:CONFIG.top_nodes]

    # Нормализуем seed-активации в 0..1
    max_score = max(s for _, s in seeds) or 1.0
    activation: dict[str, float] = {
        c: s / max_score for c, s in seeds
    }

    G = load_graph(namespace)
    if G.number_of_nodes() == 0:
        return sorted(activation.items(), key=lambda x: x[1], reverse=True)[:CONFIG.top_nodes]

    # Spreading по хопам
    frontier = dict(activation)
    for _hop in range(CONFIG.max_hops):
        next_frontier: dict[str, float] = {}
        for node, act in frontier.items():
            if node not in G:
                continue
            for neighbor, data in G[node].items():
                w = data.get("weight", 0.0)
                inc = act * CONFIG.decay * w
                if inc < CONFIG.act_threshold:
                    continue
                prev = activation.get(neighbor, 0.0)
                new_act = max(prev, inc)
                if new_act > prev:
                    activation[neighbor] = new_act
                    next_frontier[neighbor] = new_act
        frontier = next_frontier
        if not frontier:
            break

    return sorted(activation.items(), key=lambda x: x[1], reverse=True)[:CONFIG.top_nodes]
