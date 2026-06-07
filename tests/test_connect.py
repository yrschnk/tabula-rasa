"""Тесты tabula connect: merge конфигов MCP-клиентов."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tabula.connect import (
    SERVER_NAME,
    connect_claude,
    connect_codex,
    connect_cursor,
    mcp_server_config,
    _codex_section,
)


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_mcp_server_config_absolute():
    cfg = mcp_server_config()
    assert Path(cfg["command"]).is_absolute()
    assert Path(cfg["cwd"]).is_absolute()
    assert cfg["args"] == ["-m", "tabula.mcp_server"]


def test_connect_cursor_project(tmp_path):
    target = tmp_path / "mcp.json"
    path = connect_cursor(path=target)
    assert path == target
    data = json.loads(path.read_text())
    assert SERVER_NAME in data["mcpServers"]
    assert data["mcpServers"][SERVER_NAME]["args"] == ["-m", "tabula.mcp_server"]


def test_connect_cursor_merge_idempotent(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}), encoding="utf-8")

    connect_cursor(path=path)
    data = json.loads(path.read_text())
    assert "other" in data["mcpServers"]
    assert SERVER_NAME in data["mcpServers"]


def test_connect_claude(tmp_home):
    path = connect_claude()
    data = json.loads(path.read_text())
    entry = data["mcpServers"][SERVER_NAME]
    assert entry["type"] == "stdio"
    assert "tabula.mcp_server" in entry["args"]


def test_connect_codex_new_file(tmp_home):
    path = connect_codex()
    text = path.read_text()
    assert "[mcp_servers.tabula-rasa]" in text
    assert "tabula.mcp_server" in text


def test_connect_codex_merge_replace(tmp_home):
    path = Path.home() / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "[mcp_servers.tabula-rasa]\ncommand = \"old\"\nargs = [\"old\"]\ncwd = \"/old\"\n\n[other]\nx = 1\n",
        encoding="utf-8",
    )
    connect_codex()
    text = path.read_text()
    assert "old" not in text or "tabula.mcp_server" in text
    assert "[other]" in text
    assert "tabula.mcp_server" in text


def test_codex_section_format():
    section = _codex_section({
        "command": "/path/with spaces/py",
        "args": ["-m", "tabula.mcp_server"],
        "cwd": "/cwd",
    })
    assert 'command = "/path/with spaces/py"' in section
