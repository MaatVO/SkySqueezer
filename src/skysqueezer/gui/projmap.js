// The area map in the dataset's own projection (see projection.py): Leaflet with a custom CRS and a vector
// basemap (Natural Earth, public domain), since map tiles exist only in Web Mercator.
// window.sksMap.set(id, projection) switches the map; window.sksMap.fit(id, points, padding, maxZoom) fits it.
(() => {
  if (window.sksMap) return;
  const RAD = Math.PI / 180;
  const R = 6371229;
  const M0 = (2 * Math.PI * 6378137) / 256; // metres per pixel at zoom 0, as Web Mercator
  const BASEMAP_URL = "/_sks/basemap.json.gz";

  function eqc() {
    return {
      project: (ll) => L.point(R * ll.lng * RAD, R * ll.lat * RAD),
      unproject: (p) => L.latLng(p.y / R / RAD, p.x / R / RAD),
      bounds: L.bounds([-Math.PI * R, -Math.PI * R / 2], [Math.PI * R, Math.PI * R / 2]),
    };
  }

  function lcc(p) {
    // Snyder, spherical form. Longitudes are not wrapped around the central meridian: the cut of the cone stays
    // on the 180° meridian, where the basemap is already cut, so no shape is torn across the map.
    const r = p.R || R, lat1 = p.lat1 * RAD, lat2 = p.lat2 * RAD, lat0 = p.lat0 * RAD;
    const t = (phi) => Math.tan(Math.PI / 4 + phi / 2);
    const n = Math.abs(lat1 - lat2) < 1e-10 ? Math.sin(lat1) : Math.log(Math.cos(lat1) / Math.cos(lat2)) / Math.log(t(lat2) / t(lat1));
    const rf = (r * Math.cos(lat1) * Math.pow(t(lat1), n)) / n;
    const rho0 = rf / Math.pow(t(lat0), n);
    const sgn = n > 0 ? 1 : -1;
    const lim = 85 * sgn; // the far pole is at infinity
    return {
      project(ll) {
        const lat = sgn > 0 ? Math.max(ll.lat, -lim) : Math.min(ll.lat, -lim);
        const rho = rf / Math.pow(t(lat * RAD), n);
        const th = n * (ll.lng - p.lon0) * RAD;
        return L.point(rho * Math.sin(th), rho0 - rho * Math.cos(th));
      },
      unproject(pt) {
        const rho = sgn * Math.hypot(pt.x, rho0 - pt.y);
        const th = Math.atan2(sgn * pt.x, sgn * (rho0 - pt.y));
        const lat = (2 * Math.atan(Math.pow(rf / rho, 1 / n)) - Math.PI / 2) / RAD;
        return L.latLng(lat, th / n / RAD + p.lon0);
      },
      bounds: L.bounds([-2e7, -2e7], [2e7, 2e7]),
    };
  }

  function makeCrs(p) {
    return L.extend({}, L.CRS.Earth, {
      code: p.kind === "lcc" ? `SKS:lcc:${p.lat0}:${p.lon0}:${p.lat1}:${p.lat2}` : "SKS:eqc",
      projection: p.kind === "lcc" ? lcc(p) : eqc(),
      transformation: new L.Transformation(1, 0, -1, 0),
      scale: (z) => Math.pow(2, z) / M0,
      zoom: (s) => Math.log2(s * M0),
      infinite: true,
      wrapLng: undefined,
      wrapLat: undefined,
    });
  }

  // ------------------------------------------------------------ basemap (fetched once per page)
  let basemap = null;
  function decode(flat) { // [lon0*100, lat0*100, dlon, dlat, ...] -> [[lat, lon], ...]
    const out = [];
    let x = 0, y = 0;
    for (let i = 0; i < flat.length; i += 2) {
      x += flat[i]; y += flat[i + 1];
      out.push([y / 100, x / 100]);
    }
    return out;
  }
  function loadBasemap() {
    if (!basemap) {
      basemap = fetch((window.path_prefix || "") + BASEMAP_URL)
        .then((r) => {
          if (!r.ok) throw new Error(`basemap: HTTP ${r.status}`);
          return new Response(r.body.pipeThrough(new DecompressionStream("gzip"))).json();
        })
        .then((d) => ({
          land: d.land.map((poly) => poly.map(decode)),
          lakes: d.lakes.map((poly) => poly.map(decode)),
          borders: d.borders.map(decode),
          regions: d.regions.map(decode),
        }))
        .catch((e) => { basemap = null; console.warn(e); return null; });
    }
    return basemap;
  }

  function graticule(kind) {
    const lines = [], step = 10, lo = kind === "lcc" ? -80 : -90;
    for (let lat = -80; lat <= 80; lat += step) {
      const l = [];
      for (let lon = -180; lon <= 180; lon += 2) l.push([lat, lon]);
      lines.push(l);
    }
    for (let lon = -180; lon <= 180; lon += step) {
      const l = [];
      for (let lat = lo; lat <= 90; lat += 2) l.push([lat, lon]);
      lines.push(l);
    }
    return lines;
  }

  const css = (name, fallback) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

  async function waitMap(id) {
    for (let i = 0; i < 200; i++) {
      const el = typeof getElement === "function" ? getElement(id) : null;
      if (el && el.map) return el.map;
      await new Promise((r) => setTimeout(r, 50));
    }
    return null;
  }

  async function set(id, p) {
    const map = await waitMap(id);
    if (!map) return;
    p = p || { kind: "latlon" };
    const st = (map._sks = map._sks || { layers: [] });
    const code = makeCrs(p).code + JSON.stringify(p.outline || null);
    if (st.code === code) return;
    st.code = code;
    st.layers.forEach((l) => map.removeLayer(l));
    st.layers = [];
    map.eachLayer((l) => l instanceof L.TileLayer && map.removeLayer(l)); // Web Mercator only

    const center = map.getCenter();
    map.options.crs = makeCrs(p);
    map.options.zoomSnap = 0.25;
    map.options.maxZoom = 11;
    map.options.minZoom = 0;
    map.setView(center, map.getZoom(), { reset: true });

    if (!map.getPane("sksBase")) map.createPane("sksBase").style.zIndex = 250;
    const renderer = (st.renderer = st.renderer || L.canvas({ pane: "sksBase", padding: 0.3 }));
    const add = (l) => { l.addTo(map); st.layers.push(l); return l; };
    const muted = css("--edh-muted", "#98a2b0"), text = css("--edh-text", "#e6e9ee");
    const landFill = css("--edh-surface-2", "#232b37"), sea = css("--edh-bg", "#12161c");
    const base = { renderer, interactive: false, smoothFactor: 1.5 };

    if (map.attributionControl) map.attributionControl.setPrefix(false).addAttribution("Natural Earth");
    add(L.polyline(graticule(p.kind), { ...base, color: muted, weight: 0.5, opacity: 0.25 }));
    const d = await loadBasemap();
    if (st.code !== code) return; // switched again meanwhile
    if (d) {
      // a conic projection sends the far pole to infinity: a ring around it (Antarctica runs along −90°) would
      // enclose the whole map and, filled even-odd, turn the rest of the land into holes
      const far = p.kind === "lcc" ? (p.lat1 + p.lat2 >= 0 ? (q) => q.every(([a]) => a < -50) : (q) => q.every(([a]) => a > 50)) : () => false;
      const land = d.land.filter((poly) => !far(poly[0]));
      add(L.polygon(land, { ...base, stroke: true, color: muted, weight: 0.7, opacity: 0.6, fillColor: landFill, fillOpacity: 1 }));
      add(L.polygon(d.lakes, { ...base, stroke: true, color: muted, weight: 0.5, opacity: 0.4, fillColor: sea, fillOpacity: 1 }));
      const regions = L.polyline(d.regions, { ...base, color: muted, weight: 0.5, opacity: 0.35, dashArray: "2 3" });
      const showRegions = () => {
        const want = map.getZoom() >= 4.5;
        if (want !== map.hasLayer(regions)) want ? regions.addTo(map) : map.removeLayer(regions);
      };
      st.layers.push(regions);
      if (st.zoomHandler) map.off("zoomend", st.zoomHandler);
      st.zoomHandler = showRegions;
      map.on("zoomend", showRegions);
      showRegions();
      add(L.polyline(d.borders, { ...base, color: muted, weight: 0.9, opacity: 0.7 }));
      if (p.kind === "latlon") { // boxes past 180° (0 … 360 longitudes) still have land under them
        const shift = (ring) => ring.map(([a, b]) => [a, b + 360]);
        add(L.polygon(land.map((poly) => poly.map(shift)), { ...base, stroke: true, color: muted, weight: 0.7, opacity: 0.6, fillColor: landFill, fillOpacity: 1 }));
      }
    }
    if (p.outline) { // the dataset's domain: data exist only inside
      add(L.polygon(p.outline, { renderer, interactive: false, color: text, weight: 1.2, opacity: 0.7, dashArray: "6 5", fill: false }));
    }
  }

  async function fit(id, pts, pad, maxZoom) {
    const map = await waitMap(id);
    if (!map || !pts || !pts.length) return;
    map.invalidateSize();
    const pr = map.options.crs.projection;
    const b = L.bounds(pts.map((q) => pr.project(L.latLng(q[0], q[1]))));
    const size = map.getSize();
    const w = Math.max(size.x - 2 * pad, 20), h = Math.max(size.y - 2 * pad, 20);
    const dx = Math.max(b.max.x - b.min.x, 1), dy = Math.max(b.max.y - b.min.y, 1);
    let z = Math.log2(Math.min(w / dx, h / dy) * M0);
    z = Math.max(0, Math.min(maxZoom || 11, Math.floor(z * 4) / 4));
    map.setView(pr.unproject(b.getCenter()), z, { animate: false });
  }

  window.sksMap = { set, fit };
})();
