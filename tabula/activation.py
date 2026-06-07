"""Spreading activation. SPEC 5.9.
seeds (FTS5+vec) -> распространение по графу с decay -> top_nodes.
"""
from __future__ import annotations


def activate(question: str, namespace: str) -> list[tuple[str, float]]:
    """-> [(concept, activation)]. Параметры из config (decay, max_hops, threshold)."""
    raise NotImplementedError
