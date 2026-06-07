"""Бенч-раннер с изоляцией namespace на вопрос. SPEC 6.
for instance: reset_store(ns) -> ingest все сессии -> query -> judge -> metrics.
"""
from __future__ import annotations


def run(dataset: str, mode: str = "activation", judge_name: str = "claude",
        sample: int | None = None) -> dict:
    raise NotImplementedError
