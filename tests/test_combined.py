"""Combined jobs: several datasets downloaded into one store (one Icechunk repository, one export)."""

import numpy as np
import pytest
import xarray as xr
import zarr
from test_engine import times

from skysqueezer import store
from skysqueezer.job import (
    AreaSpec,
    DownloadSpec,
    JobSpec,
    OutputSpec,
    PartSpec,
    TimeSpec,
    resolve_names,
)
from skysqueezer.runner import create_job, run_foreground

BOX = {"west": -60, "east": 60, "south": -40, "north": 50}


def combined(fake, out, parts, **kw):
    base = {"dataset": "fake", "dataset_url": fake.url, "variables": ["t2m"],
            "time": TimeSpec("2019-11-10", "2019-11-20", "none"), "area": AreaSpec("bbox", **BOX),
            "output": OutputSpec(directory=str(out), name="c", keepbits=None, export_zarr=True, keep_icechunk=True),
            "download": DownloadSpec(key="test", connections=4, min_free_gb=0.1),
            "parts": resolve_names(parts)}
    base.update(kw)
    return JobSpec(**base)


def two_parts(fake):
    # the same fake Zarr under two names: the second part also asks for t2m, so its copy is renamed
    return [PartSpec("fake-single", dataset_url=fake.url, variables=["t2m", "lsm"]),
            PartSpec("era5-pressure-levels", dataset_url=fake.url, variables=["t", "t2m"], levels=[850, 500])]


def expected(fake, name, start, end, level=None):
    lat_i = np.where((fake.lat >= BOX["south"]) & (fake.lat <= BOX["north"]))[0]
    lon180 = (fake.lon + 180) % 360 - 180
    lon_i = np.where((lon180 >= BOX["west"]) & (lon180 <= BOX["east"]))[0]
    lon_i = lon_i[np.argsort(lon180[lon_i])]
    a = fake.data[name]
    if name == "lsm":
        return a[lat_i][:, lon_i]
    tt = times(fake)
    a = a[np.where((tt >= start) & (tt < end))[0]]
    if level is not None:
        a = a[:, level]
    return a[:, lat_i][:, :, lon_i]


def test_resolve_names_tags_clashes():
    parts = resolve_names([PartSpec("era5-single-levels-atmosphere", variables=["z", "t2m"]),
                           PartSpec("era5-pressure-levels", variables=["z", "t"])])
    assert parts[0].rename == {}
    assert parts[1].rename == {"z": "z_pressure_levels"}
    with pytest.raises(ValueError):
        resolve_names([PartSpec("a", variables=["x"]), PartSpec("b", variables=["y"], rename={"y": "x"})])


def test_part_spec_and_roundtrip():
    s = JobSpec(parts=[PartSpec("a", variables=["x"], stats={"x": ["max"]}), PartSpec("b", variables=["y"])])
    back = JobSpec.from_dict(s.to_dict())
    assert back.combined and [p.dataset for p in back.parts] == ["a", "b"]
    p = back.part_spec(0)
    assert (p.dataset, p.variables, p.time.stats, p.parts) == ("a", ["x"], {"x": ["max"]}, [])


