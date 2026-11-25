"""Jobs shared by several accounts on one server: a colleague sees the job and resumes it with their own key."""

import json
import os
import stat
import threading
import time

from skysqueezer import engine, keys, paths, runner, service
from skysqueezer.job import AreaSpec, DownloadSpec, JobSpec, OutputSpec, TimeSpec
from skysqueezer.util import write_json_atomic


def _spec(fake, out, name="s", key="test"):
    return JobSpec(dataset="fake", dataset_url=fake.url, variables=["t2m", "tp"],
                   time=TimeSpec("2019-11-05", "2019-12-15", "none"), area=AreaSpec("global"),
                   output=OutputSpec(directory=str(out), name=name, keepbits=None),
                   download=DownloadSpec(key=key, connections=3, min_free_gb=0.1))


def test_shared_jobs_folder_from_env_user_and_system_config(home, monkeypatch):
    assert paths.shared_jobs_dir() is None and paths.jobs_dir() == paths.data_dir() / "jobs"
    paths.SYSTEM_CONFIG.write_text(json.dumps({"jobs_dir": str(home / "sys-jobs")}))
    assert paths.jobs_dir() == home / "sys-jobs"
    assert stat.S_IMODE((home / "sys-jobs").stat().st_mode) & 0o2070 == 0o2070  # group rwx + setgid
    service.jobs_folder_set(str(home / "mine"))  # this account's choice wins over the admin's
    assert paths.jobs_dir() == home / "mine" and service.jobs_folder()["shared"]
    monkeypatch.setenv("SKS_DL_JOBS_DIR", str(home / "env"))
    assert paths.jobs_dir() == home / "env"
    monkeypatch.delenv("SKS_DL_JOBS_DIR")
    service.jobs_folder_set("")
    assert paths.jobs_dir() == home / "sys-jobs"


def test_files_in_a_shared_folder_are_group_writable_and_others_stay_private(home, monkeypatch):
    monkeypatch.setenv("SKS_DL_JOBS_DIR", str(home / "shared"))
    old = os.umask(0o002)
    try:
        write_json_atomic(paths.jobs_dir() / "x" / "state.json", {})
        write_json_atomic(home / "private.json", {})
        keys.add_key("other", "secret", quota=1)
    finally:
        os.umask(old)
    assert stat.S_IMODE((paths.jobs_dir() / "x" / "state.json").stat().st_mode) == 0o664
    assert stat.S_IMODE((home / "private.json").stat().st_mode) == 0o600
    assert stat.S_IMODE(keys._path().stat().st_mode) == 0o600  # API keys never leave their account


def test_job_records_absolute_folders_and_who_started_it(home, fake_edh, monkeypatch):
    monkeypatch.setenv("HOME", str(home))
    s = _spec(fake_edh, "~/out")
    s.download.spool_dir = "~/spool"
    d = runner.create_job(s)
    meta = json.loads((d / "job.json").read_text())
    assert meta["spec"]["output"]["directory"] == str(home / "out")
    assert meta["spec"]["download"]["spool_dir"] == str(home / "spool")
    assert meta["created_by"] == runner.whoami() and runner.status(d)["created_by"] == runner.whoami()


def test_a_process_of_another_account_counts_as_alive(monkeypatch):
    def kill(pid, sig):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(os, "kill", kill)
    assert runner._pid_exists(12345)


def test_resume_uses_my_key_when_the_jobs_key_is_not_mine(home, fake_edh):
    d = runner.create_job(_spec(fake_edh, home / "out", key="colleagues-key"))
    k = service._resume_key(runner.status(d)["spec"], None)
    assert k.name == "test"  # this account's default
    keys.add_key("second", "test-key", quota=10)
    assert service._resume_key(runner.status(d)["spec"], "second").name == "second"
    service._set_job_key(d, keys.get_key("second"))
    meta = json.loads((d / "job.json").read_text())
    assert meta["spec"]["download"]["key"] == "second"
    assert meta["runs"][-1]["by"] == runner.whoami() and meta["runs"][-1]["key"] == "second"
    assert "secret" not in json.dumps(meta) and "test-key" not in json.dumps(meta)


def test_worker_pauses_when_asked_through_control_file(home, fake_edh, monkeypatch):
    """A worker of another account cannot be signalled: it must notice the pause in control.json."""
    d = runner.create_job(_spec(fake_edh, home / "out"))
    orig = engine.Engine._process_unit
    calls = {"n": 0}

    def slow(self, u, pool):
        orig(self, u, pool)
        calls["n"] += 1
        if calls["n"] == 1:
            runner.set_control(d, action="pause")  # what runner.stop does when kill() is not allowed
            time.sleep(3)

    monkeypatch.setattr(engine.Engine, "_process_unit", slow)
    assert runner.run_foreground(d) == "paused"
    st = runner.status(d)
    assert st["status"] == "paused" and len(st["units_done"]) < st["units_total"]


def test_takeover_pauses_the_running_job_then_resumes_it(home, fake_edh, monkeypatch):
    d = runner.create_job(_spec(fake_edh, home / "out"))
    resumed = threading.Event()
    state = {"alive": True}
    monkeypatch.setattr(service, "TAKEOVER_WAIT", 20)
    real_status = runner.status

    def status(job_dir):
        s = real_status(job_dir)
        s["alive"] = state["alive"]
        return s

    stops = []
    monkeypatch.setattr(runner, "status", status)
    monkeypatch.setattr(runner, "stop", lambda job_dir, action="pause", wait=0: stops.append(action))
    monkeypatch.setattr(runner, "launch", lambda job_dir: resumed.set() or 4242)
    assert service.job_takeover(d.name, "test") == {"waiting": True}
    assert stops == ["pause"]
    assert service.jobs_list()[0]["takeover"]["key"] == "test"
    state["alive"] = False  # the worker has paused
    assert resumed.wait(10)
    time.sleep(0.2)
    assert "takeover" not in service.jobs_list()[0]


def test_folder_check_writes_an_icechunk_repository(home):
    r = service.folder_check(str(home / "nas" / "dsipdata"))
    assert r["ok"], r
    assert [c["name"] for c in r["checks"]][:2] == ["free space", "writable"]
    assert not any(p.name.startswith(".sks-check-") for p in (home / "nas" / "dsipdata").iterdir())
