import json

import numpy as np
import pytest

from skysqueezer import projection as P
from skysqueezer.sources.cds import output


def test_cerra_corners_match_the_published_grid():
    # corners of the 1069 x 1069 CERRA grid (cell edges) as gdalinfo reports them for a CERRA file
    p = P.KNOWN["reanalysis-cerra"]
    h = 1069 * 5500 / 2
    expect = {(-h, h): (63.7662, -58.1813), (-h, -h): (20.2643, -17.5002),
              (h, h): (63.7662, 74.1813), (h, -h): (20.2643, 33.5002), (0, 0): (50.0, 8.0)}
    for (x, y), (la, lo) in expect.items():
        lat, lon = P.lcc_inverse(p, x, y)
        assert float(lat) == pytest.approx(la, abs=1e-3)
        assert float(lon) == pytest.approx(lo, abs=1e-3)


def test_lcc_round_trip_two_parallels():
    p = {"kind": "lcc", "lat0": 72.0, "lon0": -36.0, "lat1": 60.0, "lat2": 80.0, "R": P.R_GRIB}
    lat, lon = np.array([55.0, 70.0, 85.0]), np.array([-60.0, -36.0, 10.0])
    x, y = P.lcc_forward(p, lat, lon)
    la, lo = P.lcc_inverse(p, x, y)
    np.testing.assert_allclose(la, lat, atol=1e-9)
    np.testing.assert_allclose(lo, lon, atol=1e-9)


def test_known_cerra_has_its_outline():
    p = P.known("reanalysis-cerra-single-levels")
    assert p["kind"] == "lcc" and len(p["outline"]) == 4 * P.OUTLINE_STEPS
    lats = [a for a, _ in p["outline"]]
    assert min(lats) == pytest.approx(20.26, abs=0.05) and max(lats) > 63.7
    assert P.known("reanalysis-era5-single-levels") is None


def test_box_outline_keeps_sides_and_crosses_180():
    ring = P.box_outline(40, 170, 50, -170, k=4)
    lons = [b for _, b in ring]
    assert min(lons) == 170 and max(lons) == 190  # east of 180 kept increasing
    assert {a for a, _ in ring} == {40, 42.5, 45, 47.5, 50}


def test_regular_grid_global_or_regional():
    assert P.from_grid("regular", np.arange(90, -90.25, -0.25), np.arange(0, 360, 0.25)) == {"kind": "latlon"}
    p = P.from_grid("regular", np.arange(72, 33.9, -0.1), np.arange(-25, 45.05, 0.1))
    assert p["kind"] == "latlon" and p["outline"]
    lats, lons = zip(*p["outline"])
    assert min(lats) == pytest.approx(34, abs=0.01) and max(lons) == pytest.approx(45, abs=0.01)


def test_curvilinear_grid_from_grib_attrs():
    p0 = P.KNOWN["reanalysis-cerra"]
    xs = np.linspace(-1e6, 1e6, 5)
    x, y = np.meshgrid(xs, xs)
    lat, lon = P.lcc_inverse(p0, x, y)
    attrs = {"grid_type": "lambert", "LaDInDegrees": 50.0, "LoVInDegrees": 8.0,
             "Latin1InDegrees": 50.0, "Latin2InDegrees": 50.0}
    p = P.from_grid("curvilinear", lat, lon, attrs)
    assert p["kind"] == "lcc" and p["lon0"] == 8.0
    np.testing.assert_allclose(p["domain"], [-1e6, -1e6, 1e6, 1e6], atol=1.0)
    # parameters unknown: plate carrée with the grid's border
    q = P.from_grid("curvilinear", lat, lon, {"grid_type": "projected"})
    assert q["kind"] == "latlon" and len(q["outline"]) > 4
    json.dumps(p), json.dumps(q)  # sent to the browser as is


def test_dataset_projection_from_cached_grid(tmp_path, monkeypatch):
    monkeypatch.setattr(output, "cache_dir", lambda: tmp_path)
    assert output.dataset_projection("reanalysis-era5-land") == {"kind": "latlon"}
    assert output.dataset_projection("reanalysis-cerra-pressure-levels")["kind"] == "lcc"
    p0 = P.KNOWN["reanalysis-cerra"]
    xs = np.linspace(-1e6, 1e6, 4)
    lat, lon = P.lcc_inverse(p0, *np.meshgrid(xs, xs))
    attrs = {"grid_type": "lambert", "LaDInDegrees": 72.0, "LoVInDegrees": -36.0,
             "Latin1InDegrees": 72.0, "Latin2InDegrees": 72.0}
    path = output._grid_path("reanalysis-carra-single-levels", None)
    path.parent.mkdir(parents=True)
    np.savez(path, kind="curvilinear", lat=lat, lon=lon, attrs=json.dumps(attrs))
    p = output.dataset_projection("reanalysis-carra-single-levels")
    assert p["kind"] == "lcc" and p["lon0"] == -36.0 and p["lat1"] == 72.0
