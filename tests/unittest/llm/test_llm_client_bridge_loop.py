#!/usr/bin/env python3
"""Unit tests for the sync bridge event loop in LLMClient."""

import concurrent.futures
import threading
from unittest.mock import AsyncMock, patch

from dolphin.core.llm import llm
from dolphin.core.llm import llm_client
from dolphin.core.llm.llm_client import LLMClient


def _build_test_client():
    """Create an LLMClient instance without running the full constructor."""
    return LLMClient.__new__(LLMClient)


def test_get_bridge_loop_reuses_single_running_loop():
    """Concurrent access should reuse one started bridge loop."""
    llm_client.shutdown_bridge_loop()

    def get_loop():
        return llm_client._get_bridge_loop()

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        loops = list(pool.map(lambda _: get_loop(), range(8)))

    first_loop = loops[0]
    assert all(loop is first_loop for loop in loops)
    assert first_loop.is_running()

    llm_client.shutdown_bridge_loop()


def test_mf_chat_reuses_bridge_loop_client_cache_for_sync_calls():
    """Sync mf_chat calls should reuse AsyncOpenAI clients via the bridge loop."""
    llm_client.shutdown_bridge_loop()
    llm._client_cache.clear()

    created_clients = []
    observed_loops = []
    client = _build_test_client()

    def build_openai_client(**kwargs):
        openai_client = AsyncMock()
        openai_client.kwargs = kwargs
        created_clients.append(openai_client)
        return openai_client

    async def fake_mf_chat_stream(self, **kwargs):
        observed_loops.append(threading.get_ident())
        await llm.get_cached_openai_client(
            base_url="https://example.com/v1",
            api_key="secret",
            headers={"User-Agent": "dolphin"},
        )
        yield {"content": "ok"}

    client.mf_chat_stream = fake_mf_chat_stream.__get__(client, LLMClient)

    with patch("dolphin.core.llm.llm.AsyncOpenAI", side_effect=build_openai_client):
        assert client.mf_chat(messages=[]) == "ok"
        assert client.mf_chat(messages=[]) == "ok"

    assert len(created_clients) == 1
    assert len(set(observed_loops)) == 1

    llm_client.shutdown_bridge_loop()
    llm._client_cache.clear()
