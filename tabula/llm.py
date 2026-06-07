"""LLM-backend (pluggable). SPEC 10.4.
backend = "mcp_sampling" (default) | "api" | "ollama".
"""
from __future__ import annotations


class LLMBackend:
    def complete(self, prompt: str, model_hint: str = "extract") -> str:
        raise NotImplementedError

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class ApiBackend(LLMBackend):
    """Claude/OpenAI через API. Нужен ключ. Для бенча."""


class OllamaBackend(LLMBackend):
    """Локальная модель через Ollama. Приватно, бесплатно."""


class SamplingBackend(LLMBackend):
    """LLM-роль выполняет хост-агент через MCP sampling. Дефолт, без ключа."""


def get_backend(name: str) -> LLMBackend:
    raise NotImplementedError
