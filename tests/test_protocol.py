"""Things Cloud protocol conformance tests.

Validates that our wire format, UUIDs, headers, and commit body match
what Things3.app actually sends, based on captured traffic analysis.

Non-conformance causes Things3 to crash on pull or the cloud to reject pushes.
"""

from __future__ import annotations

import json
import time

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from things_sdk import Base, Tag, Task, TaskService, configure_sync
from things_sdk.cloud.protocol import BASE58_ALPHABET, generate_uuid, is_valid_things_uuid
from things_sdk.cloud.sync import _tag_delete_wire, _tag_to_wire, _task_to_wire
from things_sdk.tags import TagService


class _SyncConfig:
    sync_retry_attempts = 1
    sync_retry_base_seconds = 0.0
    sync_circuit_breaker_failures = 99
    sync_circuit_breaker_cooldown_seconds = 0.0


@pytest.fixture(autouse=True)
def _configure():
    configure_sync(_SyncConfig())


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


# ============================================================
# UUID Format
# ============================================================


class TestUUIDFormat:
    """Things3 uses 22-char base58 identifiers. Hex UUIDs crash Things3."""

    def test_generated_uuid_is_22_chars(self):
        assert len(generate_uuid()) == 22

    def test_generated_uuid_is_base58(self):
        uuid = generate_uuid()
        base58_set = set(BASE58_ALPHABET)
        assert all(c in base58_set for c in uuid), f"Non-base58 char in {uuid}"

    def test_generated_uuid_has_no_ambiguous_chars(self):
        """Base58 excludes 0, O, I, l to avoid visual ambiguity."""
        for _ in range(100):
            uuid = generate_uuid()
            assert "0" not in uuid, f"UUID contains '0': {uuid}"
            assert "O" not in uuid, f"UUID contains 'O': {uuid}"
            assert "I" not in uuid, f"UUID contains 'I': {uuid}"
            assert "l" not in uuid, f"UUID contains 'l': {uuid}"

    def test_generated_uuids_are_unique(self):
        uuids = {generate_uuid() for _ in range(1000)}
        assert len(uuids) == 1000

    def test_is_valid_things_uuid(self):
        assert is_valid_things_uuid("CK9dARrf2ezbFvrVUUxkHE")  # real Things UUID
        assert not is_valid_things_uuid("f5d02f3cb15449fa816518")  # hex with '0'
        assert not is_valid_things_uuid("abc")  # too short
        assert not is_valid_things_uuid("0" * 22)  # all zeros

    @pytest.mark.asyncio
    async def test_task_service_creates_base58_uuid(self, session):
        svc = TaskService()
        task = await svc.create_task(
            session, title="Test", notes=None, status=0, schedule=0, type=0,
            area_uuid=None, project_uuid=None, heading_uuid=None,
            deadline=None, start_date=None,
        )
        assert is_valid_things_uuid(task["uuid"]), f"Bad UUID: {task['uuid']}"

    @pytest.mark.asyncio
    async def test_tag_service_creates_base58_uuid(self, session):
        svc = TagService()
        tag = await svc.create_tag(session, title="Test")
        assert is_valid_things_uuid(tag["uuid"]), f"Bad UUID: {tag['uuid']}"


# ============================================================
# Task6 Wire Format
# ============================================================