def test_two_datasets_one_store(home, fake_edh):
    s = combined(fake_edh, home / "out", two_parts(fake_edh))
    job = create_job(s)
    assert run_foreground(job) == "completed"
    for path in (s.zarr_path, None):  # the export and the repository hold the same
        if path is None:
            repo = store.open_repo(s.icechunk_path)
            ds = xr.open_zarr(repo.readonly_session("main").store, consolidated=False)
        else:
            ds = xr.open_zarr(path, consolidated=True)
        assert set(ds.data_vars) == {"t2m", "lsm", "t", "t2m_pressure_levels"}
        np.testing.assert_array_equal(ds.t2m.values, expected(fake_edh, "t2m", "2019-11-10", "2019-11-21"))
        np.testing.assert_array_equal(ds.t2m_pressure_levels.values, ds.t2m.values)
        np.testing.assert_array_equal(ds.lsm.values, expected(fake_edh, "lsm", None, None))
        np.testing.assert_array_equal(ds.t.values[:, 0], expected(fake_edh, "t", "2019-11-10", "2019-11-21", 1))
        np.testing.assert_array_equal(ds.t.values[:, 1], expected(fake_edh, "t", "2019-11-10", "2019-11-21", 2))
        assert ds.isobaricInhPa.values.tolist() == [850, 500]
    assert ds.attrs["edh_status"] == "complete"
    assert [d["dataset"] for d in ds.attrs["source_datasets"]] == ["fake-single", "era5-pressure-levels"]
    assert ds.t.attrs["source_dataset"] == "era5-pressure-levels"
    assert ds.t2m_pressure_levels.attrs["source_variable"] == "t2m"
    assert len(ds.attrs["edh_job"]["parts"]) == 2


def test_resumes_across_parts(home, fake_edh, monkeypatch):
    s = combined(fake_edh, home / "out", two_parts(fake_edh), output=OutputSpec(
        directory=str(home / "out"), name="r", keepbits=None, export_zarr=False, keep_icechunk=True))
    job = create_job(s)
    real = store.add_part
    monkeypatch.setattr(store, "add_part", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("crash")))
    assert run_foreground(job) == "failed"  # the first part is in, the second never started
    monkeypatch.setattr(store, "add_part", real)
    assert run_foreground(job) == "completed"
    assert not s.zarr_path.exists()  # Icechunk only
    repo = store.open_repo(s.icechunk_path)
    g = zarr.open_group(repo.readonly_session("main").store, mode="r")
    np.testing.assert_array_equal(g["t2m"][:], expected(fake_edh, "t2m", "2019-11-10", "2019-11-21"))
    np.testing.assert_array_equal(g["t"][:, 1], expected(fake_edh, "t", "2019-11-10", "2019-11-21", 2))
    assert g.attrs["edh_parts_added"][job.name] == [1]


def test_extend_combined_store(home, fake_edh):
    s1 = combined(fake_edh, home / "out", two_parts(fake_edh), time=TimeSpec("2019-11-10", "2019-11-14", "none"))
    assert run_foreground(create_job(s1)) == "completed"
    out = s1.output
    s2 = combined(fake_edh, home / "out", two_parts(fake_edh), time=TimeSpec("2019-11-15", "2019-11-18", "none"),
                  output=OutputSpec(directory=out.directory, name="c", keepbits=None, target_mode="extend",
                                    target_store=str(s1.icechunk_path), export_zarr=True))
    assert run_foreground(create_job(s2)) == "completed"
    ds = xr.open_zarr(s1.zarr_path)
    assert len(ds.valid_time) == 9 * 24
    np.testing.assert_array_equal(ds.t2m.values, expected(fake_edh, "t2m", "2019-11-10", "2019-11-19"))
    np.testing.assert_array_equal(ds.t.values[:, 1], expected(fake_edh, "t", "2019-11-10", "2019-11-19", 2))


def test_daily_combined_with_stats(home, fake_edh):
    parts = [PartSpec("fake-single", dataset_url=fake_edh.url, variables=["t2m"], stats={"t2m": ["mean", "max"]}),
             PartSpec("fake-pl", dataset_url=fake_edh.url, variables=["t"], levels=[850])]
    s = combined(fake_edh, home / "out", parts, time=TimeSpec("2019-11-12", "2019-11-15", "day"))
    assert run_foreground(create_job(s)) == "completed"
    ds = xr.open_zarr(s.zarr_path)
    assert set(ds.data_vars) == {"t2m_mean", "t2m_max", "t"}
    assert ds.t.shape[:2] == (4, 1)


