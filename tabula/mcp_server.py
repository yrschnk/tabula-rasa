"""MCP-сервер Tabula Rasa. SPEC 10.5.
Инструменты + server instructions (decision rubric).
LLM-роли (extract, A.U.D.N, reconstruct) выполняет хост-агент — без API-ключа.

Подключение — одна команда после pip install:
  tabula connect all        # Cursor + Claude Code + Codex
  tabula doctor --skip-embed

Или вручную (~/.claude.json → mcpServers):
  "tabula-rasa": {
    "type": "stdio",
    "command": "/path/to/.venv/bin/python",
    "args": ["-m", "tabula.mcp_server"],
    "cwd": "/path/to/tabula-rasa"
  }
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

RUBRIC_PATH = Path(__file__).parent / "prompts" / "mcp_rubric.md"

_INSTRUCTIONS = RUBRIC_PATH.read_text(encoding="utf-8") if RUBRIC_PATH.exists() else ""

app = Server("tabula-rasa", instructions=_INSTRUCTIONS)

FACT_SCHEMA = {
    "type": "object",
    "properties": {
        "content": {"type": "string", "description": "Атомарный самодостаточный факт"},
        "concept": {"type": "string", "description": "Тема/категория"},
        "attributed_to": {"type": "string", "enum": ["user", "assistant"], "default": "user"},
        "entities": {"type": "array", "items": {"type": "string"}},
        "timestamp": {"type": "string", "description": "ISO дата события (если известна)"},
        "op": {"type": "string", "enum": ["ADD", "UPDATE", "DELETE", "NOOP"]},
        "target_fact_id": {"type": "string", "description": "id (8 символов или UUID) для UPDATE/DELETE/NOOP"},
        "links": {
            "type": "array",
            "items": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2},
            "description": "Связи этого факта с другими концептами",
        },
    },
    "required": ["content", "concept"],
}


# ─── Namespace ────────────────────────────────────────────────────────────────

def _detect_namespace(hint: str | None = None) -> str:
    if hint:
        return hint
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            return f"proj:{Path(result.stdout.strip()).name}"
    except Exception:
        pass
    return "personal"


def _init(namespace: str) -> None:
    from tabula.store import init_schema
    init_schema(namespace)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_links(raw: Any, namespace: str) -> list[tuple[str, str]]:
    from tabula.concepts import canonicalize

    links: list[tuple[str, str]] = []
    if not raw:
        return links
    for pair in raw:
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            a, b = str(pair[0]).strip(), str(pair[1]).strip()
            if a and b and a != b:
                links.append((canonicalize(a, namespace), canonicalize(b, namespace)))
    return links


def _parse_related(raw: Any, namespace: str) -> list[str]:
    from tabula.concepts import canonicalize

    if not raw:
        return []
    return [canonicalize(str(c).strip(), namespace) for c in raw if str(c).strip()]


def _candidate_from_dict(data: dict, namespace: str):
    from tabula.concepts import canonicalize
    from tabula.models import FactCandidate, Op, Speaker

    content = data.get("content", "").strip()
    concept_raw = data.get("concept", "General").strip() or "General"
    canon = canonicalize(concept_raw, namespace)

    attr = data.get("attributed_to", "user")
    if attr not in ("user", "assistant"):
        attr = "user"

    op_raw = data.get("op")
    op: Op | None = op_raw.upper() if op_raw else None  # type: ignore[assignment]

    return FactCandidate(
        content=content,
        concept=canon,
        attributed_to=attr,  # type: ignore[arg-type]
        entities=[str(e) for e in data.get("entities", []) if str(e).strip()],
        timestamp=data.get("timestamp"),
    ), op, data.get("target_fact_id")


def _status_message(status: str, candidate, fid: str | None) -> str:
    prefix = {
        "added": "✅ Сохранено",
        "updated": "✅ Обновлено (старый superseded)",
        "deleted": "✅ Удалено (archived)",
        "noop": "✅ Уже есть (reinforced)",
        "reinforced": "✅ Уже в памяти (дубликат, reinforced)",
    }.get(status, "✅ OK")
    fid_part = f" id={fid[:8]}" if fid else ""
    return f"{prefix}{fid_part}: [{candidate.concept}] {candidate.content}"


def _format_facts_block(header: str, facts: list) -> str:
    from tabula.mcp_apply import format_fact_line

    if not facts:
        return header
    lines = [header]
    for f in facts:
        lines.append(format_fact_line(f))
    return "\n".join(lines)


def _apply_graph(concepts: list[str], links: list[tuple[str, str]], namespace: str,
                 *, session: bool = False) -> None:
    from tabula.graph import update_edges_for_turn, update_session_edges

    unique = list(dict.fromkeys(concepts))
    if len(unique) >= 2 or links:
        update_edges_for_turn(unique, links, namespace)
    if session and len(unique) >= 2:
        update_session_edges(unique, namespace)


# ─── Tools ────────────────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="tabula_add",
            description=(
                "Записать ОДИН атомарный факт. Ты сам делаешь extract и A.U.D.N. "
                "При обновлении знаний: сначала tabula_search, затем op=UPDATE + target_fact_id. "
                "Для нескольких фактов из одной реплики — tabula_add_batch."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **FACT_SCHEMA["properties"],
                    "related_concepts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Другие концепты из той же реплики (co-occurrence в графе)",
                    },
                    "links": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2},
                        "description": "Связи между концептами: [[\"ВНЖ\", \"Испания\"], ...]",
                    },
                    "namespace": {"type": "string"},
                    "session_id": {"type": "string"},
                },
                "required": ["content", "concept"],
            },
        ),
        Tool(
            name="tabula_add_batch",
            description=(
                "Записать несколько фактов из одной реплики/сессии за один вызов. "
                "Строит co-occurrence и LLM-links в графе. Предпочитай для multi-fact utterances."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "facts": {"type": "array", "items": FACT_SCHEMA, "minItems": 1},
                    "links": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2},
                    },
                    "utterance": {
                        "type": "string",
                        "description": "Исходная полная реплика пользователя (сохраняется в raw для аудита)",
                    },
                    "namespace": {"type": "string"},
                    "session_id": {"type": "string"},
                },
                "required": ["facts"],
            },
        ),
        Tool(
            name="tabula_update",
            description="Явно заменить старый факт новым (UPDATE/supersede). Как update_memory у Mem0.",
            inputSchema={
                "type": "object",
                "properties": {
                    "target_fact_id": {"type": "string", "description": "id старого факта (8 символов или UUID)"},
                    "content": {"type": "string"},
                    "concept": {"type": "string"},
                    "attributed_to": {"type": "string", "enum": ["user", "assistant"]},
                    "entities": {"type": "array", "items": {"type": "string"}},
                    "timestamp": {"type": "string"},
                    "namespace": {"type": "string"},
                },
                "required": ["target_fact_id", "content", "concept"],
            },
        ),
        Tool(
            name="tabula_forget",
            description="Удалить/архивировать факт (DELETE). Как delete_memory у Mem0.",
            inputSchema={
                "type": "object",
                "properties": {
                    "target_fact_id": {"type": "string"},
                    "namespace": {"type": "string"},
                },
                "required": ["target_fact_id"],
            },
        ),
        Tool(
            name="tabula_ask",
            description=(
                "Hybrid retrieval (FTS+vectors+activation) → сырые факты с id. "
                "Ты сам синтезируешь ответ. Вызывай в начале сессии и при вопросах о прошлом."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "namespace": {"type": "string"},
                    "mode": {"type": "string", "enum": ["activation", "fts5"], "default": "activation"},
                    "as_of": {"type": "string"},
                    "token_budget": {
                        "type": "integer",
                        "description": "Лимит токенов фактов (default из config, ~4000)",
                    },
                },
                "required": ["question"],
            },
        ),
        Tool(
            name="tabula_search",
            description=(
                "Hybrid поиск фактов (FTS + vectors, RRF). Возвращает fact_id для A.U.D.N. "
                "Вызывай перед tabula_add при обновлении/противоречии."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "namespace": {"type": "string"},
                    "k": {"type": "integer", "default": 10},
                    "use_activation": {
                        "type": "boolean",
                        "default": True,
                        "description": "Rerank через spreading activation (веса рёбер графа)",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="tabula_sync",
            description="Пересобрать markdown wiki (Obsidian) из SQLite. Для просмотра памяти человеком.",
            inputSchema={
                "type": "object",
                "properties": {"namespace": {"type": "string"}},
            },
        ),
        Tool(
            name="tabula_status",
            description="Статус памяти: концепты, факты, размер графа.",
            inputSchema={
                "type": "object",
                "properties": {"namespace": {"type": "string"}},
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    ns = _detect_namespace(arguments.get("namespace"))
    _init(ns)

    handlers = {
        "tabula_add": _handle_add,
        "tabula_add_batch": _handle_add_batch,
        "tabula_update": _handle_update,
        "tabula_forget": _handle_forget,
        "tabula_ask": _handle_ask,
        "tabula_search": _handle_search,
        "tabula_sync": _handle_sync,
        "tabula_status": _handle_status,
    }
    handler = handlers.get(name)
    if handler is None:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]
    return await handler(arguments, ns)


# ─── Handlers ─────────────────────────────────────────────────────────────────

async def _handle_add(args: dict, ns: str) -> list[TextContent]:
    from tabula.mcp_apply import apply_mcp_candidate, format_similar_block
    from tabula.models import RawTurn
    from tabula.raw_store import write_raw

    candidate, op, target_id = _candidate_from_dict(args, ns)
    if not candidate.content:
        return [TextContent(type="text", text="❌ Пустой факт.")]

    ts = candidate.timestamp or turn_ts()
    turn = RawTurn(
        text=candidate.content,
        namespace=ns,
        session_id=args.get("session_id", ""),
        speaker=candidate.attributed_to,
        timestamp=ts,
    )
    write_raw(turn)

    fid, status, similar = apply_mcp_candidate(
        candidate, ns,
        source_raw_id=turn.raw_id,
        op=op,
        target_fact_id=target_id,
    )

    if status == "needs_audn":
        return [TextContent(type="text", text=format_similar_block(similar))]

    related = _parse_related(args.get("related_concepts"), ns)
    links = _parse_links(args.get("links"), ns)
    concepts = list(dict.fromkeys([candidate.concept, *related]))
    _apply_graph(concepts, links, ns)

    return [TextContent(type="text", text=_status_message(status, candidate, fid))]


async def _handle_add_batch(args: dict, ns: str) -> list[TextContent]:
    from tabula.mcp_apply import apply_mcp_candidate, format_similar_block
    from tabula.models import RawTurn
    from tabula.raw_store import write_raw

    raw_facts = args.get("facts", [])
    if not raw_facts:
        return [TextContent(type="text", text="❌ Пустой список facts.")]

    session_id = args.get("session_id", "")
    utterance = args.get("utterance", "").strip()
    batch_source_id = ""

    if utterance:
        u_turn = RawTurn(text=utterance, namespace=ns, session_id=session_id)
        write_raw(u_turn)
        batch_source_id = u_turn.raw_id

    all_links = _parse_links(args.get("links"), ns)
    all_concepts: list[str] = []
    lines: list[str] = []
    blocked = False

    for item in raw_facts:
        candidate, op, target_id = _candidate_from_dict(item, ns)
        all_links.extend(_parse_links(item.get("links"), ns))
        if not candidate.content:
            continue

        turn = RawTurn(
            text=candidate.content,
            namespace=ns,
            session_id=session_id,
            speaker=candidate.attributed_to,
            timestamp=candidate.timestamp or turn_ts(),
        )
        write_raw(turn)
        source_id = batch_source_id or turn.raw_id

        fid, status, similar = apply_mcp_candidate(
            candidate, ns,
            source_raw_id=source_id,
            op=op,
            target_fact_id=target_id,
        )

        if status == "needs_audn":
            lines.append(format_similar_block(similar))
            blocked = True
            continue

        all_concepts.append(candidate.concept)
        lines.append(_status_message(status, candidate, fid))

    if all_concepts:
        _apply_graph(all_concepts, all_links, ns, session=True)

    header = "[TABULA: batch — часть фактов требует A.U.D.N]" if blocked else "[TABULA: batch сохранён]"
    return [TextContent(type="text", text=header + "\n" + "\n".join(lines))]


async def _handle_update(args: dict, ns: str) -> list[TextContent]:
    args = {**args, "op": "UPDATE"}
    return await _handle_add(args, ns)


async def _handle_forget(args: dict, ns: str) -> list[TextContent]:
    from tabula.mcp_apply import resolve_target_id
    from tabula.store import archive, get_fact

    target = args.get("target_fact_id", "")
    target_id = resolve_target_id(target, ns)
    if not target_id:
        return [TextContent(type="text", text=f"❌ Факт id={target} не найден.")]

    old = get_fact(target_id, ns)
    if not old or old.status != "active":
        return [TextContent(type="text", text=f"❌ Факт id={target} не найден или уже неактивен.")]

    archive(target_id, ns)
    return [TextContent(type="text", text=f"✅ Забыт (archived): id={target_id[:8]} {old.content}")]


async def _handle_ask(args: dict, ns: str) -> list[TextContent]:
    from tabula.mcp_apply import format_fact_line
    from tabula.retrieval import activation_map, retrieve_facts

    question = args["question"]
    mode = args.get("mode", "activation")
    as_of = args.get("as_of")
    token_budget = args.get("token_budget", 0)

    facts, activated, abstained = retrieve_facts(
        question, ns, mode=mode, as_of=as_of, token_budget=token_budget,
    )
    if abstained:
        return [TextContent(type="text", text="[TABULA: памяти по этой теме нет]")]

    scores = activation_map(activated)
    nodes = ", ".join(f"{c}({scores[c]:.2f})" for c, _ in activated[:5])
    lines = [
        f"[TABULA: {len(facts)} фактов · mode={mode} · graph-nodes: {nodes}]",
        "Синтезируй ответ сам. Учитывай act= (activation), attributed_to и даты.",
    ]
    for f in facts:
        lines.append(format_fact_line(f, activation=scores.get(f.concept)))
    return [TextContent(type="text", text="\n".join(lines))]


async def _handle_search(args: dict, ns: str) -> list[TextContent]:
    from tabula.mcp_apply import format_fact_line
    from tabula.retrieval import activation_map
    from tabula.search import search_facts_reranked

    k = args.get("k", 10)
    use_activation = args.get("use_activation", True)
    facts = search_facts_reranked(args["query"], ns, k=k, use_activation=use_activation)
    if not facts:
        return [TextContent(type="text", text="[TABULA: ничего не найдено]")]

    scores: dict[str, float] = {}
    if use_activation:
        from tabula.activation import activate
        scores = activation_map(activate(args["query"], ns, mode="activation"))

    lines = [f"[TABULA: найдено {len(facts)} фактов по '{args['query']}']"]
    for f in facts:
        lines.append(format_fact_line(f, activation=scores.get(f.concept)))
    return [TextContent(type="text", text="\n".join(lines))]


async def _handle_sync(args: dict, ns: str) -> list[TextContent]:
    from tabula.graph import load_graph
    from tabula.projection import rebuild_wiki

    G = load_graph(ns)
    rebuild_wiki(ns)
    return [TextContent(
        type="text",
        text=(
            f"✅ Sync завершён · namespace={ns}\n"
            f"  Граф: {G.number_of_nodes()} узлов, {G.number_of_edges()} рёбер\n"
            f"  Wiki обновлена в {ns}/"
        ),
    )]


async def _handle_status(args: dict, ns: str) -> list[TextContent]:
    from tabula.graph import load_graph
    from tabula.store import collect_facts, get_all_concepts

    concepts = get_all_concepts(ns)
    facts = collect_facts([c["name"] for c in concepts], ns)
    G = load_graph(ns)

    lines = [
        f"📦 **Namespace:** {ns}",
        f"  Концептов : {len(concepts)}",
        f"  Фактов    : {len(facts)}",
        f"  Граф      : {G.number_of_nodes()} узлов, {G.number_of_edges()} рёбер",
    ]
    if concepts:
        lines.append("\n  Топ концептов:")
        for c in concepts[:8]:
            lines.append(f"    · {c['name']}")

    return [TextContent(type="text", text="\n".join(lines))]


def turn_ts() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ─── Entry point ──────────────────────────────────────────────────────────────

async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream,
                      app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
