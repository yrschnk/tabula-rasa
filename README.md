# Tabula Rasa

Персональная когнитивная память (второй мозг) для агентов и человека.
Не RAG — граф концептов + spreading activation + версионирование фактов.

> Статус: MVP в разработке. Архитектура — в [`SPEC.md`](./SPEC.md).

## Идея

- Память как процесс: факты создаются, усиливаются, устаревают, архивируются.
- Поиск через ассоциации (spreading activation по графу), а не только по словам.
- Работает из коробки в Claude Code / Codex / Cursor через MCP (без API-ключа).

## Установка (dev)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Использование

```bash
tabula add "обсудили аренду в Валенсии, бюджет 1200€"
tabula ask "что я знаю про Испанию?"
tabula status
```

## Бенчмарк

```bash
tabula bench --dataset longmemeval-s --compare fts5,activation
```

См. [`SPEC.md`](./SPEC.md) и [`CLAUDE.md`](./CLAUDE.md).
