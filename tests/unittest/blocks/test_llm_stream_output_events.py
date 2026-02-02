import pytest

from dolphin.core.code_block.basic_code_block import BasicCodeBlock
from dolphin.core.context.context import Context


class _DummyLLMClient:
    def __init__(self, chunks):
        self._chunks = chunks

    async def mf_chat_stream(self, **_kwargs):
        for chunk in self._chunks:
            yield chunk


@pytest.mark.asyncio
async def test_llm_chat_stream_cli_mode_emits_llm_stream_output_events_when_missing_on_stream_chunk():
    context = Context(verbose=True, is_cli=True)
    block = BasicCodeBlock(context=context)
    block.llm_client = _DummyLLMClient(
        [
            {"content": "### Title"},
            {"content": "### Title\n\n- item"},
        ]
    )

    async for _ in block.llm_chat_stream(
        llm_params={"messages": [], "model": "mock"},
        recorder=None,
        content="irrelevant",
        on_stream_chunk=None,
    ):
        pass

    events = context.drain_output_events()
    assert [e["event_type"] for e in events] == ["llm_stream", "llm_stream", "llm_stream"]

    assert events[0]["data"]["chunk_text"] == "### Title"
    assert events[0]["data"]["full_text"] == "### Title"
    assert events[0]["data"]["is_final"] is False

    assert events[1]["data"]["chunk_text"] == "\n\n- item"
    assert events[1]["data"]["full_text"] == "### Title\n\n- item"
    assert events[1]["data"]["is_final"] is False

    assert events[2]["data"]["is_final"] is True
    assert events[2]["data"]["full_text"] == "### Title\n\n- item"


@pytest.mark.asyncio
async def test_llm_chat_stream_does_not_emit_llm_stream_output_events_when_on_stream_chunk_provided():
    context = Context(verbose=True, is_cli=True)
    block = BasicCodeBlock(context=context)
    block.llm_client = _DummyLLMClient([{"content": "hello"}])

    seen = []

    def on_stream_chunk(chunk_text: str, full_text: str, is_final: bool = False) -> None:
        seen.append((chunk_text, full_text, is_final))

    async for _ in block.llm_chat_stream(
        llm_params={"messages": [], "model": "mock"},
        recorder=None,
        content="irrelevant",
        on_stream_chunk=on_stream_chunk,
    ):
        pass

    assert seen == [("hello", "hello", False)]
    assert context.drain_output_events() == []


@pytest.mark.asyncio
async def test_llm_chat_stream_non_cli_mode_does_not_emit_llm_stream_output_events():
    context = Context(verbose=True, is_cli=False)
    block = BasicCodeBlock(context=context)
    block.llm_client = _DummyLLMClient([{"content": "hello"}])

    async for _ in block.llm_chat_stream(
        llm_params={"messages": [], "model": "mock"},
        recorder=None,
        content="irrelevant",
        on_stream_chunk=None,
    ):
        pass

    assert context.drain_output_events() == []

