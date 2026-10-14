// Probability and rainfall-distribution calibration (docs/48): tables from site_data/probcal/<cycle>.json, with the same
// rows, marks and wording as scripts/site_prob.py. Every ✓ comes from the tests in the data.
import { esc, signed, num, pct, years, listing } from './data.js';

const T_ = (d) => Object.keys(d.targets);                   // calendar order, as written by the benchmark
const bold = (on, x) => (on ? `<strong>${x}</strong>` : x);

export function phase1(d) {
  const reg = d.primary_region, T = T_(d), inc = d.incumbent;
  const rows = [...d.methods, ...('SEL' in d.targets[T[0]].methods ? ['SEL'] : [])];
  const name = (m) => (m === 'SEL' ? 'SEL (method chosen each year by inner cross-validation)' : d.registry[m].name);
  const v = (m, design, key, t) => d.targets[t].methods[m][design][reg][key];
  const conf = (m, t) => m !== inc && Boolean(d.tests[m]?.rps?.[t]?.decision?.confirmed);
  const mark = (m, t) => (conf(m, t) ? ' ✓' : '');
  const head = ['Method', ...T.map(esc)];
  const table = (key, design, withMark, caption) => ({
    head, caption,
    rows: rows.map((m) => [bold(m === inc, esc(name(m))), ...T.map((t) => bold(m === inc, signed(v(m, design, key, t)) + (withMark ? mark(m, t) : '')))]),
  });
  const tests = [];
  for (const m of d.methods) {
    if (m === inc) continue;
    for (const t of T) {
      const x = d.tests[m].rps[t];
      tests.push([esc(name(m)), esc(t), signed(x.training.mean_difference, 4), `${x.training.years_better}/${x.training.years}`,
        num(x.decision.holm_p_family, 4), signed(x.test.mean_difference, 4), `${x.test.years_better}/${x.test.years}`, x.decision.confirmed ? 'yes' : 'no']);
    }
  }
  if (d.tests.SEL) for (const t of T) {
    const x = d.tests.SEL.rps[t];
    tests.push(['SEL', esc(t), signed(x.training.mean_difference, 4), `${x.training.years_better}/${x.training.years}`,
      `${num(x.decision.holm_p, 4)} (targets)`, signed(x.test.mean_difference, 4), `${x.test.years_better}/${x.test.years}`, x.decision.confirmed ? 'yes' : 'no']);
  }
  const fits = T.map((t) => {
    const f = d.targets[t].fitted, s = d.targets[t].selection ?? {};
    const ord = f.ordinal_logistic?.test_fit ?? {};
    const freq = Object.entries(s.frequency ?? {}).filter(([, n]) => n).sort((a, b) => b[1] - a[1]).map(([m, n]) => `${name(m)} ${n}`).join(', ');
    const fb = Object.values(f).reduce((a, x) => a + (x.fallbacks ?? 0), 0);
    return [esc(t), num(f.climatology_blend?.test_fit?.lam), num(f.temperature?.test_fit?.temperature),
      esc((ord.cutpoints ?? []).map((c) => signed(c, 2)).join(', ')), esc((ord.beta ?? []).map((c) => signed(c, 2)).join(', ')), esc(freq), String(fb)];
  });
  const tr = years(d.training_years), te = years(d.test_years);
  const confirmed = rows.filter((m) => T.some((t) => conf(m, t))).map((m) => `${name(m)} (${T.filter((t) => conf(m, t)).join(', ')})`);
  return {
    tr, te, confirmed: listing(confirmed), amount: d.amount_method, region: d.regions[reg], provenance: d.provenance ?? {},
    rpss: table('rpss', 'training', true, `Tercile RPSS, outer leave-one-year-out ${tr} (bold: incumbent)`),
    test: table('rpss', 'test', false, `Tercile RPSS, fit ${tr}, scored ${te} (exploratory)`),
    logloss: table('log_loss_skill', 'training', false, `Log-loss skill against climatology, ${tr}`),
    below: table('bss_below', 'training', false, `Brier skill, below normal, ${tr}`),
    above: table('bss_above', 'training', false, `Brier skill, above normal, ${tr}`),
    tests: { head: ['Method', 'Target', `Δ RPS ${tr}`, 'Years better', 'Holm p', `Δ RPS ${te}`, 'Years better', 'Confirmed'], rows: tests,
      caption: 'Each method against the incumbent (negative Δ favours the method)' },
    fits: { head: ['Target', 'Blend weight λ', 'Temperature T', 'Ordinal cutpoints', 'Ordinal slopes (mean, log spread)', `SEL choices (${tr} folds)`, 'Fallbacks'],
      rows: fits, caption: `Fitted parameters (fit on ${tr}) and the selection-aware choices` },
  };
}

