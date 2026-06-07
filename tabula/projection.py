"""Markdown-проекция для Obsidian (только просмотр). SPEC 5.7.
Генерируется из SQLite. Редактировать руками не стоит — перезапишется при sync.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from tabula.config import CONFIG
from tabula.store import _conn, collect_facts, get_all_concepts, get_edges


def _collect_all_facts(concept: str, namespace: str):
    """Все факты концепта включая superseded/archived."""
    with _conn(namespace) as con:
        rows = con.execute(
            "SELECT * FROM facts WHERE namespace=? AND concept=? ORDER BY valid_from",
            (namespace, concept),
        ).fetchall()
    from tabula.store import _row_to_fact
    return [_row_to_fact(r) for r in rows]


def render_concept_page(concept: str, namespace: str) -> str:
    """Рендерить страницу концепта по шаблону SPEC Приложение B."""
    all_facts = _collect_all_facts(concept, namespace)
    active = [f for f in all_facts if f.status == "active"]
    superseded = [f for f in all_facts if f.status in ("superseded", "archived")]

    # Связанные концепты из графа
    edges = get_edges(namespace)
    linked = []
    for e in edges:
        if e["src_concept"] == concept:
            linked.append(e["dst_concept"])
        elif e["dst_concept"] == concept:
            linked.append(e["src_concept"])
    linked = sorted(set(linked))
    wikilinks = " ".join(f"[[{c}]]" for c in linked[:10])

    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines = [
        "---",
        f"title: {concept}",
        f"updated: {updated}",
        f"links: [{', '.join(repr(f'[[{c}]]') for c in linked[:10])}]",
        "---",
        "",
        f"# {concept}",
        "",
    ]

    if linked:
        lines += [f"> Связано с: {wikilinks}", ""]

    lines += ["## Актуальные факты", ""]
    if active:
        for f in active:
            ts = f.timestamp or f.valid_from[:10]
            lines.append(f"- ({f.fact_id[:8]} · {ts} · {f.attributed_to}) {f.content} ^{f.fact_id[:8]}")
    else:
        lines.append("_нет актуальных фактов_")

    if superseded:
        lines += ["", "## История (superseded/archived)", ""]
        for f in superseded:
            ts_from = f.valid_from[:10]
            ts_to = f.valid_to[:10] if f.valid_to else "?"
            lines.append(f"- ({f.fact_id[:8]} · {ts_from} → {ts_to}) {f.content}")

    return "\n".join(lines) + "\n"


def rebuild_wiki(namespace: str) -> None:
    """Пересобрать все концепт-страницы из SQLite. SPEC 5.7."""
    wiki_dir = CONFIG.wiki_dir / namespace / "concepts"
    wiki_dir.mkdir(parents=True, exist_ok=True)

    concepts = get_all_concepts(namespace)
    for c in concepts:
        name = c["name"]
        content = render_concept_page(name, namespace)
        safe_name = name.replace("/", "_").replace("\\", "_")
        path = wiki_dir / f"{safe_name}.md"
        path.write_text(content, encoding="utf-8")

    # Обновить index.md
    _write_index(namespace, [c["name"] for c in concepts])


def _write_index(namespace: str, concept_names: list[str]) -> None:
    index_path = CONFIG.wiki_dir / namespace / "index.md"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Tabula Rasa — Index",
        f"_Обновлено: {updated}_",
        f"_Namespace: {namespace}_",
        "",
        "## Концепты",
        "",
    ]
    for name in sorted(concept_names):
        lines.append(f"- [[{name}]]")
    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
