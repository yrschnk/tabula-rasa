"""Дедупликация: normalize + content_hash. SPEC 5.4."""
from __future__ import annotations

import hashlib
import re


def normalize(text: str) -> str:
    """Нижний регистр, сжатые пробелы — для сравнения."""
    return re.sub(r"\s+", " ", text.strip().lower())


def content_hash(text: str) -> str:
    """SHA-256 нормализованного текста."""
    return hashlib.sha256(normalize(text).encode()).hexdigest()
