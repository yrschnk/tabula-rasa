"""MCP-path: запись фактов без LLM (A.U.D.N решает агент). SPEC 5.4, 10.5."""
from __future__ import annotations

from tabula.dedup import content_hash
from tabula.models import Fact, FactCandidate, Op
from tabula.store import (
    add_fact,
    archive,
    find_by_hash,
    get_fact,
    init_schema,
    reinforce,
    supersede,
    upsert_concept,
)
from tabula.update import _index_embedding, find_similar


def resolve_target_id(
    target: str | None,
    namespace: str,
    similar: list[Fact] | None = None,
) -> str | None:
    """Разрешить fact_id по полному UUID или 8-символьному префиксу."""
    if not target:
        return None
    target = target.strip()
    if len(target) >= 32:
        f = get_fact(target, namespace)
        return f.fact_id if f else None
    pool = similar or []
    for f in pool:
        if f.fact_id.startswith(target):
            return f.fact_id
    # Поиск по префиксу в сторе
    from tabula.store import _conn

    with _conn(namespace) as con:
        row = con.execute(
            "SELECT fact_id FROM facts WHERE fact_id LIKE ? AND status='active' LIMIT 1",
            (f"{target}%",),
        ).fetchone()
    return row["fact_id"] if row else None


def format_fact_line(
    f: Fact,
    *,
    include_entities: bool = True,
    activation: float | None = None,
) -> str:
    """Строка факта для MCP-ответов (с id для A.U.D.N)."""
    ts = f.timestamp or f.valid_from[:10]
    act_part = f"act={activation:.2f} · " if activation is not None else ""
    parts = [f"id={f.fact_id[:8]}", f"[{f.concept}]", f"({act_part}{ts} · {f.attributed_to})"]
    if include_entities and f.entities:
        parts.append(f"entities: {', '.join(f.entities)}")
    parts.append(f.content)
    return "• " + " ".join(parts)


def format_similar_block(similar: list[Fact]) -> str:
    lines = ["[TABULA: найдены похожие факты — выбери op и target_fact_id]"]
    for f in similar:
        lines.append(format_fact_line(f))
    lines.append(
        "Повтори tabula_add с op=UPDATE|DELETE|NOOP|ADD и target_fact_id=id, "
        "или tabula_update / tabula_forget."
    )
    return "\n".join(lines)


ApplyResult = tuple[str | None, str, list[Fact]]


def apply_mcp_candidate(
    candidate: FactCandidate,
    namespace: str,
    source_raw_id: str = "",
    op: Op | None = None,
    target_fact_id: str | None = None,
    *,
    skip_similar_check: bool = False,
) -> ApplyResult:
    """Запись факта в MCP-mode без LLM.

    Returns:
        (new_fact_id | None, status, similar_facts)
        status: added | reinforced | updated | deleted | noop | needs_audn
    """
    init_schema(namespace)
    upsert_concept(candidate.concept, namespace)

    resolved_op: Op = op or "ADD"
    target_id = resolve_target_id(target_fact_id, namespace)

    # DELETE/NOOP не проходят через hash-дедуп
    if resolved_op == "DELETE":
        if not target_id:
            similar = [] if skip_similar_check else find_similar(candidate, namespace)
            return None, "needs_audn", similar or []
        archive(target_id, namespace)
        return None, "deleted", []

    if resolved_op == "NOOP":
        if not target_id:
            similar = [] if skip_similar_check else find_similar(candidate, namespace)
            return None, "needs_audn", similar or []
        reinforce(target_id, namespace)
        return None, "noop", []

    ch = content_hash(candidate.content)
    existing = find_by_hash(ch, namespace)
    if existing:
        reinforce(existing.fact_id, namespace)
        return None, "reinforced", []

    similar = [] if skip_similar_check else find_similar(candidate, namespace)

    if resolved_op == "ADD" and op is None and similar:
        return None, "needs_audn", similar

    if resolved_op == "UPDATE":
        if not target_id:
            return None, "needs_audn", similar or []
        supersede(target_id, namespace)
        fid = add_fact(candidate, namespace, source_raw_id=source_raw_id)
        _index_embedding(fid, candidate.content, namespace)
        return fid, "updated", similar

    # ADD (явный или по умолчанию)
    fid = add_fact(candidate, namespace, source_raw_id=source_raw_id)
    _index_embedding(fid, candidate.content, namespace)
    return fid, "added", similar
