"""Query: collect -> abstention -> build_context -> one-shot reconstruct. SPEC 5.10."""
from __future__ import annotations

from pathlib import Path

from tabula.activation import activate
from tabula.config import CONFIG
from tabula.llm import llm
from tabula.models import Fact, QueryResult
from tabula.store import collect_facts

RECONSTRUCT_PROMPT = Path(__file__).parent / "prompts" / "reconstruct.md"


def activation_map(activated: list[tuple[str, float]]) -> dict[str, float]:
    return {c: s for c, s in activated}


def collect_facts_ranked(
    activated: list[tuple[str, float]],
    namespace: str,
    as_of: str | None = None,
) -> list[Fact]:
    """Факты, отсортированные по activation(concept) × strength. SPEC 5.9 → 5.10."""
    if not activated:
        return []
    scores = activation_map(activated)
    concepts = list(scores.keys())
    facts = collect_facts(concepts, namespace, as_of=as_of)
    facts.sort(
        key=lambda f: (scores.get(f.concept, 0.0) * f.strength, scores.get(f.concept, 0.0)),
        reverse=True,
    )
    return facts


def trim_facts_to_budget(facts: list[Fact], token_budget: int = 0) -> list[Fact]:
    """Обрезать список фактов под token_budget (1 токен ≈ 4 символа)."""
    budget = token_budget or CONFIG.token_budget
    char_budget = budget * 4
    selected: list[Fact] = []
    used = 0
    for f in facts:
        ts = f.timestamp or f.valid_from[:10]
        line_len = len(f.content) + len(f.fact_id) + len(ts) + 40
        if used + line_len > char_budget and selected:
            break
        selected.append(f)
        used += line_len
    return selected


def retrieve_facts(
    question: str,
    namespace: str,
    mode: str = "activation",
    as_of: str | None = None,
    token_budget: int = 0,
) -> tuple[list[Fact], list[tuple[str, float]], bool]:
    """Retrieval для MCP и CLI: activation → ranked facts → budget.

    Returns:
        (facts, activated_nodes, abstained)
    """
    activated = activate(question, namespace, mode=mode)
    max_act = activated[0][1] if activated else 0.0
    if not activated or max_act < CONFIG.abstain_threshold:
        return [], activated, True

    ranked = collect_facts_ranked(activated, namespace, as_of=as_of)
    if not ranked:
        return [], activated, True

    return trim_facts_to_budget(ranked, token_budget), activated, False


def build_context(facts: list[Fact], token_budget: int = 0) -> str:
    """Собрать контекст из фактов в виде строки с ограничением токенов.
    Грубая оценка: 1 токен ≈ 4 символа.
    """
    trimmed = trim_facts_to_budget(facts, token_budget) if facts else []
    budget = token_budget or CONFIG.token_budget
    char_budget = budget * 4
    lines = []
    used = 0
    for f in trimmed:
        ts = f.timestamp or f.valid_from[:10]
        line = f"- ({f.fact_id[:8]} · {ts} · {f.attributed_to}) {f.content}"
        if used + len(line) > char_budget:
            break
        lines.append(line)
        used += len(line)
    return "\n".join(lines)


def llm_reconstruct(question: str, context: str,
                    as_of: str | None = None) -> dict:
    """One-shot ответ. Промпт: prompts/reconstruct.md."""
    template = RECONSTRUCT_PROMPT.read_text(encoding="utf-8")
    prompt = (
        template
        .replace("{as_of}", as_of or "сейчас")
        .replace("{question}", question)
        .replace("{facts}", context or "(нет релевантных фактов)")
    )
    return llm().complete_json(prompt, model_hint="reconstruct")


def query(question: str, namespace: str = "personal",
          as_of: str | None = None, mode: str = "activation") -> QueryResult:
    """Полный retrieval-пайплайн. SPEC 5.10."""
    facts, activated, abstained = retrieve_facts(
        question, namespace, mode=mode, as_of=as_of,
    )
    concepts = [c for c, _ in activated]

    if abstained:
        return QueryResult(
            answer="Информации об этом нет.",
            sources=[],
            activated_nodes=concepts,
            confidence=0.0,
            abstained=True,
        )

    context = build_context(facts)

    # 5. One-shot LLM
    raw = llm_reconstruct(question, context, as_of)

    answer = raw.get("answer", "Не удалось получить ответ.")
    confidence = float(raw.get("confidence", 0.0))
    used_ids = raw.get("used", [])

    # Abstention от LLM
    abstained = confidence == 0 or "нет" in answer.lower()[:30]

    return QueryResult(
        answer=answer,
        sources=used_ids,
        activated_nodes=concepts,
        confidence=confidence,
        abstained=abstained,
    )
