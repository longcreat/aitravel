"""Citation extraction and annotation resolution tests."""

from __future__ import annotations

import pytest

from app.schemas.chat import ChatTextPart, CitationSource
from app.agent.streaming import (
    StreamRunState,
    _extract_citation_sources_from_trace,
    resolve_annotations_from_text,
)
from app.schemas.chat import ToolTrace


class TestExtractCitationSourcesFromTrace:
    """Test _extract_citation_sources_from_trace with various payload formats."""

    def test_exa_results_payload(self):
        """Exa-style artifact: dict with results list."""
        trace = ToolTrace(
            phase="returned",
            tool_name="exa_search",
            payload={
                "results": [
                    {"title": "三亚旅游攻略", "url": "https://example.com/sanya"},
                    {"title": "海南酒店推荐", "url": "https://example.com/hainan"},
                ]
            },
            tool_call_id="call-1",
            result_status="success",
        )
        sources = _extract_citation_sources_from_trace(trace)
        assert len(sources) == 2
        assert sources[0].url == "https://example.com/sanya"
        assert sources[0].title == "三亚旅游攻略"
        assert sources[1].url == "https://example.com/hainan"
        assert sources[1].title == "海南酒店推荐"

    def test_mcp_hotel_list_payload(self):
        """MCP hotel tool: list of dicts with bookingUrl."""
        trace = ToolTrace(
            phase="returned",
            tool_name="search_hotels",
            payload=[
                {"hotelName": "希尔顿", "bookingUrl": "https://hilton.com/1"},
                {"hotelName": "万豪", "bookingUrl": "https://marriott.com/2"},
            ],
            tool_call_id="call-2",
            result_status="success",
        )
        sources = _extract_citation_sources_from_trace(trace)
        assert len(sources) == 2
        assert sources[0].url == "https://hilton.com/1"
        assert sources[0].title == "希尔顿"
        assert sources[1].url == "https://marriott.com/2"
        assert sources[1].title == "万豪"

    def test_empty_payload(self):
        """No payload returns empty."""
        trace = ToolTrace(
            phase="returned",
            tool_name="some_tool",
            payload=None,
            tool_call_id="call-3",
            result_status="success",
        )
        assert _extract_citation_sources_from_trace(trace) == []

    def test_payload_without_urls(self):
        """Dict without recognizable URL fields."""
        trace = ToolTrace(
            phase="returned",
            tool_name="calc",
            payload={"result": 42},
            tool_call_id="call-4",
            result_status="success",
        )
        assert _extract_citation_sources_from_trace(trace) == []

    def test_list_with_url_field(self):
        """Generic list items with url field."""
        trace = ToolTrace(
            phase="returned",
            tool_name="web_search",
            payload=[
                {"name": "Page 1", "url": "https://a.com"},
                {"name": "Page 2", "url": "https://b.com"},
                {"text": "no url here"},
            ],
            tool_call_id="call-5",
            result_status="success",
        )
        sources = _extract_citation_sources_from_trace(trace)
        assert len(sources) == 2
        assert sources[0].title == "Page 1"
        assert sources[1].title == "Page 2"

    def test_json_string_payload_list(self):
        """JSON string payload (MCP tools return content text)."""
        import json
        trace = ToolTrace(
            phase="returned",
            tool_name="rollinggo-hotel_search",
            payload=json.dumps([
                {"hotelName": "希尔顿", "bookingUrl": "https://hilton.com/1"},
                {"hotelName": "万豪", "bookingUrl": "https://marriott.com/2"},
            ]),
            tool_call_id="call-6",
            result_status="success",
        )
        sources = _extract_citation_sources_from_trace(trace)
        assert len(sources) == 2
        assert sources[0].url == "https://hilton.com/1"
        assert sources[0].title == "希尔顿"

    def test_json_string_payload_dict(self):
        """JSON string dict payload with results."""
        import json
        trace = ToolTrace(
            phase="returned",
            tool_name="exa_search",
            payload=json.dumps({
                "results": [
                    {"title": "页面1", "url": "https://page1.com"},
                ]
            }),
            tool_call_id="call-7",
            result_status="success",
        )
        sources = _extract_citation_sources_from_trace(trace)
        assert len(sources) == 1
        assert sources[0].url == "https://page1.com"

    def test_plain_text_payload(self):
        """Plain text payload returns empty."""
        trace = ToolTrace(
            phase="returned",
            tool_name="some_tool",
            payload="天气晴朗，温度25度。",
            tool_call_id="call-8",
            result_status="success",
        )
        assert _extract_citation_sources_from_trace(trace) == []