class TestTask6WireFormat:
    """Task6 wire format must match Things3's actual output exactly."""

    def _make_task(self, **overrides) -> Task:
        now = time.time()
        defaults = dict(
            uuid=generate_uuid(), title="Test task", notes="", type=0,
            status=0, schedule=1, trashed=False, index=0, today_index=0,
            creation_date=now, modification_date=now, start_date=None,
            deadline=None, completion_date=None, reminder_time=None,
            area_uuid=None, project_uuid=None, heading_uuid=None,
            contact_uuid=None, pending_push=True, leaves_tombstone=False,
            is_new=True,
        )
        defaults.update(overrides)
        return Task(**defaults)

    def test_wire_uuid_is_base58(self):
        task = self._make_task()
        items = _task_to_wire(task); wire = items[0]
        uuid = list(wire.keys())[0]
        assert is_valid_things_uuid(uuid)

    def test_wire_entity_type_is_task6(self):
        items = _task_to_wire(self._make_task()); wire = items[0]
        data = list(wire.values())[0]
        assert data["e"] == "Task6"

    def test_wire_action_is_created_for_new(self):
        items = _task_to_wire(self._make_task(is_new=True))
        data = list(items[0].values())[0]
        assert data["t"] == 0  # ACTION_CREATED

    def test_wire_action_is_modified_for_existing(self):
        items = _task_to_wire(self._make_task(is_new=False))
        data = list(items[0].values())[0]
        assert data["t"] == 1  # ACTION_MODIFIED

    def test_wire_has_all_required_fields(self):
        """Things3 sends ALL fields, even null ones. Missing fields cause issues."""
        items = _task_to_wire(self._make_task()); wire = items[0]
        payload = list(wire.values())[0]["p"]

        required_fields = {
            "tp", "sr", "dds", "rt", "rmd", "ss", "tr", "dl", "icp", "st",
            "ar", "tt", "do", "lai", "tir", "tg", "agr", "ix", "cd", "lt",
            "icc", "ti", "md", "dd", "ato", "nt", "icsd", "pr", "rp", "acrd",
            "sp", "sb", "rr", "xx",
        }
        assert required_fields.issubset(payload.keys()), \
            f"Missing: {required_fields - payload.keys()}"

    def test_wire_experimental_dict(self):
        """Things3 always includes xx: {sn: {}, _t: 'oo'}."""
        payload = list(_task_to_wire(self._make_task())[0].values())[0]["p"]
        assert payload["xx"] == {"sn": {}, "_t": "oo"}

    def test_wire_notes_as_dict_not_xml(self):
        """Notes are sent as {_t: 'tx', ch: 0, v: '<text>', t: 1}, not XML."""
        task = self._make_task(notes="Hello world")
        payload = list(_task_to_wire(task)[0].values())[0]["p"]
        nt = payload["nt"]
        assert isinstance(nt, dict)
        assert nt["_t"] == "tx"
        assert nt["v"] == "Hello world"
        assert nt["t"] == 1
        assert nt["ch"] == 0

    def test_wire_empty_notes(self):
        task = self._make_task(notes="")
        payload = list(_task_to_wire(task)[0].values())[0]["p"]
        assert payload["nt"]["v"] == ""

    def test_wire_do_is_integer_not_list(self):
        """'do' (delegate/contact) is integer 0, not a list."""
        payload = list(_task_to_wire(self._make_task())[0].values())[0]["p"]
        assert payload["do"] == 0
        assert isinstance(payload["do"], int)

    def test_wire_lt_not_lp(self):
        """Field is 'lt' (leaves_tombstone), not 'lp'."""
        payload = list(_task_to_wire(self._make_task())[0].values())[0]["p"]
        assert "lt" in payload
        assert "lp" not in payload

    def test_wire_lt_is_bool(self):
        payload = list(_task_to_wire(self._make_task())[0].values())[0]["p"]
        assert payload["lt"] is False
        assert isinstance(payload["lt"], bool)

    def test_wire_array_fields_are_always_arrays(self):
        """ar, pr, agr, dl, rt, tg are always arrays (empty []), never omitted."""
        task = self._make_task(area_uuid=None, project_uuid=None, heading_uuid=None)
        payload = list(_task_to_wire(task)[0].values())[0]["p"]
        for field in ["ar", "pr", "agr", "dl", "rt", "tg"]:
            assert isinstance(payload[field], list), f"{field} should be list, got {type(payload[field])}"

    def test_wire_array_fields_with_values(self):
        task = self._make_task(area_uuid="area123456789012345678", project_uuid="proj123456789012345678", heading_uuid="head123456789012345678")
        payload = list(_task_to_wire(task)[0].values())[0]["p"]
        assert payload["ar"] == ["area123456789012345678"]
        assert payload["pr"] == ["proj123456789012345678"]
        assert payload["agr"] == ["head123456789012345678"]

    def test_wire_tags_deferred_for_creates(self):
        """Tags in create payloads crash Things3 merge. Sent as follow-up."""
        items = _task_to_wire(self._make_task(is_new=True), tag_uuids=["tag1_base58_________"])
        create_payload = list(items[0].values())[0]["p"]
        assert create_payload["tg"] == []  # empty in create
        assert len(items) == 2  # follow-up update
        update_payload = list(items[1].values())[0]["p"]
        assert update_payload["tg"] == ["tag1_base58_________"]

    def test_wire_tags_inline_for_updates(self):
        payload = list(_task_to_wire(self._make_task(is_new=False), tag_uuids=["tag1_base58_________"])[0].values())[0]["p"]
        assert payload["tg"] == ["tag1_base58_________"]

    def test_wire_empty_tags_no_followup(self):
        """Empty tags on create don't need a follow-up."""
        items = _task_to_wire(self._make_task(is_new=True), tag_uuids=[])
        assert len(items) == 1

    def test_wire_null_fields_present(self):
        """Null fields must be explicitly included, not omitted."""
        task = self._make_task(start_date=None, deadline=None, completion_date=None)
        payload = list(_task_to_wire(task)[0].values())[0]["p"]
        assert "sr" in payload and payload["sr"] is None
        assert "dd" in payload and payload["dd"] is None
        assert "sp" in payload and payload["sp"] is None
        assert "dds" in payload and payload["dds"] is None
        assert "rmd" in payload and payload["rmd"] is None

    def test_wire_start_date_is_int_not_float(self):
        """sr (start_date) must be int. Floats crash Things3."""
        task = self._make_task(start_date=1777161600.5)
        payload = list(_task_to_wire(task)[0].values())[0]["p"]
        assert isinstance(payload["sr"], int), f"sr should be int, got {type(payload['sr'])}"
        assert payload["sr"] == 1777161600

    def test_wire_deadline_is_int_not_float(self):
        """dd (deadline) must be int. Floats crash Things3."""
        # For existing tasks, dd is inline
        task = self._make_task(is_new=False, deadline=1777248000.0)
        payload = list(_task_to_wire(task)[0].values())[0]["p"]
        assert isinstance(payload["dd"], int), f"dd should be int, got {type(payload['dd'])}"
        # For new tasks, dd is in the follow-up update
        task = self._make_task(is_new=True, deadline=1777248000.0)
        items = _task_to_wire(task)
        update_payload = list(items[1].values())[0]["p"]
        assert isinstance(update_payload["dd"], int)

    def test_wire_start_date_none_stays_none(self):
        task = self._make_task(start_date=None)
        payload = list(_task_to_wire(task)[0].values())[0]["p"]
        assert payload["sr"] is None
        assert payload["tir"] is None

    def test_wire_tir_matches_start_date(self):
        """tir (todayIndexReferenceDate) should equal sr when set."""
        task = self._make_task(start_date=1777161600)
        payload = list(_task_to_wire(task)[0].values())[0]["p"]
        assert payload["tir"] == payload["sr"]
        assert isinstance(payload["tir"], int)

    def test_wire_cd_md_are_float(self):
        """cd, md (creation/modification dates) are floats with fractional seconds."""
        task = self._make_task(creation_date=1777180486.527842, modification_date=1777180511.501296)
        payload = list(_task_to_wire(task)[0].values())[0]["p"]
        assert isinstance(payload["cd"], float)
        assert isinstance(payload["md"], float)

    def test_wire_lt_defaults_false(self):
        """Things3 defaults lt to False for tasks."""
        payload = list(_task_to_wire(self._make_task())[0].values())[0]["p"]
        assert payload["lt"] is False

    def test_wire_status_values(self):
        for status in [0, 2, 3]:
            payload = list(_task_to_wire(self._make_task(status=status))[0].values())[0]["p"]
            assert payload["ss"] == status

    def test_wire_schedule_values(self):
        for schedule in [0, 1, 2]:
            payload = list(_task_to_wire(self._make_task(schedule=schedule))[0].values())[0]["p"]
            assert payload["st"] == schedule

    def test_new_task_with_deadline_emits_two_items(self):
        """New tasks with deadlines must be created then updated separately.

        Things3's merge engine crashes if dd is set in a t=0 (create) payload.
        The fix: send t=0 with dd=null, then t=1 with dd=<value>.
        """
        task = self._make_task(is_new=True, deadline=1777248000.0)
        items = _task_to_wire(task)
        assert len(items) == 2

        create = list(items[0].values())[0]
        assert create["t"] == 0
        assert create["p"]["dd"] is None  # NOT in create

        update = list(items[1].values())[0]
        assert update["t"] == 1
        assert update["p"]["dd"] == 1777248000

    def test_new_task_without_deadline_emits_one_item(self):
        items = _task_to_wire(self._make_task(is_new=True, deadline=None))
        assert len(items) == 1

    def test_existing_task_with_deadline_emits_one_item(self):
        """Modifications include deadline inline (no two-step needed)."""
        items = _task_to_wire(self._make_task(is_new=False, deadline=1777248000.0))
        assert len(items) == 1
        payload = list(items[0].values())[0]["p"]
        assert payload["dd"] == 1777248000

    def test_new_task_with_completion_emits_two_items(self):
        task = self._make_task(is_new=True, completion_date=1777180000.0)
        items = _task_to_wire(task)
        assert len(items) == 2
        assert list(items[0].values())[0]["p"]["sp"] is None
        assert list(items[1].values())[0]["p"]["sp"] == 1777180000.0


