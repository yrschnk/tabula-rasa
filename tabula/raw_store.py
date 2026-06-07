"""Иммутабельный raw-слой (JSON). SPEC 5.2."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from tabula.config import CONFIG
from tabula.models import RawTurn


def _turn_path(namespace: str, session_id: str, raw_id: str) -> Path:
    p = CONFIG.raw_dir / namespace / session_id / f"{raw_id}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def write_raw(turn: RawTurn) -> str:
    """Записать реплику. Идемпотентно (одинаковый raw_id → тот же файл)."""
    path = _turn_path(turn.namespace, turn.session_id, turn.raw_id)
    if not path.exists():
        path.write_text(json.dumps(asdict(turn), ensure_ascii=False, indent=2))
    return turn.raw_id


def read_raw(raw_id: str, namespace: str = "personal",
             session_id: str = "") -> RawTurn:
    # Если session_id не задан — ищем по всем сессиям
    base = CONFIG.raw_dir / namespace
    if session_id:
        path = _turn_path(namespace, session_id, raw_id)
    else:
        found = list(base.rglob(f"{raw_id}.json"))
        if not found:
            raise FileNotFoundError(f"raw_id={raw_id} not found in ns={namespace}")
        path = found[0]
    data = json.loads(path.read_text())
    return RawTurn(**data)


def iter_session(session_id: str, namespace: str = "personal"):
    """Итератор по всем репликам сессии (порядок по timestamp)."""
    session_dir = CONFIG.raw_dir / namespace / session_id
    if not session_dir.exists():
        return
    files = sorted(session_dir.glob("*.json"))
    for f in files:
        data = json.loads(f.read_text())
        yield RawTurn(**data)


def clear_raw(namespace: str) -> None:
    """Очистить raw для namespace (для тестов)."""
    import shutil
    p = CONFIG.raw_dir / namespace
    if p.exists():
        shutil.rmtree(p)
