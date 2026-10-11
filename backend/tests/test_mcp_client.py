"""统一 MCP 装配层（app.mcp.client）测试：不触网，fastmcp/langchain.mcp 用 fake 替换。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.mcp.client import (
    MCPToolBundle,
    ServerSpec,
    _entry_to_spec,
    assemble_mcp_tools,
    load_mcp_tools,
)


class _FakeAdapter:
    """按 spec 路由的最小 MCPAdapter fake：`bad` 抛错，其余返回带前缀的工具。"""

    built_entries: list[str] = []
    auth_tokens: list[object] = []
    cache_modes: list[object] = []

    def __init__(self, target) -> None:
        group = target
        self.spec_name = next(iter(group._clients))
        self.client = group._clients[self.spec_name]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def list_tools(self, *, cache_mode=None):
        if self.spec_name == "bad":
            raise RuntimeError("unauthorized")
        _FakeAdapter.cache_modes.append(cache_mode)
        auth = getattr(self.client, "_auth_marker", None)
        _FakeAdapter.auth_tokens.append(auth)
        return [SimpleNamespace(name=f"{self.spec_name}_tool")]


class _FakeGroup:
    def __init__(self, clients) -> None:
        self._clients = dict(clients)

    @classmethod
    def from_config(cls, config) -> "_FakeGroup":
        return cls(dict(config["mcpServers"]))


class _FakeStdioGroup:
    """load_mcp_tools 走 ClientGroup({name: Client}) 形态的 fake。"""

    instances: list["_FakeStdioGroup"] = []

    def __init__(self, clients) -> None:
        self._clients = dict(clients)
        _FakeStdioGroup.instances.append(self)


def _patch_assembly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.mcp.client.MCPAdapter", _FakeAdapter)
    monkeypatch.setattr("app.mcp.client.ClientGroup", lambda clients: _FakeStdioGroup(clients))
    monkeypatch.setattr("app.mcp.client.FastMCPClient", _fake_client_ctor)
    _FakeAdapter.cache_modes.clear()
    _FakeAdapter.auth_tokens.clear()
    _FakeStdioGroup.instances.clear()


def _fake_client_ctor(transport):
    client = SimpleNamespace(_transport=transport)
    if isinstance(transport, SimpleNamespace):
        client._auth_marker = getattr(transport, "auth", None)
        client._transport_kind = getattr(transport, "kind", "?")
    return client


def _fake_transports(monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    """把 fastmcp transports 替换为带 kind/auth 标记的简单对象。"""

    class _T:
        def __init__(self, *args, headers=None, auth=None, **kwargs):
            self.kind = kind
            self.headers = headers
            self.auth = auth

    import sys

    fake_mod = types_module()
    monkeypatch.setitem(sys.modules, "fastmcp.client.transports", fake_mod)


def types_module():
    import types

    mod = types.ModuleType("fastmcp.client.transports")

    class _T:
        def __init__(self, *args, headers=None, auth=None, **kwargs):
            self.args = args
            self.headers = headers
            self.auth = auth

    mod.StreamableHttpTransport = _T
    mod.SSETransport = _T
    mod.StdioTransport = _T
    return mod


@pytest.mark.asyncio
async def test_parallel_discovery_isolates_server_failures(monkeypatch) -> None:
    _patch_assembly(monkeypatch)

    bundle = await assemble_mcp_tools(
        [
            ServerSpec(name="bad", url="https://mcp.example.invalid/mcp"),
            ServerSpec(name="good", url="https://mcp.example.ok/mcp"),
            ServerSpec(name="good2", url="https://mcp.example.ok2/mcp"),
        ]
    )

    assert [tool.name for tool in bundle.tools] == ["good_tool", "good2_tool"]
    assert bundle.connected_servers == ["good", "good2"]
    assert len(bundle.errors) == 1
    assert bundle.errors[0].startswith("bad:")


@pytest.mark.asyncio
async def test_per_user_auth_flows_to_transport(monkeypatch) -> None:
    import sys

    fake_mod = types_module()
    captured: list[object] = []

    class _CapTransport:
        def __init__(self, url, headers=None, auth=None):
            captured.append({"url": url, "headers": headers, "auth": auth})
            self.url = url

    fake_mod.StreamableHttpTransport = _CapTransport
    monkeypatch.setitem(sys.modules, "fastmcp.client.transports", fake_mod)
    _patch_assembly(monkeypatch)

    await assemble_mcp_tools([ServerSpec(name="c1", url="https://mcp.example.com/mcp", auth="user-token")])

    assert captured == [{"url": "https://mcp.example.com/mcp", "headers": None, "auth": "user-token"}]


@pytest.mark.asyncio
async def test_sse_url_uses_sse_transport(monkeypatch) -> None:
    import sys

    fake_mod = types_module()
    captured: list[object] = []

    class _CapSSE:
        def __init__(self, url, headers=None, auth=None):
            captured.append({"url": url, "auth": auth})
            self.url = url

    class _CapHTTP:
        def __init__(self, url, headers=None, auth=None):
            captured.append("SHOULD-NOT-HTTP")

    fake_mod.SSETransport = _CapSSE
    fake_mod.StreamableHttpTransport = _CapHTTP
    monkeypatch.setitem(sys.modules, "fastmcp.client.transports", fake_mod)
    _patch_assembly(monkeypatch)

    await assemble_mcp_tools([ServerSpec(name="s1", url="https://mcp.example.com/sse", auth="tk")])

    assert captured == [{"url": "https://mcp.example.com/sse", "auth": "tk"}]


@pytest.mark.asyncio
async def test_load_mcp_tools_keeps_working_servers_when_one_fails(monkeypatch) -> None:
    _patch_assembly(monkeypatch)

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


def test_entry_to_spec_normalizes_and_defaults(monkeypatch) -> None:
    import sys

    fake_mod = types_module()
    import pytest as _pytest

    monkeypatch.setitem(sys.modules, "fastmcp.client.transports", fake_mod)

    http_spec = _entry_to_spec(
        "h", {"transport": "http", "url": "https://mcp.example.com/mcp", "headers": {"X": "1"}}
    )
    assert http_spec.url == "https://mcp.example.com/mcp"
    assert http_spec.transport is None  # http 别名归一化 → URL 推断
    assert http_spec.headers == {"X": "1"}
    assert http_spec.mode == "legacy"  # 默认协议时代

    sse_spec = _entry_to_spec("s", {"transport": "sse", "url": "https://mcp.example.com/sse"})
    assert sse_spec.transport == "sse"

    modern_spec = _entry_to_spec("m", {"transport": "streamable_http", "url": "https://x/mcp", "mode": "modern"})
    assert modern_spec.mode == "modern"  # 配置可覆盖

    stdio_spec = _entry_to_spec("d", {"command": "uvx", "args": ["a"], "env": {"K": "V"}})
    assert stdio_spec.command == "uvx"
    assert stdio_spec.args == ["a"]


@pytest.mark.asyncio
async def test_discovery_uses_cache(monkeypatch) -> None:
    _patch_assembly(monkeypatch)

    await assemble_mcp_tools([ServerSpec(name="c1", url="https://mcp.example.com/mcp")])

    # cache_mode="use"：现代服务器可用响应缓存加速重复发现
    assert _FakeAdapter.cache_modes == ["use"]


def test_mcp_tool_bundle_defaults() -> None:
    bundle = MCPToolBundle()
    assert bundle.tools == []
    assert bundle.connected_servers == []
    assert bundle.errors == []
