"""Things Cloud protocol utilities — UUID generation and validation.

Things3 uses canonical base58 identifiers of 16 random bytes
(Bitcoin alphabet, usually 22 characters; no 0, O, I, l).
Using hex UUIDs or non-canonical base58 will crash Things3 when it pulls them.
"""

from __future__ import annotations

import secrets

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_SET = frozenset(BASE58_ALPHABET)
UUID_LENGTH = 22


def _b58encode(raw: bytes) -> str:
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = BASE58_ALPHABET[r] + out
    pad = len(raw) - len(raw.lstrip(b"\0"))
    return "1" * pad + out


def _b58decode(value: str) -> bytes | None:
    if not value or any(c not in _BASE58_SET for c in value):
        return None
    n = 0
    for c in value:
        n = n * 58 + BASE58_ALPHABET.index(c)
    pad = len(value) - len(value.lstrip("1"))
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * pad + body


def generate_uuid() -> str:
    """Return a canonical Things id: base58 of 16 random bytes, 22 characters.

    Official clients encode 16 bytes with the Bitcoin alphabet (leading-1
    padding). Picking 22 random alphabet characters often yields a value
    that decodes to more than 16 bytes and crashes Things.app
    (``decodeBase58String``). Cloud history is append-only, so such an
    id cannot be repaired later.

    About 14% of 16-byte encodings are 21 characters; those are retried
    so new ids match the 22-character length official clients write.
    """
    while True:
        s = _b58encode(secrets.token_bytes(16))
        # 16-byte base58 is usually 22 chars; retry the ~14% that encode to 21
        # so ids match the length Things.app itself writes.
        if len(s) == UUID_LENGTH and is_valid_things_uuid(s):
            return s


def is_valid_things_uuid(value: str) -> bool:
    """True if *value* is canonical base58 that decodes to exactly 16 bytes.

    Accepted length is 21 or 22 characters: a 16-byte value usually encodes
    to 22, occasionally to 21. :func:`generate_uuid` always returns 22.
    """
    if not isinstance(value, str) or not (21 <= len(value) <= 22):
        return False
    raw = _b58decode(value)
    return raw is not None and len(raw) == 16 and _b58encode(raw) == value
