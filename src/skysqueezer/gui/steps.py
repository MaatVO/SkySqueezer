"""The one-line summary and state of each New job step, shown on its folded row: pure, so testable without a browser.

A step is ``done`` (set and valid), ``defaults`` (valid, still as the app started it), ``todo`` (required and not set),
``pending`` (being loaded) or ``error`` (set, but the job cannot run like this).
"""

from datetime import date

from ..job import FREQS

TITLES = {1: "Dataset", 2: "Variables and levels", 3: "Time", 4: "Area", 5: "Output"}
REQUIRED = {1, 2, 3, 4}
SOURCES = {"edh": "Earth Data Hub", "cds": "Climate Data Store"}
FORMATS = {"zarr": "Zarr", "both": "Zarr + Icechunk", "icechunk": "Icechunk"}
TIME_KEYS = ("start", "end", "start_hour", "end_hour", "freq", "hours", "tz_offset")
AREA_KEYS = ("mode", "west", "south", "east", "north", "points", "lon_convention", "grid", "grid_custom")
OUTPUT_KEYS = ("directory", "name", "out_format", "target_mode", "target_store", "extend_direction", "lossless",
               "keepbits", "chunk_layout", "dtype", "compressor", "clevel", "shuffle", "sharding", "extra_attrs")
STATUS = {"done": ("Done", "ok"), "defaults": ("Defaults", "muted"), "todo": ("Empty", "muted"),
          "pending": ("Loading", "muted"), "error": ("Check", "warn")}


def _num(v) -> str:
    try:
        return f"{float(v):g}"
    except (TypeError, ValueError):
        return "?"


def _hour(v) -> str:
    try:
        return f"{int(v):02d}:00"
    except (TypeError, ValueError):
        return "--:--"


def _same(f: dict, defaults: dict, keys) -> bool:
    return all(f.get(k) == defaults.get(k) for k in keys)


def dataset_step(f: dict, title: str | None, loaded: bool, failed: bool, has_key: bool) -> tuple[str, str]:
    src = SOURCES.get(f.get("source"), f.get("source") or "")
    if failed:
        return "error", f"{src} · {title or f.get('dataset')} · could not be loaded"
    if loaded:
        return "done", f"{src} · {title or f.get('dataset')}"
    if title and not has_key:
        return "error", f"{src} · {title} · add an API key in Keys to load it"
    if title:
        return "pending", f"{src} · {title}"
    return "todo", "Pick a source and a dataset"


def variables_step(f: dict) -> tuple[str, str]:
    names = list(f.get("variables") or [])
    if not names:
        return "todo", "Choose what to download"
    shown = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
    levels = f.get("levels") or []
    lv = f" · {len(levels)} level{'s' if len(levels) != 1 else ''}" if levels else ""
    return "done", f"{len(names)} variable{'s' if len(names) != 1 else ''}{lv} · {shown}"


def time_step(f: dict, defaults: dict) -> tuple[str, str]:
    try:
        first, last = date.fromisoformat(str(f.get("start"))), date.fromisoformat(str(f.get("end")))
    except ValueError:
        return "error", "Enter the first and last day as YYYY-MM-DD"
    if (last, int(f.get("end_hour") or 0)) < (first, int(f.get("start_hour") or 0)):
        return "error", "The end is before the start"
    freq = f.get("freq") or "none"
    step = f"every {f.get('hours')} hours" if freq == "hours" else FREQS.get(freq, freq)
    tz = int(f.get("tz_offset") or 0)
    zone = f" · UTC{tz:+d}" if freq != "none" and tz else ""
    line = f"{first} {_hour(f.get('start_hour'))} → {last} {_hour(f.get('end_hour'))} · {step}{zone}"
    return ("defaults" if _same(f, defaults, TIME_KEYS) else "done"), line


def area_step(f: dict, defaults: dict) -> tuple[str, str]:
    mode = f.get("mode")
    if mode == "global":
        line = "Global"
    elif mode == "points":
        pts = [x for x in (f.get("points") or "").splitlines() if x.strip() and not x.strip().startswith("#")]
        if not pts:
            return "todo", "Add at least one point: name, lat, lon"
        line = f"{len(pts)} point{'s' if len(pts) != 1 else ''}"
    else:
        try:
            if float(f.get("north")) <= float(f.get("south")):
                return "error", "North must be above south"
        except (TypeError, ValueError):
            return "error", "Enter all four sides of the box"
        line = "Box · N {} · W {} · S {} · E {}".format(*(_num(f.get(k)) for k in ("north", "west", "south", "east")))
    if f.get("source") == "cds" and f.get("grid") not in (None, "native"):
        line += f" · grid {_num(f.get('grid_custom') if f.get('grid') == 'custom' else f.get('grid'))}°"
    return ("defaults" if _same(f, defaults, AREA_KEYS) else "done"), line


def output_step(f: dict, defaults: dict) -> tuple[str, str]:
    if f.get("target_mode") == "extend":
        store = (f.get("target_store") or "").strip()
        if not store:
            return "error", "Enter the Icechunk store to extend"
        return "done", f"Extend {store} {f.get('extend_direction', 'forward')}"
    path = f"{(f.get('directory') or '').rstrip('/')}/{f.get('name') or ''}"
    line = f"New store · {FORMATS.get(f.get('out_format'), f.get('out_format'))} · {path}"
    return ("defaults" if _same(f, defaults, OUTPUT_KEYS) else "done"), line


def step_states(f: dict, defaults: dict, *, title: str | None = None, loaded: bool = False, failed: bool = False,
                has_key: bool = True) -> dict[int, tuple[str, str]]:
    """Step number -> (state, line). ``title``: the dataset chosen (shown before it loads)."""
    return {1: dataset_step(f, title, loaded, failed, has_key), 2: variables_step(f), 3: time_step(f, defaults),
            4: area_step(f, defaults), 5: output_step(f, defaults)}
