"""Канонизация концептов через embedding-кластеризацию. SPEC 5.3."""
from __future__ import annotations


def canonicalize(name: str, namespace: str) -> str:
    """Найти близкий концепт по embedding (cosine > порога) или создать новый.
    Возвращает канон-имя; синонимы пишет в aliases."""
    raise NotImplementedError
