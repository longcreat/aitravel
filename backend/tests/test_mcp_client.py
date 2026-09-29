from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.mcp.client import load_mcp_tools


class _FakeAdapter:
    """按 server 名路由的最小 MCPAdapter fake：`bad` 抛错，`good` 返回一个工具。"""

    def __init__(self, target) -> None:
        group = target
        self.server_name = next(iter(group._clients))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def list_tools(self):
        if self.server_name == "bad":
            raise RuntimeError("unauthorized")
        return [SimpleNamespace(name=f"{self.server_name}_tool")]


class _FakeGroup:
    def __init__(self, clients) -> None:
        self._clients = clients

    @classmethod
    def from_config(cls, config) -> "_FakeGroup":
        return cls(dict(config["mcpServers"]))


@pytest.mark.asyncio
async def test_load_mcp_tools_keeps_working_servers_when_one_fails(monkeypatch) -> None:
    monkeypatch.setattr("app.mcp.client.MCPAdapter", _FakeAdapter)
    monkeypatch.setattr("app.mcp.client.ClientGroup", _FakeGroup)

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


@pytest.mark.asyncio
async def test_load_mcp_tools_maps_sse_transport_and_strips_streamable(monkeypatch) -> None:
    captured: dict[str, dict] = {}

    class _CaptureGroup(_FakeGroup):
        @classmethod
        def from_config(cls, config) -> "_CaptureGroup":
            captured.update(config["mcpServers"])
            return super().from_config(config)

    monkeypatch.setattr("app.mcp.client.MCPAdapter", _FakeAdapter)
    monkeypatch.setattr("app.mcp.client.ClientGroup", _CaptureGroup)

    await load_mcp_tools(
        {
            "sse1": {"transport": "sse", "url": "https://mcp.example.invalid/sse"},
            "http1": {"transport": "streamable_http", "url": "https://mcp.example.invalid/mcp"},
            "stdio1": {"transport": "stdio", "command": "demo", "args": ["x"], "env": {"A": "1"}},
        }
    )

    assert captured["sse1"] == {"url": "https://mcp.example.invalid/sse", "transport": "sse", "mode": "legacy"}
    assert captured["http1"] == {"url": "https://mcp.example.invalid/mcp", "mode": "legacy"}
    assert captured["stdio1"] == {"command": "demo", "args": ["x"], "env": {"A": "1"}, "mode": "legacy"}
