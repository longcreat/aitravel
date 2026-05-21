"""Connector 目录加载（管理员维护的应用列表）。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.schemas.connectors import ConnectorDefinition


_DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "connectors.json"


def _resolve_registry_path() -> Path:
    """决定 connector 目录文件位置；环境变量优先。"""
    explicit = os.getenv("CONNECTORS_CONFIG_PATH", "").strip()
    if explicit:
        return Path(explicit)
    return _DEFAULT_REGISTRY_PATH


class ConnectorRegistry:
    """管理员维护的 connector 元数据集合。"""

    def __init__(self, definitions: dict[str, ConnectorDefinition]) -> None:
        self._definitions = definitions

    @classmethod
    def load(cls) -> "ConnectorRegistry":
        """从 `connectors.json` 加载 connector 定义。"""
        path = _resolve_registry_path()
        if not path.exists():
            return cls({})

        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("connectors.json 必须是 {connector_id: definition} 形式")

        definitions: dict[str, ConnectorDefinition] = {}
        for connector_id, payload in raw.items():
            if not isinstance(connector_id, str) or not isinstance(payload, dict):
                raise ValueError(f"非法的 connector 配置项：{connector_id!r}")
            normalized = {**payload, "id": connector_id}
            definition = ConnectorDefinition.model_validate(normalized)
            definitions[connector_id] = definition
        return cls(definitions)

    def list(self) -> list[ConnectorDefinition]:
        """按字母序返回启用中的 connector 定义。"""
        return sorted(
            (definition for definition in self._definitions.values() if definition.enabled),
            key=lambda item: item.id,
        )

    def get(self, connector_id: str) -> ConnectorDefinition | None:
        """读取指定 connector 定义；未启用或不存在时返回 None。"""
        definition = self._definitions.get(connector_id)
        if definition is None or not definition.enabled:
            return None
        return definition
