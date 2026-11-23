"""Small shared helpers: write a file only when its content changed, prune stale files, stable content hashes.

Why: the daily run rewrote ~6,000 per-stock files whether or not they changed, and deleted/recreated whole directories.
Unchanged files now keep their bytes (and mtime), and a file that dropped out of today's set is the only thing removed.
"""
import hashlib
import json
from pathlib import Path


def write_if_changed(path: Path, data: str | bytes) -> bool:
    """Write `data` to `path` unless it already holds exactly these bytes. Returns True when the file was (re)written."""
    b = data.encode("utf-8") if isinstance(data, str) else data
    try:
        if path.exists() and path.stat().st_size == len(b) and path.read_bytes() == b:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b)
    return True


def prune(directory: Path, keep: set[str], pattern: str = "*.json") -> int:
    """Delete files matching `pattern` in `directory` whose file name is not in `keep`. Returns how many were removed."""
    n = 0
    if directory.exists():
        for f in directory.glob(pattern):
            if f.name not in keep:
                f.unlink()
                n += 1
    return n


def canon(obj) -> str:
    """Canonical JSON (sorted keys, compact): equal data gives equal text whatever the dict insertion order."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def digest(obj, n: int = 16) -> str:
    """Short stable content hash of any JSON-able value (str and bytes are hashed as they are)."""
    if isinstance(obj, bytes):
        b = obj
    elif isinstance(obj, str):
        b = obj.encode("utf-8")
    else:
        b = canon(obj).encode("utf-8")
    return hashlib.sha1(b).hexdigest()[:n]


def file_digest(path: Path, n: int = 16) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:n]
