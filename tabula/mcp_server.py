"""MCP-сервер Tabula Rasa. SPEC 10.5.
4 инструмента + server instructions (decision rubric).
Дефолтный backend = MCP sampling: LLM-вызовы делегируются хост-агенту
(Claude Code / Cursor) через session.create_message() — без API-ключа.

Подключение (добавить в ~/.claude.json → mcpServers):
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

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

RUBRIC_PATH = Path(__file__).parent / "prompts" / "mcp_rubric.md"

_INSTRUCTIONS = RUBRIC_PATH.read_text(encoding="utf-8") if RUBRIC_PATH.exists() else ""

app = Server("tabula-rasa", instructions=_INSTRUCTIONS)


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


# ─── Tools ────────────────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="tabula_add",
            description=(
                "Записать ОДИН атомарный факт в память. "
                "Ты сам заранее извлекаешь факты из текста пользователя и вызываешь "
                "этот инструмент по одному разу на каждый факт. "
                "Указывай concept — тему/категорию факта."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "string",
                                "description": "Один атомарный самодостаточный факт"},
                    "concept": {"type": "string",
                                "description": "Тема/категория факта (Переезд, Финансы, Работа…)"},
                    "namespace": {"type": "string", "description": "Namespace (default: auto)"},
                    "session_id": {"type": "string"},
                },
                "required": ["content", "concept"],
            },
        ),
        Tool(
            name="tabula_ask",
            description=(
                "Получить сырые факты из памяти по теме. "
                "Ты сам формулируешь связный ответ из возвращённых фактов. "
                "Вызывай в начале сессии и когда пользователь спрашивает о прошлом."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "namespace": {"type": "string"},
                    "mode": {"type": "string", "enum": ["activation", "fts5"],
                             "default": "activation"},
                    "as_of": {"type": "string"},
                },
                "required": ["question"],
            },
        ),
        Tool(
            name="tabula_search",
            description="Быстрый поиск сырых фактов без LLM-реконструкции.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "namespace": {"type": "string"},
                    "k": {"type": "integer", "default": 10},
                },
                "required": ["query"],
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

    if name == "tabula_add":
        return await _handle_add(arguments, ns)
    elif name == "tabula_ask":
        return await _handle_ask(arguments, ns)
    elif name == "tabula_search":
        return await _handle_search(arguments, ns)
    elif name == "tabula_status":
        return await _handle_status(ns)
    return [TextContent(type="text", text=f"Unknown tool: {name}")]


# ─── Handlers ─────────────────────────────────────────────────────────────────

async def _handle_add(args: dict, ns: str) -> list[TextContent]:
    """Записать один атомарный факт. Extract уже выполнен агентом."""
    from tabula.concepts import canonicalize
    from tabula.graph import update_edges_for_turn
    from tabula.models import FactCandidate, RawTurn
    from tabula.raw_store import write_raw
    from tabula.update import apply_candidate

    content = args.get("content", args.get("text", "")).strip()
    concept_raw = args.get("concept", "General").strip() or "General"

    if not content:
        return [TextContent(type="text", text="❌ Пустой факт.")]

    # Сырьё
    turn = RawTurn(text=content, namespace=ns,
                   session_id=args.get("session_id", ""))
    write_raw(turn)

    # Канонизация концепта + запись факта
    canon = canonicalize(concept_raw, ns)
    c = FactCandidate(content=content, concept=canon, attributed_to="user")
    fid = apply_candidate(c, ns, source_raw_id=turn.raw_id)

    if fid is None:
        return [TextContent(type="text", text="✅ Уже в памяти (дубликат).")]

    # Граф — записать co-occurrence с другими концептами этой сессии
    update_edges_for_turn([canon], [], ns)

    return [TextContent(type="text", text=f"✅ Сохранено: [{canon}] {content}")]


async def _handle_ask(args: dict, ns: str) -> list[TextContent]:
    """Найти релевантные факты. Агент сам формулирует ответ из них."""
    from tabula.activation import activate
    from tabula.config import CONFIG
    from tabula.store import collect_facts

    question = args["question"]
    mode = args.get("mode", "activation")
    as_of = args.get("as_of")

    # Поиск концептов через FTS5 + vectors + spreading activation
    activated = activate(question, ns, mode=mode)
    concepts = [c for c, _ in activated]
    facts = collect_facts(concepts, ns, as_of=as_of)

    max_act = activated[0][1] if activated else 0.0
    if not facts or max_act < CONFIG.abstain_threshold:
        return [TextContent(type="text",
                            text="[TABULA: памяти по этой теме нет]")]

    # Возвращаем сырые факты — агент сам делает reconstruct
    lines = [f"[TABULA: найдено {len(facts)} фактов по теме '{question}']"]
    for f in facts:
        ts = f.timestamp or f.valid_from[:10]
        lines.append(f"• [{f.concept}] ({ts}) {f.content}")

    return [TextContent(type="text", text="\n".join(lines))]


async def _handle_search(args: dict, ns: str) -> list[TextContent]:
    from tabula.store import collect_facts, search_fts

    k = args.get("k", 10)
    hits = search_fts(args["query"], ns, k=k)
    if not hits:
        return [TextContent(type="text", text="Ничего не найдено.")]

    concepts = [c for c, _ in hits]
    facts = collect_facts(concepts, ns)[:k]
    lines = [f"- [{f.concept}] {f.content}" for f in facts]
    return [TextContent(type="text", text="\n".join(lines))]


async def _handle_status(ns: str) -> list[TextContent]:
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


# ─── Entry point ──────────────────────────────────────────────────────────────

async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream,
                      app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
