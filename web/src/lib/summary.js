// Build-time plain-language summary of a target and view (the page's hero), from the per-cell data in site_data/cells/
// (scripts/site_cells.py) through the same functions as the interactive map (lib/plain.js).
import { read } from './data.js';
import * as P from './plain.js';

function cells(cycleId, targetId) {
  try {
    return [read(`cells/${cycleId}/grid.json`), read(`cells/${cycleId}/${targetId}.json`), read('areas.json')];
  } catch {
    return null;                                     // no cell data for this cycle (e.g. an older build)
  }
}

export function summaryFor(cycleId, view, targetId, label) {
  const got = cells(cycleId, targetId);
  if (!got) return null;
  const [grid, d, areas] = got;
  const pos = grid.views[view] ?? grid.views.all_ethiopia;
  const r = P.regional(grid, d, areas, pos, label);
  const s = r.all;
  return { text: r.text, p: s.p, tenths: s.p ? P.tenths(s.p) : null, track: P.track(s.rpss), rpss: s.rpss, years: s.years, view, label,
           cycle: cycleId, target: targetId };
}

// The verification scorecard of a target and view (lib/plain.js scorecard), null before observations are in.
export function scorecardFor(cycleId, view, targetId) {
  const got = cells(cycleId, targetId);
  if (!got) return null;
  const [grid, d] = got;
  return P.scorecard(grid, d, grid.views[view] ?? grid.views.all_ethiopia);
}

// The regions of a target and view (lib/plain.js regionRows), for the print sheet.
export function regionsFor(cycleId, view, targetId) {
  const got = cells(cycleId, targetId);
  if (!got) return [];
  const [grid, d, areas] = got;
  return P.regionRows(grid, d, areas, grid.views[view] ?? grid.views.all_ethiopia);
}
