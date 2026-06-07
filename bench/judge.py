"""LLM-судья. SPEC 6, Приложение A.4.
config.judge: "claude" (dev) | "gpt-4o" (финал, официальный LongMemEval).
"""
from __future__ import annotations

from pathlib import Path

from tabula.config import CONFIG
from tabula.llm import get_backend

JUDGE_PROMPT = Path(__file__).parent.parent / "tabula" / "prompts" / "judge.md"


def judge(question: str, gold: str, pred: str, qtype: str = "") -> bool:
    """Оценить ответ модели. Возвращает True если верно.

    Для abstention-вопросов: верно если модель сказала 'нет данных'.
    Использует LLM-as-judge (>97% совпадение с людьми по оригинальному paper).
    """
    # Быстрая проверка abstention без LLM
    is_abstention_q = "_abs" in qtype or "abstention" in qtype.lower() or not gold or gold.upper() in ("N/A", "NONE", "")
    pred_lower = pred.lower()
    pred_is_abstain = any(p in pred_lower for p in [
        "нет данных", "информации нет", "не знаю", "нет информации",
        "информации об этом нет", "об этом нет", "данных нет",
        "no information", "don't know", "not mentioned", "not found",
        "i don't have", "no data",
    ])

    if is_abstention_q:
        return pred_is_abstain

    if not pred or pred_is_abstain:
        return False

    template = JUDGE_PROMPT.read_text(encoding="utf-8")
    prompt = (
        template
        .replace("{question}", question)
        .replace("{gold}", gold)
        .replace("{pred}", pred)
        .replace("{qtype}", qtype)
    )

    try:
        backend_name = "api" if CONFIG.judge == "gpt-4o" else CONFIG.backend
        if backend_name == "mcp_sampling":
            backend_name = "api"  # judge требует детерминированного бэкенда

        b = get_backend(backend_name)
        raw = b.complete_json(prompt, model_hint="judge")
        return bool(raw.get("correct", False))
    except Exception:
        # Fallback: exact match нормализованный
        return _exact_match_fallback(gold, pred)


def _exact_match_fallback(gold: str, pred: str) -> bool:
    """Нормализованное точное совпадение как последний fallback."""
    import re
    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", s.strip().lower())
    return norm(gold) in norm(pred) or norm(pred) in norm(gold)
