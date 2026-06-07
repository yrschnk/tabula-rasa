"""Append-only лог операций ingest/update. SPEC 5.7."""
from __future__ import annotations


def append(namespace: str, event: str) -> None:
    raise NotImplementedError
