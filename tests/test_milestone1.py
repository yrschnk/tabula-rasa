"""Тесты Вехи 1: models, store, dedup, llm. SPEC раздел 10."""
import json
import pytest
from tabula.models import RawTurn, FactCandidate, QueryResult
from tabula.dedup import normalize, content_hash
from tabula.store import init_schema, reset_store, add_fact, reinforce, \
    supersede, archive, get_fact, find_by_hash, search_fts, \
    upsert_edge, get_edges, upsert_concept, get_all_concepts

NS = "test_m1"


@pytest.fixture(autouse=True)
def clean():
    reset_store(NS)
    yield
    reset_store(NS)


# ─── models ───────────────────────────────────────────────────────────────────

def test_raw_turn_defaults():
    t = RawTurn(text="hello")
    assert t.raw_id
    assert t.timestamp
    assert t.session_id.startswith("sess_")
    assert t.namespace == "personal"


def test_fact_candidate():
    c = FactCandidate(content="test fact", concept="TestConcept")
    assert c.attributed_to == "user"
    assert c.entities == []


# ─── dedup ────────────────────────────────────────────────────────────────────

def test_normalize():
    assert normalize("  Hello  World  ") == "hello world"
    assert normalize("ВНЖ") == "внж"


def test_content_hash_stable():
    h1 = content_hash("ВНЖ готов")
    h2 = content_hash("внж готов ")  # нормализуется одинаково
    assert h1 == h2


def test_content_hash_different():
    assert content_hash("fact A") != content_hash("fact B")


# ─── store: schema ────────────────────────────────────────────────────────────

def test_schema_creates():
    init_schema(NS)  # уже создана в reset_store, повторный вызов идемпотентен


# ─── store: facts ─────────────────────────────────────────────────────────────

def test_add_and_get_fact():
    c = FactCandidate(content="документы на ВНЖ готовы",
                      concept="ВНЖ", attributed_to="user")
    fid = add_fact(c, NS)
    fact = get_fact(fid, NS)
    assert fact is not None
    assert fact.content == "документы на ВНЖ готовы"
    assert fact.concept == "ВНЖ"
    assert fact.status == "active"
    assert fact.valid_to is None
    assert fact.strength == 1.0


def test_reinforce():
    c = FactCandidate(content="тест reinforce", concept="Test")
    fid = add_fact(c, NS)
    reinforce(fid, NS)
    fact = get_fact(fid, NS)
    assert fact.strength > 1.0 or fact.reinforce_cnt == 1  # strength cap 1.0


def test_supersede():
    c = FactCandidate(content="старый факт", concept="Test")
    fid = add_fact(c, NS)
    supersede(fid, NS)
    fact = get_fact(fid, NS)
    assert fact.status == "superseded"
    assert fact.valid_to is not None


def test_archive():
    c = FactCandidate(content="противоречивый факт", concept="Test")
    fid = add_fact(c, NS)
    archive(fid, NS)
    fact = get_fact(fid, NS)
    assert fact.status == "archived"


def test_find_by_hash():
    c = FactCandidate(content="уникальный факт для хеша", concept="Test")
    fid = add_fact(c, NS)
    from tabula.dedup import content_hash as ch
    found = find_by_hash(ch("уникальный факт для хеша"), NS)
    assert found is not None
    assert found.fact_id == fid


def test_fts_search():
    c = FactCandidate(content="переезд в Испанию в 2026 году", concept="Испания")
    add_fact(c, NS)
    results = search_fts("переезд Испания", NS, k=5)
    assert len(results) > 0
    assert results[0][0] == "Испания"


# ─── store: edges ─────────────────────────────────────────────────────────────

def test_upsert_edge():
    upsert_edge("ВНЖ", "Испания", "link", 1.0, NS)
    edges = get_edges(NS)
    assert any(e["src_concept"] == "ВНЖ" for e in edges)


def test_edge_weight_accumulates():
    upsert_edge("A", "B", "cooccur_rec", 0.5, NS)
    upsert_edge("A", "B", "cooccur_rec", 0.5, NS)
    edges = get_edges(NS)
    ab = next(e for e in edges if e["src_concept"] == "A")
    assert ab["weight"] == 1.0  # MIN(0.5+0.5, 1.0)


# ─── store: concepts ──────────────────────────────────────────────────────────

def test_upsert_concept():
    upsert_concept("ВНЖ", NS, aliases=["residency", "вид на жительство"])
    concepts = get_all_concepts(NS)
    names = [c["name"] for c in concepts]
    assert "ВНЖ" in names
    vnzh = next(c for c in concepts if c["name"] == "ВНЖ")
    assert "residency" in vnzh["aliases"]
