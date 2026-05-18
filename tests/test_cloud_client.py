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


class _PaginatedTransport(httpx.AsyncBaseTransport):
    """Returns canned `/items` pages keyed by `start-index` query param."""

    def __init__(self, auth_payload: dict, pages: dict[int, dict]) -> None:
        self.auth_payload = auth_payload
        self.pages = pages
        self.calls: list[int] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if "/version/1/account/" in str(request.url):
            return httpx.Response(200, json=self.auth_payload)
        if "/items" in str(request.url):
            start = int(request.url.params.get("start-index", "0"))
            self.calls.append(start)
            page = self.pages.get(start)
            if page is None:
                # Defensive: returning empty stops the loop cleanly.
                return httpx.Response(200, json={"items": [], "current-item-index": start})
            return httpx.Response(200, json=page)
        return httpx.Response(404, json={"error": "not found"})


@pytest.mark.asyncio
async def test_get_items_walks_all_pages():
    """Pagination must concatenate every page and stop when the server's
    cursor stops advancing — otherwise pull_sync silently loses items."""
    from things_api.cloud.client import ThingsCloudClient

    pages = {
        # Page 1: start-index=0 → 2 items, server cursor advanced to 5 (more available).
        0: {
            "items": [
                {"uuid_a": {"t": 0, "e": "Task6", "p": {"tt": "A"}}},
                {"uuid_b": {"t": 0, "e": "Task6", "p": {"tt": "B"}}},
            ],
            "current-item-index": 5,
        },
        # Page 2: client advances start-index by 2 (len of page 1).
        2: {
            "items": [
                {"uuid_c": {"t": 0, "e": "Task6", "p": {"tt": "C"}}},
                {"uuid_d": {"t": 0, "e": "Task6", "p": {"tt": "D"}}},
                {"uuid_e": {"t": 0, "e": "Task6", "p": {"tt": "E"}}},
            ],
            # cursor == start (2) + len (3) → terminator condition.
            "current-item-index": 5,
        },
    }
    transport = _PaginatedTransport(
        auth_payload={"SYServerHistoryKeyKey": "k"},
        pages=pages,
    )
    client = ThingsCloudClient("e@x", "p")
    client._client = httpx.AsyncClient(transport=transport, base_url="https://cloud.culturedcode.com")

    await client.authenticate()
    items, final_index = await client.get_items(start_index=0)

    assert [next(iter(item)) for item in items] == ["uuid_a", "uuid_b", "uuid_c", "uuid_d", "uuid_e"]
    assert final_index == 5
    # Confirm the client actually walked two pages (not just one).
    assert transport.calls == [0, 2]
    await client.close()


@pytest.mark.asyncio
async def test_get_items_stops_on_empty_first_page():
    """Edge case: server says we're already up-to-date — must not loop forever."""
    from things_api.cloud.client import ThingsCloudClient

    transport = _PaginatedTransport(
        auth_payload={"SYServerHistoryKeyKey": "k"},
        pages={42: {"items": [], "current-item-index": 42}},
    )
    client = ThingsCloudClient("e@x", "p")
    client._client = httpx.AsyncClient(transport=transport, base_url="https://cloud.culturedcode.com")

    await client.authenticate()
    items, final_index = await client.get_items(start_index=42)

    assert items == []
    assert final_index == 42
    assert transport.calls == [42]  # one round-trip, no infinite loop
    await client.close()


@pytest.mark.asyncio
async def test_get_items_warns_on_newer_server_schema(caplog):
    import logging
    from things_api.cloud.client import ThingsCloudClient

    items_payload = {
        "items": [],
        "current-item-index": 0,
        "schema": 999,
    }

    transport = MockTransport({
        "/version/1/account/": httpx.Response(
            200, json={"SYServerHistoryKeyKey": "hist-key-abc123"}
        ),
        "/version/1/history/": httpx.Response(200, json=items_payload),
    })

    client = ThingsCloudClient("test@example.com", "password123")
    client._client = httpx.AsyncClient(transport=transport, base_url="https://cloud.culturedcode.com")

    with caplog.at_level(logging.WARNING, logger="things_sdk.cloud.client"):
        await client.authenticate()
        await client.get_items(start_index=0)

    assert any("schema" in r.message.lower() for r in caplog.records)
    await client.close()
