import importlib

import pytest
from httpx import ASGITransport, AsyncClient

from things_api.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_ready(client):
    import things_api.main as main_mod

    await main_mod.engine_mod.init_db()

    resp = await client.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"
    assert resp.json()["db"] == "ok"


@pytest.mark.asyncio
async def test_ready_returns_503_when_db_unavailable(client, monkeypatch):
    import things_api.main as main_mod

    class BrokenConn:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class BrokenEngine:
        def connect(self):
            return BrokenConn()

    monkeypatch.setattr(main_mod.engine_mod, "engine", BrokenEngine())

    resp = await client.get("/ready")
    assert resp.status_code == 503
    assert resp.json()["status"] == "not_ready"


@pytest.mark.asyncio
async def test_ready_returns_503_when_sync_state_unavailable(client, monkeypatch):
    import things_api.main as main_mod

    class BrokenSessionCM:
        async def __aenter__(self):
            raise RuntimeError("sync state unavailable")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(main_mod.engine_mod, "async_session", lambda: BrokenSessionCM())

    resp = await client.get("/ready")
    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"
    assert resp.json()["reason"] == "sync_state_unavailable"


@pytest.mark.asyncio
async def test_lifespan_does_not_start_scheduler_when_disabled(monkeypatch):
    import things_api.main as main_mod

    starts = {"count": 0}

    class FakeScheduler:
        def __init__(self, pull_fn, push_fn, interval_seconds):
            self.pull_fn = pull_fn
            self.push_fn = push_fn
            self.interval_seconds = interval_seconds

        def start(self):
            starts["count"] += 1

        def stop(self):
            return None

    monkeypatch.setattr(main_mod.config.settings, "enable_scheduler", False)
    monkeypatch.setattr(main_mod.config.settings, "sync_interval_seconds", 10)
    monkeypatch.setattr(main_mod.config.settings, "things_email", "user@example.com")
    monkeypatch.setattr("things_api.cloud.scheduler.SyncScheduler", FakeScheduler)

    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/health")
        assert resp.status_code == 200

    assert starts["count"] == 0


@pytest.mark.asyncio
async def test_lifespan_does_not_start_scheduler_without_lock(monkeypatch):
    import things_api.main as main_mod

    starts = {"count": 0}

    class FakeScheduler:
        def __init__(self, pull_fn, push_fn, interval_seconds):
            self.pull_fn = pull_fn
            self.push_fn = push_fn
            self.interval_seconds = interval_seconds

        def start(self):
            starts["count"] += 1

        def stop(self):
            return None

    async def deny_lock(_owner: str) -> bool:
        return False

    monkeypatch.setattr(main_mod.config.settings, "enable_scheduler", True)
    monkeypatch.setattr(main_mod.config.settings, "sync_interval_seconds", 10)
    monkeypatch.setattr(main_mod.config.settings, "things_email", "user@example.com")
    monkeypatch.setattr(main_mod, "_try_acquire_scheduler_lock", deny_lock)
    monkeypatch.setattr("things_api.cloud.scheduler.SyncScheduler", FakeScheduler)

    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/health")
        assert resp.status_code == 200

    assert starts["count"] == 0


@pytest.mark.asyncio
async def test_scheduler_lock_allows_only_one_owner(monkeypatch):
    import things_api.main as main_mod

    await main_mod.engine_mod.init_db()

    monkeypatch.setattr(main_mod.config.settings, "scheduler_lock_seconds", 30.0)

    first = await main_mod._try_acquire_scheduler_lock("owner-a")
    second = await main_mod._try_acquire_scheduler_lock("owner-b")

    assert first is True
    assert second is False

    await main_mod._release_scheduler_lock("owner-a")
    third = await main_mod._try_acquire_scheduler_lock("owner-b")
    assert third is True


@pytest.mark.asyncio
async def test_make_sync_fns_closes_cloud_clients(monkeypatch):
    import things_api.main as main_mod
    import things_api.cloud.client as cloud_client_mod
    import things_api.cloud.sync as sync_mod
    import things_api.db.engine as engine_mod

    closed_clients: list[bool] = []

    class FakeClient:
        def __init__(self, email: str, password: str):
            self.email = email
            self.password = password
            self.closed = False

        async def close(self):
            self.closed = True
            closed_clients.append(True)

    class DummySessionCM:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_pull_sync(client, session):
        return {"created": 0}

    async def fake_push_sync(client, session):
        return {"pushed": 0}

    monkeypatch.setattr(cloud_client_mod, "ThingsCloudClient", FakeClient)
    monkeypatch.setattr(sync_mod, "pull_sync", fake_pull_sync)
    monkeypatch.setattr(sync_mod, "push_sync", fake_push_sync)
    monkeypatch.setattr(engine_mod, "async_session", lambda: DummySessionCM())

    # Ensure fresh imports inside _make_sync_fns pick up monkeypatches
    importlib.reload(main_mod)

    pull_fn, push_fn = main_mod._make_sync_fns()
    await pull_fn()
    await push_fn()

    assert len(closed_clients) == 2