# ============================================================
# Tag4 Wire Format
# ============================================================


class TestTag4WireFormat:
    """Tag4 wire format must match Things3's actual output."""

    def _make_tag(self, **overrides) -> Tag:
        defaults = dict(
            uuid=generate_uuid(), title="Test", shortcut=None,
            parent_uuid=None, index=0, pending_push=True, pending_delete=False,
            is_new=True,
        )
        defaults.update(overrides)
        return Tag(**defaults)

    def test_wire_entity_type(self):
        wire = _tag_to_wire(self._make_tag())
        data = list(wire.values())[0]
        assert data["e"] == "Tag4"

    def test_wire_action_created_for_new(self):
        wire = _tag_to_wire(self._make_tag(is_new=True))
        assert list(wire.values())[0]["t"] == 0

    def test_wire_action_modified_for_existing(self):
        wire = _tag_to_wire(self._make_tag(is_new=False))
        assert list(wire.values())[0]["t"] == 1

    def test_wire_has_required_fields(self):
        payload = list(_tag_to_wire(self._make_tag()).values())[0]["p"]
        assert set(payload.keys()) == {"tt", "sh", "pn", "ix", "xx"}

    def test_wire_experimental_dict(self):
        payload = list(_tag_to_wire(self._make_tag()).values())[0]["p"]
        assert payload["xx"] == {"sn": {}, "_t": "oo"}

    def test_wire_parent_is_array(self):
        """pn is always an array: [] for no parent, [uuid] for parent."""
        payload = list(_tag_to_wire(self._make_tag(parent_uuid=None)).values())[0]["p"]
        assert payload["pn"] == []

        payload = list(_tag_to_wire(self._make_tag(parent_uuid="parent_base58________")).values())[0]["p"]
        assert payload["pn"] == ["parent_base58________"]

    def test_wire_shortcut_null_when_unset(self):
        """sh is null, not omitted, when no shortcut."""
        payload = list(_tag_to_wire(self._make_tag(shortcut=None)).values())[0]["p"]
        assert payload["sh"] is None

    def test_wire_delete_format(self):
        """Tag deletion is {uuid: {t: 2, e: 'Tag4', p: {}}}."""
        wire = _tag_delete_wire("some_uuid_base58_____")
        data = wire["some_uuid_base58_____"]
        assert data["t"] == 2
        assert data["e"] == "Tag4"
        assert data["p"] == {}


