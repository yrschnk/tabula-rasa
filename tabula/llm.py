"""LLM-backend (pluggable). SPEC 10.4.
backend = "mcp_sampling" (default) | "api" | "ollama".
"""
from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod

from tabula.config import CONFIG

MODEL_EXTRACT = "claude-haiku-4-5"
MODEL_RECONSTRUCT = "claude-sonnet-4-5"
MODEL_JUDGE = "claude-sonnet-4-5"


class LLMBackend(ABC):
    @abstractmethod
    def complete(self, prompt: str, model_hint: str = "extract") -> str:
        """model_hint: extract | reconstruct | judge"""

    def complete_json(self, prompt: str, model_hint: str = "extract",
                      retries: int = 3) -> dict:
        """Вызов с гарантированным JSON-ответом + ретраи."""
        last_err = None
        for attempt in range(retries):
            try:
                raw = self.complete(prompt, model_hint)
                match = re.search(r"\{.*\}", raw, re.DOTALL)
                if match:
                    return json.loads(match.group())
                return json.loads(raw)
            except (json.JSONDecodeError, AttributeError) as e:
                last_err = e
                if attempt < retries - 1:
                    prompt = prompt + "\n\nВАЖНО: верни ТОЛЬКО валидный JSON, без пояснений."
                    time.sleep(0.5 * (attempt + 1))
        raise ValueError(f"Не удалось получить JSON за {retries} попыток: {last_err}")


class ApiBackend(LLMBackend):
    """Claude через Anthropic API. Нужен ключ. Для бенча."""

    def complete(self, prompt: str, model_hint: str = "extract") -> str:
        import anthropic
        model = {
            "extract": MODEL_EXTRACT,
            "reconstruct": MODEL_RECONSTRUCT,
            "judge": MODEL_JUDGE,
        }.get(model_hint, MODEL_RECONSTRUCT)
        client = anthropic.Anthropic(api_key=CONFIG.anthropic_api_key)
        msg = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text


class OllamaBackend(LLMBackend):
    """Локальная модель через Ollama. Приватно, бесплатно."""

    def complete(self, prompt: str, model_hint: str = "extract") -> str:
        import urllib.request
        payload = json.dumps({
            "model": CONFIG.ollama_model,
            "prompt": prompt,
            "stream": False,
        }).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        return data["response"]


class SamplingBackend(LLMBackend):
    """LLM-роль выполняет хост-агент через MCP sampling. Дефолт, без ключа."""

    def complete(self, prompt: str, model_hint: str = "extract") -> str:
        raise RuntimeError(
            "SamplingBackend работает только внутри MCP-сервера. "
            "Для прямого вызова используй backend=api или backend=ollama."
        )


def get_backend(name: str | None = None) -> LLMBackend:
    n = name or CONFIG.backend
    if n == "api":
        return ApiBackend()
    if n == "ollama":
        return OllamaBackend()
    return SamplingBackend()


_backend: LLMBackend | None = None


def llm() -> LLMBackend:
    global _backend
    if _backend is None:
        _backend = get_backend()
    return _backend
