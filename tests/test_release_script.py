from __future__ import annotations

import pytest

from scripts.release import replace_version, validate_version


def test_validate_version_accepts_semver() -> None:
    validate_version("1.2.3")


@pytest.mark.parametrize("value", ["1.2", "v1.2.3", "1.2.3-rc1", "abc"])
def test_validate_version_rejects_non_simple_semver(value: str) -> None:
    with pytest.raises(ValueError):
        validate_version(value)


def test_replace_version_replaces_first_version_field_only() -> None:
    content = 'name = "pkg"\nversion = "0.1.0"\nother = "x"\nversion = "leave-me"\n'
    updated = replace_version(content, "0.2.0")
    assert 'version = "0.2.0"' in updated
    assert 'version = "leave-me"' in updated


def test_replace_version_errors_when_missing() -> None:
    with pytest.raises(ValueError):
        replace_version('name = "pkg"\n', "0.2.0")
