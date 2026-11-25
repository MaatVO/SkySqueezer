"""Self-update of the packaged executable from the latest GitHub release.

Each time the app is opened (every load of its page, ``check``) it asks GitHub for the latest release. If it is
newer than this build, a pop-up (gui/connect.py) shows the start of its release notes and asks: only on a yes is
the matching executable downloaded, checked against the release's ``.sha256`` file and swapped in place of the
running one, which carries on; the new version runs from the next start. On a no it is asked again the next time
the app is opened. Anything that goes wrong (offline, no permission to write next to the executable, unknown
platform, ...) is reported and nothing changes.

Only the packaged executable updates itself; running from source / ``uv tool install`` never does.
Opt out with ``--no-update`` or ``SKS_DL_NO_UPDATE=1``. ``sks-dl update`` does the same on demand.
"""

import hashlib
import json
import os
import platform
import re
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from . import __version__
from .paths import env

REPO = "MaatVO/SkySqueezer"
API = f"https://api.github.com/repos/{REPO}/releases/latest"


def parse(v: str) -> tuple[int, ...]:
    """'v0.2.13' -> (0, 2, 13); unparsable -> ()."""
    m = re.match(r"v?(\d+(?:\.\d+)*)", v.strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def platform_tag() -> str | None:
    m = platform.machine().lower()
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(m)
    os_ = {"linux": "linux", "darwin": "macos", "win32": "windows"}.get(sys.platform)
    tag = f"{os_}-{arch}" if os_ and arch else None
    return tag if tag in ("linux-x86_64", "macos-arm64", "windows-x86_64") else None


def can_self_update() -> bool:
    return bool(getattr(sys, "frozen", False)) and not os.environ.get("APPIMAGE") and platform_tag() is not None


def _get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "skysqueezer-updater",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def latest(timeout: float = 4.0) -> dict | None:
    """{'version': '0.2.5', 'url': ..., 'sha_url': ..., 'page': ..., 'notes': markdown} for this platform, or
    None."""
    rel = json.loads(_get(API, timeout))
    if rel.get("draft") or rel.get("prerelease"):
        return None
    tag = platform_tag()
    assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
    for name, url in assets.items():
        if f"-{tag}" in name and not name.endswith(".sha256") and f"{name}.sha256" in assets:
            return {"version": rel["tag_name"].lstrip("v"), "url": url, "sha_url": assets[f"{name}.sha256"],
                    "page": rel.get("html_url") or "", "notes": rel.get("body") or ""}
    return None


def is_newer(remote: str, local: str | None = None) -> bool:
    r, l = parse(remote), parse(__version__ if local is None else local)  # read now: tests patch __version__
    return bool(r) and r > l


def install(info: dict, exe: Path, timeout: float = 120.0) -> None:
    """Download, verify and swap in the new executable (raises on any problem; the old one stays usable)."""
    for u in (info["url"], info["sha_url"]):
        if not u.startswith("https://"):
            raise ValueError(f"refusing non-https url {u}")
    want = _get(info["sha_url"], 15).decode().split()[0].lower()
    fd, tmp_name = tempfile.mkstemp(prefix=".sks-dl-new-", dir=exe.parent)  # same folder: atomic rename
    tmp = Path(tmp_name)
    try:
        h = hashlib.sha256()
        req = urllib.request.Request(info["url"], headers={"User-Agent": "skysqueezer-updater"})
        with os.fdopen(fd, "wb") as f, urllib.request.urlopen(req, timeout=timeout) as r:
            while chunk := r.read(1 << 20):
                h.update(chunk)
                f.write(chunk)
        if h.hexdigest() != want:
            raise ValueError("checksum mismatch, update discarded")
        tmp.chmod(0o755)
        if sys.platform == "win32":  # a running .exe can be renamed but not overwritten
            old = exe.with_name(exe.name + ".old")
            old.unlink(missing_ok=True)
            os.replace(exe, old)
            try:
                os.replace(tmp, exe)
            except OSError:
                os.replace(old, exe)
                raise
        else:
            os.replace(tmp, exe)
    finally:
        tmp.unlink(missing_ok=True)


def check_and_update(force_notice: bool = False) -> bool:
    """Update if a newer release exists. True when the executable was replaced."""
    try:
        info = latest()
    except Exception as e:
        if force_notice:
            print(f"could not check for updates: {e}")
        return False
    if not info or not is_newer(info["version"]):
        if force_notice:
            print(f"sks-dl {__version__} is up to date")
        return False
    print(f"Updating sks-dl {__version__} → {info['version']} …", flush=True)
    try:
        install(info, Path(sys.executable))
    except Exception as e:
        print(f"update failed ({e}); starting {__version__}", flush=True)
        return False
    return True


def is_local_build(version: str | None = None) -> bool:
    """A build made on a developer's machine (packaging/build.sh without a release number): '0.2.0+local'."""
    return (version or __version__).endswith("+local")


AVAILABLE: dict | None = None  # the newer release last found, waiting for the user's yes
UPDATED: str | None = None  # the version installed after the user said yes, which runs from the next start
ENABLED = False  # this program may update itself (set by ``auto_update``)
CHECK_TTL = 60.0  # seconds a check is reused: a reload storm must not hit GitHub's limit (60 requests/hour)
_checked: tuple[float, dict | None] | None = None


def check(timeout: float = 6.0) -> dict | None:
    """The newer release to offer now, or None (up to date, already updated, offline, or not self-updating).
    Called each time the app's page opens."""
    global AVAILABLE, _checked
    if not ENABLED or UPDATED:
        return None
    now = time.monotonic()
    if _checked is None or now - _checked[0] > CHECK_TTL:
        try:
            info = latest(timeout=timeout)
        except Exception as e:  # noqa: BLE001 - offline, rate-limited …: this version just keeps running
            print(f"(update check: {e})", flush=True)
            return AVAILABLE  # what an earlier check found still stands
        _checked = (now, info if info and is_newer(info["version"]) else None)
        AVAILABLE = _checked[1]
    return AVAILABLE


NOTES_LINES = 10  # lines of release notes shown in the pop-up
NOTES_CHARS = 900


def notes_excerpt(notes: str, lines: int = NOTES_LINES, chars: int = NOTES_CHARS) -> tuple[str, bool]:
    """The start of a release's notes for the pop-up (markdown) and whether it was cut."""
    text = re.sub(r"<!--.*?-->", "", notes or "", flags=re.DOTALL).replace("\r\n", "\n").strip()
    keep, used, cut = [], 0, False
    for line in text.splitlines():
        if len(keep) >= lines or used + len(line) > chars:
            cut = True
            break
        keep.append(line)
        used += len(line) + 1
    while keep and not keep[-1].strip():
        keep.pop()
    return "\n".join(keep), cut


def apply(info: dict) -> None:
    """The user said yes: download, verify and swap in ``info``'s executable (raises on any problem; this version
    keeps running either way)."""
    global AVAILABLE, UPDATED
    install(info, Path(sys.executable))
    AVAILABLE, UPDATED = None, info["version"]


def _clean_leftovers(exe: Path) -> None:
    """Remove what an interrupted update or a replaced Windows executable left next to ``exe``."""
    old = exe.with_name(exe.name + ".old")
    stale = [p for pat in (".sks-dl-new-*", ".edh-dl-new-*")  # and leftovers from before the rename
             for p in exe.parent.glob(pat) if time.time() - p.stat().st_mtime > 3600]
    for p in [old, *stale]:
        try:
            p.unlink(missing_ok=True)
        except OSError:  # still running (another window of the old version), or not ours to delete
            pass


def _check_in_background() -> None:
    """At start-up: find a newer release early, so the first page can ask at once; nothing is downloaded until the
    user says yes."""
    info = check(timeout=10)
    if info:
        print(f"SkySqueezer {info['version']} is available: the app asks before installing it.", flush=True)


def auto_update() -> None:
    """Called at startup: allows the checks each time the page opens (``check``) and makes the first one in the
    background, so the start is never delayed. A newer release is offered to the user and installed only on a yes
    (``apply``); it runs from the next start. Local builds never offer updates here (``sks-dl update`` still can)."""
    global ENABLED
    if env("NO_UPDATE") or not can_self_update() or is_local_build():
        return
    ENABLED = True
    _clean_leftovers(Path(sys.executable))
    threading.Thread(target=_check_in_background, name="sks-dl-update", daemon=True).start()
