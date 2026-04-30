from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.mcp.client import load_mcp_tools


@pytest.mark.asyncio
async def test_load_mcp_tools_keeps_working_servers_when_one_fails(monkeypatch) -> None:
    class _FakeMCPClient:
        def __init__(self, connections, tool_name_prefix: bool) -> None:
            self.server_name = next(iter(connections))
            self.tool_name_prefix = tool_name_prefix

        async def get_tools(self):
            if self.server_name == "bad":
                raise RuntimeError("unauthorized")
            return [SimpleNamespace(name=f"{self.server_name}_tool")]

    monkeypatch.setattr("app.mcp.client.MultiServerMCPClient", _FakeMCPClient)

    bundle = await load_mcp_tools(
        {
            "bad": {"transport": "streamable_http", "url": "https://mcp.example.invalid/mcp"},
            "good": {"transport": "stdio", "command": "demo"},
        }
    )

    assert [tool.name for tool in bundle.tools] == ["good_tool"]
    assert bundle.connected_servers == ["good"]
    assert len(bundle.errors) == 1
    assert bundle.errors[0].startswith("bad:")
