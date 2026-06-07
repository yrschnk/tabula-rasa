"""A.U.D.N: разрешение операции при похожих фактах. SPEC 5.4.
Веха 2: ADD only (hash-дедуп).
Веха 5: find_similar через векторы.
Веха 6: полный A.U.D.N (UPDATE/DELETE через LLM).
"""
from __future__ import annotations

from pathlib import Path

from tabula.config import CONFIG
from tabula.dedup import content_hash
from tabula.models import Fact, FactCandidate, Op
from tabula.store import (
    add_fact, archive, collect_facts, find_by_hash, reinforce, supersede,
)

AUDN_PROMPT_PATH = Path(__file__).parent / "prompts" / "audn.md"


def find_similar(candidate: FactCandidate, namespace: str,
                 k: int | None = None) -> list[Fact]:
    """Поиск похожих фактов.
    Веха 2: concept-scoped (все активные факты того же концепта).
    Веха 5: заменить/дополнить векторным поиском.
    """
    k = k or CONFIG.similar_k
    facts = collect_facts([candidate.concept], namespace)
    # Исключаем точный дубль (уже обработан hash-дедупом)
    ch = content_hash(candidate.content)
    return [f for f in facts if f.content_hash != ch][:k]


def resolve_operation(candidate: FactCandidate,
                      similar: list[Fact]) -> tuple[Op, str | None]:
    """LLM A.U.D.N. SPEC 5.4, Промпт: prompts/audn.md.
    Веха 2: если нет похожих → ADD. LLM вызов включается в вехе 6.
    """
    if not similar:
        return "ADD", None

    # Веха 6: здесь будет LLM-вызов для UPDATE/DELETE/NOOP
    # Пока — простая эвристика: нет похожих → ADD
    return "ADD", None


def apply_candidate(candidate: FactCandidate, namespace: str,
                    source_raw_id: str = "") -> str | None:
    """Полный пайплайн: hash-дедуп → similar → resolve → применить.
    Возвращает fact_id нового факта или None если NOOP/reinforce.
    """
    # 1. Точный дубль — reinforce
    ch = content_hash(candidate.content)
    existing = find_by_hash(ch, namespace)
    if existing:
        reinforce(existing.fact_id, namespace)
        return None

    # 2. Поиск похожих
    similar = find_similar(candidate, namespace)

    # 3. Разрешение операции
    op, target_id = resolve_operation(candidate, similar)

    # 4. Применение
    if op == "ADD":
        return add_fact(candidate, namespace, source_raw_id=source_raw_id)

    elif op == "UPDATE" and target_id:
        supersede(target_id, namespace)
        return add_fact(candidate, namespace)

    elif op == "DELETE" and target_id:
        archive(target_id, namespace)
        return None

    elif op == "NOOP" and target_id:
        reinforce(target_id, namespace)
        return None

    # fallback
    return add_fact(candidate, namespace)
