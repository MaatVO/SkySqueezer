"""Variable descriptions from the ECMWF Parameter Database: parsing, safe rendering, cache and offline use."""

import pytest

from skysqueezer import params, service
from skysqueezer.gui.app import description_html

RAW = ("This parameter is the temperature of air at 2m.<br/><br/>Calculated by interpolation."
       "<a href='https://www.ecmwf.int/doc.pdf#s3'> See further information </a>.<br/><br/>"
       "Units: kelvin (K) &amp; more <script>alert(1)</script><a href=\"javascript:alert(1)\">bad</a>")


def test_paragraphs_keep_https_links_only():
    ps = params.paragraphs(RAW)
    assert len(ps) == 3
    assert ps[1][1] == {"text": "See further information", "href": "https://www.ecmwf.int/doc.pdf#s3"}
    assert all("href" not in x for x in ps[2])  # the javascript: link is plain text
    assert "<script>" not in params.text(RAW) and "kelvin (K) & more" in params.text(RAW)


def test_description_html_escapes_everything():
    h = description_html([[{"text": "a <b>x</b>"}, {"text": "link", "href": "https://e.int/?a=1&b=\"2\""}],
                          [{"text": "no", "href": "javascript:alert(1)"}]])
    assert "<b>" not in h and "&lt;b&gt;" in h
    assert 'href="https://e.int/?a=1&amp;b=&quot;2&quot;"' in h and 'rel="noopener noreferrer"' in h
    assert "javascript:" not in h


def test_info_is_cached_and_used_offline(home, monkeypatch):
    calls = []

    def fake_get(url):
        calls.append(url)
        if "/unit/" in url:
            return {"id": 15, "name": "m**2 s**-2"}
        return {"id": 129, "name": "Geopotential", "shortname": "z", "unit_id": 15, "description": "<p>Energy.</p>"}

    monkeypatch.setattr(params, "_get", fake_get)
    r = service.param_info(129)
    assert r["ok"] and r["name"] == "Geopotential" and r["units"] == "m**2 s**-2"
    assert r["url"] == "https://codes.ecmwf.int/grib/param-db/129" and r["paragraphs"] == [[{"text": "Energy."}]]
    n = len(calls)
    assert service.param_info(129)["name"] == "Geopotential" and len(calls) == n  # from the cache

    def offline(url):
        raise OSError("no network")

    monkeypatch.setattr(params, "_get", offline)
    assert params.info(129, refresh=True)["name"] == "Geopotential"  # stale answer when offline
    r = service.param_info(130)  # never read: a clear failure, with the page to open
    assert not r["ok"] and r["url"].endswith("/130")
    with pytest.raises(OSError):
        params.info(130)
