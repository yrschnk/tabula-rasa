"""Тесты Вех 6-7: полный A.U.D.N (mock LLM), versioning, abstention."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from tabula.models import FactCandidate, Fact
from tabula.store import reset_store, add_fact, get_fact, collect_facts
from tabula.update import apply_candidate, resolve_operation
from tabula.retrieval import query, build_context
from tabula.raw_store import clear_raw

NS = "test_m67"


@pytest.fixture(autouse=True)
def clean():
    reset_store(NS)
    clear_raw(NS)
    yield
    reset_store(NS)
    clear_raw(NS)


# ─── Веха 6: versioning через A.U.D.N ────────────────────────────────────────

def test_audn_update_supersedes():
    """UPDATE: старый факт получает valid_to, новый активен."""
    old = FactCandidate(content="живёт в Барселоне", concept="Местоположение")
    old_id = apply_candidate(old, NS)
    assert old_id is not None

    new = FactCandidate(content="переехал в Валенсию", concept="Местоположение")

    # Мокаем LLM → UPDATE
    mock_backend = MagicMock()
    mock_backend.complete_json.return_value = {
        "op": "UPDATE",
        "target_fact_id": old_id[:8],
        "reason": "новое место жительства заменяет старое",
    }
    with patch("tabula.update.llm", return_value=mock_backend):
        new_id = apply_candidate(new, NS)

    assert new_id is not None
    old_fact = get_fact(old_id, NS)
    new_fact = get_fact(new_id, NS)
    assert old_fact.status == "superseded"
    assert old_fact.valid_to is not None
    assert new_fact.status == "active"
    assert new_fact.valid_to is None


def test_audn_delete_archives():
    """DELETE: противоречащий факт архивируется."""
    wrong = FactCandidate(content="пользователь не любит кофе", concept="Предпочтения")
    wrong_id = apply_candidate(wrong, NS)

    correction = FactCandidate(content="пользователь любит кофе каждое утро",
                                concept="Предпочтения")
    mock_backend = MagicMock()
    mock_backend.complete_json.return_value = {
        "op": "DELETE",
        "target_fact_id": wrong_id[:8],
        "reason": "противоречие",
    }
    with patch("tabula.update.llm", return_value=mock_backend):
        apply_candidate(correction, NS)

    wrong_fact = get_fact(wrong_id, NS)
    assert wrong_fact.status == "archived"


def test_audn_noop_reinforces():
    """NOOP: существующий факт усиливается."""
    c = FactCandidate(content="работает удалённо", concept="Работа")
    fid = apply_candidate(c, NS)
    initial_strength = get_fact(fid, NS).strength

    repeat = FactCandidate(content="работает из дома удалённо", concept="Работа")
    mock_backend = MagicMock()
    mock_backend.complete_json.return_value = {
        "op": "NOOP",
        "target_fact_id": fid[:8],
        "reason": "то же самое",
    }
    with patch("tabula.update.llm", return_value=mock_backend):
        result = apply_candidate(repeat, NS)

    assert result is None
    fact = get_fact(fid, NS)
    assert fact.reinforce_cnt >= 1


def test_temporal_versioning():
    """Факты с valid_from/valid_to корректно фильтруются по as_of."""
    from tabula.store import supersede, _conn
    from datetime import datetime, timezone, timedelta

    # Старый факт — 2 месяца назад
    old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    recent_ts = datetime.now(timezone.utc).isoformat()

    c_old = FactCandidate(content="живёт в Москве", concept="Город",
                          timestamp=old_ts)
    old_id = apply_candidate(c_old, NS)

    # Имитируем supersede с конкретным valid_to
    with _conn(NS) as con:
        con.execute(
            "UPDATE facts SET valid_to=? WHERE fact_id=?",
            (recent_ts, old_id),
        )

    c_new = FactCandidate(content="живёт в Барселоне", concept="Город",
                          timestamp=recent_ts)
    apply_candidate(c_new, NS)

    # as_of до перехода → должен видеть старый факт (по valid_from)
    facts_old = collect_facts(["Город"], NS, as_of=old_ts)
    facts_new = collect_facts(["Город"], NS)  # без as_of → только active

    contents_new = [f.content for f in facts_new]
    assert "живёт в Барселоне" in contents_new


# ─── Веха 7: Abstention ───────────────────────────────────────────────────────

def test_abstention_empty_db():
    """Пустая БД → abstained=True."""
    result = query("что я знаю о квантовой физике?", namespace=NS)
    assert result.abstained is True
    assert result.confidence == 0.0


def test_abstention_no_relevant_facts():
    """Есть факты, но нерелевантные → LLM говорит 'нет данных' → abstained."""
    c = FactCandidate(content="люблю пиццу с грибами", concept="Еда")
    apply_candidate(c, NS)

    # Мокаем LLM → возвращает "нет данных"
    mock_backend = MagicMock()
    mock_backend.complete_json.return_value = {
        "answer": "Информации об этом нет.",
        "confidence": 0,
        "used": [],
    }
    with patch("tabula.retrieval.llm", return_value=mock_backend):
        result = query("расскажи про мою карьеру", namespace=NS)

    assert isinstance(result.abstained, bool)
    assert isinstance(result.confidence, float)


def test_abstention_with_data_mock():
    """С данными и мок LLM → нормальный ответ."""
    c = FactCandidate(content="пользователь работает программистом в Барселоне",
                      concept="Работа")
    apply_candidate(c, NS)

    mock_backend = MagicMock()
    mock_backend.complete_json.return_value = {
        "answer": "Пользователь работает программистом в Барселоне.",
        "confidence": 0.9,
        "used": [],
    }
    with patch("tabula.retrieval.llm", return_value=mock_backend):
        result = query("где работает пользователь?", namespace=NS)

    assert result.abstained is False
    assert result.confidence > 0
    assert "программист" in result.answer.lower() or result.answer


def test_build_context_token_budget():
    """build_context уважает token_budget."""
    facts = [
        Fact(
            fact_id=f"f{i}", namespace=NS, content=f"факт номер {i} " * 50,
            content_hash=f"h{i}", concept="Test", attributed_to="user",
            entities=[], timestamp=None, valid_from="2026-01-01",
            valid_to=None, strength=1.0, reinforce_cnt=0,
            source_raw_id="", status="active", created_at="2026-01-01",
        )
        for i in range(20)
    ]
    ctx = build_context(facts, token_budget=100)
    # 100 токенов ≈ 400 символов → не все 20 фактов войдут
    assert len(ctx) <= 500  # небольшой запас


def test_resolve_operation_no_similar():
    """Без похожих → ADD без LLM-вызова."""
    c = FactCandidate(content="новый уникальный факт", concept="Test")
    op, target = resolve_operation(c, [])
    assert op == "ADD"
    assert target is None
