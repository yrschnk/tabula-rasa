"""Дедупликация: normalize + content_hash. SPEC 5.4."""
from __future__ import annotations


def normalize(text: str) -> str:
    raise NotImplementedError


def content_hash(text: str) -> str:
    raise NotImplementedError
