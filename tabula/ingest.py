"""Ingest: extract пачкой по сессии (Haiku) + кэш по hash. SPEC 5.3."""
from __future__ import annotations

from pathlib import Path

from tabula.concepts import canonicalize, get_concept_registry
from tabula.dedup import content_hash
from tabula.llm import llm
from tabula.models import FactCandidate, RawTurn
from tabula.raw_store import write_raw
from tabula.store import find_by_hash, init_schema, reinforce

PROMPT_PATH = Path(__file__).parent / "prompts" / "extract.md"


def _get_processed_raw_ids(namespace: str) -> set[str]:
    """Вернуть set raw_id реплик, уже обработанных в этом namespace."""
    from tabula.store import _conn
    with _conn(namespace) as con:
        rows = con.execute(
            "SELECT DISTINCT source_raw_id FROM facts WHERE namespace=? AND source_raw_id != ''",
            (namespace,),
        ).fetchall()
    return {r["source_raw_id"] for r in rows}


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _format_turns(turns: list[RawTurn]) -> str:
    lines = []
    for t in turns:
        lines.append(f"[{t.timestamp}] {t.speaker}: {t.text}")
    return "\n".join(lines)


def extract_facts_for_session(turns: list[RawTurn],
                               namespace: str = "personal") -> list[FactCandidate]:
    """Один LLM extract-вызов на сессию. SPEC 5.3."""
    if not turns:
        return []

    registry = get_concept_registry(namespace)
    registry_str = ", ".join(registry) if registry else "(пока пусто)"

    prompt = (
        _load_prompt()
        .replace("{concept_registry}", registry_str)
        .replace("{session_turns}", _format_turns(turns))
    )

    raw = llm().complete_json(prompt, model_hint="extract")

    candidates = []
    for f in raw.get("facts", []):
        content = f.get("content", "").strip()
        if not content:
            continue
        concept_raw = f.get("concept", "General")
        canon = canonicalize(concept_raw, namespace)
        candidates.append(FactCandidate(
            content=content,
            concept=canon,
            attributed_to=f.get("attributed_to", "user"),
            entities=f.get("entities", []),
            timestamp=f.get("timestamp"),
            links=[(a, b) for a, b in raw.get("links", [])
                   if a == concept_raw or b == concept_raw],
        ))
    return candidates


def ingest_session(turns: list[RawTurn], namespace: str = "personal") -> int:
    """Полный пайплайн для списка реплик одной сессии.
    Возвращает число добавленных/обновлённых фактов.
    """
    from tabula.update import apply_candidate

    if not turns:
        return 0

    init_schema(namespace)

    # Записываем сырьё
    for turn in turns:
        write_raw(turn)

    # Кэш: пропускаем реплики, raw_id которых уже записан в raw_store
    # (write_raw идемпотентен — файл существует → уже обработано)
    from tabula.config import CONFIG
    new_turns = []
    for turn in turns:
        raw_path = (CONFIG.raw_dir / namespace / turn.session_id
                    / f"{turn.raw_id}.json")
        # Файл ещё не существовал до write_raw выше →
        # мы только что его создали → нужно обработать.
        # Используем флаг: если файл уже существовал ДО нашего write_raw
        # мы не можем это проверить в текущей схеме.
        # Поэтому используем более надёжный кэш: hash текста → уже есть факты?
        # Но это семантически неверно (факты могут прийти из другой реплики).
        # Правильный кэш для сессионного ingest: сравниваем raw_id.
        # В тестах используем одинаковые объекты → одинаковые raw_id.
        new_turns.append(turn)

    # Настоящий кэш: если сессия уже имеет факты с source_raw_id этих реплик
    processed_ids = _get_processed_raw_ids(namespace)
    truly_new = [t for t in new_turns if t.raw_id not in processed_ids]

    if not truly_new:
        return 0

    new_turns = truly_new

    # Для кэша: все raw_id новых реплик объединяем в один source
    source_raw_ids = ",".join(t.raw_id for t in truly_new)

    candidates = extract_facts_for_session(truly_new, namespace)
    count = 0
    for c in candidates:
        from tabula.update import apply_candidate as _apply
        fid = _apply(c, namespace, source_raw_id=source_raw_ids)
        if fid:
            count += 1
    return count


def ingest_turn(turn: RawTurn) -> None:
    """Один turn → ingest_session с одной репликой. SPEC 5.3."""
    ingest_session([turn], namespace=turn.namespace)
