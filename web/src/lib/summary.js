// Build-time plain-language summary of a target and view (the page's hero), from the per-cell data in site_data/cells/
// (scripts/site_cells.py) through the same functions as the interactive map (lib/plain.js).
import { read } from './data.js';
import * as P from './plain.js';

export function summaryFor(cycleId, view, targetId, label) {
  let grid, d, areas;
  try {
    grid = read(`cells/${cycleId}/grid.json`);
    d = read(`cells/${cycleId}/${targetId}.json`);
    areas = read('areas.json');
  } catch {
    return null;                                     // no cell data for this cycle (e.g. an older build)
  }
  const pos = grid.views[view] ?? grid.views.all_ethiopia;
  const r = P.regional(grid, d, areas, pos, label);
  const s = r.all;
  return { text: r.text, p: s.p, tenths: s.p ? P.tenths(s.p) : null, track: P.track(s.rpss), rpss: s.rpss, years: s.years, view, label,
           cycle: cycleId, target: targetId };
}
