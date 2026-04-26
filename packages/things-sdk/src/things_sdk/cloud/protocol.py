"""Things Cloud protocol utilities — UUID generation and validation.

Things3 uses 22-character base58 identifiers (no 0, O, I, l).
Using hex UUIDs will crash Things3 when it pulls them.
"""

from __future__ import annotations

import secrets

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_SET = frozenset(BASE58_ALPHABET)
UUID_LENGTH = 22


def generate_uuid() -> str:
    """Generate a 22-char base58 UUID matching Things3 format."""
    return "".join(secrets.choice(BASE58_ALPHABET) for _ in range(UUID_LENGTH))


def is_valid_things_uuid(value: str) -> bool:
    """Check if a string is a valid Things3 UUID (22 chars, base58)."""
    return len(value) == UUID_LENGTH and all(c in _BASE58_SET for c in value)
