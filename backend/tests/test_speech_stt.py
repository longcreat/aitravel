"""DashScopeSttSession 文本累积/交付逻辑单元测试（不触网，不走 SDK）。"""

from __future__ import annotations

import asyncio

from app.speech.stt import DashScopeSttSession


def _make_session() -> tuple[DashScopeSttSession, list[dict]]:
    session = DashScopeSttSession(api_key="test-key")
    events: list[dict] = []
    session._enqueue = events.append  # type: ignore[method-assign]
    session._loop = asyncio.get_running_loop()
    return session, events


async def test_multiple_completed_segments_are_joined() -> None:
    session, events = _make_session()

    session._on_text("帮我查一下天气。", is_final=True)
    session._on_text("顺便推荐景点。", is_final=True)
    session._finishing = True
    session._emit_done()

    done = [event for event in events if event["type"] == "done"]
    assert done, "松手后应交付 done 事件"
    assert done[-1]["text"] == "帮我查一下天气。顺便推荐景点。"


async def test_done_falls_back_to_latest_partial_without_completed() -> None:
    session, events = _make_session()

    session._on_text("帮我查", is_final=False)
    session._finishing = True
    session._emit_done()

    done = [event for event in events if event["type"] == "done"]
    assert done[-1]["text"] == "帮我查"


async def test_interim_partial_events_are_forwarded_live() -> None:
    session, events = _make_session()

    session._on_text("帮我查一下明天北京", is_final=False)

    sentences = [event for event in events if event["type"] == "sentence"]
    assert sentences == [{"type": "sentence", "text": "帮我查一下明天北京", "sentence_end": False}]
