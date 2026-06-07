"""Локальные эмбеддинги (fastembed). SPEC 10.4.
Модель из config.embed_model, авто-загрузка при первом запуске.
ВАЖНО: размерность зависит от модели → при смене нужна переиндексация facts_vec.
"""
from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

from tabula.config import CONFIG

if TYPE_CHECKING:
    from fastembed import TextEmbedding

_model: "TextEmbedding | None" = None


def _get_model() -> "TextEmbedding":
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _model = TextEmbedding(CONFIG.embed_model)
    return _model


def embed(texts: list[str]) -> list[list[float]]:
    """Векторизовать список текстов. Возвращает list[list[float]]."""
    if not texts:
        return []
    model = _get_model()
    return [v.tolist() for v in model.embed(texts)]


def embed_one(text: str) -> list[float]:
    """Векторизовать один текст."""
    return embed([text])[0]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Косинусное сходство двух векторов."""
    import math
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def embedding_dim() -> int:
    """Размерность эмбеддинга текущей модели."""
    v = embed_one("test")
    return len(v)
