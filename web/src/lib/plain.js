// Plain-language outlook summaries and area statistics from the per-cell data (scripts/site_cells.py), used at build time
// (the page's summary) and in the browser (the interactive map and the area search). Area means are cos(latitude)-weighted,
// as the published area summaries; probabilities are averaged over the cells where terciles are defined.

import { t } from './i18n.js';

export const CAT = ['below', 'near', 'above'];
export const CAT_LABEL = { below: 'below normal', near: 'near normal', above: 'above normal' };
export const LEAN = 0.40;                     // a category "is favoured" where its probability is at least 40% and the largest

const num = (v) => (v == null ? NaN : v);

export function weights(grid) {
  return grid.cells.map((c) => Math.cos(((grid.lat0 + grid.dlat * Math.floor(c / grid.nlon)) * Math.PI) / 180));
}

// Positions (into grid.cells) of the full-grid cell indices of an area; cells outside the country are dropped.
export function positions(grid, cellIdx) {
  if (!grid._pos) grid._pos = new Map(grid.cells.map((c, i) => [c, i]));
  return cellIdx.map((c) => grid._pos.get(c)).filter((i) => i !== undefined);
}

// Statistics of a set of positions: area-mean probabilities, favoured category, amounts and the historical skill.
export function stats(grid, d, pos) {
  const w = grid._w ?? (grid._w = weights(grid));
  let sw = 0, sp = [0, 0, 0], np = 0;
  let am = 0, an = 0, aq1 = 0, aq9 = 0, sa = 0, na = 0;
  const lean = { below: 0, near: 0, above: 0, none: 0 };
  let rb = 0, rc = 0, rbo = 0, rco = 0, obs = 0, nobs = 0;
  for (const i of pos) {
    const p = [num(d.pb[i]), num(d.pn[i]), num(d.pa[i])];
    if (p.every(Number.isFinite)) {
      sp = sp.map((s, k) => s + w[i] * p[k]);
      sw += w[i];
      np++;
      const k = p.indexOf(Math.max(...p));
      lean[p[k] >= LEAN && p.filter((x) => x === p[k]).length === 1 ? CAT[k] : 'none'] += w[i];
    }
    if (Number.isFinite(num(d.mean[i])) && Number.isFinite(num(d.normal[i]))) {
      am += w[i] * d.mean[i]; an += w[i] * d.normal[i]; aq1 += w[i] * num(d.q10[i]); aq9 += w[i] * num(d.q90[i]); sa += w[i]; na++;
      if (d.obs && Number.isFinite(num(d.obs[i]))) { obs += w[i] * d.obs[i]; nobs += w[i]; }
    }
    if (d.rb_tr && Number.isFinite(num(d.rb_tr[i])) && Number.isFinite(num(d.rc_tr[i]))) { rb += w[i] * d.rb_tr[i]; rc += w[i] * d.rc_tr[i]; }
    if (d.rb_op && Number.isFinite(num(d.rb_op[i])) && Number.isFinite(num(d.rc_op[i]))) { rbo += w[i] * d.rb_op[i]; rco += w[i] * d.rc_op[i]; }
  }
  const p = sw ? sp.map((s) => s / sw) : null;
  const total = lean.below + lean.near + lean.above + lean.none;
  const share = total ? Object.fromEntries(Object.entries(lean).map(([k, v]) => [k, v / total])) : null;
  const ny = (d.n_tr ?? 0) + (d.n_op ?? 0);
  // historical skill: RPSS of the published probabilities, the training (leave-one-year-out) and test years pooled by year count
  const rpss = rc > 0 && rco > 0 ? 1 - ((d.n_tr * rb / rc) + (d.n_op * rbo / rco)) / ny : rc > 0 ? 1 - rb / rc : null;
  return {
    cells: pos.length, probCells: np, p, share,
    favoured: p ? favoured(p) : null,
    mean: sa ? am / sa : null, normal: sa ? an / sa : null, q10: sa ? aq1 / sa : null, q90: sa ? aq9 / sa : null,
    anomaly: sa && an > 0 ? am / an - 1 : null,
    observed: nobs ? obs / nobs : null,
    rpss, years: ny,
  };
}

// The favoured category of area-mean probabilities: the largest at >= 36% (area means are smoother than cells), else none.
export function favoured(p) {
  const k = p.indexOf(Math.max(...p));
  return p[k] >= 0.36 && p.filter((x) => Math.abs(x - p[k]) < 0.005).length === 1 ? CAT[k] : null;
}

// Whole tenths that add to 10 (largest remainder): "x in 10" for the icon rows.
export function tenths(p) {
  const raw = p.map((x) => x * 10);
  const out = raw.map(Math.floor);
  let left = 10 - out.reduce((a, b) => a + b, 0);
  raw.map((x, i) => [x - Math.floor(x), i]).sort((a, b) => b[0] - a[0]).forEach(([, i]) => { if (left > 0) { out[i]++; left--; } });
  return out;
}

// How the published approach has done here: words for the RPSS of past forecasts made the same way.
export function track(rpss, lang = 'en') {
  const lv = rpss == null || !Number.isFinite(rpss) ? 'unknown' : rpss <= 0 ? 'low' : rpss < 0.05 ? 'modest' : rpss < 0.15 ? 'fair' : 'good';
  const K = lv[0].toUpperCase() + lv.slice(1);
  return { level: lv, word: t(lang, `track${K}W`), text: t(lang, `track${K}`) };
}

