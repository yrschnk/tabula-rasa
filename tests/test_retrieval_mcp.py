"""Тесты retrieval для MCP: activation-rank, token budget, graph rerank."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from tabula.models import FactCandidate
from tabula.raw_store import clear_raw
from tabula.store import reset_store, add_fact
from tabula.graph import update_edges_for_turn
from tabula.retrieval import collect_facts_ranked, retrieve_facts, trim_facts_to_budget
from tabula.search import search_facts_reranked
from tabula.update import apply_candidate

NS = "test_retrieval_mcp"


@pytest.fixture(autouse=True)
def clean():
    reset_store(NS)
    clear_raw(NS)
    yield
    reset_store(NS)
    clear_raw(NS)


def test_collect_facts_ranked_by_activation():
    mock_llm = MagicMock()
    with patch("tabula.update.llm", return_value=mock_llm):
        apply_candidate(FactCandidate(content="слабый факт", concept="B"), NS)
        apply_candidate(FactCandidate(content="сильный факт", concept="A"), NS)

    activated = [("A", 0.9), ("B", 0.2)]
    ranked = collect_facts_ranked(activated, NS)
    assert ranked[0].concept == "A"


def test_retrieve_facts_abstains_on_empty():
    facts, activated, abstained = retrieve_facts("нет такого", NS)
    assert abstained
    assert facts == []


def test_trim_facts_to_budget():
    mock_llm = MagicMock()
    with patch("tabula.update.llm", return_value=mock_llm):
        ids = [
            apply_candidate(FactCandidate(content=f"уникальный факт номер {i} " + "x" * 200, concept=f"C{i}"), NS)
            for i in range(15)
        ]
    from tabula.store import get_fact
    objs = [get_fact(fid, NS) for fid in ids if fid]
    trimmed = trim_facts_to_budget(objs, token_budget=50)
    assert len(trimmed) < len(objs)


def test_search_facts_reranked_uses_graph():
    mock_llm = MagicMock()
    with patch("tabula.update.llm", return_value=mock_llm):
        apply_candidate(FactCandidate(content="ВНЖ требует медстраховку", concept="ВНЖ"), NS)
        apply_candidate(FactCandidate(content="Испания — страна переезда", concept="Испания"), NS)
    update_edges_for_turn(["ВНЖ", "Испания"], [("ВНЖ", "Испания")], NS)

    results = search_facts_reranked("ВНЖ", NS, k=5, use_activation=True)
    concepts = {f.concept for f in results}
    assert "ВНЖ" in concepts


def test_mcp_ask_shows_activation_scores():
    import asyncio
    from tabula.mcp_server import call_tool

    mock_llm = MagicMock()
    with patch("tabula.update.llm", return_value=mock_llm):
        asyncio.run(call_tool("tabula_add", {
            "content": "тест activation score",
            "concept": "ТестAct",
            "namespace": NS,
        }))

    result = asyncio.run(call_tool("tabula_ask", {
        "question": "activation score",
        "namespace": NS,
    }))
    assert "act=" in result[0].text
    assert "graph-nodes" in result[0].text


def test_mcp_sync_tool():
    import asyncio
    from tabula.mcp_server import call_tool, list_tools

    tools = asyncio.run(list_tools())
    assert "tabula_sync" in [t.name for t in tools]

    mock_llm = MagicMock()
    with patch("tabula.update.llm", return_value=mock_llm):
        asyncio.run(call_tool("tabula_add", {
            "content": "sync test fact",
            "concept": "Sync",
            "namespace": NS,
        }))

    result = asyncio.run(call_tool("tabula_sync", {"namespace": NS}))
    assert "Sync завершён" in result[0].text
