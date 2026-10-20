// The evidence of each method in a few words (the "In short" boxes and the method cards): from the cross-method summary
// (site_data/method_summary.json, scripts/method_summary.py) and the method selection (site_data/selection.json, docs/50).
import { read } from './data.js';

const tryRead = (rel) => { try { return read(rel); } catch { return null; } };
export const SUMMARY = tryRead('method_summary.json');
export const SELECTION = tryRead('selection.json');
const SEASON = { jan_fmam: 'FMAM (Jan)', feb_fmam: 'FMAM (Feb)', may_jjas: 'JJAS (May)', sep_ondj: 'ONDJ (Sep)' };
const PRODUCT = { probabilities: 'tercile probabilities', amounts: 'rainfall amounts' };

// Selection candidates of a method: [{season, target, product}] (status "candidate" in the method selection)
export function candidates(method) {
  return (SELECTION?.cycles ?? []).flatMap((c) => Object.entries(c.targets).flatMap(([t, v]) => Object.entries(v)
    .filter(([, x]) => x.status === 'candidate' && x.selected?.method === method)
    .map(([p, x]) => ({ season: SEASON[c.name] ?? c.name, target: t, product: p,
      scored: x.validation?.seasons?.length ?? 0, required: x.validation?.required ?? null }))));
}

// One method's evidence: per product the rows of the summary, plus the candidates.
export function evidence(method) {
  const rows = (SUMMARY?.rows ?? []).filter((r) => r.method === method);
  if (!rows.length) return null;
  return {
    method, label: rows[0].label, category: rows[0].category ?? rows[0].family,
    products: rows.map((r) => ({
      product: r.product, name: PRODUCT[r.product] ?? r.product, targets: r.targets,
      training: r.training_better, test: r.test_better, testScored: r.test_scored,
      validation: r.validation_better, validationScored: r.validation_scored,
      confirmed: r.confirmed, pooled: r.pooled,
      cells: (SUMMARY.target_order ?? []).map((o) => ({ key: o.key, ...(r.by_target?.[o.key] ?? {}) })),
    })),
    candidates: candidates(method),
  };
}

// The sentences of an "In short" bullet for one product of a method
export function productLine(p) {
  const conf = p.confirmed.length
    ? `confirmed better for ${p.confirmed.length} (${p.confirmed.join(', ')})`
    : 'confirmed better for none';
  return `${cap(p.name)}: lower (better) score than the published approach for ${p.training} of ${p.targets} targets over 1993–2016 and ` +
    `${p.test} of ${p.testScored} over the test years; ${conf} under the selection rule.`;
}

export const PRODUCT_NAME = PRODUCT;

// One line per method: where it is confirmed better and whether it is a selection candidate
export function verdictLine(e) {
  const conf = e.products.filter((p) => p.confirmed.length).map((p) => `${p.name} in ${p.confirmed.join(', ')}`);
  if (!conf.length) return `${e.label}: not confirmed better than the published approach for any target or product.`;
  const pending = e.candidates.filter((c) => c.required != null && c.scored < c.required).length;
  return `${e.label}: confirmed better for ${conf.join('; ')}.` + (e.candidates.length
    ? ` Selection candidate for ${e.candidates.length} target${e.candidates.length > 1 ? 's' : ''}` + (pending ? `, waiting for ${e.candidates[0].required} validation seasons` : '') + '.'
    : ' Not a selection candidate (another method is preferred there, or the test years show harm).');
}
export function selectionLine(e) {
  if (!e.candidates.length) return 'Selection: not a candidate anywhere; the published approach stays.';
  const by = e.candidates.map((c) => `${c.season} ${c.target} (${PRODUCT[c.product] ?? c.product})`);
  return `Selection: candidate for ${by.join(', ')}; it needs 3 validation seasons before a switch is considered, and any switch is an explicit decision.`;
}

// Whole-family counts: methods tested, confirmed somewhere, candidates
export function overview(filter = () => true) {
  const rows = (SUMMARY?.rows ?? []).filter(filter);
  const methods = [...new Set(rows.map((r) => r.method))];
  const confirmed = [...new Set(rows.filter((r) => r.confirmed.length).map((r) => r.method))];
  const cands = methods.flatMap((m) => candidates(m).map((c) => ({ method: m, ...c })));
  const probConfirmed = rows.filter((r) => r.product === 'probabilities' && r.confirmed.length).map((r) => r.method);
  return { methods, confirmed, candidates: cands, probConfirmed, label: (m) => rows.find((r) => r.method === m)?.label ?? m };
}

const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

// The "In short" sentences of a group of methods (all of them, or one category)
export function overviewPoints(filter = () => true, scope = 'methods') {
  const o = overview(filter);
  if (!o.methods.length) return [];
  const names = (ms) => ms.map(o.label).join(', ');
  const nTargets = SUMMARY?.target_order?.length ?? 20;
  const pts = [`${o.methods.length} ${scope} tested against the published approach for ${nTargets} targets (four seasons and their months), cross-validated over 1993–2016 with 2017 onward as test years.`];
  pts.push(o.confirmed.length
    ? `Confirmed better somewhere under the selection rule: ${o.confirmed.length} (${o.confirmed.map(o.label).join('; ')}).` +
      (o.probConfirmed.length ? ` For tercile probabilities: ${names([...new Set(o.probConfirmed)])}.` : ' None for tercile probabilities.')
    : 'None is confirmed better than the published approach for any target.');
  if (o.candidates.length) {
    const short = o.candidates.filter((c) => c.required != null && c.scored < c.required).length;
    const byMethod = [...new Set(o.candidates.map((c) => c.method))].map((m) => `${o.label(m)} for ` +
      o.candidates.filter((c) => c.method === m).map((c) => `${c.season} ${c.target} ${c.product === 'amounts' ? 'amounts' : 'probabilities'}`).join(', '));
    pts.push(`${o.candidates.length} selection candidate${o.candidates.length > 1 ? 's' : ''}: ` + byMethod.join('; ') + '.' +
      (short ? ` ${short === o.candidates.length ? 'None has' : `${o.candidates.length - short} of them have`} the validation seasons the rule needs yet.` : ''));
  }
  pts.push('The published forecasts keep the published approach; a switch is made only by an explicit decision.');
  return pts;
}
