"""Локальные эмбеддинги (fastembed). SPEC 10.4.
Модель из config.embed_model, авто-загрузка при первом запуске.
ВАЖНО: размерность зависит от модели → при смене переиндексация facts_vec.
"""
from __future__ import annotations


def embed(texts: list[str]) -> list[list[float]]:
    raise NotImplementedError


def embed_one(text: str) -> list[float]:
    raise NotImplementedError
