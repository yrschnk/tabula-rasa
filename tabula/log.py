"""Append-only лог операций ingest/update. SPEC 5.7."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from tabula.config import CONFIG


def append(namespace: str, event: str) -> None:
    """Дописать строку в wiki/{namespace}/log.md."""
    log_path = CONFIG.wiki_dir / namespace / "log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"- {ts} — {event}\n")
