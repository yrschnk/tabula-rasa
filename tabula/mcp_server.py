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

import json
import re
import subprocess
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import SamplingMessage, TextContent, Tool

RUBRIC_PATH = Path(__file__).parent / "prompts" / "mcp_rubric.md"
EXTRACT_PROMPT = Path(__file__).parent / "prompts" / "extract.md"
RECONSTRUCT_PROMPT = Path(__file__).parent / "prompts" / "reconstruct.md"

_INSTRUCTIONS = RUBRIC_PATH.read_text(encoding="utf-8") if RUBRIC_PATH.exists() else ""

app = Server("tabula-rasa", instructions=_INSTRUCTIONS)


# ─── MCP Sampling helper ──────────────────────────────────────────────────────

async def _sampling_complete(prompt: str, max_tokens: int = 4096) -> str:
    """Делегировать LLM-вызов хост-агенту через MCP sampling.
    Работает только внутри call_tool (request context).
    """
    session = app.request_context.session
    result = await session.create_message(
        messages=[SamplingMessage(
            role="user",
            content=TextContent(type="text", text=prompt),
        )],
        max_tokens=max_tokens,
    )
    # Результат может быть TextContent или list
    content = result.content
    if hasattr(content, "text"):
        return content.text
    if isinstance(content, list):
        return "".join(c.text for c in content if hasattr(c, "text"))
    return str(content)


async def _sampling_complete_json(prompt: str, retries: int = 3) -> dict:
    """sampling_complete с гарантированным JSON + ретраи."""
    last_err = None
    for attempt in range(retries):
        raw = await _sampling_complete(prompt)
        try:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                return json.loads(match.group())
            return json.loads(raw)
        except (json.JSONDecodeError, AttributeError) as e:
            last_err = e
            if attempt < retries - 1:
                prompt = prompt + "\n\nВАЖНО: верни ТОЛЬКО валидный JSON, без пояснений."
    raise ValueError(f"Не удалось получить JSON за {retries} попыток: {last_err}")


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
                "когда пользователь спрашивает о прошлом."
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
    """ingest через MCP sampling: extract → store → graph."""
    from tabula.concepts import canonicalize, get_concept_registry
    from tabula.dedup import content_hash
    from tabula.graph import update_edges_for_turn
    from tabula.models import FactCandidate, RawTurn
    from tabula.raw_store import write_raw
    from tabula.store import find_by_hash
    from tabula.update import apply_candidate

    text = args["text"]

    # Записать сырьё
    turn = RawTurn(text=text, namespace=ns,
                   session_id=args.get("session_id", ""))
    write_raw(turn)

    # Кэш — уже обработано?
    from tabula.store import _conn
    processed = set()
    with _conn(ns) as con:
        rows = con.execute(
            "SELECT DISTINCT source_raw_id FROM facts WHERE namespace=? AND source_raw_id != ''",
            (ns,),
        ).fetchall()
        processed = {r["source_raw_id"] for r in rows}
    if turn.raw_id in processed:
        return [TextContent(type="text", text="✅ Уже в памяти (дубликат).")]

    # Extract через MCP sampling
    registry = get_concept_registry(ns)
    registry_str = ", ".join(registry) if registry else "(пока пусто)"

    prompt = (
        EXTRACT_PROMPT.read_text(encoding="utf-8")
        .replace("{concept_registry}", registry_str)
        .replace("{session_turns}", f"[user]: {text}")
    )

    try:
        raw = await _sampling_complete_json(prompt)
    except Exception as e:
        # Fallback: записать как атомарный факт без LLM
        c = FactCandidate(content=text, concept="General", attributed_to="user")
        apply_candidate(c, ns, source_raw_id=turn.raw_id)
        return [TextContent(type="text",
                            text=f"✅ Записано (без extract: {e}).")]

    # Применить факты
    count = 0
    all_concepts = []
    for f in raw.get("facts", []):
        content = f.get("content", "").strip()
        if not content:
            continue
        canon = canonicalize(f.get("concept", "General"), ns)
        c = FactCandidate(
            content=content, concept=canon,
            attributed_to=f.get("attributed_to", "user"),
            entities=f.get("entities", []),
            timestamp=f.get("timestamp"),
        )
        fid = apply_candidate(c, ns, source_raw_id=turn.raw_id)
        if fid:
            count += 1
        all_concepts.append(canon)

    # Обновить граф
    links = [(a, b) for a, b in raw.get("links", [])]
    if all_concepts:
        update_edges_for_turn(all_concepts, links, ns)

    return [TextContent(type="text",
                        text=f"✅ Записано. Добавлено фактов: {count}")]


async def _handle_ask(args: dict, ns: str) -> list[TextContent]:
    """Retrieval через MCP sampling: activate → collect → reconstruct."""
    from tabula.activation import activate
    from tabula.config import CONFIG
    from tabula.store import collect_facts

    question = args["question"]
    mode = args.get("mode", "activation")
    as_of = args.get("as_of")

    # Поиск концептов
    activated = activate(question, ns, mode=mode)
    concepts = [c for c, _ in activated]
    facts = collect_facts(concepts, ns, as_of=as_of)

    # Abstention
    max_act = activated[0][1] if activated else 0.0
    if not facts or max_act < CONFIG.abstain_threshold:
        return [TextContent(type="text", text="🤷 Информации об этом нет в памяти.")]

    # Контекст
    from tabula.retrieval import build_context
    context = build_context(facts)

    # Reconstruct через MCP sampling
    prompt = (
        RECONSTRUCT_PROMPT.read_text(encoding="utf-8")
        .replace("{as_of}", as_of or "сейчас")
        .replace("{question}", question)
        .replace("{facts}", context)
    )

    try:
        raw = await _sampling_complete_json(prompt)
        answer = raw.get("answer", "")
        confidence = float(raw.get("confidence", 0.0))
    except Exception:
        # Fallback: вернуть сырые факты
        answer = "\n".join(f"- {f.content}" for f in facts[:5])
        confidence = 0.5

    if not answer or confidence == 0:
        return [TextContent(type="text", text="🤷 Информации об этом нет в памяти.")]

    text = answer
    if concepts:
        text += f"\n\n_Концепты: {', '.join(concepts[:5])}_"
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
