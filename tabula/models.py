"""Базовые модели данных. См. SPEC.md разделы 5.1, 5.5, 5.10."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

Speaker = Literal["user", "assistant"]
Op = Literal["ADD", "UPDATE", "DELETE", "NOOP"]


@dataclass
class RawTurn:
    """Единица входа (реплика). SPEC 5.1."""
    text: str
    raw_id: str = ""
    speaker: Speaker = "user"
    session_id: str = ""
    timestamp: str = ""          # ISO8601
    source: str = "cli"          # cli | longmemeval | locomo | import
    namespace: str = "personal"


@dataclass
class FactCandidate:
    """Кандидат факта после extract. SPEC 5.3."""
    content: str
    concept: str
    attributed_to: Speaker = "user"
    entities: list[str] = field(default_factory=list)
    timestamp: Optional[str] = None


@dataclass
class QueryResult:
    """Структурный результат query. SPEC 5.10."""
    answer: str
    sources: list[str] = field(default_factory=list)        # fact_id
    activated_nodes: list[str] = field(default_factory=list) # concept
    confidence: float = 0.0
    abstained: bool = False
