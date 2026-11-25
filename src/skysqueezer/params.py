"""What a variable is, from the official source: the ECMWF Parameter Database (public, no key).

ERA5 variables carry their GRIB parameter id (``GRIB_paramId``); the database gives its name, short name, units and
a description. Answers are cached on disk for a long time (parameters rarely change) and a stale answer is used when
the database cannot be reached.
"""

import html
import json
import re
import time
import urllib.request

from .paths import cache_dir
from .util import read_json, write_json_atomic

API = "https://codes.ecmwf.int/parameter-database/api/v1"
PAGE = "https://codes.ecmwf.int/grib/param-db/{id}"
TTL = 60 * 24 * 3600
TIMEOUT = 15


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "skysqueezer", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


_LINK = re.compile(r"""<a\s[^>]*?href\s*=\s*(["'])(.*?)\1[^>]*>(.*?)</a\s*>""", re.IGNORECASE | re.DOTALL)


def _plain(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s)))


def paragraphs(description: str) -> list[list[dict]]:
    """The database's HTML description as paragraphs of text pieces and links (``{"text"}`` or ``{"text",
    "href"}``, https links only). Its markup is never passed on as HTML: it is data from another site."""
    out = []
    for para in re.split(r"(?i)(?:<br\s*/?>\s*){2,}|</p\s*>\s*<p[^>]*>|</?p[^>]*>", description or ""):
        para = re.sub(r"(?i)<br\s*/?>", " ", para)
        pieces, pos = [], 0
        for m in _LINK.finditer(para):
            if m.start() > pos:
                pieces.append({"text": _plain(para[pos:m.start()])})
            label, href = _plain(m.group(3)).strip(), html.unescape(m.group(2)).strip()
            pieces.append({"text": label or href, "href": href} if href.startswith("https://") else {"text": label})
            pos = m.end()
        pieces.append({"text": _plain(para[pos:])})
        pieces = [x for x in pieces if x["text"].strip()]
        if pieces:
            pieces[0]["text"] = pieces[0]["text"].lstrip()
            out.append(pieces)
    return out


def text(description: str) -> str:
    """The description as plain text (paragraphs separated by blank lines, link labels kept)."""
    return "\n\n".join("".join(x["text"] for x in para).strip() for para in paragraphs(description))


def info(param_id: int, refresh: bool = False) -> dict:
    """Name, short name, units, description and page URL of a GRIB parameter. Raises when it cannot be read and
    nothing is cached."""
    pid = int(param_id)
    path = cache_dir() / "ecmwf_params.json"
    cache = read_json(path, {}, dict)
    hit = cache.get(str(pid))
    if hit and not refresh and time.time() - hit.get("t", 0) < TTL:
        return hit["v"]
    try:
        d = _get(f"{API}/param/{pid}/")
        units = ""
        if d.get("unit_id") is not None:
            try:
                units = _get(f"{API}/unit/{int(d['unit_id'])}/").get("name", "")
            except Exception:  # noqa: BLE001 - the description is still worth showing
                units = ""
        v = {"id": pid, "name": d.get("name", ""), "shortname": d.get("shortname", ""), "units": units,
             "description": text(d.get("description", "")),
             "paragraphs": paragraphs(d.get("description", "")), "url": PAGE.format(id=pid),
             "retired": bool(d.get("retired"))}
    except Exception:
        if hit:  # offline: the last answer
            return hit["v"]
        raise
    cache[str(pid)] = {"t": time.time(), "v": v}
    write_json_atomic(path, cache)
    return v
