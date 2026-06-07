"""Бенч-раннер с изоляцией namespace на вопрос. SPEC 6."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from tabula.config import CONFIG

RESULTS_DIR = Path(__file__).parent / "results"


def run(dataset: str = "longmemeval-s",
        dataset_path: str | None = None,
        mode: str = "activation",
        judge_name: str | None = None,
        sample: int | None = None,
        save: bool = True) -> dict:
    """Прогнать бенч.

    Args:
        dataset:      "longmemeval-s" | "locomo"
        dataset_path: путь к файлу датасета (если не задан — ищем в bench/datasets/data/)
        mode:         "fts5" | "activation" (режим retrieval)
        judge_name:   "claude" | "gpt-4o" (default: config.judge)
        sample:       число вопросов (None = все, 50 для dev-сабсета)
        save:         сохранить results/*.json
    """
    from bench.judge import judge as do_judge
    from bench.metrics import aggregate, print_report

    if judge_name:
        CONFIG.judge = judge_name

    loader, path = _resolve_dataset(dataset, dataset_path)
    instances = list(loader(path, sample=sample))
    print(f"[bench] {dataset} | {len(instances)} вопросов | mode={mode} | judge={CONFIG.judge}")

    results = []
    for i, inst in enumerate(instances):
        qid = inst["question_id"]
        ns = f"bench_{qid}"

        t0 = time.time()
        try:
            # 1. Изолированная память для инстанса
            from tabula.store import reset_store
            reset_store(ns)

            # 2. Ingest всех сессий
            from tabula.ingest import ingest_session
            turns = inst["turns"]
            if turns:
                ingest_session(turns, namespace=ns)

            # 3. Query
            from tabula.retrieval import query
            result = query(inst["question"], namespace=ns,
                           as_of=inst.get("as_of"), mode=mode)
            pred = result.answer
            abstained = result.abstained
            confidence = result.confidence

        except Exception as e:
            pred = f"ERROR: {e}"
            abstained = False
            confidence = 0.0

        latency = time.time() - t0

        # 4. Judge
        correct = do_judge(inst["question"], inst["gold"], pred, inst["qtype"])

        rec = {
            "question_id": qid,
            "qtype": inst["qtype"],
            "question": inst["question"],
            "gold": inst["gold"],
            "pred": pred,
            "correct": correct,
            "abstained": abstained,
            "confidence": confidence,
            "latency_s": latency,
        }
        results.append(rec)

        if (i + 1) % 10 == 0 or i == 0:
            acc_so_far = sum(r["correct"] for r in results) / len(results)
            print(f"  [{i+1}/{len(instances)}] acc={acc_so_far:.1%} lat={latency:.1f}s")

    metrics = aggregate(results)
    metrics["dataset"] = dataset
    metrics["mode"] = mode
    metrics["judge"] = CONFIG.judge
    metrics["timestamp"] = datetime.now(timezone.utc).isoformat()

    print_report(metrics, mode=f"mode={mode}")

    if save:
        _save_results(results, metrics, dataset, mode)

    return metrics


def compare(dataset: str = "longmemeval-s",
            dataset_path: str | None = None,
            modes: list[str] | None = None,
            sample: int | None = None) -> dict:
    """Сравнить несколько режимов на одном датасете. SPEC 6.

    Usage: tabula bench --compare fts5,activation --dataset longmemeval-s
    """
    modes = modes or ["fts5", "activation"]
    comparison = {}
    for mode in modes:
        print(f"\n[compare] mode={mode}")
        metrics = run(dataset=dataset, dataset_path=dataset_path,
                      mode=mode, sample=sample, save=True)
        comparison[mode] = metrics

    print("\n" + "="*50)
    print("  COMPARISON SUMMARY")
    print("="*50)
    for mode, m in comparison.items():
        print(f"  {mode:<15} accuracy={m.get('overall_accuracy', 0):.1%}")

    delta = None
    if len(modes) == 2:
        acc0 = comparison[modes[0]].get("overall_accuracy", 0)
        acc1 = comparison[modes[1]].get("overall_accuracy", 0)
        delta = acc1 - acc0
        print(f"\n  Delta ({modes[1]} vs {modes[0]}): {delta:+.1%}")
        if delta > 0:
            print(f"  ✅ {modes[1]} лучше на {delta:.1%}")
        elif delta < 0:
            print(f"  ❌ {modes[0]} лучше на {-delta:.1%}")
        else:
            print("  = Одинаково")

    return {"modes": comparison, "delta": delta}


def _resolve_dataset(dataset: str, path: str | None):
    data_dir = Path(__file__).parent / "datasets" / "data"

    if dataset in ("longmemeval-s", "longmemeval"):
        from bench.datasets.longmemeval import load
        p = path or str(data_dir / "longmemeval_s.json")
        return load, p

    if dataset == "locomo":
        from bench.datasets.locomo import load
        p = path or str(data_dir / "locomo.json")
        return load, p

    raise ValueError(f"Unknown dataset: {dataset}. Use: longmemeval-s | locomo")


def _save_results(results: list[dict], metrics: dict,
                  dataset: str, mode: str) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    fname = RESULTS_DIR / f"{dataset}_{mode}_{ts}.json"
    with open(fname, "w") as f:
        json.dump({"metrics": metrics, "results": results},
                  f, ensure_ascii=False, indent=2)
    print(f"[bench] Результаты сохранены: {fname}")