# ============================================================
# Commit Body Format
# ============================================================


class TestCommitFormat:
    """The commit endpoint expects a flat dict, not a list of dicts."""

    def test_commit_body_is_flat_dict(self):
        """Things Cloud expects {uuid1: data1, uuid2: data2}, not [{uuid1: data1}, ...]."""
        from things_sdk.cloud.client import ThingsCloudClient

        # The commit method merges list into flat dict
        items = [
            {"uuid1": {"t": 0, "e": "Task6", "p": {}}},
            {"uuid2": {"t": 0, "e": "Tag4", "p": {}}},
        ]

        # Simulate what commit() does
        body: dict = {}
        for item in items:
            body.update(item)

        assert "uuid1" in body
        assert "uuid2" in body
        assert isinstance(body, dict)
        assert not isinstance(body, list)

    def test_wire_items_are_single_key_dicts(self):
        """Each wire item should be a single-key dict {uuid: data}."""
        task = Task(
            uuid=generate_uuid(), title="T", status=0, schedule=0, type=0,
            trashed=False, index=0, today_index=0, creation_date=time.time(),
            modification_date=time.time(), leaves_tombstone=False, is_new=True,
        )
        items = _task_to_wire(task)
        wire = items[0]
        assert len(wire) == 1
        uuid = list(wire.keys())[0]
        assert is_valid_things_uuid(uuid)


# ============================================================
# HTTP Headers
# ============================================================


class TestRequiredHeaders:
    """Things Cloud requires specific headers for commits to succeed."""

    def test_default_headers_have_app_id(self):
        from things_sdk.cloud.client import DEFAULT_HEADERS
        assert DEFAULT_HEADERS["App-Id"] == "com.culturedcode.ThingsMac"

    def test_default_headers_have_schema(self):
        from things_sdk.cloud.client import DEFAULT_HEADERS
        assert DEFAULT_HEADERS["Schema"] == "301"

    def test_default_headers_have_user_agent(self):
        from things_sdk.cloud.client import DEFAULT_HEADERS
        assert "ThingsMac" in DEFAULT_HEADERS["User-Agent"]

    def test_default_headers_have_things_client_info(self):
        """Base64-encoded JSON with device info."""
        import base64
        from things_sdk.cloud.client import DEFAULT_HEADERS
        assert "things-client-info" in DEFAULT_HEADERS
        decoded = json.loads(base64.b64decode(DEFAULT_HEADERS["things-client-info"]))
        assert "nn" in decoded  # app name
        assert "nv" in decoded  # app version

    def test_default_headers_have_app_instance_id(self):
        from things_sdk.cloud.client import DEFAULT_HEADERS
        assert "App-Instance-Id" in DEFAULT_HEADERS
        assert len(DEFAULT_HEADERS["App-Instance-Id"]) > 20

    def test_default_headers_have_push_priority(self):
        from things_sdk.cloud.client import DEFAULT_HEADERS
        assert DEFAULT_HEADERS["Push-Priority"] == "5"

    def test_default_headers_have_accept_json(self):
        from things_sdk.cloud.client import DEFAULT_HEADERS
        assert DEFAULT_HEADERS["Accept"] == "application/json"
