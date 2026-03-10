#!/usr/bin/env python3
"""Unit tests for cached AsyncOpenAI client management."""

from unittest.mock import AsyncMock, patch

import pytest

from dolphin.core.llm import llm


@pytest.fixture(autouse=True)
def clear_client_cache():
    """Reset cached OpenAI clients between tests."""
    llm._client_cache.clear()
    yield
    llm._client_cache.clear()


@pytest.mark.asyncio
async def test_get_cached_openai_client_reuses_same_configuration():
    """Identical connection settings should reuse a cached client."""
    created_clients = []

    def build_client(**kwargs):
        client = AsyncMock()
        client.kwargs = kwargs
        created_clients.append(client)
        return client

    with patch("dolphin.core.llm.llm.AsyncOpenAI", side_effect=build_client):
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

    assert client_a is client_b
    assert len(created_clients) == 1


@pytest.mark.asyncio
async def test_get_cached_openai_client_separates_different_headers():
    """Different header sets must not share the same client."""
    created_clients = []

    def build_client(**kwargs):
        client = AsyncMock()
        client.kwargs = kwargs
        created_clients.append(client)
        return client

    with patch("dolphin.core.llm.llm.AsyncOpenAI", side_effect=build_client):
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

    assert client_a is not client_b
    assert len(created_clients) == 2


@pytest.mark.asyncio
async def test_close_cached_openai_clients_closes_and_clears_cache():
    """Closing cached clients should await close() and clear cache state."""
    client_a = AsyncMock()
    client_b = AsyncMock()

    with patch("dolphin.core.llm.llm.AsyncOpenAI", side_effect=[client_a, client_b]):
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

    client_a.aclose.assert_awaited_once()
    client_b.aclose.assert_awaited_once()
    assert llm._client_cache == {}
