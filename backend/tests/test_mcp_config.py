from __future__ import annotations

from pathlib import Path

import pytest

from app.mcp.config import load_mcp_connections


def test_load_mcp_connections_with_env_substitution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_MCP_URL", "https://mcp.example.com")
    monkeypatch.setenv("DEMO_MCP_TOKEN", "token-123")

    cfg = tmp_path / "mcp.servers.json"
    cfg.write_text(
        """
{
  "demo": {
    "transport": "http",
    "url": "${DEMO_MCP_URL}",
    "headers": {"Authorization": "Bearer ${DEMO_MCP_TOKEN}"}
  }
}
""".strip(),
        encoding="utf-8",
    )

    result = load_mcp_connections(cfg)
    assert result["demo"]["transport"] == "streamable_http"
    assert result["demo"]["url"] == "https://mcp.example.com"
    assert result["demo"]["headers"]["Authorization"] == "Bearer token-123"


def test_load_mcp_connections_missing_env_raises(tmp_path: Path) -> None:
    cfg = tmp_path / "mcp.servers.json"
    cfg.write_text(
        """
{
  "demo": {
    "transport": "http",
    "url": "${MISSING_URL}"
  }
}
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_mcp_connections(cfg)
