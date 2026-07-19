import hashlib
import json
from pathlib import Path
from typing import Any, BinaryIO

CHUNK = 1024 * 1024


def sha256_stream(fp: BinaryIO) -> str:
    h = hashlib.sha256()
    while chunk := fp.read(CHUNK):
        h.update(chunk)
    return h.hexdigest()


def sha256_file(path: Path) -> str:
    with open(path, "rb") as fp:
        return sha256_stream(fp)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(obj: Any) -> str:
    """Stable serialization for hash chains: sorted keys, compact, real UTF-8."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)