class TestResolveAnnotationsFromText:
    """Test resolve_annotations_from_text."""

    def test_basic_markers(self):
        """Detects [src-N] and maps to sources."""
        sources = [
            CitationSource(url="https://a.com", title="A"),
            CitationSource(url="https://b.com", title="B"),
        ]
        text = "推荐A酒店[src-1]，B酒店也不错[src-2]。"
        annotations = resolve_annotations_from_text(text, sources)
        assert len(annotations) == 2
        assert annotations[0].url == "https://a.com"
        assert annotations[0].start_index == text.index("[src-1]")
        assert annotations[0].end_index == text.index("[src-1]") + len("[src-1]")
        assert annotations[0].cited_text == "[src-1]"
        assert annotations[1].url == "https://b.com"

    def test_no_markers(self):
        """Text without markers returns empty."""
        sources = [CitationSource(url="https://a.com", title="A")]
        assert resolve_annotations_from_text("没有引用", sources) == []

    def test_out_of_range_marker(self):
        """Marker with index > len(sources) is ignored."""
        sources = [CitationSource(url="https://a.com", title="A")]
        text = "引用[src-1]和不存在的[src-5]"
        annotations = resolve_annotations_from_text(text, sources)
        assert len(annotations) == 1
        assert annotations[0].url == "https://a.com"

    def test_zero_index_ignored(self):
        """[src-0] is ignored since sources are 1-indexed."""
        sources = [CitationSource(url="https://a.com", title="A")]
        text = "错误的[src-0]和正确的[src-1]"
        annotations = resolve_annotations_from_text(text, sources)
        assert len(annotations) == 1
        assert annotations[0].url == "https://a.com"

    def test_empty_sources(self):
        """Empty sources returns empty annotations."""
        assert resolve_annotations_from_text("text[src-1]", []) == []

    def test_multiple_same_source(self):
        """Same source cited multiple times."""
        sources = [CitationSource(url="https://a.com", title="A")]
        text = "第一次[src-1]，第二次[src-1]"
        annotations = resolve_annotations_from_text(text, sources)
        assert len(annotations) == 2
        assert all(a.url == "https://a.com" for a in annotations)
        assert annotations[0].start_index != annotations[1].start_index


class TestStreamRunStateCitationAccumulation:
    """Test that StreamRunState accumulates citation sources."""

    def test_initial_state(self):
        state = StreamRunState()
        assert state.citation_sources == []

    def test_accumulation(self):
        state = StreamRunState()
        state.citation_sources.append(CitationSource(url="https://a.com", title="A"))
        state.citation_sources.append(CitationSource(url="https://b.com", title="B"))
        assert len(state.citation_sources) == 2


class TestCitationSourceModel:
    """Test CitationSource pydantic model."""

    def test_defaults(self):
        source = CitationSource(url="https://example.com", title="Example")
        assert source.type == "citation"
        assert source.start_index is None
        assert source.end_index is None
        assert source.cited_text is None
        assert source.extras == {}

    def test_full_fields(self):
        source = CitationSource(
            url="https://example.com",
            title="Example",
            start_index=10,
            end_index=17,
            cited_text="[src-1]",
            extras={"source_tool": "exa"},
        )
        assert source.start_index == 10
        assert source.end_index == 17
        assert source.cited_text == "[src-1]"
        assert source.extras == {"source_tool": "exa"}

    def test_serialization(self):
        source = CitationSource(url="https://a.com", title="A", start_index=0, end_index=7)
        data = source.model_dump()
        assert data["type"] == "citation"
        assert data["url"] == "https://a.com"
        assert data["title"] == "A"
        assert data["start_index"] == 0
        assert data["end_index"] == 7
