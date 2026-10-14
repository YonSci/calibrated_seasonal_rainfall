// Forecast cycles from site_data/cycles.json: page addresses and the per-cycle data files (docs/49).
import { read, href } from './data.js';

export const C = read('cycles.json');
export const cycleOf = (id) => C.cycles.find((c) => c.id === id);
export const dataFile = (rel) => (rel ? read(rel) : null);            // 'data/<cycle>_comparison.json' etc.

// Addresses: /outlooks/<cycle>/<view>/<target>/, /outlooks/<cycle>/<view>/verification/, /outlooks/<cycle>/<view>/history/
export const url = {
  cycle: (c) => href(`outlooks/${c.id}/`),
  target: (c, view, t) => href(`outlooks/${c.id}/${view}/${t}/`),
  verification: (c, view) => href(`outlooks/${c.id}/${view}/verification/`),
  history: (c, view) => href(`outlooks/${c.id}/${view}/history/`),
};
export const defaultTarget = (c) => c.targets[0].id;
export const pagesFor = (c, view) => ({
  target: (t) => url.target(c, view, t),
  history: url.history(c, view),
  verification: url.verification(c, view),
});
