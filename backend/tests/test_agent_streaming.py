from __future__ import annotations

import pytest
from langchain_core.messages import AIMessageChunk
from langgraph.types import Interrupt

from app.agent.context import AgentRequestContext
from app.agent.streaming import AgentStreamService, StreamRunState, _extract_interrupt_payload, _serialize_stream_part


class _WhitespaceChunkAgent:
    async def astream(self, _payload, config=None, context=None, stream_mode=None, version=None):
        assert config is not None
        assert context is not None
        assert stream_mode == ["messages", "updates", "values"]
        assert version == "v2"
        yield {
            "type": "messages",
            "data": (AIMessageChunk(content="你好 ", id="chunk-1"), {"langgraph_node": "model"}),
        }
        yield {
            "type": "messages",
            "data": (AIMessageChunk(content="世界", id="chunk-2"), {"langgraph_node": "model"}),
        }


class _FakeRuntimeService:
    def require_runtime(self):
        return type("Runtime", (), {"agent": _WhitespaceChunkAgent()})()


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


@pytest.mark.asyncio
async def test_stream_agent_run_preserves_whitespace_for_tts_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROFILE_STANDARD_MODEL", "test-standard-model")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_PROVIDER", "openai")
    monkeypatch.setenv("LLM_PROFILE_STANDARD_TEMPERATURE", "0.2")

    service = AgentStreamService(runtime_service=_FakeRuntimeService())
    state = StreamRunState()
    captured_chunks: list[str] = []

    async for _event_name, _payload in service.stream_agent_run(
        thread_id="thread-tts",
        agent_input={"messages": ["ignored"]},
        checkpoint_id=None,
        model_profile_key="standard",
        state=state,
        agent_context=AgentRequestContext(
            user_id="user-1",
            thread_id="thread-tts",
            locale="zh-CN",
            model_profile_key="standard",
            session_meta={},
        ),
        on_assistant_text_chunk=captured_chunks.append,
    ):
        pass

    assert "".join(captured_chunks) == "你好 世界"


def test_extract_interrupt_payload_normalizes_langgraph_interrupts() -> None:
    payload = _extract_interrupt_payload(
        {
            "type": "values",
            "data": {},
            "interrupts": (
                Interrupt(
                    value={
                        "kind": "clarification",
                        "question": "请问你想去哪座城市？",
                        "missing_field": "destination_city",
                        "suggested_replies": ["杭州", "上海"],
                        "allow_custom_input": True,
                    },
                    id="interrupt-1",
                ),
            ),
        }
    )

    assert payload is not None
    assert payload.interrupt_id == "interrupt-1"
    assert payload.question == "请问你想去哪座城市？"
    assert payload.missing_field == "destination_city"
    assert payload.suggested_replies == ["杭州", "上海"]
