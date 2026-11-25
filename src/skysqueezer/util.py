"""Small helpers shared across modules."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def current_umask() -> int:
    """The process umask, read without changing it (setting it to read it back would open a window in which
    other threads create files with the wrong mode)."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("Umask:"):
                    return int(line.split()[1], 8)
    except (OSError, ValueError, IndexError):
        pass
    um = os.umask(0o077)  # no /proc (macOS): the brief window errs on the private side
    os.umask(um)
    return um


def _in_shared(path: Path) -> bool:
    from .paths import shared_jobs_dir

    shared = shared_jobs_dir()
    if not shared:
        return False
    try:
        path.resolve().relative_to(shared.resolve())
        return True
    except (ValueError, OSError):
        return False


def write_json_atomic(path: Path | str, data: Any, mode: int | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, default=str)
        if mode is None:  # mkstemp makes 0600; in a shared jobs folder the group must be able to write it too
            mode = 0o666 & ~current_umask() if _in_shared(path) else 0o600
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def read_json(path: Path | str, default: Any = None, kind: type | None = None) -> Any:
    """The JSON in ``path``, or ``default`` when it is missing, unreadable as JSON (also binary garbage) or, with
    ``kind``, not of that type (a stray ``[]`` where an object is expected)."""
    try:
        with open(path) as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError):  # JSONDecodeError and UnicodeDecodeError are ValueErrors
        return default
    return data if kind is None or isinstance(data, kind) else default


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1000 or unit == "PB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1000
    return f"{n:.1f} PB"


def human_duration(seconds: float | None) -> str:
    if seconds is None or seconds != seconds or seconds == float("inf"):
        return "—"
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"
