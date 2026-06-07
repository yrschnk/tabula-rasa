"""Тесты MCP-path: apply без LLM, A.U.D.N от агента."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from tabula.models import FactCandidate
from tabula.raw_store import clear_raw
from tabula.store import reset_store, get_fact
from tabula.mcp_apply import apply_mcp_candidate, format_similar_block, resolve_target_id
from tabula.update import apply_candidate

NS = "test_mcp_apply"


@pytest.fixture(autouse=True)
def clean():
    reset_store(NS)
    clear_raw(NS)
    yield
    reset_store(NS)
    clear_raw(NS)


def test_apply_mcp_adds_fact():
    c = FactCandidate(content="живёт в Барселоне", concept="Местоположение")
    fid, status, similar = apply_mcp_candidate(c, NS)
    assert status == "added"
    assert fid
    assert similar == []


def test_apply_mcp_reinforces_duplicate():
    c = FactCandidate(content="дубликат факт", concept="Тест")
    fid1, _, _ = apply_mcp_candidate(c, NS)
    fid2, status, _ = apply_mcp_candidate(c, NS)
    assert fid1
    assert fid2 is None
    assert status == "reinforced"


def test_apply_mcp_needs_audn_on_similar():
    mock_llm = MagicMock()
    with patch("tabula.update.llm", return_value=mock_llm):
        apply_candidate(FactCandidate(content="бюджет 1200 евро", concept="Финансы"), NS)

    c = FactCandidate(content="бюджет 1500 евро", concept="Финансы")
    fid, status, similar = apply_mcp_candidate(c, NS)
    assert fid is None
    assert status == "needs_audn"
    assert len(similar) >= 1
    assert "1200" in format_similar_block(similar)


def test_apply_mcp_update_supersedes():
    mock_llm = MagicMock()
    with patch("tabula.update.llm", return_value=mock_llm):
        old_id = apply_candidate(FactCandidate(content="старый бюджет 1200", concept="Финансы"), NS)

    c = FactCandidate(content="новый бюджет 1500", concept="Финансы")
    fid, status, _ = apply_mcp_candidate(
        c, NS, op="UPDATE", target_fact_id=old_id[:8],
    )
    assert status == "updated"
    assert fid
    old = get_fact(old_id, NS)
    assert old.status == "superseded"


def test_apply_mcp_delete_archives():
    mock_llm = MagicMock()
    with patch("tabula.update.llm", return_value=mock_llm):
        fid = apply_candidate(FactCandidate(content="факт для удаления", concept="Тест"), NS)

    c = FactCandidate(content="любой текст", concept="Тест")
    _, status, _ = apply_mcp_candidate(
        c, NS, op="DELETE", target_fact_id=fid[:8], skip_similar_check=True,
    )
    assert status == "deleted"
    assert get_fact(fid, NS).status == "archived"


def test_resolve_target_id_by_prefix():
    mock_llm = MagicMock()
    with patch("tabula.update.llm", return_value=mock_llm):
        fid = apply_candidate(FactCandidate(content="x", concept="Y"), NS)
    resolved = resolve_target_id(fid[:8], NS)
    assert resolved == fid