def test_parts_compatible_rejects_clash_and_levels(home, fake_edh):
    from skysqueezer import catalog, keys
    from skysqueezer.planner import Plan

    k = keys.get_key("test")
    info = {"id": "fake", "title": "fake", "url": fake_edh.url}
    ds = catalog.load_dataset(fake_edh.url, k.secret, info=info)
    a = combined(fake_edh, home / "o", [PartSpec("a", dataset_url=fake_edh.url, variables=["t"], levels=[850]),
                                        PartSpec("b", dataset_url=fake_edh.url, variables=["t"], levels=[500])])
    plans = [Plan(a.part_spec(i), ds) for i in range(2)]
    assert "different levels" in store.parts_compatible(plans)
    plans[1].spec.rename = {}
    b = JobSpec(dataset="b", dataset_url=fake_edh.url, variables=["t2m"], time=a.time, area=a.area, output=a.output)
    c = JobSpec(dataset="c", dataset_url=fake_edh.url, variables=["t2m"], time=a.time, area=a.area, output=a.output)
    assert "comes from both" in store.parts_compatible([Plan(b, ds), Plan(c, ds)])


def test_service_plans_and_checks_combined(home, fake_edh):
    from skysqueezer import service

    info = {"id": "fake", "title": "fake", "url": fake_edh.url}
    service.dataset_load(info, "test")
    s = combined(fake_edh, home / "out", two_parts(fake_edh))
    d = s.to_dict()
    for p in d["parts"]:
        p["rename"] = {}  # the service resolves clashes itself
    res = service.plan(d, connections=4, follow=True)
    assert res["ok"], res
    assert res["summary"]["outputs"] == ["t2m", "lsm", "t", "t2m_pressure_levels"]
    assert [p["dataset"] for p in res["parts"]] == ["fake-single", "era5-pressure-levels"]
    assert res["summary"]["requests"] == sum(p["requests"] for p in res["parts"])
    assert {x["name"] for x in res["struct"]["data"]} == {"t2m", "lsm", "t", "t2m_pressure_levels"}
    assert "isobaricInhPa" in {c["name"] for c in res["struct"]["coords"]}

    # the same dataset twice is one part; one part left is a plain job
    one = service._combined(JobSpec.from_dict({**d, "parts": [
        {"dataset": "x", "dataset_url": fake_edh.url, "variables": ["t2m"]},
        {"dataset": "x", "dataset_url": fake_edh.url, "variables": ["tp", "t2m"]}]}))
    assert one.parts == [] and one.variables == ["t2m", "tp"] and one.dataset == "x"

    started = service.job_start(d)
    import time

    from skysqueezer.runner import resolve, status
    t0 = time.time()
    while status(resolve(started["id"])).get("status") not in ("completed", "failed") and time.time() - t0 < 60:
        time.sleep(0.3)
    st = status(resolve(started["id"]))
    assert st["status"] == "completed", st.get("error")
    assert st["spec"]["parts"][1]["rename"] == {"t2m": "t2m_pressure_levels"}


def test_service_refuses_cds_combined(home):
    from skysqueezer import service

    res = service.plan({"source": "cds", "parts": [{"dataset": "a", "variables": ["x"]}]}, 1, False)
    assert not res["ok"] and "Earth Data Hub" in res["error"]


def test_part_with_its_own_period_leaves_the_rest_empty(home, fake_edh):
    # the second dataset "starts later": its steps before 2019-11-15 stay NaN, the store keeps the whole axis
    parts = [PartSpec("a", dataset_url=fake_edh.url, variables=["t2m"]),
             PartSpec("b", dataset_url=fake_edh.url, variables=["tp"], start="2019-11-15", end="2019-11-18")]
    s = combined(fake_edh, home / "out", parts, time=TimeSpec("2019-11-10", "2019-11-20", "none"))
    assert run_foreground(create_job(s)) == "completed"
    ds = xr.open_zarr(s.zarr_path)
    assert len(ds.valid_time) == 11 * 24
    np.testing.assert_array_equal(ds.t2m.values, expected(fake_edh, "t2m", "2019-11-10", "2019-11-21"))
    k0, k1 = 5 * 24, 9 * 24
    assert np.isnan(ds.tp.values[:k0]).all() and np.isnan(ds.tp.values[k1:]).all()
    np.testing.assert_array_equal(ds.tp.values[k0:k1], expected(fake_edh, "tp", "2019-11-15", "2019-11-19"))


