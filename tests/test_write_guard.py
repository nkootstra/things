"""Local write-guard tests. These never talk to Things Cloud."""

from __future__ import annotations

import pytest

from things_sdk.cloud.client import (
    ThingsCloudClient,
    ThingsCloudWriteRefused,
    _guard_commit,
)
from things_sdk.cloud.protocol import generate_uuid
from things_sdk.cloud.sync import notes_to_wire


def _item(uuid: str, payload: dict) -> list[dict]:
    return [{uuid: {"t": 1, "e": "Task6", "p": payload}}]


def test_guard_accepts_a_well_formed_item():
    u = generate_uuid()
    _guard_commit(_item(u, {"sr": 86400, "nt": notes_to_wire("ok")}))


def test_guard_refuses_non_canonical_id():
    with pytest.raises(ThingsCloudWriteRefused, match="non-canonical"):
        _guard_commit(_item("1" * 22, {}))


def test_guard_refuses_non_canonical_ref():
    u = generate_uuid()
    with pytest.raises(ThingsCloudWriteRefused, match="non-canonical ref pr="):
        _guard_commit(_item(u, {"pr": ["1" * 22]}))


def test_guard_refuses_duplicate_id():
    u = generate_uuid()
    with pytest.raises(ThingsCloudWriteRefused, match="duplicate"):
        _guard_commit(_item(u, {}) + _item(u, {}))


def test_guard_refuses_non_midnight_date():
    u = generate_uuid()
    with pytest.raises(ThingsCloudWriteRefused, match="UTC-midnight"):
        _guard_commit(_item(u, {"sr": 1}))


def test_guard_refuses_completed_without_stop_date():
    u = generate_uuid()
    with pytest.raises(ThingsCloudWriteRefused, match="without sp"):
        _guard_commit(_item(u, {"ss": 3, "sp": None}))


def test_guard_refuses_project_and_heading_together():
    u, project, heading = generate_uuid(), generate_uuid(), generate_uuid()
    with pytest.raises(ThingsCloudWriteRefused, match="both pr and agr"):
        _guard_commit(_item(u, {"pr": [project], "agr": [heading]}))


def test_guard_refuses_notes_checksum_mismatch():
    u = generate_uuid()
    with pytest.raises(ThingsCloudWriteRefused, match="checksum"):
        _guard_commit(_item(u, {"nt": {"_t": "tx", "ch": 0, "v": "x", "t": 1}}))


def test_guard_freeze_file(tmp_path, monkeypatch):
    import things_sdk.cloud.client as client_mod

    freeze = tmp_path / "WRITE_FREEZE"
    monkeypatch.setattr(client_mod, "WRITE_FREEZE_FILE", None)
    _guard_commit(_item(generate_uuid(), {}))

    freeze.write_text("")
    monkeypatch.setattr(client_mod, "WRITE_FREEZE_FILE", str(freeze))
    with pytest.raises(ThingsCloudWriteRefused, match="frozen"):
        _guard_commit(_item(generate_uuid(), {}))


@pytest.mark.asyncio
async def test_commit_refuses_before_any_http():
    """A refused commit must not open a network client."""
    client = ThingsCloudClient("user@example.com", "password")
    client.history_key = "already-authed"

    async def _boom() -> None:
        raise AssertionError("HTTP client should not be created")

    client._get_client = _boom  # type: ignore[method-assign]
    with pytest.raises(ThingsCloudWriteRefused, match="non-canonical"):
        await client.commit(_item("1" * 22, {}), ancestor_index=0)
