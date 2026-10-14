// Forecast cycles from site_data/cycles.json: page addresses and the per-cycle data files (docs/49).
import { read, href } from './data.js';

export const C = read('cycles.json');
export const cycleOf = (id) => C.cycles.find((c) => c.id === id);
export const dataFile = (rel) => (rel ? read(rel) : null);            // 'data/<cycle>_comparison.json' etc.

// Addresses, one per cycle, area and target, with the section last:
//   /outlooks/<cycle>/<area>/<target>/                 outlook and maps
//   /outlooks/<cycle>/<area>/<target>/verification/    verification
//   /outlooks/<cycle>/<area>/<target>/skill/           historical performance
//   /outlooks/<cycle>/<area>/official/                 official-outlook comparison (season)
export const url = {
  cycle: (c) => href(`outlooks/${c.id}/`),
  target: (c, view, t) => href(`outlooks/${c.id}/${view}/${t}/`),
  verification: (c, view, t) => href(`outlooks/${c.id}/${view}/${t}/verification/`),
  skill: (c, view, t) => href(`outlooks/${c.id}/${view}/${t}/skill/`),
  official: (c, view) => href(`outlooks/${c.id}/${view}/official/`),
  section: (s, c, view, t) => (s === 'verification' ? url.verification(c, view, t) : s === 'skill' ? url.skill(c, view, t)
    : s === 'official' ? url.official(c, view) : url.target(c, view, t)),
};
export const defaultTarget = (c) => c.targets[0].id;
export const seasonTarget = (c) => (c.targets.find((t) => t.kind === 'season') || c.targets[0]).id;
export const pagesFor = (c, view, t) => ({
  target: (x) => url.target(c, view, x),
  history: url.skill(c, view, t),
  verification: url.verification(c, view, t),
});
