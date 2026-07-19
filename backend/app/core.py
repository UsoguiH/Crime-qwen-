"""Small shared primitives: time-ordered ids, UTC timestamps."""
import os
import time
from datetime import datetime, timezone

_last_ms = 0
_counter = 0


def make_id() -> str:
    """UUIDv7-style 32-hex id: 48-bit ms timestamp + 80 random bits.

    Lexicographic order ≈ creation order, which keeps SQLite indexes tight
    and makes evidence/run ids naturally sortable.
    """
    global _last_ms, _counter
    ms = time.time_ns() // 1_000_000
    if ms == _last_ms:
        _counter = (_counter + 1) & 0xFFF
    else:
        _counter = 0
        _last_ms = ms
    rand = os.urandom(9).hex()  # 72 bits
    return f"{ms:012x}{_counter:03x}{rand[:17]}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
