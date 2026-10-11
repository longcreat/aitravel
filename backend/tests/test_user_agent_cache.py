"""用户级 agent 构建缓存（AgentRuntimeService.build_user_agent 签名缓存）测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.runtime import AgentRuntimeService


def _service_with_runtime(tmp_path: Path) -> AgentRuntimeService:
    service = AgentRuntimeService(
        mcp_config_path=tmp_path / "mcp.servers.json",
        sqlite_db_path=tmp_path / "chat.db",
    )
    service._runtime = SimpleNamespace(
        agent=SimpleNamespace(name="default-agent"),
        mcp_bundle=SimpleNamespace(tools=[], connected_servers=[], errors=[]),
        local_tools=[],
        local_tool_names=[],
        checkpointer=SimpleNamespace(),
        store=None,
        chat_models_by_profile={"standard": "fake-model", "thinking": "fake-thinking"},
        default_profile_key="standard",
    )
    service._runtime.default_model = "fake-model"
    return service


def _patch_create_agent(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    built: list[dict] = []
    monkeypatch.setattr(
        "app.agent.runtime.create_agent",
        lambda **kwargs: SimpleNamespace(name=f"agent-{len(built)}", **{"tools": kwargs.get("tools", [])})
        or built.append(kwargs),
    )

    def _create(**kwargs):
        built.append(kwargs)
        return SimpleNamespace(name=f"agent-{len(built)}", tools=kwargs.get("tools", []))

    monkeypatch.setattr("app.agent.runtime.create_agent", _create)
    monkeypatch.setattr(
        "app.agent.runtime.build_agent_middleware",
        lambda **_kwargs: [],
    )
    return built


def test_same_signature_reuses_cached_agent(tmp_path, monkeypatch) -> None:
    service = _service_with_runtime(tmp_path)
    built = _patch_create_agent(monkeypatch)

    a = service.build_user_agent(["toolA"], signature="v1:connA")
    b = service.build_user_agent(["toolA"], signature="v1:connA")

    assert a is b
    assert len(built) == 1


def test_signature_change_rebuilds_agent(tmp_path, monkeypatch) -> None:
    service = _service_with_runtime(tmp_path)
    built = _patch_create_agent(monkeypatch)

    a = service.build_user_agent(["toolA"], signature="v1:connA")
    b = service.build_user_agent(["toolA"], signature="v2:connA")  # token 刷新 → 版本变化

    assert a is not b
    assert len(built) == 2


def test_no_signature_always_rebuilds(tmp_path, monkeypatch) -> None:
    service = _service_with_runtime(tmp_path)
    built = _patch_create_agent(monkeypatch)

    service.build_user_agent(["toolA"])
    service.build_user_agent(["toolA"])

    assert len(built) == 2


def test_no_extra_tools_returns_default_agent(tmp_path, monkeypatch) -> None:
    service = _service_with_runtime(tmp_path)
    built = _patch_create_agent(monkeypatch)

    agent = service.build_user_agent([], signature="v1:connA")

    assert agent.name == "default-agent"
    assert built == []


def test_cache_size_is_bounded(tmp_path, monkeypatch) -> None:
    service = _service_with_runtime(tmp_path)
    _patch_create_agent(monkeypatch)

    for i in range(300):
        service.build_user_agent(["t"], signature=f"v{i}:c")

    assert len(service._user_agent_cache) <= 256
