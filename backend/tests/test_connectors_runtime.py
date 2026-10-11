"""connector 运行时（app.connectors.runtime）测试：不触网。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.connectors import runtime as connectors_runtime
from app.connectors.runtime import user_connector_tools


class _FakeConnectorService:
    def __init__(self, active, version: int = 7):
        self._active = active
        self._version = version

    async def list_user_active_connections(self, user_id):
        return self._active

    def credentials_version(self):
        return self._version


def _definition(connector_id: str, url: str = "https://conn.example.com/mcp") -> SimpleNamespace:
    return SimpleNamespace(id=connector_id, mcp_server_url=url)


@pytest.mark.asyncio
async def test_no_connectors_yields_empty_bundle_with_empty_signature() -> None:
    service = _FakeConnectorService(active=[])
    async with user_connector_tools(service, "user-1") as bundle:
        assert bundle.tools == []
        assert bundle.signature == ""


@pytest.mark.asyncio
async def test_bundle_signature_encodes_version_and_connector_set(monkeypatch) -> None:
    captured_specs: list = []

    async def fake_assemble(specs):
        captured_specs.extend(specs)
        from app.mcp.client import MCPToolBundle

        return MCPToolBundle(
            tools=[SimpleNamespace(name=f"{spec.name}_t") for spec in specs],
            connected_servers=[spec.name for spec in specs],
            errors=[],
        )

    monkeypatch.setattr(connectors_runtime, "assemble_mcp_tools", fake_assemble)
    service = _FakeConnectorService(
        active=[(_definition("rollinggo"), None, "tok-r"), (_definition("notion"), None, "tok-n")],
        version=42,
    )

    async with user_connector_tools(service, "user-1") as bundle:
        assert bundle.signature == "42:notion,rollinggo"
        assert bundle.connected_servers == ["rollinggo", "notion"]
        assert [spec.name for spec in captured_specs] == ["rollinggo", "notion"]


@pytest.mark.asyncio
async def test_tokens_flow_as_native_auth(monkeypatch) -> None:
    captured_specs: list = []

    async def fake_assemble(specs):
        captured_specs.extend(specs)
        from app.mcp.client import MCPToolBundle

        return MCPToolBundle()

    monkeypatch.setattr(connectors_runtime, "assemble_mcp_tools", fake_assemble)
    service = _FakeConnectorService(active=[(_definition("rollinggo"), None, "secret-token")])

    async with user_connector_tools(service, "user-1"):
        pass

    assert len(captured_specs) == 1
    # token 作为 fastmcp 原生 auth 凭证（不再烘焙 headers）
    assert captured_specs[0].auth == "secret-token"
    assert captured_specs[0].headers is None
