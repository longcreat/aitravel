from __future__ import annotations

from langchain_core.messages import AIMessageChunk

from app.agent.streaming import _serialize_stream_part


def test_serialize_stream_part_converts_langchain_messages() -> None:
    part = {
        "type": "messages",
        "data": (
            AIMessageChunk(content="你好", additional_kwargs={"reasoning_content": "先想一下。"}, id="chunk-1"),
            {"langgraph_node": "model"},
        ),
    }

    serialized = _serialize_stream_part(part)

    assert serialized["type"] == "messages"
    assert serialized["data"][0]["type"] == "AIMessageChunk"
    assert serialized["data"][0]["data"]["content"] == "你好"
    assert serialized["data"][0]["data"]["additional_kwargs"]["reasoning_content"] == "先想一下。"
