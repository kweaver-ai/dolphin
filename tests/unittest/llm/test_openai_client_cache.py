#!/usr/bin/env python3
"""Unit tests for cached AsyncOpenAI client management."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from dolphin.core.llm import llm


@pytest.fixture(autouse=True)
def clear_client_cache():
    """Reset cached OpenAI clients between tests."""
    llm._client_cache.clear()
    yield
    llm._client_cache.clear()


def test_get_cached_openai_client_reuses_same_configuration():
    """Identical connection settings should reuse a cached client."""
    created_clients = []

    def build_client(**kwargs):
        client = AsyncMock()
        client.kwargs = kwargs
        created_clients.append(client)
        return client

    async def get_clients():
        client_a = await llm.get_cached_openai_client(
            base_url="https://example.com/v1",
            api_key="secret",
            headers={"X-Trace": "1", "User-Agent": "dolphin"},
        )
        client_b = await llm.get_cached_openai_client(
            base_url="https://example.com/v1",
            api_key="secret",
            headers={"User-Agent": "dolphin", "X-Trace": "1"},
        )
        return client_a, client_b

    with patch("dolphin.core.llm.llm.AsyncOpenAI", side_effect=build_client):
        client_a, client_b = asyncio.run(get_clients())

    assert client_a is client_b
    assert len(created_clients) == 1


def test_get_cached_openai_client_isolates_across_event_loops():
    """Different event loops must get separate clients (httpx binds connections to a loop)."""
    created_clients = []

    def build_client(**kwargs):
        client = AsyncMock()
        client.kwargs = kwargs
        created_clients.append(client)
        return client

    async def get_client():
        return await llm.get_cached_openai_client(
            base_url="https://example.com/v1",
            api_key="secret",
            headers={"User-Agent": "dolphin"},
        )

    with patch("dolphin.core.llm.llm.AsyncOpenAI", side_effect=build_client):
        client_a = asyncio.run(get_client())
        client_b = asyncio.run(get_client())

    assert client_a is not client_b
    assert len(created_clients) == 2


def test_get_cached_openai_client_separates_different_headers():
    """Different header sets must not share the same client."""
    created_clients = []

    def build_client(**kwargs):
        client = AsyncMock()
        client.kwargs = kwargs
        created_clients.append(client)
        return client

    async def get_clients():
        client_a = await llm.get_cached_openai_client(
            base_url="https://example.com/v1",
            api_key="secret",
            headers={"User-Agent": "dolphin-a"},
        )
        client_b = await llm.get_cached_openai_client(
            base_url="https://example.com/v1",
            api_key="secret",
            headers={"User-Agent": "dolphin-b"},
        )
        return client_a, client_b

    with patch("dolphin.core.llm.llm.AsyncOpenAI", side_effect=build_client):
        client_a, client_b = asyncio.run(get_clients())

    assert client_a is not client_b
    assert len(created_clients) == 2


def test_close_cached_openai_clients_closes_and_clears_cache():
    """Closing cached clients should await close() and clear cache state."""
    client_a = AsyncMock()
    client_b = AsyncMock()

    async def populate_and_close():
        await llm.get_cached_openai_client(
            base_url="https://example.com/v1",
            api_key="secret-a",
            headers={"User-Agent": "dolphin-a"},
        )
        await llm.get_cached_openai_client(
            base_url="https://example.com/v1",
            api_key="secret-b",
            headers={"User-Agent": "dolphin-b"},
        )
        await llm.close_cached_openai_clients()

    with patch("dolphin.core.llm.llm.AsyncOpenAI", side_effect=[client_a, client_b]):
        asyncio.run(populate_and_close())

    client_a.close.assert_awaited_once()
    client_b.close.assert_awaited_once()
    assert dict(llm._client_cache) == {}


def test_close_only_closes_current_loop_clients():
    """close_cached_openai_clients must only close clients owned by the calling loop."""
    client_loop_b = AsyncMock()

    # We need loop A to stay alive so its cache entry persists in the
    # WeakKeyDictionary.  Run both loops concurrently via threads.
    import concurrent.futures
    import threading

    loop_a = asyncio.new_event_loop()
    client_loop_a = AsyncMock()

    async def populate_loop_a():
        return await llm.get_cached_openai_client(
            base_url="https://example.com/v1",
            api_key="secret",
            headers={"User-Agent": "dolphin"},
        )

    # Populate cache in loop A (keep loop alive in a background thread)
    barrier = threading.Event()
    done = threading.Event()

    def run_loop_a():
        asyncio.set_event_loop(loop_a)
        with patch("dolphin.core.llm.llm.AsyncOpenAI", return_value=client_loop_a):
            loop_a.run_until_complete(populate_loop_a())
        # Signal that loop A's cache is populated, then wait
        barrier.set()
        done.wait()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(run_loop_a)
        barrier.wait()  # wait for loop A cache to be populated

        # Loop B (main thread): create its own client, then close
        async def populate_and_close_loop_b():
            await llm.get_cached_openai_client(
                base_url="https://example.com/v1",
                api_key="secret-b",
                headers={"User-Agent": "dolphin-b"},
            )
            await llm.close_cached_openai_clients()

        with patch("dolphin.core.llm.llm.AsyncOpenAI", return_value=client_loop_b):
            asyncio.run(populate_and_close_loop_b())

        # Loop A's client must NOT have been closed
        client_loop_a.close.assert_not_awaited()
        client_loop_b.close.assert_awaited_once()

        # Loop A's entry should still be in the cache
        assert len(dict(llm._client_cache)) == 1

        done.set()
        fut.result()

    loop_a.close()
