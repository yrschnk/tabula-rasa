"""MCP-сервер Tabula Rasa. SPEC 10.5.
4 инструмента + server instructions (decision rubric).
Дефолтный backend = MCP sampling (LLM-роль у хоста, без API-ключа).

Подключение к Claude Code / Cursor / Codex (добавить в mcp config):
  {
    "tabula-rasa": {
      "command": "python",
      "args": ["-m", "tabula.mcp_server"],
      "cwd": "/path/to/tabula-rasa"
    }
  }
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# ─── Загрузка decision rubric ─────────────────────────────────────────────────

RUBRIC_PATH = Path(__file__).parent / "prompts" / "mcp_rubric.md"

_INSTRUCTIONS = RUBRIC_PATH.read_text(encoding="utf-8") if RUBRIC_PATH.exists() else ""

# ─── Авто-определение namespace по git-root ───────────────────────────────────

def _detect_namespace(hint: str | None = None) -> str:
    if hint:
        return hint
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            repo = Path(result.stdout.strip()).name
            return f"proj:{repo}"
    except Exception:
        pass
    return "personal"


# ─── Инициализация ────────────────────────────────────────────────────────────

def _init(namespace: str) -> None:
    from tabula.store import init_schema
    init_schema(namespace)


# ─── MCP-сервер ───────────────────────────────────────────────────────────────

app = Server("tabula-rasa", instructions=_INSTRUCTIONS)


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="tabula_add",
            description=(
                "Записать текст/факт/решение в персональную память Tabula Rasa. "
                "Вызывай проактивно когда пользователь сообщает важный факт, "
                "решение или предпочтение."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Текст для записи"},
                    "namespace": {"type": "string", "description": "Namespace (default: auto)"},
                    "session_id": {"type": "string", "description": "ID сессии (optional)"},
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="tabula_ask",
            description=(
                "Спросить персональную память. Вызывай в начале темы и "
                "когда пользователь спрашивает о прошлом ('что мы решали', 'что я говорил про X')."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Вопрос к памяти"},
                    "namespace": {"type": "string"},
                    "mode": {"type": "string", "enum": ["activation", "fts5"],
                             "default": "activation"},
                    "as_of": {"type": "string", "description": "ISO дата для temporal вопросов"},
                },
                "required": ["question"],
            },
        ),
        Tool(
            name="tabula_search",
            description="Быстрый поиск фактов без LLM-реконструкции. Возвращает сырые факты.",
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
            description="Показать статус памяти: концепты, факты, размер графа.",
            inputSchema={
                "type": "object",
                "properties": {
                    "namespace": {"type": "string"},
                },
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
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def _handle_add(args: dict, ns: str) -> list[TextContent]:
    from tabula.ingest import ingest_session
    from tabula.models import RawTurn

    turn = RawTurn(
        text=args["text"],
        namespace=ns,
        session_id=args.get("session_id", ""),
    )
    count = ingest_session([turn], namespace=ns)
    return [TextContent(type="text",
                        text=f"✅ Записано. Добавлено фактов: {count}")]


async def _handle_ask(args: dict, ns: str) -> list[TextContent]:
    from tabula.retrieval import query

    result = query(
        args["question"],
        namespace=ns,
        as_of=args.get("as_of"),
        mode=args.get("mode", "activation"),
    )
    if result.abstained:
        text = "🤷 Информации об этом нет в памяти."
    else:
        text = result.answer
        if result.activated_nodes:
            text += f"\n\n_Использованные концепты: {', '.join(result.activated_nodes[:5])}_"

    return [TextContent(type="text", text=text)]


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
