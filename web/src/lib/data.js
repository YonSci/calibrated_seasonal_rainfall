// Data access and formatting for the pages. Everything shown comes from site_data/ (written by scripts/build_site.py through
// scripts/site_data.py; docs/49). Nothing is computed here that the Python build has not already decided, except how to
// display it.
import fs from 'node:fs';
import path from 'node:path';

const DATA_DIR = process.env.SITE_DATA ?? path.resolve(process.cwd(), '..', 'site_data');

const CACHE = new Map();                                              // each file is parsed once per build
export function read(rel) {
  if (!CACHE.has(rel)) CACHE.set(rel, JSON.parse(fs.readFileSync(path.join(DATA_DIR, rel), 'utf-8')));
  return CACHE.get(rel);
}

export function names(folder) {
  const d = path.join(DATA_DIR, folder);
  return fs.existsSync(d) ? fs.readdirSync(d).filter((f) => f.endsWith('.json')).map((f) => f.slice(0, -5)) : [];
}

export const SITE = read('site.json');
export const FILES = read('files.json');
export const REPO = 'https://github.com/YonSci/calibrated_seasonal_rainfall';

// URLs: the Astro pages live under BASE; figures and the current page live at the site root.
export const BASE = import.meta.env.BASE_URL.endsWith('/') ? import.meta.env.BASE_URL : import.meta.env.BASE_URL + '/';
export const ROOT = BASE.replace(/next\/$/, '');
export const href = (p = '') => BASE + p.replace(/^\//, '');
export const asset = (p) => ROOT + p.replace(/^\//, '');
export const link = (u) => (/^https?:/.test(u) ? u : asset(u));

// Formatting (the same conventions as the current page)
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (x) => String(x ?? '').replace(/[&<>"']/g, (c) => ESC[c]);
const ok = (x) => typeof x === 'number' && Number.isFinite(x);
export const signed = (x, d = 3) => (ok(x) ? (x >= 0 ? '+' : '-') + Math.abs(x).toFixed(d) : '—');
export const num = (x, d = 2) => (ok(x) ? x.toFixed(d) : '—');
export const pct = (x, d = 0) => (ok(x) ? (100 * x).toFixed(d) + '%' : '—');
export const years = (a) => (a ? `${a[0]}–${a[1]}` : '');
export const listing = (items) => (items.length > 1 ? items.slice(0, -1).join(', ') + ' and ' + items.at(-1) : items[0] ?? 'none');
export const mb = (b) => (ok(b) ? (b / 1e6 >= 0.1 ? (b / 1e6).toFixed(1) + ' MB' : Math.max(1, Math.round(b / 1e3)) + ' kB') : '');
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
export const monthName = (m) => MONTHS[m - 1];

// Downloads of a section: every linked file whose site path starts with the prefix (e.g. downloads/bias/jan_fmam/).
export function downloads(prefix) {
  return Object.values(FILES).filter((f) => f.path.startsWith(prefix)).sort((a, b) => a.path.localeCompare(b.path));
}

export const cycleTitle = (init, season) => `${monthName(init)} initialization · ${season} and its months`;
