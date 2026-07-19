"""Content-addressed, read-only original storage + path jail for serving."""
import os
import stat
from pathlib import Path

from app.config import Settings


def store_original(settings: Settings, tmp_path: Path, sha256: str, ext: str) -> str:
    """Move an uploaded temp file into originals/<h2>/<hash><ext>, mark read-only.

    Returns the DATA_DIR-relative path. Idempotent: same content → same path.
    """
    ext = ext.lower() if ext.startswith(".") else f".{ext.lower()}" if ext else ""
    rel = Path("originals") / sha256[:2] / f"{sha256}{ext}"
    dest = settings.data_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        tmp_path.unlink(missing_ok=True)
    else:
        os.replace(tmp_path, dest)
        _make_read_only(dest)
    return rel.as_posix()


def _make_read_only(path: Path) -> None:
    try:
        path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)  # 0o444
    except OSError:
        pass  # best-effort on non-POSIX filesystems


def safe_resolve(settings: Settings, rel_path: str) -> Path:
    """Resolve a DATA_DIR-relative path, refusing anything that escapes the jail."""
    if "\\" in rel_path or "\x00" in rel_path or rel_path.startswith(("/", "~")):
        raise PermissionError(f"suspicious path rejected: {rel_path!r}")
    if any(part == ".." for part in Path(rel_path).parts):
        raise PermissionError(f"traversal rejected: {rel_path!r}")
    base = settings.data_dir.resolve()
    candidate = (base / rel_path).resolve()
    if not candidate.is_relative_to(base):
        raise PermissionError(f"path escapes data dir: {rel_path!r}")
    return candidate


def derived_path(settings: Settings, *parts: str) -> Path:
    p = settings.derived_dir.joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def rel_to_data(settings: Settings, path: Path) -> str:
    return path.resolve().relative_to(settings.data_dir.resolve()).as_posix()
