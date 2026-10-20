// Canvas drawing of the 0.25-degree cells (the interactive outlook map and the forecast-against-observed slider): an
// equirectangular projection with cos(latitude) aspect, colour scales, outlines of the country and regions, hit-testing,
// zoom and pan. Data: site/data/cells/<cycle>/ and areas.json (scripts/site_cells.py).

// The tercile ramps of the published maps (scripts/plot_forecast_products.py) and colour-blind friendly ones (BrBG family)
export const RAMPS = {
  standard: [['#fff3a1', '#ffe100', '#ffbd00', '#ff9400', '#ff7100', '#ff4300', '#ef0000'],
             ['#e3ffff', '#b4ffff', '#80ffff', '#49f5f5', '#1adede', '#00bebe', '#009595'],
             ['#c1ffc1', '#83f76b', '#50d425', '#30ab00', '#218500', '#106000', '#004000']],
  cb: [['#f6e8c3', '#ecd29b', '#dfc27d', '#c8963f', '#bf812d', '#8c510a', '#543005'],
       ['#f0f0f0', '#e0e0e0', '#cccccc', '#b5b5b5', '#9e9e9e', '#868686', '#6e6e6e'],
       ['#d8f0ec', '#c7eae5', '#80cdc1', '#5ab4ac', '#35978f', '#01665e', '#003c30']],
};
export const BOUNDS = [100 / 3, 40, 50, 60, 70, 80, 90, 100];
export const SEQ = { standard: ['#ffffcc', '#d9f0a3', '#addd8e', '#78c679', '#41ab5d', '#238443', '#005a32'],
                     cb: ['#f7fbff', '#c6dbef', '#9ecae1', '#6baed6', '#4292c6', '#2171b5', '#084594'] };
export const RAIN = ['#ffffd9', '#edf8b1', '#c7e9b4', '#7fcdbb', '#41b6c4', '#1d91c0', '#225ea8', '#0c2c84'];
export const DIV = ['#8c510a', '#bf812d', '#dfc27d', '#f6e8c3', '#f5f5f5', '#c7eae5', '#80cdc1', '#35978f', '#01665e'];
export const DIV_EDGES = [-1e9, -60, -40, -20, -5, 5, 20, 40, 60, 1e9];
export const SKILL = ['#b2182b', '#ef8a62', '#fddbc7', '#f7f7f7', '#d1e5f0', '#92c5de', '#4393c3', '#2166ac'];
export const DRY = '#e6dcc6', OUT = '#e9ecef', NONE = '#ffffff', LINE = '#35414b';

export function bin(v, edges) { let k = 0; while (k < edges.length - 2 && v >= edges[k + 1]) k++; return k; }

// The most likely tercile of a cell as on the published maps: white below 40% or for ties.
export function tercileColor(p, palette) {
  const k = p.indexOf(Math.max(...p));
  if (100 * p[k] < 40 || p.filter((x) => x === p[k]).length > 1) return NONE;
  return RAMPS[palette][k][bin(100 * p[k], BOUNDS)];
}
// The observed category of a cell (below y < t1, near t1 <= y <= t2, above y > t2), in the mid shade of its ramp.
export function observedCategory(y, t1, t2) { return y == null || t1 == null || t2 == null ? -1 : y < t1 ? 0 : y > t2 ? 2 : 1; }
export function observedColor(k, palette) { return k < 0 ? DRY : RAMPS[palette][k][4]; }
export function anomalyColor(v, n) { return v == null || !(n > 0) ? DRY : DIV[bin(100 * (v / n - 1), DIV_EDGES)]; }

