"""Иммутабельный raw-слой (JSON). SPEC 5.2."""
from __future__ import annotations

from tabula.models import RawTurn


def write_raw(turn: RawTurn) -> str:
    """raw/{namespace}/{session_id}/{raw_id}.json. Возвращает raw_id."""
    raise NotImplementedError


def read_raw(raw_id: str, namespace: str = "personal") -> RawTurn:
    raise NotImplementedError


def iter_session(session_id: str, namespace: str = "personal"):
    raise NotImplementedError
