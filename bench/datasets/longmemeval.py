"""Загрузчик LongMemEval -> поток RawTurn + as_of. SPEC 6.
Типы: single-session-user/assistant/preference, multi-session, knowledge-update, temporal.
Abstention: id с _abs. Каждый инстанс -> свой namespace (изоляция).
"""
from __future__ import annotations


def load(path: str, sample: int | None = None):
    """-> iterable of (question_id, qtype, haystack_sessions, question, gold, as_of)."""
    raise NotImplementedError