export function createMap(canvas, G, A) {
  const ctx = canvas.getContext('2d');
  const view = { scale: 1, ox: 0, oy: 0 };
  if (!G._pos) G._pos = new Map(G.cells.map((c, i) => [c, i]));
  function extent() {
    const w = canvas.clientWidth, lonSpan = G.nlon * G.dlon, latSpan = G.nlat * G.dlat;
    const k = Math.cos(((G.lat0 + latSpan / 2) * Math.PI) / 180);
    const base = w / (lonSpan * k);
    return { w, h: base * latSpan, base, k, latSpan };
  }
  function toXY(lon, lat, e) {
    return [(lon - (G.lon0 - G.dlon / 2)) * e.k * e.base * view.scale + view.ox,
            (G.lat0 - G.dlat / 2 + e.latSpan - lat) * e.base * view.scale + view.oy];
  }
  function cellRect(i, e) {
    const c = G.cells[i], la = G.lat0 + G.dlat * Math.floor(c / G.nlon), lo = G.lon0 + G.dlon * (c % G.nlon);
    const [x, y] = toXY(lo - G.dlon / 2, la + G.dlat / 2, e);
    return [x, y, G.dlon * e.k * e.base * view.scale, G.dlat * e.base * view.scale];
  }
  function ring(pts, width, col, e) {
    ctx.beginPath();
    pts.forEach(([lo, la], j) => { const [x, y] = toXY(lo, la, e); j ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.closePath(); ctx.lineWidth = width; ctx.strokeStyle = col; ctx.stroke();
  }
  // colour(i) for every cell; with split (0..1) and colour2, the right part of the map is drawn with colour2
  function draw(colour, { sel = null, split = null, colour2 = null, cursor = -1 } = {}) {
    const e = extent(), dpr = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(e.w * dpr) || canvas.height !== Math.round(e.h * dpr)) {
      canvas.width = Math.round(e.w * dpr); canvas.height = Math.round(e.h * dpr); canvas.style.height = e.h + 'px';
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    canvas.style.touchAction = view.scale > 1 ? 'none' : 'pan-y';
    ctx.clearRect(0, 0, e.w, e.h);
    const paint = (fn) => G.cells.forEach((_, i) => { const [x, y, w, h] = cellRect(i, e); ctx.fillStyle = fn(i); ctx.fillRect(x, y, w + 0.6, h + 0.6); });
    if (split == null || !colour2) paint(colour);
    else {
      const sx = split * e.w;
      ctx.save(); ctx.beginPath(); ctx.rect(0, 0, sx, e.h); ctx.clip(); paint(colour); ctx.restore();
      ctx.save(); ctx.beginPath(); ctx.rect(sx, 0, e.w - sx, e.h); ctx.clip(); paint(colour2); ctx.restore();
    }
    Object.values(A.outlines.regions).forEach((rings) => rings.forEach((r) => ring(r, 0.7, 'rgba(53,65,75,.55)', e)));
    A.outlines.country.forEach((r) => ring(r, 1.4, LINE, e));
    if (sel) {
      ctx.lineWidth = 2; ctx.strokeStyle = '#111';
      for (const i of sel) { const [x, y, w, h] = cellRect(i, e); ctx.strokeRect(x + 1, y + 1, w - 2, h - 2); }
    }
    if (cursor >= 0) {                                         // the keyboard cursor: one cell, ringed in black and white
      const [x, y, w, h] = cellRect(cursor, e);
      ctx.lineWidth = 3; ctx.strokeStyle = '#fff'; ctx.strokeRect(x - 1, y - 1, w + 2, h + 2);
      ctx.lineWidth = 1.5; ctx.strokeStyle = '#111'; ctx.strokeRect(x - 1, y - 1, w + 2, h + 2);
    }
    if (split != null) {
      const sx = split * e.w;
      ctx.fillStyle = '#111'; ctx.fillRect(sx - 1.5, 0, 3, e.h);
      ctx.beginPath(); ctx.arc(sx, e.h / 2, 13, 0, 2 * Math.PI); ctx.fillStyle = '#fff'; ctx.fill(); ctx.lineWidth = 2; ctx.strokeStyle = '#111'; ctx.stroke();
      ctx.fillStyle = '#111'; ctx.font = 'bold 12px Inter, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('⇔', sx, e.h / 2 + 1);
    }
    return e;
  }
  function cellAt(clientX, clientY) {
    const e = extent(), rect = canvas.getBoundingClientRect();
    const x = (clientX - rect.left - view.ox) / view.scale, y = (clientY - rect.top - view.oy) / view.scale;
    const lon = G.lon0 - G.dlon / 2 + x / (e.k * e.base), lat = G.lat0 - G.dlat / 2 + e.latSpan - y / e.base;
    const ci = Math.round((lat - G.lat0) / G.dlat), cj = Math.round((lon - G.lon0) / G.dlon);
    if (ci < 0 || cj < 0 || ci >= G.nlat || cj >= G.nlon) return -1;
    const pos = G._pos.get(ci * G.nlon + cj);
    return pos === undefined ? -1 : pos;
  }
  function zoom(f, cx = null, cy = null) {
    const e = extent(), mx = cx ?? e.w / 2, my = cy ?? e.h / 2;
    const ns = Math.min(8, Math.max(1, view.scale * f)), g = ns / view.scale;
    view.ox = mx - (mx - view.ox) * g; view.oy = my - (my - view.oy) * g; view.scale = ns;
    if (view.scale === 1) { view.ox = 0; view.oy = 0; }
  }
  function reset() { view.scale = 1; view.ox = 0; view.oy = 0; }
  // the cell's box in CSS pixels relative to the canvas (for a tooltip at a keyboard-selected cell)
  function cellBox(i) { const [x, y, w, h] = cellRect(i, extent()); return { x, y, w, h }; }
  // the nearest cell of the country from position i in direction (dlat, dlon) grid steps, or i if none within reach
  function step(i, dlat, dlon) {
    const c = G.cells[i];
    let r = Math.floor(c / G.nlon), k = c % G.nlon;
    for (let n = 0; n < Math.max(G.nlat, G.nlon); n++) {
      r += dlat; k += dlon;
      if (r < 0 || k < 0 || r >= G.nlat || k >= G.nlon) return i;
      const p = G._pos.get(r * G.nlon + k);
      if (p !== undefined) return p;
    }
    return i;
  }
  // keep a cell in view when zoomed in (keyboard moves)
  function reveal(i) {
    if (view.scale <= 1) return;
    const e = extent(), b = cellBox(i), m = 20;
    if (b.x < m) view.ox += m - b.x; else if (b.x + b.w > e.w - m) view.ox -= b.x + b.w - (e.w - m);
    if (b.y < m) view.oy += m - b.y; else if (b.y + b.h > e.h - m) view.oy -= b.y + b.h - (e.h - m);
  }
  function latlon(i) { const c = G.cells[i]; return [G.lat0 + G.dlat * Math.floor(c / G.nlon), G.lon0 + G.dlon * (c % G.nlon)]; }
  return { draw, cellAt, zoom, reset, view, extent, latlon, cellBox, step, reveal };
}