export function binary(d) {
  if (!d) return null;
  const reg = d.primary_region, T = T_(d), inc = d.incumbent;
  const rows = [...d.methods, ...('SEL' in d.targets[T[0]].methods ? ['SEL'] : [])];
  const name = (m) => (m === 'SEL' ? 'SEL (chosen each year)' : d.registry[m].name);
  const conf = (m, t) => m !== inc && Boolean(d.tests[m]?.rps?.[t]?.decision?.confirmed);
  const cell = (m, t, design) => signed(d.targets[t].methods[m][design][reg].rpss) + (design === 'training' && conf(m, t) ? ' ✓' : '');
  const head = ['Method', ...T.map(esc)];
  const tr = years(d.training_years), te = years(d.test_years);
  const found = rows.filter((m) => T.some((t) => conf(m, t))).map((m) => `${name(m)} (${T.filter((t) => conf(m, t)).join(', ')})`);
  return {
    confirmed: listing(found),
    training: { head, caption: `Tercile RPSS, outer leave-one-year-out ${tr}`, rows: rows.map((m) => [bold(m === inc, esc(name(m))), ...T.map((t) => bold(m === inc, cell(m, t, 'training')))]) },
    test: { head, caption: `Tercile RPSS, fit ${tr}, scored ${te} (exploratory)`, rows: rows.map((m) => [bold(m === inc, esc(name(m))), ...T.map((t) => bold(m === inc, cell(m, t, 'test')))]) },
  };
}

export function distribution(d) {
  if (!d) return null;
  const reg = d.primary_region, T = T_(d);
  const head = ['Method', ...T.map(esc)];
  const v = (k, design, key, t) => d.targets[t].methods[k][design][reg][key];
  const conf = (k, sc, t) => Boolean(d.tests[k][sc][t].decision.confirmed);
  const name = (k) => d.registry[k].name;
  const tr = years(d.training_years), te = years(d.test_years);
  const rows = (ref, refLabel, key, fmt, mark) => [
    [`<strong>${refLabel}</strong>`, ...T.map((t) => `<strong>${fmt(v(ref, 'training', key, t))}</strong>`)],
    ...d.models.map((k) => [esc(name(k)), ...T.map((t) => fmt(v(k, 'training', key, t)) + (mark && conf(k, mark, t) ? ' ✓' : ''))]),
  ];
  const found = (sc) => listing(d.models.filter((k) => T.some((t) => conf(k, sc, t))).map((k) => `${name(k)} (${T.filter((t) => conf(k, sc, t)).join(', ')})`));
  const testRows = [['Published probabilities / MVS ensemble', ...T.map((t) => `${signed(v('incumbent', 'test', 'rpss', t))} / ${signed(v('mvs_ensemble', 'test', 'crpss', t))}`)],
    ...d.models.map((k) => [`${esc(name(k))} (RPSS / CRPSS)`, ...T.map((t) => `${signed(v(k, 'test', 'rpss', t))} / ${signed(v(k, 'test', 'crpss', t))}`)])];
  return {
    phase: d.phase ?? 2, te, foundRps: found('rps'), foundCrps: found('crps'),
    rps: { head, rows: rows('incumbent', 'Published probabilities (incumbent)', 'rpss', signed, 'rps'), caption: `Tercile RPSS, outer leave-one-year-out ${tr}` },
    crps: { head, rows: rows('mvs_ensemble', 'MVS-corrected ensemble', 'crpss', signed, 'crps'), caption: `Amount CRPSS against the CHIRPS climatology, ${tr}` },
    coverage: { head, rows: rows('mvs_ensemble', 'MVS-corrected ensemble', 'coverage_80', pct, null), caption: `Share of observations inside the 10–90% interval, ${tr} (80% is calibrated)` },
    pinball: { head, rows: rows('mvs_ensemble', 'MVS-corrected ensemble', 'pinball_50', (x) => num(x), null), caption: `Pinball loss of the median (mm), ${tr} (lower is better)` },
    test: { head, rows: testRows, caption: `Fit ${tr}, scored ${te} (exploratory)` },
    models: { head: ['Model', 'Estimates', 'Predictors', 'Fitting', 'Outputs'], caption: 'Models',
      rows: Object.entries(d.registry).map(([k, r]) => [esc(name(k)), esc(r.estimates), esc(r.predictors), esc(r.fitting), esc(r.outputs)]) },
    diagnostics: d.models.map((k) => {
      const ds = T.map((t) => d.targets[t].diagnostics?.[k]).filter(Boolean);
      const cross = ds.map((x) => x.mean_crossing_share).filter((x) => x !== null && x !== undefined);
      return { name: name(k), converged: ds.every((x) => x.all_converged), crossing: cross.length ? Math.max(...cross) : null };
    }),
  };
}