const pc = (x) => `${Math.round(100 * x)}%`;
const mm = (x) => `${Math.round(x)} mm`;
const join = (names, lang) => (names.length > 1 ? names.slice(0, -1).join(', ') + ' ' + t(lang, 'and') + ' ' + names.at(-1) : names[0]);

function amounts(s, lang, members) {
  if (s.mean == null || s.normal == null) return '';
  const a = s.anomaly;
  return t(lang, 'expected', { mean: mm(s.mean) }) +
    (a != null ? t(lang, 'anomaly', { pct: `${Math.abs(Math.round(100 * a))}%`, dir: t(lang, a >= 0 ? 'dirAbove' : 'dirBelow'), normal: mm(s.normal) }) : '') +
    (members && s.q10 != null && s.q90 != null && s.cells <= 4 ? t(lang, 'members', { lo: mm(s.q10), hi: mm(s.q90) }) : '') +
    (lang === 'am' ? '።' : '.');
}

// One area in words (the map's area panel).
export function describe(s, place, target, lang = 'en') {
  if (!s || !s.p) return t(lang, 'dry', { place });
  const f = s.favoured;
  const parts = [f ? t(lang, 'favoured', { target, cat: t(lang, f), place, p: pc(s.p[CAT.indexOf(f)]) }) : t(lang, 'none', { target, place })];
  const am = amounts(s, lang, true);
  if (am) parts.push(am);
  parts.push(track(s.rpss, lang).text);
  return parts.join(' ');
}

// The page summary: which regions favour which category, from the regions' area means within the view's domain.
export function regional(grid, d, areas, viewPos, target, lang = 'en') {
  const inView = new Set(viewPos);
  const groups = { below: [], near: [], above: [] };
  for (const a of areas.areas.filter((x) => x.level === 1)) {
    const pos = positions(grid, a.cells).filter((i) => inView.has(i));
    if (pos.length < 3) continue;                                  // regions with almost no cells in the view
    const s = stats(grid, d, pos);
    if (s.p && s.favoured) groups[s.favoured].push({ name: a.name, p: s.p[CAT.indexOf(s.favoured)], cells: pos.length });
  }
  const all = stats(grid, d, viewPos);
  const out = [];
  for (const k of ['above', 'below', 'near']) {
    const g = groups[k].sort((a, b) => b.p - a.p);
    if (!g.length) continue;
    const range = g.length > 1 ? `${pc(Math.min(...g.map((x) => x.p)))}–${pc(Math.max(...g.map((x) => x.p)))}` : pc(g[0].p);
    out.push(t(lang, 'regionalLine', { Cat: t(lang, k[0].toUpperCase() + k.slice(1)), cat: t(lang, k), names: join(g.map((x) => x.name), lang), range }));
  }
  if (!out.length) out.push(t(lang, 'regionalNone', { target }));
  else out.unshift(t(lang, 'regionalHead', { target }));
  if (all.mean != null && all.anomaly != null)
    out.push(t(lang, 'across', { mean: mm(all.mean), pct: `${Math.abs(Math.round(100 * all.anomaly))}%`, dir: t(lang, all.anomaly >= 0 ? 'dirAbove' : 'dirBelow'), normal: mm(all.normal) }));
  out.push(track(all.rpss, lang).text);
  return { text: out.join(' '), all };
}

// "How did we do?" for a verified target: where the forecast favoured a category (>= 40% and the largest), the share of
// that area where the observed rainfall fell in it (by chance about 1 in 3) and the share where it fell in the opposite
// outer category; observed categories against the reference terciles t1, t2. Shares are cos(latitude)-weighted.
export function scorecard(grid, d, pos) {
  if (!d.obs || !d.t1) return null;
  const w = grid._w ?? (grid._w = weights(grid));
  const seen = [0, 0, 0];
  let all = 0, leaned = 0, hit = 0, opposite = 0, cells = 0;
  for (const i of pos) {
    const y = num(d.obs[i]), t1 = num(d.t1[i]), t2 = num(d.t2[i]);
    const p = [num(d.pb[i]), num(d.pn[i]), num(d.pa[i])];
    if (![y, t1, t2, ...p].every(Number.isFinite)) continue;
    const o = y < t1 ? 0 : y > t2 ? 2 : 1;
    seen[o] += w[i]; all += w[i]; cells++;
    const k = p.indexOf(Math.max(...p));
    if (p[k] < LEAN || p.filter((x) => x === p[k]).length > 1) continue;
    leaned += w[i];
    if (o === k) hit += w[i];
    else if (k !== 1 && o === 2 - k) opposite += w[i];
  }
  if (!all) return null;
  const r = { cells, observed: seen.map((x) => x / all), leaned: leaned / all, hit: leaned ? hit / leaned : null, opposite: leaned ? opposite / leaned : null };
  r.verdict = r.leaned < 0.1 ? 'nosignal' : r.hit >= 0.5 ? 'right' : r.opposite >= 1 / 3 ? 'missed' : 'partly';
  return r;
}

// One row per region (admin 1) with enough cells in the view: area-mean probabilities, amounts and track record
// (the print sheet and the embeddable widget).
export function regionRows(grid, d, areas, viewPos) {
  const inView = new Set(viewPos);
  return areas.areas.filter((x) => x.level === 1).map((a) => {
    const pos = positions(grid, a.cells).filter((i) => inView.has(i));
    if (pos.length < 3) return null;
    const s = stats(grid, d, pos);
    return { name: a.name, cells: pos.length, p: s.p, favoured: s.p ? s.favoured : null, mean: s.mean, normal: s.normal, anomaly: s.anomaly, rpss: s.rpss };
  }).filter(Boolean).sort((a, b) => a.name.localeCompare(b.name));
}