def test_periods_with_a_gap_are_refused(home, fake_edh):
    from skysqueezer import catalog, keys
    from skysqueezer.planner import Plan

    ds = catalog.load_dataset(fake_edh.url, keys.get_key("test").secret,
                              info={"id": "fake", "title": "fake", "url": fake_edh.url})
    s = combined(fake_edh, home / "o", [
        PartSpec("a", dataset_url=fake_edh.url, variables=["t2m"], end="2019-11-12"),
        PartSpec("b", dataset_url=fake_edh.url, variables=["tp"], start="2019-11-16")])
    assert "gap" in store.parts_compatible([Plan(s.part_spec(i), ds) for i in range(2)])
    # touching periods are fine
    s = combined(fake_edh, home / "o", [
        PartSpec("a", dataset_url=fake_edh.url, variables=["t2m"], end="2019-11-12"),
        PartSpec("b", dataset_url=fake_edh.url, variables=["tp"], start="2019-11-13")])
    plans = [Plan(s.part_spec(i), ds) for i in range(2)]
    assert store.parts_compatible(plans) is None
    assert plans[1].axis_offset == 3 * 24 and plans[0].out_periods == 11 * 24


def test_extend_combined_with_a_shorter_part(home, fake_edh):
    parts = lambda: [PartSpec("a", dataset_url=fake_edh.url, variables=["t2m"]),  # noqa: E731
                     PartSpec("b", dataset_url=fake_edh.url, variables=["tp"], start="2019-11-12")]
    s1 = combined(fake_edh, home / "out", parts(), time=TimeSpec("2019-11-10", "2019-11-14", "none"))
    assert run_foreground(create_job(s1)) == "completed"
    s2 = combined(fake_edh, home / "out", [PartSpec("a", dataset_url=fake_edh.url, variables=["t2m"]),
                                           PartSpec("b", dataset_url=fake_edh.url, variables=["tp"])],
                  time=TimeSpec("2019-11-15", "2019-11-16", "none"),
                  output=OutputSpec(directory=s1.output.directory, name="c", keepbits=None, target_mode="extend",
                                    target_store=str(s1.icechunk_path), export_zarr=True))
    assert run_foreground(create_job(s2)) == "completed"
    ds = xr.open_zarr(s1.zarr_path)
    assert len(ds.valid_time) == 7 * 24
    assert np.isnan(ds.tp.values[:48]).all()
    np.testing.assert_array_equal(ds.tp.values[48:], expected(fake_edh, "tp", "2019-11-12", "2019-11-17"))


def test_sample_of_combined_job_samples_each_dataset(home, fake_edh):
    """The sample of a combined job uses each part's own variables, not the job's top-level list (which the
    form fills from the dataset being edited, so it may name variables the main dataset does not have)."""
    from skysqueezer import sample, service

    service.dataset_load({"id": "fake", "title": "fake", "url": fake_edh.url}, "test")
    s = combined(fake_edh, home / "out", two_parts(fake_edh), variables=["no_such_variable"])
    d = s.to_dict()
    for p in d["parts"]:
        p["rename"] = {}
    seen = []
    res = service.sample_run(d, "test", n=6, emit=seen.append)
    assert res == {"n": 6}
    assert [e["i"] for e in seen] == [1, 2, 3, 4, 5, 6] and {e["total"] for e in seen} == {6}
    smp = sample.last_result(fake_edh.url)
    assert smp and smp["requests"] == 3  # the last part's share (both parts read the same fake Zarr)
