"""Подключение MCP-сервера к Cursor / Claude Code / Codex. SPEC 10.5."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Literal

SERVER_NAME = "tabula-rasa"

Client = Literal["cursor", "claude", "codex"]


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def python_executable() -> Path:
    return Path(sys.executable).resolve()


def mcp_server_config() -> dict:
    """Конфиг stdio MCP-сервера (абсолютные пути)."""
    root = project_root()
    py = python_executable()
    return {
        "command": str(py),
        "args": ["-m", "tabula.mcp_server"],
        "cwd": str(root),
    }


def claude_server_entry() -> dict:
    return {"type": "stdio", **mcp_server_config()}


def _merge_json_file(path: Path, updater) -> None:
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"Невалидный JSON в {path}: {e}") from e
    updater(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def connect_cursor(
    *,
    global_config: bool = False,
    project_dir: Path | None = None,
    path: Path | None = None,
) -> Path:
    """Записать MCP в .cursor/mcp.json (project) или ~/.cursor/mcp.json (global)."""
    if path is not None:
        target = path
    elif global_config:
        target = Path.home() / ".cursor" / "mcp.json"
    else:
        root = project_dir or project_root()
        target = root / ".cursor" / "mcp.json"

    entry = mcp_server_config()

    def _update(data: dict) -> None:
        servers = data.setdefault("mcpServers", {})
        servers[SERVER_NAME] = entry

    _merge_json_file(target, _update)
    return target


def connect_claude(config_path: Path | None = None) -> Path:
    """Merge tabula-rasa в ~/.claude.json → mcpServers."""
    path = config_path or Path.home() / ".claude.json"
    entry = claude_server_entry()

    def _update(data: dict) -> None:
        servers = data.setdefault("mcpServers", {})
        servers[SERVER_NAME] = entry

    _merge_json_file(path, _update)
    return path


def _format_toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _format_toml_array(items: list[str]) -> str:
    inner = ", ".join(_format_toml_string(i) for i in items)
    return f"[{inner}]"


def _codex_section(entry: dict) -> str:
    return (
        f"[mcp_servers.{SERVER_NAME}]\n"
        f"command = {_format_toml_string(entry['command'])}\n"
        f"args = {_format_toml_array(entry['args'])}\n"
        f"cwd = {_format_toml_string(entry['cwd'])}\n"
    )


def connect_codex(config_path: Path | None = None) -> Path:
    """Merge [mcp_servers.tabula-rasa] в ~/.codex/config.toml."""
    path = config_path or Path.home() / ".codex" / "config.toml"
    entry = mcp_server_config()
    section = _codex_section(entry)
    header = f"[mcp_servers.{SERVER_NAME}]"

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(section, encoding="utf-8")
        return path

    content = path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^\[mcp_servers\.{re.escape(SERVER_NAME)}\]\s*\n(?:^(?!^\[).*\n?)*",
        re.MULTILINE,
    )
    if pattern.search(content):
        content = pattern.sub(section, content)
    elif header in content:
        # fallback: заменить от header до следующей секции
        lines = content.splitlines(keepends=True)
        out: list[str] = []
        skipping = False
        for line in lines:
            if line.strip() == header:
                skipping = True
                out.append(section)
                continue
            if skipping and line.startswith("[") and line.strip() != header:
                skipping = False
            if not skipping:
                out.append(line)
        content = "".join(out)
    else:
        if not content.endswith("\n"):
            content += "\n"
        content += "\n" + section

    path.write_text(content, encoding="utf-8")
    return path


def connect(client: Client, *, global_cursor: bool = False) -> Path:
    if client == "cursor":
        return connect_cursor(global_config=global_cursor)
    if client == "claude":
        return connect_claude()
    if client == "codex":
        return connect_codex()
    raise ValueError(f"Unknown client: {client}")


def connect_all(*, global_cursor: bool = False) -> dict[str, Path]:
    return {
        "cursor": connect_cursor(global_config=global_cursor),
        "claude": connect_claude(),
        "codex": connect_codex(),
    }


def restart_hint(client: Client) -> str:
    hints = {
        "cursor": "Перезапусти Cursor или: Settings → MCP → Reload",
        "claude": "Перезапусти Claude Code или выполни /mcp",
        "codex": "Перезапусти Codex CLI или перезапусти сессию",
    }
    return hints[client]
