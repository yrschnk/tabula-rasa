"""Агрегация метрик бенча. SPEC 6."""
from __future__ import annotations

from collections import defaultdict


def aggregate(results: list[dict]) -> dict:
    """Агрегировать результаты прогона.

    Каждый result:
      question_id, qtype, correct (bool), abstained (bool),
      confidence (float), latency_s (float), pred, gold
    """
    if not results:
        return {}

    total = len(results)
    correct = sum(1 for r in results if r.get("correct"))
    abstained = sum(1 for r in results if r.get("abstained"))

    # По типам
    by_type: dict[str, dict] = defaultdict(lambda: {"total": 0, "correct": 0})
    for r in results:
        qt = r.get("qtype", "unknown")
        by_type[qt]["total"] += 1
        if r.get("correct"):
            by_type[qt]["correct"] += 1

    type_accuracy = {
        qt: v["correct"] / v["total"]
        for qt, v in by_type.items()
        if v["total"] > 0
    }

    # Abstention-вопросы
    abs_results = [r for r in results
                   if "_abs" in r.get("qtype", "") or "abstention" in r.get("qtype", "")]
    abs_accuracy = (
        sum(1 for r in abs_results if r.get("correct")) / len(abs_results)
        if abs_results else None
    )

    # Latency
    latencies = [r["latency_s"] for r in results if "latency_s" in r]
    latencies_sorted = sorted(latencies) if latencies else []
    p50 = latencies_sorted[len(latencies_sorted) // 2] if latencies_sorted else None
    p95_idx = int(len(latencies_sorted) * 0.95)
    p95 = latencies_sorted[p95_idx] if latencies_sorted else None

    return {
        "overall_accuracy": correct / total,
        "total": total,
        "correct": correct,
        "abstained": abstained,
        "accuracy_by_type": type_accuracy,
        "abstention_accuracy": abs_accuracy,
        "latency_p50_s": p50,
        "latency_p95_s": p95,
    }


def print_report(metrics: dict, mode: str = "") -> None:
    """Вывести красивый отчёт в stdout."""
    print(f"\n{'='*50}")
    print(f"  TABULA RASA BENCHMARK RESULTS  {mode}")
    print(f"{'='*50}")
    print(f"  Overall accuracy:  {metrics.get('overall_accuracy', 0):.1%}")
    print(f"  Total questions:   {metrics.get('total', 0)}")
    print(f"  Correct:           {metrics.get('correct', 0)}")
    print(f"  Abstained:         {metrics.get('abstained', 0)}")
    if metrics.get("abstention_accuracy") is not None:
        print(f"  Abstention acc:    {metrics['abstention_accuracy']:.1%}")
    print()
    print("  By question type:")
    for qt, acc in sorted(metrics.get("accuracy_by_type", {}).items()):
        print(f"    {qt:<30} {acc:.1%}")
    if metrics.get("latency_p50_s"):
        print()
        print(f"  Latency p50: {metrics['latency_p50_s']:.2f}s")
        print(f"  Latency p95: {metrics['latency_p95_s']:.2f}s")
    print(f"{'='*50}\n")
