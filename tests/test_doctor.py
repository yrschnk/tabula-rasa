"""Тесты tabula doctor."""
from __future__ import annotations

from tabula.doctor import run_doctor, format_report


def test_doctor_skip_embed():
    report = run_doctor(skip_embed=True)
    assert any(c.name == "embeddings" and "skipped" in c.detail for c in report.checks)
    assert "python" in [c.name for c in report.checks]
    assert format_report(report)


def test_doctor_mcp_tools():
    report = run_doctor(skip_embed=True)
    mcp = next(c for c in report.checks if c.name == "mcp_tools")
    assert mcp.ok
