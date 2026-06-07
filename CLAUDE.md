# Tabula Rasa — контекст для разработки

Tabula Rasa — персональная когнитивная память (второй мозг) для агентов и человека.
Не RAG и не векторная база, а граф концептов + spreading activation + версионирование.

**Полная спецификация: `SPEC.md`** — читай её перед работой над любым модулем.
Каждый модуль в коде ссылается на раздел SPEC (например `# SPEC 5.4`).

## Главное

- **Гипотеза:** spreading activation по графу даёт лучший контекст, чем плоский поиск. Проверяем на LongMemEval (`--compare fts5,activation`).
- **Источник правды — SQLite** (`tabula/store.py`); markdown в `wiki/` — только проекция для Obsidian.
- **LLM backend pluggable** (`tabula/config.py: backend`): `mcp_sampling` (дефолт, без ключа) / `api` (бенч) / `ollama`.
- **Эмбеддинги локальные** (fastembed), модель в `config.embed_model`.
- **Все параметры — в `tabula/config.py`.** Не хардкодить по модулям.
- **Промпты — в `tabula/prompts/*.md`.** Не зашивать в код.

## Поток

```
add → raw_store → extract(сессия) → dedup/A.U.D.N → store(SQLite) → graph → (sync→wiki)
ask → fts+vector seed → spreading activation → abstention-check → one-shot reconstruct → QueryResult
```

## Порядок реализации (SPEC раздел 10)

1. Скелет: models, config, store (schema+FTS+concepts), llm
2. Запись: ingest(сессия, Haiku, кэш) → dedup → update(ADD) → store. CLI `add`
3. Поиск-baseline: search.fts + retrieval(mode=fts5). CLI `ask --mode fts5`
4. Граф+активация: graph(record+session), activation, retrieval(mode=activation)
5. Векторы (обязательно): embeddings, vector_search, rrf_fuse; канонизация; similar для A.U.D.N
6. Версионирование: полный A.U.D.N (UPDATE/DELETE + valid_from/to)
7. Abstention: пороги + ветка "не знаю"
8. Бенч: datasets/longmemeval → runner(изоляция ns) → judge(claude) → metrics. Dev-сабсет ~50
9. Сравнение: --compare fts5,activation. Зафиксировать прирост
10. Финал: полный прогон 500, judge=gpt-4o, тюнинг
11. Проекция/Obsidian: projection + sync
12. MCP-сервер: mcp_server (4 инструмента + rubric)

## Команды

```bash
tabula add "..."          tabula ask "..." [--as-of] [--mode]
tabula sync               tabula status
```

## Конвенции

- Python 3.11+, dataclasses/pydantic, типы обязательны
- Каждый модуль: docstring со ссылкой на SPEC
- Тесты в `tests/`, расширять при реализации модуля
- Стиль: ruff, line-length 100
