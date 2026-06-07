"""Smoke-test установки Tabula Rasa (MCP + deps)."""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class DoctorReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append(CheckResult(name=name, ok=ok, detail=detail))


def run_doctor(*, skip_embed: bool = False) -> DoctorReport:
    report = DoctorReport()

    v = sys.version_info
    report.add(
        "python",
        v >= (3, 11),
        f"{v.major}.{v.minor}.{v.micro}" + ("" if v >= (3, 11) else " (нужен ≥3.11)"),
    )

    try:
        from tabula.config import CONFIG
        report.add("config", True, f"backend={CONFIG.backend}")
    except Exception as e:
        report.add("config", False, str(e))
        return report

    try:
        from tabula.mcp_server import RUBRIC_PATH, list_tools

        rubric_ok = RUBRIC_PATH.exists() and len(RUBRIC_PATH.read_text(encoding="utf-8")) > 100
        report.add("mcp_rubric", rubric_ok, str(RUBRIC_PATH))

        tools = asyncio.run(list_tools())
        names = [t.name for t in tools]
        expected = {
            "tabula_add", "tabula_add_batch", "tabula_update", "tabula_forget",
            "tabula_ask", "tabula_search", "tabula_sync", "tabula_status",
        }
        missing = expected - set(names)
        report.add(
            "mcp_tools",
            not missing,
            f"{len(names)} tools" + (f", missing: {missing}" if missing else ""),
        )
    except Exception as e:
        report.add("mcp_tools", False, str(e))

    try:
        from tabula.store import init_schema, reset_store
        ns = "_doctor_probe"
        reset_store(ns)
        init_schema(ns)
        report.add("sqlite", True, "schema OK")
    except Exception as e:
        report.add("sqlite", False, str(e))

    try:
        import sqlite_vec  # noqa: F401
        report.add("sqlite_vec", True, sqlite_vec.__version__)
    except Exception as e:
        report.add("sqlite_vec", False, str(e))

    if skip_embed:
        report.add("embeddings", True, "skipped (--skip-embed)")
    else:
        try:
            from tabula.embeddings import embed_one, embedding_dim
            vec = embed_one("doctor probe")
            report.add("embeddings", len(vec) == embedding_dim(), f"dim={len(vec)}")
        except Exception as e:
            report.add("embeddings", False, str(e))

    try:
        from tabula.connect import mcp_server_config, project_root, python_executable
        cfg = mcp_server_config()
        root = project_root()
        py_ok = python_executable().exists()
        cwd_ok = (root / "tabula" / "mcp_server.py").exists()
        report.add(
            "connect_paths",
            py_ok and cwd_ok,
            f"python={cfg['command']}, cwd={cfg['cwd']}",
        )
    except Exception as e:
        report.add("connect_paths", False, str(e))

    return report


def format_report(report: DoctorReport) -> str:
    lines = ["Tabula Rasa doctor", ""]
    for c in report.checks:
        icon = "✅" if c.ok else "❌"
        suffix = f" — {c.detail}" if c.detail else ""
        lines.append(f"  {icon} {c.name}{suffix}")
    lines.append("")
    lines.append("✅ OK" if report.ok else "❌ Есть проблемы — исправь перед connect")
    return "\n".join(lines)