export function shadow(rec, targetsOrder) {
  const out = [];
  for (const year of Object.keys(rec ?? {}).sort().reverse()) {
    const rows = rec[year];
    const T = targetsOrder.filter((t) => t in rows);
    const fc = [], sc = [];
    for (const t of T) {
      const r = rows[t], f = r.forecast;
      const rng = (k) => `${num(f[k].q50_mm, 0)} (${num(f[k].q10_mm, 0)}–${num(f[k].q90_mm, 0)})`;
      fc.push([esc(t), num(f.climatology_mm, 0), rng('shadow'), rng('mvs_ensemble'), `${num(f.shadow.width_relative)} / ${num(f.mvs_ensemble.width_relative)}`]);
      if (r.observed) {
        const s = r.scores[r.primary_region], sh = s.shadow, mv = s.mvs_ensemble, pu = s.published ?? {};
        sc.push([esc(t), pct(sh.coverage_80), pct(mv.coverage_80), signed(sh.crpss), signed(mv.crpss), num(sh.pinball_50, 1), num(mv.pinball_50, 1),
          signed(sh.rpss), signed(pu.rpss)]);
      }
    }
    const first = rows[T[0]];
    out.push({
      year, targets: T, observed: T.filter((t) => rows[t].observed), model: first.model, provenance: first.provenance ?? {},
      forecast: { head: ['Target', 'Climatology (mm)', 'Shadow: median (10–90%), mm', 'MVS ensemble: median (10–90%), mm', 'Range width / climatology (shadow / MVS)'],
        rows: fc, caption: `Forecast ${year}: national area-weighted means over the modelled cells (fitted on ${years(first.reference_years)})` },
      scores: sc.length ? { head: ['Target', 'Coverage, shadow', 'Coverage, MVS', 'CRPSS, shadow', 'CRPSS, MVS', 'Median pinball, shadow (mm)',
        'Median pinball, MVS (mm)', 'RPSS, shadow terciles', 'RPSS, published'], rows: sc, caption: `Scored against CHIRPS ${year} (one season each; 80% coverage is calibrated)` } : null,
    });
  }
  return out;
}

// Sub-pages of a cycle ('' = summary), only those with content.
export function parts(D) {
  return [['', 'Summary'], ['phase-1', 'Phase 1'], ...(D.phase2_binary || D.phase2_distribution ? [['phase-2', 'Phase 2']] : []),
    ...(D.phase3 ? [['phase-3', 'Phase 3']] : []), ...(Object.keys(D.amount_shadow ?? {}).length ? [['shadow', 'Amount and range shadow']] : []),
    ['downloads', 'Downloads']];
}
