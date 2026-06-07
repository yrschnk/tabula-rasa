"""Загрузчик LongMemEval. SPEC 6.
Формат датасета: JSON array с полями:
  question_id, question_type, question, answer,
  haystack_sessions: [{session_id, turns: [{role, content, timestamp}]}]
  as_of (опционально)

Скачать: https://github.com/xiaowu0162/LongMemEval
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Iterator

from tabula.models import RawTurn

# Типы вопросов LongMemEval
QUESTION_TYPES = {
    "single-session-user",
    "single-session-assistant",
    "single-session-preference",
    "multi-session",
    "knowledge-update",
    "temporal-reasoning",
}


def load(path: str, sample: int | None = None,
         stratified: bool = True) -> Iterator[dict]:
    """Загрузить датасет и вернуть итератор инстансов.

    Yields:
        dict с ключами:
          question_id: str
          qtype: str
          turns: list[RawTurn]  — реплики сессий для ingest
          question: str
          gold: str             — эталонный ответ
          as_of: str | None     — временная метка вопроса
    """
    data = _load_json(path)

    if sample:
        if stratified:
            data = _stratified_sample(data, sample)
        else:
            random.shuffle(data)
            data = data[:sample]

    for item in data:
        turns = _extract_turns(item)
        yield {
            "question_id": item.get("question_id", item.get("id", "")),
            "qtype": item.get("question_type", "unknown"),
            "turns": turns,
            "question": item.get("question", ""),
            "gold": item.get("answer", ""),
            "as_of": item.get("as_of"),
        }


def _load_json(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"LongMemEval dataset not found: {path}")
    with open(p) as f:
        data = json.load(f)
    if isinstance(data, dict):
        # Может быть обёрнут в {"data": [...]}
        data = data.get("data", list(data.values())[0])
    return data


def _extract_turns(item: dict) -> list[RawTurn]:
    """Развернуть haystack_sessions в список RawTurn."""
    turns = []
    sessions = item.get("haystack_sessions", [])
    if not sessions:
        # Fallback: flat история
        for t in item.get("history", []):
            turns.append(RawTurn(
                text=t.get("content", ""),
                speaker="user" if t.get("role") == "user" else "assistant",
                session_id=item.get("question_id", "default"),
                timestamp=t.get("timestamp", ""),
                source="longmemeval",
            ))
        return turns

    for session in sessions:
        sess_id = session.get("session_id", f"sess_{len(turns)}")
        for t in session.get("turns", []):
            turns.append(RawTurn(
                text=t.get("content", ""),
                speaker="user" if t.get("role") == "user" else "assistant",
                session_id=sess_id,
                timestamp=t.get("timestamp", ""),
                source="longmemeval",
            ))
    return turns


def _stratified_sample(data: list[dict], n: int) -> list[dict]:
    """~равномерная выборка по типам вопросов."""
    by_type: dict[str, list] = {}
    for item in data:
        qt = item.get("question_type", "unknown")
        by_type.setdefault(qt, []).append(item)

    n_types = len(by_type)
    per_type = max(1, n // n_types)
    result = []
    for items in by_type.values():
        random.shuffle(items)
        result.extend(items[:per_type])

    random.shuffle(result)
    return result[:n]
