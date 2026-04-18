from __future__ import annotations

from langchain_core.messages import AIMessage, AIMessageChunk

from app.llm.qwen_chat_openai import PatchedQwenChatOpenAI


def test_streaming_chunk_keeps_qwen_reasoning_content() -> None:
    model = PatchedQwenChatOpenAI(
        model="qwen-plus",
        api_key="demo-key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    generation_chunk = model._convert_chunk_to_generation_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": "先拆解一下问题。",
                    },
                    "finish_reason": None,
                }
            ]
        },
        AIMessageChunk,
        None,
    )

    assert generation_chunk is not None
    assert isinstance(generation_chunk.message, AIMessageChunk)
    assert generation_chunk.message.additional_kwargs["reasoning_content"] == "先拆解一下问题。"
    assert generation_chunk.message.content_blocks[0]["type"] == "reasoning"


def test_final_chat_result_keeps_qwen_reasoning_content() -> None:
    model = PatchedQwenChatOpenAI(
        model="qwen-plus",
        api_key="demo-key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    result = model._create_chat_result(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "这是最终答案。",
                        "reasoning_content": "先分析问题，再组织答案。",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }
    )

    assert len(result.generations) == 1
    assert isinstance(result.generations[0].message, AIMessage)
    assert result.generations[0].message.additional_kwargs["reasoning_content"] == "先分析问题，再组织答案。"
    assert result.generations[0].message.content_blocks[0]["type"] == "reasoning"
