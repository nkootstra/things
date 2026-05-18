"""Tests for optional observability — logging and metrics."""

import logging

import pytest
from httpx import ASGITransport, AsyncClient

from things_sdk.cloud.sync import SyncCircuitOpenError

from things_api.main import app
from things_api.metrics import SyncMetrics, instrument_sync, metrics
from things_api.observability import configure_logging


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --- Logging ---

def test_configure_logging_text_sets_root_handler():
    configure_logging("text")
    root = logging.getLogger()
    assert root.handlers


def test_configure_logging_json_sets_json_formatter():
    configure_logging("json")
    root = logging.getLogger()
    handler = root.handlers[0]
    assert isinstance(handler.formatter, logging.Formatter)
    # Emit a record and check JSON output
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="hello", args=(), exc_info=None,
    )
    output = handler.formatter.format(record)
    import json
    parsed = json.loads(output)
    assert parsed["msg"] == "hello"
    assert parsed["level"] == "INFO"


# --- Metrics counters ---

def test_sync_metrics_counters():
    m = SyncMetrics()
    m.record_pull()
    m.record_pull()
    m.record_push()
    m.record_error()
    m.record_circuit_open()

    assert m.sync_pull_total == 2
    assert m.sync_push_total == 1
    assert m.sync_errors_total == 1
    assert m.circuit_open_total == 1


def test_sync_metrics_prometheus_text():
    m = SyncMetrics()
    m.record_pull()
    m.record_push()
    text = m.to_prometheus_text()

    assert "sync_pull_total 1" in text
    assert "sync_push_total 1" in text
    assert "sync_errors_total 0" in text
    assert "# TYPE sync_pull_total counter" in text


# --- Metrics endpoint ---

@pytest.mark.asyncio
async def test_metrics_endpoint_disabled_by_default(client, monkeypatch):
    import things_api.config as config_mod
    monkeypatch.setattr(config_mod.settings, "enable_metrics", False)

    resp = await client.get("/metrics")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_metrics_endpoint_enabled(client, monkeypatch):
    import things_api.config as config_mod
    monkeypatch.setattr(config_mod.settings, "enable_metrics", True)

    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "sync_pull_total" in resp.text
    assert "text/plain" in resp.headers["content-type"]


# --- instrument_sync helper ---


@pytest.fixture
def reset_metrics():
    before = (
        metrics.sync_pull_total,
        metrics.sync_push_total,
        metrics.sync_errors_total,
        metrics.circuit_open_total,
    )
    yield
    (
        metrics.sync_pull_total,
        metrics.sync_push_total,
        metrics.sync_errors_total,
        metrics.circuit_open_total,
    ) = before


@pytest.mark.asyncio
async def test_instrument_sync_records_pull_on_success(reset_metrics):
    before = metrics.sync_pull_total

    async def fake_pull():
        return {"created": 1}

    result = await instrument_sync("pull", fake_pull())
    assert result == {"created": 1}
    assert metrics.sync_pull_total == before + 1


@pytest.mark.asyncio
async def test_instrument_sync_records_push_on_success(reset_metrics):
    before = metrics.sync_push_total

    async def fake_push():
        return {"pushed": 2}

    await instrument_sync("push", fake_push())
    assert metrics.sync_push_total == before + 1


@pytest.mark.asyncio
async def test_instrument_sync_records_error_and_reraises(reset_metrics):
    before_errors = metrics.sync_errors_total
    before_pull = metrics.sync_pull_total

    async def fake_pull():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await instrument_sync("pull", fake_pull())

    assert metrics.sync_errors_total == before_errors + 1
    assert metrics.sync_pull_total == before_pull  # success not recorded


@pytest.mark.asyncio
async def test_instrument_sync_records_circuit_open_on_circuit_error(reset_metrics):
    before_errors = metrics.sync_errors_total
    before_circuit = metrics.circuit_open_total

    async def fake_pull():
        raise SyncCircuitOpenError(retry_after_seconds=30)

    with pytest.raises(SyncCircuitOpenError):
        await instrument_sync("pull", fake_pull())

    assert metrics.sync_errors_total == before_errors + 1
    assert metrics.circuit_open_total == before_circuit + 1
