"""Тесты Вех 2-4: raw_store, concepts, ingest(mock), update, graph, search, activation."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from tabula.models import RawTurn, FactCandidate
from tabula.raw_store import write_raw, read_raw, iter_session, clear_raw
from tabula.store import (
    reset_store, add_fact, collect_facts, get_all_concepts,
    upsert_edge, get_edges,
)
from tabula.dedup import content_hash
from tabula.concepts import canonicalize, get_concept_registry
from tabula.update import apply_candidate, find_similar
from tabula.graph import update_edges_for_turn, update_session_edges, load_graph
from tabula.search import fts_search, rrf_fuse
from tabula.activation import activate

NS = "test_m24"


@pytest.fixture(autouse=True)
def clean():
    reset_store(NS)
    clear_raw(NS)
    yield
    reset_store(NS)
    clear_raw(NS)


# ─── raw_store ────────────────────────────────────────────────────────────────

def test_write_and_read_raw():
    turn = RawTurn(text="тест сырого слоя", namespace=NS,
                   session_id="sess_test")
    write_raw(turn)
    loaded = read_raw(turn.raw_id, namespace=NS)
    assert loaded.text == turn.text
    assert loaded.raw_id == turn.raw_id


def test_write_raw_idempotent():
    turn = RawTurn(text="дубль", namespace=NS, session_id="sess_dup")
    write_raw(turn)
    write_raw(turn)  # повторно — не должно упасть
    loaded = read_raw(turn.raw_id, namespace=NS)
    assert loaded.text == "дубль"


def test_iter_session():
    sess = "sess_iter"
    turns = [
        RawTurn(text=f"реплика {i}", namespace=NS, session_id=sess)
        for i in range(3)
    ]
    for t in turns:
        write_raw(t)
    loaded = list(iter_session(sess, namespace=NS))
    assert len(loaded) == 3


# ─── concepts ─────────────────────────────────────────────────────────────────

def test_canonicalize_new():
    name = canonicalize("ВНЖ", NS)
    assert name == "ВНЖ"
    concepts = get_concept_registry(NS)
    assert "ВНЖ" in concepts


def test_canonicalize_case_insensitive():
    canonicalize("Испания", NS)
    name2 = canonicalize("испания", NS)  # та же, другой регистр
    assert name2 == "Испания"


def test_canonicalize_alias():
    from tabula.concepts import register_alias
    canonicalize("ВНЖ", NS)
    register_alias("ВНЖ", "residency", NS)
    canon = canonicalize("residency", NS)
    assert canon == "ВНЖ"


# ─── update: apply_candidate ──────────────────────────────────────────────────

def test_apply_candidate_add():
    c = FactCandidate(content="переезд в Испанию в 2026", concept="Испания")
    fid = apply_candidate(c, NS)
    assert fid is not None
    facts = collect_facts(["Испания"], NS)
    assert any(f.content == "переезд в Испанию в 2026" for f in facts)


def test_apply_candidate_dedup_reinforce():
    c = FactCandidate(content="уникальный факт dedup", concept="Test")
    fid1 = apply_candidate(c, NS)
    fid2 = apply_candidate(c, NS)  # дубль → reinforce
    assert fid2 is None  # reinforce, не добавлен новый
    facts = collect_facts(["Test"], NS)
    assert len(facts) == 1
    assert facts[0].reinforce_cnt == 1


def test_find_similar_concept_scoped():
    add_fact(FactCandidate(content="живёт в Барселоне", concept="Испания"), NS)
    add_fact(FactCandidate(content="работает в Мадриде", concept="Испания"), NS)
    candidate = FactCandidate(content="переезжает в Валенсию", concept="Испания")
    similar = find_similar(candidate, NS)
    assert len(similar) == 2


# ─── graph ────────────────────────────────────────────────────────────────────

def test_update_edges_links():
    concepts = ["ВНЖ", "Испания"]
    links = [("ВНЖ", "Испания")]
    update_edges_for_turn(concepts, links, NS)
    edges = get_edges(NS)
    link_edges = [e for e in edges if e["type"] == "link"]
    assert len(link_edges) >= 2  # A→B и B→A


def test_update_edges_cooccur():
    concepts = ["ВНЖ", "Испания", "Переезд"]
    update_edges_for_turn(concepts, [], NS)
    edges = get_edges(NS)
    cooccur = [e for e in edges if e["type"] == "cooccur_rec"]
    # 3 концепта → 3 пары × 2 направления = 6
    assert len(cooccur) == 6


def test_update_session_edges():
    update_session_edges(["A", "B", "C"], NS)
    edges = get_edges(NS)
    sess = [e for e in edges if e["type"] == "cooccur_sess"]
    assert len(sess) == 6


def test_load_graph():
    update_edges_for_turn(["ВНЖ", "Испания"], [("ВНЖ", "Испания")], NS)
    G = load_graph(NS)
    assert G.number_of_nodes() >= 2
    assert G.has_edge("ВНЖ", "Испания")


# ─── search: FTS5 ─────────────────────────────────────────────────────────────

def test_fts_search_finds():
    add_fact(FactCandidate(content="документы на ВНЖ готовы",
                           concept="ВНЖ"), NS)
    add_fact(FactCandidate(content="переезд в Испанию в 2026",
                           concept="Испания"), NS)
    results = fts_search("ВНЖ документы", NS, k=5)
    concepts = [c for c, _ in results]
    assert "ВНЖ" in concepts


def test_fts_search_empty():
    results = fts_search("несуществующийзапрос123", NS, k=5)
    assert results == []


def test_rrf_fuse():
    r1 = [("A", 3.0), ("B", 2.0), ("C", 1.0)]
    r2 = [("B", 5.0), ("C", 3.0), ("D", 1.0)]
    fused = rrf_fuse(r1, r2)
    # B встречается в обоих → должен быть выше чем только один
    concepts = [c for c, _ in fused]
    assert concepts.index("B") < concepts.index("A")


# ─── activation ───────────────────────────────────────────────────────────────

def test_activate_fts5_mode():
    add_fact(FactCandidate(content="ВНЖ в Испании оформляется 3 месяца",
                           concept="ВНЖ"), NS)
    update_edges_for_turn(["ВНЖ", "Испания"], [("ВНЖ", "Испания")], NS)
    results = activate("ВНЖ", NS, mode="fts5")
    assert len(results) > 0
    assert results[0][0] == "ВНЖ"


def test_activate_spreads():
    # ВНЖ → Испания (через граф)
    add_fact(FactCandidate(content="ВНЖ требует страховку", concept="ВНЖ"), NS)
    add_fact(FactCandidate(content="Испания — страна переезда", concept="Испания"), NS)
    update_edges_for_turn(["ВНЖ", "Испания"], [("ВНЖ", "Испания")], NS)

    results = activate("ВНЖ документы", NS, mode="activation")
    concepts = [c for c, _ in results]
    # Испания должна попасть через распространение от ВНЖ
    assert "ВНЖ" in concepts
    assert "Испания" in concepts


def test_activate_empty_db():
    results = activate("что угодно", NS, mode="activation")
    assert results == []


# ─── ingest (mock LLM) ────────────────────────────────────────────────────────

MOCK_EXTRACT_RESPONSE = {
    "facts": [
        {
            "content": "пользователь планирует переезд в Испанию",
            "concept": "Переезд",
            "attributed_to": "user",
            "entities": ["Испания"],
            "timestamp": None,
        },
        {
            "content": "бюджет на аренду квартиры ~1200 евро в месяц",
            "concept": "Финансы",
            "attributed_to": "user",
            "entities": [],
            "timestamp": None,
        },
    ],
    "links": [["Переезд", "Финансы"]],
}


def test_ingest_session_mock():
    """Тест ingest с замоканным LLM (не тратим API)."""
    from tabula.ingest import ingest_session
    from tabula.llm import LLMBackend
    import json

    turns = [
        RawTurn(text="хочу переехать в Испанию, бюджет 1200 евро",
                namespace=NS, session_id="sess_mock"),
    ]

    mock_backend = MagicMock(spec=LLMBackend)
    mock_backend.complete_json.return_value = MOCK_EXTRACT_RESPONSE

    with patch("tabula.ingest.llm", return_value=mock_backend):
        count = ingest_session(turns, namespace=NS)

    assert count == 2
    facts = collect_facts(["Переезд", "Финансы"], NS)
    assert len(facts) == 2
    contents = [f.content for f in facts]
    assert any("переезд" in c.lower() or "аренда" in c.lower() or "бюджет" in c.lower()
               for c in contents)


def test_ingest_dedup_on_repeat():
    """Повторный ingest той же сессии не дублирует факты."""
    from tabula.ingest import ingest_session
    from tabula.llm import LLMBackend

    turns = [
        RawTurn(text="тест дедупа при повторе",
                namespace=NS, session_id="sess_dedup"),
    ]
    mock_backend = MagicMock(spec=LLMBackend)
    mock_backend.complete_json.return_value = MOCK_EXTRACT_RESPONSE

    with patch("tabula.ingest.llm", return_value=mock_backend):
        count1 = ingest_session(turns, namespace=NS)
        count2 = ingest_session(turns, namespace=NS)  # повтор

    assert count1 == 2
    assert count2 == 0  # кэш по hash — пропускаем
