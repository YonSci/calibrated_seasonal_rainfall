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

// Every method against the published approach, all seasons (scripts/method_summary.py): ranked by targets confirmed better,
// then by the share better on average over 1993-2016, then over the test years.
let SUM = null;
try { SUM = read('method_summary.json'); } catch { SUM = null; }
export const SUMMARY = SUM;
export const ranked = (product) => (SUM?.rows ?? []).filter((r) => r.product === product).sort((a, b) =>
  b.confirmed.length - a.confirmed.length || b.training_better / b.targets - a.training_better / a.targets
  || b.test_better / Math.max(b.test_scored, 1) - a.test_better / Math.max(a.test_scored, 1));
// Ranking by season (method_summary.py): per cycle and product, every method by its skill gain over the published approach,
// averaged over the season's months and 1993-2025; the published approach is in the list at 0.
export const RANKING = SUM?.ranking ?? null;

// Validation progress of a selection entry ('1 of 3'), as on the method-selection page.
export const validationText = (e) => (e.validation && e.validation.seasons ? `${e.validation.seasons.length} of ${e.validation.required}` : e.status === 'keep' ? '—' : '0 of 3');
