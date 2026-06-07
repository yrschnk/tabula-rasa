"""Тесты Вехи 8: bench infrastructure (judge, metrics, runner mock)."""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from bench.judge import judge, _exact_match_fallback
from bench.metrics import aggregate


# ─── judge ────────────────────────────────────────────────────────────────────

def test_judge_exact_match_fallback_correct():
    # Точное вхождение (одинаковый регистр/слово)
    assert _exact_match_fallback("Barcelona", "User lives in Barcelona") is True


def test_judge_exact_match_fallback_wrong():
    assert _exact_match_fallback("Мадрид", "Пользователь живёт в Барселоне") is False


def test_judge_abstention_correct():
    """Abstention-вопрос: отказ = правильный ответ."""
    result = judge(
        question="test",
        gold="N/A",
        pred="Информации об этом нет.",
        qtype="abstention_abs",
    )
    assert result is True


def test_judge_abstention_wrong():
    """Abstention-вопрос: галлюцинация = неправильный ответ."""
    result = judge(
        question="test",
        gold="N/A",
        pred="Пользователь живёт в Лондоне.",
        qtype="abstention_abs",
    )
    assert result is False


def test_judge_with_mock_llm():
    """judge через мок LLM."""
    mock_backend = MagicMock()
    mock_backend.complete_json.return_value = {"correct": True, "reason": "совпадает"}
    with patch("bench.judge.get_backend", return_value=mock_backend):
        result = judge("вопрос", "Барселона", "пользователь в Барселоне", "single-session-user")
    assert result is True


# ─── metrics ──────────────────────────────────────────────────────────────────

def test_aggregate_basic():
    results = [
        {"qtype": "single-session-user", "correct": True, "abstained": False,
         "confidence": 0.9, "latency_s": 1.2},
        {"qtype": "single-session-user", "correct": False, "abstained": False,
         "confidence": 0.4, "latency_s": 0.8},
        {"qtype": "multi-session", "correct": True, "abstained": False,
         "confidence": 0.7, "latency_s": 2.1},
        {"qtype": "knowledge-update", "correct": True, "abstained": False,
         "confidence": 0.8, "latency_s": 1.5},
    ]
    m = aggregate(results)
    assert m["overall_accuracy"] == 0.75
    assert m["total"] == 4
    assert m["correct"] == 3
    assert "single-session-user" in m["accuracy_by_type"]
    assert m["accuracy_by_type"]["single-session-user"] == 0.5
    assert m["latency_p50_s"] is not None


def test_aggregate_empty():
    m = aggregate([])
    assert m == {}


def test_aggregate_all_correct():
    results = [
        {"qtype": "t", "correct": True, "abstained": False,
         "confidence": 1.0, "latency_s": 0.5}
        for _ in range(10)
    ]
    m = aggregate(results)
    assert m["overall_accuracy"] == 1.0


# ─── runner (mock) ────────────────────────────────────────────────────────────

def test_runner_with_mock_dataset(tmp_path):
    """Прогон runner'а с мок-датасетом и мок-компонентами."""
    from tabula.models import RawTurn

    mock_instances = [
        {
            "question_id": f"q{i}",
            "qtype": "single-session-user",
            "turns": [RawTurn(text=f"факт {i}", namespace="bench_q{i}",
                              session_id="sess_test")],
            "question": f"вопрос {i}?",
            "gold": f"ответ {i}",
            "as_of": None,
        }
        for i in range(3)
    ]

    from tabula.models import QueryResult

    with patch("bench.runner._resolve_dataset") as mock_loader, \
         patch("tabula.store.reset_store"), \
         patch("tabula.ingest.ingest_session"), \
         patch("tabula.retrieval.query",
               return_value=QueryResult(answer="мок-ответ", confidence=0.8)), \
         patch("bench.judge.judge", return_value=True):

        mock_loader.return_value = (lambda p, **kw: iter(mock_instances), "mock.json")

        from bench.runner import run
        metrics = run(dataset="longmemeval-s", sample=3, save=False)

    assert metrics["overall_accuracy"] == 1.0
    assert metrics["total"] == 3
