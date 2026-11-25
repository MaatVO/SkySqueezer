"""The map projection of a dataset's grid, for the area map: what the browser needs to draw the map in the
grid's own projection, and the outline of a regional domain.

Two kinds:

* ``latlon``: a regular latitude/longitude grid (ERA5, ERA5-Land, Earth Data Hub): plate carrée, where a
  latitude/longitude box is a rectangle, as the grid is;
* ``lcc``: Lambert conformal conic on a sphere (CERRA; CARRA and other projected grids once a file has told
  their parameters).

A projected grid whose parameters are not known is shown in plate carrée with its outline. Projected
coordinates are metres; the formulas are Snyder's (Map Projections: A Working Manual, 1987), spherical form.
"""

from __future__ import annotations

import math

import numpy as np

R_GRIB = 6371229.0  # the sphere of GRIB edition 2 shape 6, CERRA's

# grids known before any file arrives: dataset id prefix -> projection (verified against the CERRA user guide
# and the corner coordinates of its 1069 x 1069 grid, 5.5 km, centred on the projection origin)
_CERRA_HALF = 1069 * 5500.0 / 2
KNOWN = {
    "reanalysis-cerra": {"kind": "lcc", "lat0": 50.0, "lon0": 8.0, "lat1": 50.0, "lat2": 50.0, "R": R_GRIB,
                         "domain": [-_CERRA_HALF, -_CERRA_HALF, _CERRA_HALF, _CERRA_HALF]},
}
OUTLINE_STEPS = 32  # points per side of a domain outline


def latlon(extent: list[float] | None = None) -> dict:
    """Plate carrée; ``extent`` ``[south, west, north, east]`` for a regional grid (its outline)."""
    p = {"kind": "latlon"}
    if extent is not None:
        s, w, n, e = extent
        p["outline"] = box_outline(s, w, n, e)
    return p


# ------------------------------------------------------------------ Lambert conformal conic (sphere)

def _lcc_consts(p: dict) -> tuple[float, float, float]:
    r = math.radians
    lat1, lat2, lat0 = r(p["lat1"]), r(p["lat2"]), r(p["lat0"])
    if abs(lat1 - lat2) < 1e-10:
        n = math.sin(lat1)
    else:
        n = (math.log(math.cos(lat1) / math.cos(lat2))
             / math.log(math.tan(math.pi / 4 + lat2 / 2) / math.tan(math.pi / 4 + lat1 / 2)))
    big_f = math.cos(lat1) * math.tan(math.pi / 4 + lat1 / 2) ** n / n
    rf = p.get("R", R_GRIB) * big_f
    rho0 = rf / math.tan(math.pi / 4 + lat0 / 2) ** n
    return n, rf, rho0


def lcc_forward(p: dict, lat, lon):
    """Latitude/longitude (degrees) -> x, y (metres)."""
    n, rf, rho0 = _lcc_consts(p)
    lat, lon = np.radians(np.asarray(lat, dtype="f8")), np.asarray(lon, dtype="f8")
    rho = rf / np.tan(np.pi / 4 + lat / 2) ** n
    theta = n * np.radians((lon - p["lon0"] + 180.0) % 360.0 - 180.0)
    return rho * np.sin(theta), rho0 - rho * np.cos(theta)


def lcc_inverse(p: dict, x, y):
    """x, y (metres) -> latitude, longitude (degrees, longitude in −180 … 180)."""
    n, rf, rho0 = _lcc_consts(p)
    x, y = np.asarray(x, dtype="f8"), np.asarray(y, dtype="f8")
    sgn = 1.0 if n > 0 else -1.0
    rho = sgn * np.hypot(x, rho0 - y)
    theta = np.arctan2(sgn * x, sgn * (rho0 - y))
    lat = np.degrees(2 * np.arctan((rf / rho) ** (1 / n)) - np.pi / 2)
    lon = (np.degrees(theta / n) + p["lon0"] + 180.0) % 360.0 - 180.0
    return lat, lon


def _rect_outline(x0, y0, x1, y1, k: int = OUTLINE_STEPS) -> tuple[np.ndarray, np.ndarray]:
    t = np.linspace(0.0, 1.0, k, endpoint=False)
    xs = np.concatenate([x0 + (x1 - x0) * t, np.full(k, x1), x1 - (x1 - x0) * t, np.full(k, x0)])
    ys = np.concatenate([np.full(k, y0), y0 + (y1 - y0) * t, np.full(k, y1), y1 - (y1 - y0) * t])
    return xs, ys


