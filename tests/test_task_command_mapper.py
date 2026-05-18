"""Direct unit tests for TaskCommandMapper._resolve_enum.

Currently uncovered by the API tests — invalid inputs are rejected by FastAPI
serialization before they reach the mapper, so a regression in the bool /
invalid int / invalid string branches could ship silently and corrupt task
status values in the cloud commit body.
"""

from __future__ import annotations

from enum import IntEnum

import pytest
from fastapi import HTTPException

from things_api.services.task_command_mapper import TaskCommandMapper


class _Status(IntEnum):
    pending = 0
    completed = 3
    canceled = 2


@pytest.fixture
def mapper() -> TaskCommandMapper:
    return TaskCommandMapper()


# --- Happy paths ---


def test_resolve_enum_accepts_valid_int(mapper):
    assert mapper._resolve_enum(3, _Status) == 3


def test_resolve_enum_accepts_valid_string(mapper):
    assert mapper._resolve_enum("completed", _Status) == 3


def test_resolve_enum_accepts_zero_int(mapper):
    """0 evaluates falsy but is a valid IntEnum value — must not be rejected."""
    assert mapper._resolve_enum(0, _Status) == 0


def test_resolve_enum_passes_through_none(mapper):
    """None is intentionally passed through; callers gate on `is not None`
    before invoking the mapper for partial updates."""
    assert mapper._resolve_enum(None, _Status) is None


# --- Rejection paths ---


def test_resolve_enum_rejects_bool_true(mapper):
    """bool is an int subclass; without the explicit check, True would
    silently coerce to status=completed via int(True)==1."""
    with pytest.raises(HTTPException) as exc:
        mapper._resolve_enum(True, _Status)
    assert exc.value.status_code == 422
    assert "Valid:" in exc.value.detail


def test_resolve_enum_rejects_bool_false(mapper):
    with pytest.raises(HTTPException) as exc:
        mapper._resolve_enum(False, _Status)
    assert exc.value.status_code == 422


def test_resolve_enum_rejects_invalid_int(mapper):
    with pytest.raises(HTTPException) as exc:
        mapper._resolve_enum(99, _Status)
    assert exc.value.status_code == 422
    # Error message lists name=value so client can recover.
    assert "pending=0" in exc.value.detail
    assert "completed=3" in exc.value.detail


def test_resolve_enum_rejects_invalid_string(mapper):
    with pytest.raises(HTTPException) as exc:
        mapper._resolve_enum("nope", _Status)
    assert exc.value.status_code == 422
    assert "Valid:" in exc.value.detail


def test_resolve_enum_string_is_case_sensitive(mapper):
    """IntEnum lookup by name is case-sensitive; document that behavior."""
    with pytest.raises(HTTPException):
        mapper._resolve_enum("COMPLETED", _Status)
