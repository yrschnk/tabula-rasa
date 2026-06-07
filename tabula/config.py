"""Единый источник правды для всех параметров Tabula Rasa.
Тюнинг ведём здесь, не хардкодим по модулям."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    # --- Пути ---
    db_path: Path = ROOT / "db" / "memory.db"
    raw_dir: Path = ROOT / "raw"
    wiki_dir: Path = ROOT / "wiki"

    # --- LLM backend: "mcp_sampling" (default) | "api" | "ollama" ---
    backend: str = "mcp_sampling"
    extract_model: str = "claude-haiku"      # дешёвая модель для extract (api/ollama)
    reconstruct_model: str = "claude-sonnet" # сильная модель для ответа
    ollama_model: str = "qwen2.5"

    # --- Эмбеддинги (локально, fastembed) ---
    # personal: paraphrase-multilingual-MiniLM-L12-v2 (RU+EN, ~470MB)
    # bench:    BAAI/bge-small-en-v1.5 (EN, ~130MB)
    # quality:  intfloat/multilingual-e5-large (~2.2GB)
    embed_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    # --- Граф (веса рёбер, тюнить на dev-сабсете) ---
    w_link: float = 1.0       # LLM-предложенная связь
    w_rec: float = 0.3        # co-occurrence на уровне реплики (сильное)
    w_sess: float = 0.09      # co-occurrence на уровне сессии (слабое, 0.3×0.3)

    # --- Spreading activation ---
    decay: float = 0.5        # затухание на хоп
    max_hops: int = 2
    act_threshold: float = 0.2
    top_seed: int = 5
    top_nodes: int = 15

    # --- Retrieval ---
    token_budget: int = 4000  # максимум токенов фактов в one-shot контекст
    abstain_threshold: float = 0.25  # ниже → "Информации нет"

    # --- Dedup ---
    similar_k: int = 5
    reinforce_delta: float = 0.2
    concept_sim_threshold: float = 0.82  # cosine для канонизации концептов

    # --- Бенч ---
    judge: str = "claude"     # "claude" (dev) | "gpt-4o" (финал)
    dev_sample: int = 50      # размер dev-сабсета

    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))


CONFIG = Config()
