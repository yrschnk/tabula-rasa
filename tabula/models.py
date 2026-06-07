"""Базовые модели данных. SPEC 5.1, 5.5, 5.10."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

Speaker = Literal["user", "assistant"]
Op = Literal["ADD", "UPDATE", "DELETE", "NOOP"]
Status = Literal["active", "superseded", "archived"]


@dataclass
class RawTurn:
    """Единица входа — реплика. SPEC 5.1."""
    text: str
    raw_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    speaker: Speaker = "user"
    session_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = "cli"          # cli | longmemeval | locomo | import
    namespace: str = "personal"

    def __post_init__(self):
        if not self.session_id:
            self.session_id = f"sess_{datetime.now(timezone.utc).strftime('%Y%m%d')}"


@dataclass
class FactCandidate:
    """Кандидат факта после LLM extract. SPEC 5.3."""
    content: str
    concept: str
    attributed_to: Speaker = "user"
    entities: list[str] = field(default_factory=list)
    timestamp: Optional[str] = None
    links: list[tuple[str, str]] = field(default_factory=list)  # [(src,dst)]


@dataclass
class Fact:
    """Сохранённый факт из SQLite. SPEC 5.5."""
    fact_id: str
    namespace: str
    content: str
    content_hash: str
    concept: str
    attributed_to: str
    entities: list[str]
    timestamp: Optional[str]
    valid_from: str
    valid_to: Optional[str]
    strength: float
    reinforce_cnt: int
    source_raw_id: str
    status: Status
    created_at: str


@dataclass
class QueryResult:
    """Структурный результат query. SPEC 5.10."""
    answer: str
    sources: list[str] = field(default_factory=list)         # fact_id
    activated_nodes: list[str] = field(default_factory=list)  # concept
    confidence: float = 0.0
    abstained: bool = False
