"""MCP-сервер: 4 инструмента + server instructions (decision rubric). SPEC 10.5.
Дефолтный backend = MCP sampling (LLM-роль у хоста).
"""
from __future__ import annotations

# TODO: MCP Python SDK, stdio
# Инструменты: tabula_add, tabula_ask, tabula_search, tabula_status
# Server instructions грузить из prompts/mcp_rubric.md
# Авто-namespace: personal | proj:<repo> по git-root


def main() -> None:
    raise NotImplementedError


if __name__ == "__main__":
    main()