def box_outline(s: float, w: float, n: float, e: float, k: int = OUTLINE_STEPS) -> list[list[float]]:
    """A latitude/longitude box as a closed ring of ``[lat, lon]``, its sides divided so that it stays a box
    (parallels and meridians) in any projection. ``e < w`` crosses the 180° meridian."""
    if e < w:
        e += 360.0
    lons, lats = _rect_outline(w, s, e, n, k)
    return [[round(float(a), 4), round(float(b), 4)] for a, b in zip(lats, lons)]


def lcc_outline(p: dict) -> list[list[float]]:
    """The outline of an LCC domain as ``[lat, lon]`` points."""
    lat, lon = lcc_inverse(p, *_rect_outline(*p["domain"]))
    return [[round(float(a), 4), round(float(b), 4)] for a, b in zip(lat, lon)]


# ------------------------------------------------------------------ from a grid

def from_grid_attrs(attrs: dict) -> dict | None:
    """LCC parameters from a grid's projection attributes: GRIB keys (``LaDInDegrees`` ...) or a CF
    ``grid_mapping`` (``lambert_conformal_conic``). None for anything else."""
    a = attrs or {}
    if str(a.get("grid_type", "")).startswith("lambert") and "LoVInDegrees" in a:
        lad = float(a.get("LaDInDegrees", a.get("Latin1InDegrees", 0.0)))
        return {"kind": "lcc", "lat0": lad, "lon0": float(a["LoVInDegrees"]),
                "lat1": float(a.get("Latin1InDegrees", lad)), "lat2": float(a.get("Latin2InDegrees", lad)),
                "R": R_GRIB}
    if a.get("grid_mapping_name") == "lambert_conformal_conic":
        sp = np.atleast_1d(np.asarray(a.get("standard_parallel"), dtype="f8"))
        if not sp.size:
            return None
        lat0 = float(a.get("latitude_of_projection_origin", sp[0]))
        return {"kind": "lcc", "lat0": lat0, "lon0": float(a.get("longitude_of_central_meridian", 0.0)),
                "lat1": float(sp[0]), "lat2": float(sp[-1]), "R": float(a.get("earth_radius", R_GRIB))}
    return None


def _edge_ring(lat: np.ndarray, lon: np.ndarray, k: int = OUTLINE_STEPS) -> list[list[float]]:
    """The border of a 2-D grid of coordinates as ``[lat, lon]`` points."""
    ny, nx = lat.shape
    ii = np.linspace(0, ny - 1, k).round().astype(int)
    jj = np.linspace(0, nx - 1, k).round().astype(int)
    idx = ([(0, j) for j in jj] + [(i, nx - 1) for i in ii[1:]] + [(ny - 1, j) for j in jj[::-1][1:]]
           + [(i, 0) for i in ii[::-1][1:-1]])
    out = []
    for i, j in idx:
        la, lo = float(lat[i, j]), float(lon[i, j])
        out.append([round(la, 4), round((lo + 180.0) % 360.0 - 180.0, 4)])
    return out


def from_grid(kind: str, lat, lon, attrs: dict | None = None) -> dict:
    """The projection of a grid as delivered: regular -> plate carrée (outline if regional); curvilinear ->
    LCC when its parameters are known, else plate carrée with the domain's outline."""
    lat, lon = np.asarray(lat), np.asarray(lon)
    if kind == "regular" or lat.ndim == 1:
        return latlon(regional_extent(lat, lon))
    p = from_grid_attrs(attrs or {})
    if p is not None:
        x, y = lcc_forward(p, lat, lon)
        p["domain"] = [float(np.nanmin(x)), float(np.nanmin(y)), float(np.nanmax(x)), float(np.nanmax(y))]
        p["outline"] = lcc_outline(p)
        return p
    return {"kind": "latlon", "outline": _edge_ring(lat, lon)}


def regional_extent(lat, lon) -> list[float] | None:
    """``[south, west, north, east]`` of a regular grid, or None when it covers the globe."""
    lat = np.asarray(lat, dtype="f8")
    lon = np.asarray(lon, dtype="f8")
    if not lat.size or not lon.size:
        return None
    s, n = float(lat.min()), float(lat.max())
    step = float(np.median(np.abs(np.diff(lon)))) if lon.size > 1 else 0.0
    span = float(lon.max() - lon.min()) + step
    if span >= 359.0 and s <= -80.0 and n >= 80.0:
        return None
    w, e = (-180.0, 180.0) if span >= 359.0 else (float(lon[0]), float(lon[-1]))
    w = (w + 180.0) % 360.0 - 180.0 if span < 359.0 else w
    e = (e + 180.0) % 360.0 - 180.0 if span < 359.0 else e
    return [s, w, n, e]


def known(dataset: str) -> dict | None:
    """A projection known from the dataset id alone (with its outline), else None."""
    for prefix, p in KNOWN.items():
        if dataset.startswith(prefix):
            p = dict(p)
            p["outline"] = lcc_outline(p)
            return p
    return None
