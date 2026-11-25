import hashlib
import sys

import pytest

from skysqueezer import update


def test_parse_and_newer():
    assert update.parse("v0.2.13") == (0, 2, 13)
    assert update.is_newer("0.2.13", "0.2.9")
    assert not update.is_newer("0.2.2", "0.2.2")
    assert not update.is_newer("junk", "0.2.0")


def test_install_verifies_checksum(tmp_path, monkeypatch):
    payload = b"new-binary"
    exe = tmp_path / "sks-dl"
    exe.write_bytes(b"old")
    served = {"https://x/bin": payload, "https://x/bin.sha256": f"{hashlib.sha256(payload).hexdigest()} bin".encode()}
    monkeypatch.setattr(update, "_get", lambda url, timeout: served[url])

    class R:
        def __init__(s, b): s.b = b; s.i = 0
        def read(s, n): d, s.b = s.b[:n], s.b[n:]; return d
        def __enter__(s): return s
        def __exit__(s, *a): pass

    monkeypatch.setattr(update.urllib.request, "urlopen", lambda req, timeout: R(served[req.full_url]))
    info = {"url": "https://x/bin", "sha_url": "https://x/bin.sha256"}
    if sys.platform != "win32":
        update.install(info, exe)
        assert exe.read_bytes() == payload
    served["https://x/bin.sha256"] = b"0" * 64 + b" bin"
    exe.write_bytes(b"old")
    with pytest.raises(ValueError, match="checksum"):
        update.install(info, exe)
    assert exe.read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir()] == ["sks-dl"]  # no temp leftovers
    with pytest.raises(ValueError, match="https"):
        update.install({"url": "http://x/bin", "sha_url": "https://x/bin.sha256"}, exe)


def test_latest_picks_platform_asset(monkeypatch):
    import json
    monkeypatch.setattr(update, "platform_tag", lambda: "linux-x86_64")
    rel = {"tag_name": "v0.2.9", "body": "- faster maps", "assets": [
        {"name": n, "browser_download_url": f"https://g/{n}"} for n in (
            "sks-dl-v0.2.9-linux-x86_64", "sks-dl-v0.2.9-linux-x86_64.sha256", "sks-dl-v0.2.9-macos-arm64")]}
    monkeypatch.setattr(update, "_get", lambda url, timeout: json.dumps(rel).encode())
    assert update.latest()["url"] == "https://g/sks-dl-v0.2.9-linux-x86_64"
    assert update.latest()["version"] == "0.2.9" and update.latest()["notes"] == "- faster maps"


class _Threads:
    def __init__(self):
        self.started = []

    def __call__(self, target, **kw):
        self.started.append(target)
        return self

    def start(self):
        pass


def _startup(monkeypatch, tmp_path, version):
    monkeypatch.setattr(update, "__version__", version)
    monkeypatch.setattr(update, "can_self_update", lambda: True)
    monkeypatch.setattr(update.sys, "executable", str(tmp_path / "sks-dl"))
    monkeypatch.delenv("SKS_DL_NO_UPDATE", raising=False)
    monkeypatch.setattr(update, "ENABLED", False)  # auto_update turns it on: undone after the test
    threads = _Threads()
    monkeypatch.setattr(update.threading, "Thread", threads)
    update.auto_update()
    return threads.started


def test_local_build_never_replaces_itself_at_startup(monkeypatch, tmp_path):
    """A build from packaging/build.sh without a release number must not swap itself for the latest release."""
    assert _startup(monkeypatch, tmp_path, "0.2.0+local") == []
    assert update.is_local_build("0.2.0+local") and not update.is_local_build("0.2.17")
    assert update.is_newer("0.2.5", "0.2.0+local")  # an explicit `sks-dl update` still sees releases as newer


def test_release_build_checks_in_the_background_without_delaying_the_start(monkeypatch, tmp_path):
    (tmp_path / ".sks-dl-new-abandoned").write_bytes(b"x")
    import os
    os.utime(tmp_path / ".sks-dl-new-abandoned", (0, 0))  # an update interrupted long ago
    (tmp_path / ".sks-dl-new-current").write_bytes(b"x")  # another window downloading right now
    assert _startup(monkeypatch, tmp_path, "0.2.3") == [update._check_in_background]
    assert not (tmp_path / ".sks-dl-new-abandoned").exists()
    assert (tmp_path / ".sks-dl-new-current").exists()


@pytest.fixture
def offering(monkeypatch):
    """A self-updating 0.2.3 that GitHub answers with ``served`` (counted in ``calls``)."""
    monkeypatch.setattr(update, "__version__", "0.2.3")
    monkeypatch.setattr(update, "ENABLED", True)
    monkeypatch.setattr(update, "AVAILABLE", None)
    monkeypatch.setattr(update, "UPDATED", None)
    monkeypatch.setattr(update, "_checked", None)
    st = {"served": {"version": "0.2.9", "url": "u", "sha_url": "s", "notes": "- faster"}, "calls": 0}

    def latest(timeout):
        st["calls"] += 1
        if isinstance(st["served"], Exception):
            raise st["served"]
        return st["served"]
    monkeypatch.setattr(update, "latest", latest)
    return st


def test_a_newer_release_is_only_offered_until_the_user_says_yes(monkeypatch, tmp_path, offering):
    exe = tmp_path / "sks-dl"
    monkeypatch.setattr(update.sys, "executable", str(exe))
    got = []
    monkeypatch.setattr(update, "install", lambda info, path: got.append((info["version"], path)))
    assert update.check()["version"] == "0.2.9" and got == [] and update.UPDATED is None  # found, not downloaded
    update.apply(update.AVAILABLE)  # the pop-up's "Update"
    assert got == [("0.2.9", exe)] and update.UPDATED == "0.2.9" and update.AVAILABLE is None
    assert update.check() is None  # installed: runs from the next start, not offered again


def test_each_opening_asks_again_after_a_no(monkeypatch, offering):
    assert update.check()["version"] == "0.2.9"  # the user says "Not now"
    assert update.check()["version"] == "0.2.9" and offering["calls"] == 1  # a reload at once: no new request
    monkeypatch.setattr(update, "CHECK_TTL", 0.0)
    offering["served"] = {"version": "0.3.0", "url": "u", "sha_url": "s"}
    assert update.check()["version"] == "0.3.0" and offering["calls"] == 2  # the next opening asks GitHub again


def test_nothing_is_offered_when_up_to_date_offline_or_not_self_updating(monkeypatch, offering):
    offering["served"] = {"version": "0.2.3", "url": "u", "sha_url": "s"}
    assert update.check() is None
    monkeypatch.setattr(update, "CHECK_TTL", 0.0)
    offering["served"] = OSError("offline")
    assert update.check() is None  # says so, changes nothing, raises nothing
    monkeypatch.setattr(update, "ENABLED", False)  # from source, a local build, --no-update
    offering["served"] = {"version": "0.9.0", "url": "u", "sha_url": "s"}
    assert update.check() is None and offering["calls"] == 2


def test_release_notes_excerpt():
    notes = "<!-- generated -->\r\n## What's new\r\n\r\n" + "\n".join(f"- change {i}" for i in range(30))
    text, cut = update.notes_excerpt(notes, lines=5)
    assert text.splitlines() == ["## What's new", "", "- change 0", "- change 1", "- change 2"] and cut
    assert update.notes_excerpt("- one\n- two") == ("- one\n- two", False)
    assert update.notes_excerpt("") == ("", False)
