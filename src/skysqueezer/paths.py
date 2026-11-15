"""Where the app keeps its configuration, state, cache and jobs (XDG locations, overridable).

The folders are named ``sks-dl``. Installs from before the SkySqueezer rename have them as ``edh-dl``: while only the
old folder exists it stays in use, so keys, quota counts and jobs (and workers still running from the old version)
keep working; nothing is moved. ``SKS_DL_*`` variables also accept their old ``EDH_DL_*`` names.
"""

import os
from pathlib import Path

NAME = "sks-dl"
LEGACY_NAME = "edh-dl"


def env(name: str) -> str | None:
    """``SKS_DL_<name>``, else the pre-rename ``EDH_DL_<name>``."""
    return os.environ.get(f"SKS_DL_{name}") or os.environ.get(f"EDH_DL_{name}") or None


def pick(base: Path) -> Path:
    """``base/sks-dl``, unless only the pre-rename ``base/edh-dl`` exists."""
    new, old = base / NAME, base / LEGACY_NAME
    return old if old.is_dir() and not new.exists() else new


def _xdg(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / default)


def _dir(override: str, xdg: str, default: str) -> Path:
    p = Path(env(override) or pick(_xdg(xdg, default)))
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_dir() -> Path:
    return _dir("CONFIG_DIR", "XDG_CONFIG_HOME", ".config")


def data_dir() -> Path:
    return _dir("DATA_DIR", "XDG_DATA_HOME", ".local/share")


def cache_dir() -> Path:
    return _dir("CACHE_DIR", "XDG_CACHE_HOME", ".cache")


def jobs_dir() -> Path:
    p = data_dir() / "jobs"
    p.mkdir(parents=True, exist_ok=True)
    return p
