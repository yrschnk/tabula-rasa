"""Канонизация концептов. SPEC 5.3.
Веха 2: точное совпадение + алиасы (без векторов).
Веха 5: embedding-кластеризация заменит _find_by_embedding.
"""
from __future__ import annotations

from tabula.store import get_all_concepts, upsert_concept


def canonicalize(name: str, namespace: str) -> str:
    """Найти существующий концепт по имени/алиасам или создать новый.
    Возвращает канон-имя.
    Веха 5: добавить embedding-поиск перед exact-match.
    """
    normalized = name.strip()
    if not normalized:
        return "General"

    concepts = get_all_concepts(namespace)

    # 1. Точное совпадение по канон-имени (case-insensitive)
    for c in concepts:
        if c["name"].lower() == normalized.lower():
            return c["name"]

    # 2. Совпадение по алиасам
    for c in concepts:
        for alias in c["aliases"]:
            if alias.lower() == normalized.lower():
                return c["name"]

    # 3. Embedding-сходство (если есть векторы)
    try:
        from tabula.embeddings import cosine_similarity, embed_one
        from tabula.config import CONFIG
        new_vec = embed_one(normalized)
        for c in concepts:
            if c["embedding"] is not None:
                import struct
                stored = c["embedding"]
                dim = len(stored) // 4
                old_vec = list(struct.unpack(f"{dim}f", stored))
                if cosine_similarity(new_vec, old_vec) >= CONFIG.concept_sim_threshold:
                    # Нашли близкий — добавляем алиас
                    aliases = c["aliases"] + [normalized]
                    upsert_concept(c["name"], namespace, aliases=aliases)
                    return c["name"]
        # Новый концепт с эмбеддингом
        vec_bytes = struct.pack(f"{len(new_vec)}f", *new_vec)
        upsert_concept(normalized, namespace, embedding=vec_bytes)
        return normalized
    except Exception:
        pass

    # 4. Fallback: создаём без эмбеддинга
    upsert_concept(normalized, namespace)
    return normalized


def register_alias(canon_name: str, alias: str, namespace: str) -> None:
    """Добавить алиас к существующему концепту."""
    concepts = get_all_concepts(namespace)
    existing = next((c for c in concepts if c["name"] == canon_name), None)
    aliases = existing["aliases"] if existing else []
    if alias not in aliases:
        aliases.append(alias)
    upsert_concept(canon_name, namespace, aliases=aliases)


def get_concept_registry(namespace: str) -> list[str]:
    """Список канон-имён для промпта extract."""
    return [c["name"] for c in get_all_concepts(namespace)]
