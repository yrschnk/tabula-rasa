# Tabula Rasa

Персональная когнитивная память (второй мозг) для агентов и человека.
Не RAG — граф концептов + spreading activation + версионирование фактов.

> Статус: MVP в разработке. Архитектура — в [`SPEC.md`](./SPEC.md).

## Идея

- Память как процесс: факты создаются, усиливаются, устаревают, архивируются.
- Поиск через ассоциации (spreading activation по графу), а не только по словам.
- **MCP без API-ключа** — extract/reconstruct делает хост-агент (Cursor / Claude Code / Codex).

## Быстрый старт (MCP, ~5 минут)

```bash
git clone <repo> tabula-rasa && cd tabula-rasa
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

tabula doctor --skip-embed    # быстрая проверка (без загрузки модели)
tabula connect all            # прописать MCP во все клиенты
# перезапусти Cursor / Claude Code / Codex
tabula doctor                 # полная проверка (+ embed-модель, ~470MB при первом запуске)
```

### Подключить один клиент

```bash
tabula connect cursor    # → .cursor/mcp.json в корне проекта
tabula connect claude    # → ~/.claude.json
tabula connect codex     # → ~/.codex/config.toml
tabula connect cursor --global   # → ~/.cursor/mcp.json (все проекты)
```

После connect перезапусти клиент. Агент получит 8 MCP-tools + rubric (`mcp_rubric.md`).

### Проверка что работает

Спроси агента: «Запомни, что я предпочитаю TypeScript» → должен вызвать `tabula_add`.  
В новой сессии: «Что ты знаешь о моих предпочтениях?» → `tabula_ask`.

## CLI (нужен API-ключ)

Команды `tabula add` / `tabula ask` используют LLM через API (для бенча и отладки):

```bash
cp .env.example .env   # добавь ANTHROPIC_API_KEY
export TABULA_BACKEND=api
tabula add "обсудили аренду в Валенсии, бюджет 1200€"
tabula ask "что я знаю про Испанию?"
tabula status
```

Для повседневной работы с агентом используй **MCP**, не CLI.

## Конфиги (если connect не подходит)

<details>
<summary>Cursor — .cursor/mcp.json</summary>

```json
{
  "mcpServers": {
    "tabula-rasa": {
      "command": "/ABS/PATH/tabula-rasa/.venv/bin/python",
      "args": ["-m", "tabula.mcp_server"],
      "cwd": "/ABS/PATH/tabula-rasa"
    }
  }
}
```
</details>

<details>
<summary>Claude Code — ~/.claude.json</summary>

```json
"mcpServers": {
  "tabula-rasa": {
    "type": "stdio",
    "command": "/ABS/PATH/tabula-rasa/.venv/bin/python",
    "args": ["-m", "tabula.mcp_server"],
    "cwd": "/ABS/PATH/tabula-rasa"
  }
}
```
</details>

<details>
<summary>Codex — ~/.codex/config.toml</summary>

```toml
[mcp_servers.tabula-rasa]
command = "/ABS/PATH/tabula-rasa/.venv/bin/python"
args = ["-m", "tabula.mcp_server"]
cwd = "/ABS/PATH/tabula-rasa"
```
</details>

## Бенчмарк

```bash
export TABULA_BACKEND=api
tabula bench --dataset longmemeval-s --compare fts5,activation
```

См. [`SPEC.md`](./SPEC.md) и [`CLAUDE.md`](./CLAUDE.md).
