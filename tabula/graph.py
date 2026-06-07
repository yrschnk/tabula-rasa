"""Граф: LLM-links + record/session co-occurrence. SPEC 5.6."""
from __future__ import annotations

import networkx as nx


def update_edges_for_turn(concepts: list[str], links: list[tuple[str, str]], namespace: str) -> None:
    """record-рёбра (сильные) + LLM-links."""
    raise NotImplementedError


def update_session_edges(session_concepts: list[str], namespace: str) -> None:
    """session-рёбра (слабые, ×0.3)."""
    raise NotImplementedError


def load_graph(namespace: str) -> nx.Graph:
    """Суммарные веса из edges. SPEC формула weight(A,B)."""
    raise NotImplementedError
