"""Ingest: extract пачкой по сессии (Haiku) + кэш по hash. SPEC 5.3."""
from __future__ import annotations

from tabula.models import FactCandidate, RawTurn


def extract_facts_for_session(turns: list[RawTurn]) -> list[FactCandidate]:
    """Один LLM extract-вызов на сессию. Промпт: prompts/extract.md."""
    raise NotImplementedError


def ingest_turn(turn: RawTurn) -> None:
    """add → raw_store → (накопление сессии) → extract → dedup/update → store."""
    raise NotImplementedError
