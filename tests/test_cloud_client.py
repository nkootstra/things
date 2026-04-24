"""Tests for Things Cloud client — HTTP responses mocked via httpx transport."""

import json

import httpx
import pytest


class MockTransport(httpx.AsyncBaseTransport):
    """Mock transport that returns pre-configured responses by URL pattern."""

    def __init__(self, responses: dict[str, httpx.Response]):
        self.responses = responses

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        for pattern, response in self.responses.items():
            if pattern in str(request.url):
                return response
        return httpx.Response(404, json={"error": "not found"})


@pytest.mark.asyncio
async def test_authenticate_returns_history_key():
    from things_api.cloud.client import ThingsCloudClient

    transport = MockTransport({
        "/version/1/account/": httpx.Response(
            200, json={"SYServerHistoryKeyKey": "hist-key-abc123"}
        ),
    })

    client = ThingsCloudClient("test@example.com", "password123")
    client._client = httpx.AsyncClient(transport=transport, base_url="https://cloud.culturedcode.com")

    key = await client.authenticate()
    assert key == "hist-key-abc123"
    assert client.history_key == "hist-key-abc123"

    await client.close()


@pytest.mark.asyncio
async def test_authenticate_raises_on_invalid_password():
    from things_api.cloud.client import ThingsCloudAuthError, ThingsCloudClient

    transport = MockTransport({
        "/version/1/account/": httpx.Response(401),
    })

    client = ThingsCloudClient("test@example.com", "wrong")
    client._client = httpx.AsyncClient(transport=transport, base_url="https://cloud.culturedcode.com")

    with pytest.raises(ThingsCloudAuthError, match="Invalid password"):
        await client.authenticate()

    await client.close()


@pytest.mark.asyncio
async def test_get_items_returns_parsed_items():
    from things_api.cloud.client import ThingsCloudClient

    items_payload = {
        "items": [
            {"uuid1": {"t": 0, "e": "Task6", "p": {"tt": "Buy milk"}}}
        ],
        "current-item-index": 1,
    }

    transport = MockTransport({
        "/version/1/account/": httpx.Response(
            200, json={"SYServerHistoryKeyKey": "hist-key-abc123"}
        ),
        "/version/1/history/": httpx.Response(200, json=items_payload),
    })

    client = ThingsCloudClient("test@example.com", "password123")
    client._client = httpx.AsyncClient(transport=transport, base_url="https://cloud.culturedcode.com")

    await client.authenticate()
    items, index = await client.get_items(start_index=0)

    assert len(items) == 1
    assert index == 1
    assert "uuid1" in items[0]

    await client.close()
