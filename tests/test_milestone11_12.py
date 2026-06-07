"""Тесты Вех 11-12: projection/Obsidian + MCP-сервер."""
from __future__ import annotations

import pytest
from tabula.models import FactCandidate
from tabula.store import reset_store
from tabula.update import apply_candidate
from tabula.raw_store import clear_raw

NS = "test_m1112"


@pytest.fixture(autouse=True)
def clean():
    reset_store(NS)
    clear_raw(NS)
    yield
    reset_store(NS)
    clear_raw(NS)


# ─── Веха 11: projection ──────────────────────────────────────────────────────

def test_render_concept_page_basic():
    from tabula.projection import render_concept_page
    apply_candidate(FactCandidate(
        content="живёт в Барселоне", concept="Местоположение",
    ), NS)
    page = render_concept_page("Местоположение", NS)
    assert "# Местоположение" in page
    assert "живёт в Барселоне" in page
    assert "---" in page  # frontmatter


def test_render_concept_page_with_links():
    from tabula.graph import update_edges_for_turn
    from tabula.projection import render_concept_page
    apply_candidate(FactCandidate(content="факт про ВНЖ", concept="ВНЖ"), NS)
    apply_candidate(FactCandidate(content="факт про Испанию", concept="Испания"), NS)
    update_edges_for_turn(["ВНЖ", "Испания"], [("ВНЖ", "Испания")], NS)

    page = render_concept_page("ВНЖ", NS)
    assert "[[Испания]]" in page


def test_rebuild_wiki_creates_files(tmp_path):
    from tabula.config import CONFIG
    from tabula.projection import rebuild_wiki

    # Временно подменим wiki_dir
    orig = CONFIG.wiki_dir
    CONFIG.wiki_dir = tmp_path / "wiki"
    try:
        apply_candidate(FactCandidate(content="факт 1", concept="А"), NS)
        apply_candidate(FactCandidate(content="факт 2", concept="Б"), NS)
        rebuild_wiki(NS)

        wiki_ns = tmp_path / "wiki" / NS
        assert (wiki_ns / "index.md").exists()
        assert (wiki_ns / "concepts" / "А.md").exists()
        assert (wiki_ns / "concepts" / "Б.md").exists()
    finally:
        CONFIG.wiki_dir = orig


def test_log_append(tmp_path):
    from tabula.config import CONFIG
    from tabula.log import append

    orig = CONFIG.wiki_dir
    CONFIG.wiki_dir = tmp_path / "wiki"
    try:
        append(NS, "тестовое событие")
        log_path = tmp_path / "wiki" / NS / "log.md"
        assert log_path.exists()
        content = log_path.read_text()
        assert "тестовое событие" in content
    finally:
        CONFIG.wiki_dir = orig


def test_superseded_facts_in_history():
    from tabula.projection import render_concept_page
    from tabula.store import supersede

    c_old = FactCandidate(content="старый факт о погоде", concept="Погода")
    old_id = apply_candidate(c_old, NS)
    supersede(old_id, NS)

    apply_candidate(FactCandidate(content="новый факт о погоде", concept="Погода"), NS)

    page = render_concept_page("Погода", NS)
    assert "История" in page
    assert "старый факт о погоде" in page
    assert "новый факт о погоде" in page


# ─── Веха 12: MCP-сервер ──────────────────────────────────────────────────────

def test_mcp_tools_list():
    """MCP-сервер регистрирует инструменты."""
    import asyncio
    from tabula.mcp_server import list_tools
    tools = asyncio.run(list_tools())
    names = [t.name for t in tools]
    for expected in (
        "tabula_add", "tabula_add_batch", "tabula_update", "tabula_forget",
        "tabula_ask", "tabula_search", "tabula_sync", "tabula_status",
    ):
        assert expected in names


def test_mcp_add_and_search():
    """tabula_add сохраняет факты, tabula_search их находит."""
    import asyncio
    from tabula.mcp_server import call_tool

    asyncio.run(call_tool("tabula_add", {
        "content": "mcp тест факт про память",
        "concept": "MCP",
        "namespace": NS,
    }))

    result = asyncio.run(call_tool("tabula_search", {"query": "mcp", "namespace": NS}))
    assert "mcp тест факт" in result[0].text
    assert "id=" in result[0].text


def test_mcp_add_batch_graph():
    """tabula_add_batch строит несколько фактов и links."""
    import asyncio
    from tabula.graph import load_graph
    from tabula.mcp_server import call_tool

    asyncio.run(call_tool("tabula_add_batch", {
        "namespace": NS,
        "facts": [
            {"content": "факт про ВНЖ batch", "concept": "ВНЖ"},
            {"content": "факт про Испанию batch", "concept": "Испания"},
        ],
        "links": [["ВНЖ", "Испания"]],
    }))
    G = load_graph(NS)
    assert G.number_of_edges() >= 1


def test_mcp_update():
    """tabula_update заменяет старый факт."""
    import asyncio
    from unittest.mock import patch, MagicMock
    from tabula.mcp_server import call_tool
    from tabula.store import collect_facts

    mock_llm = MagicMock()
    with patch("tabula.update.llm", return_value=mock_llm):
        asyncio.run(call_tool("tabula_add", {
            "content": "бюджет 1200",
            "concept": "Финансы",
            "namespace": NS,
        }))

    search = asyncio.run(call_tool("tabula_search", {"query": "бюджет", "namespace": NS}))
    prefix = search[0].text.split("id=")[1][:8]

    asyncio.run(call_tool("tabula_update", {
        "target_fact_id": prefix,
        "content": "бюджет 1500",
        "concept": "Финансы",
        "namespace": NS,
    }))

    facts = collect_facts(["Финансы"], NS)
    active = [f for f in facts if f.status == "active"]
    assert len(active) == 1
    assert "1500" in active[0].content


def test_mcp_status():
    """tabula_status возвращает текст со статистикой."""
    import asyncio
    from tabula.mcp_server import call_tool
    apply_candidate(FactCandidate(content="тест статуса", concept="Стат"), NS)
    result = asyncio.run(call_tool("tabula_status", {"namespace": NS}))
    text = result[0].text
    assert "Namespace" in text
    assert "Концептов" in text


def test_mcp_rubric_loaded():
    """Server instructions загружены из mcp_rubric.md."""
    from tabula.mcp_server import _INSTRUCTIONS
    assert "tabula_add_batch" in _INSTRUCTIONS
    assert "A.U.D.N" in _INSTRUCTIONS
    assert "tabula_update" in _INSTRUCTIONS


def test_mcp_namespace_detection():
    """Авто-определение namespace."""
    from tabula.mcp_server import _detect_namespace
    ns = _detect_namespace(None)
    assert isinstance(ns, str)
    assert len(ns) > 0

    ns_explicit = _detect_namespace("custom_ns")
    assert ns_explicit == "custom_ns"
