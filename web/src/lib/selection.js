// Method selection (scripts/method_selection.py, docs/50): the approach the evidence supports for each season, target and product.
import { read } from './data.js';

let SEL = null;
try { SEL = read('selection.json'); } catch { SEL = null; }
export const SELECTION = SEL;
export const STATUS_LABEL = { keep: 'Published approach kept', candidate: 'Candidate', recommended: 'Recommended', not_supported: 'Not supported by validation' };
const MON = { 1: 'jan', 2: 'feb', 3: 'mar', 4: 'apr', 5: 'may', 6: 'jun', 7: 'jul', 8: 'aug', 9: 'sep', 10: 'oct', 11: 'nov', 12: 'dec' };

// The selection of a forecast cycle (matched by initialization month and season, e.g. jan_fmam).
export function selectionFor(cycle) {
  if (!SEL) return null;
  const m = Number(cycle.init_date.slice(5, 7));
  return SEL.cycles.find((c) => c.name === `${MON[m]}_${cycle.season.toLowerCase()}`) || null;
}
export const fmt = (x, d = 4) => (typeof x === 'number' && Number.isFinite(x) ? (x >= 0 ? '+' : '-') + Math.abs(x).toPrecision(d) : '—');
