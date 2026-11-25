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


SYSTEM_CONFIG = Path("/etc/sks-dl/config.json")  # set by the server's admin, read by every account


_CONFIGS: dict[Path, tuple[float, dict]] = {}  # file -> (mtime, content): read again only when it changes


def _config(f: Path) -> dict:
    import json

    try:
        mt = f.stat().st_mtime
    except OSError:
        return {}
    hit = _CONFIGS.get(f)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        d = json.loads(f.read_text())
    except (OSError, ValueError):
        d = {}
    d = d if isinstance(d, dict) else {}
    _CONFIGS[f] = (mt, d)
    return d


def user_config() -> Path:
    return config_dir() / "config.json"


def _setting(name: str) -> str | None:
    """A setting from ``SKS_DL_<NAME>``, else the user's ``config.json``, else the server-wide one."""
    v = env(name.upper())
    if v:
        return v
    for f in (user_config(), SYSTEM_CONFIG):
        x = _config(f).get(name)
        if isinstance(x, str) and x.strip():
            return x.strip()
    return None


def shared_jobs_dir() -> Path | None:
    """A jobs folder several accounts share (e.g. ``/srv/sks-dl/jobs``), or None for the private default."""
    v = _setting("jobs_dir")
    return Path(v).expanduser() if v else None


def jobs_dir() -> Path:
    shared = shared_jobs_dir()
    p = shared or data_dir() / "jobs"
    if shared and not p.exists():
        p.mkdir(parents=True, exist_ok=True)
        try:  # group-writable, and new folders inherit the group (setgid)
            p.chmod(0o2775)
        except OSError:
            pass
    p.mkdir(parents=True, exist_ok=True)
    return p


def share_files() -> None:
    """With a shared jobs folder, files this process creates are group-writable (umask 002), so a colleague can
    resume a job: its state, its temporary chunks and its Icechunk repository. Private files (API keys) set their
    own mode."""
    if shared_jobs_dir():
        # umask 002 would leave new folders of this account group-writable: the app's private folders (keys,
        # request counts, the catalogue and sample caches that jobs trust) are made private first
        for d in (config_dir(), data_dir(), cache_dir()):
            if d.name in (NAME, LEGACY_NAME) and not d.is_symlink():
                try:
                    d.chmod(0o700)
                except OSError:
                    pass
        os.umask(0o002)
