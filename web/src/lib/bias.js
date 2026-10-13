// Bias-correction benchmark (docs/47): tables from site_data/bias/<cycle>.json with the same rows, marks and wording as
// scripts/site_bias.py. Every ✓ comes from the screening gates or the confirmation tests in the data.
import { esc, signed, num, pct, years, listing } from './data.js';

const REF_LABEL = { 'Boe et al. 2007': 'Boé et al. 2007', 'Themessl et al. 2011': 'Themeßl et al. 2011' };

export class View {
  constructor(D) {
    this.D = D;
    this.d = D.benchmark;
    this.c = D.confirmation;
    this.cfg = this.d.config_contents;
    this.targets = Object.keys(this.d.targets);
    this.season = this.targets.at(-1);
    this.months = this.targets.slice(0, -1);
    this.methods = Object.keys(this.d.targets[this.targets[0]].methods);
    this.ref = this.cfg.reference_method;
    const fam = (m) => this.d.methods?.[m]?.family;
    this.candidates = this.methods.filter((m) => m !== this.ref && m in this.d.gates && fam(m) !== 'variant');
    this.variants = this.methods.filter((m) => fam(m) === 'variant');
    this.primary = this.cfg.primary_region;
    this.year = this.cfg.forecast_year;
    this.tr = years(this.cfg.training_years);
    this.te = years(this.cfg.test_years);
    this.national = this.cfg.regions[this.primary].label;
    this.commit = this.d.provenance?.commit ?? 'main';
  }
  v(m, design, key, t, region) { return this.d.targets[t].methods[m][design][region ?? this.primary][key]; }
  dist(m, key, t, region, stat = 'area_median') { return this.d.targets[t].methods[m].distribution_full[region ?? this.primary][key][stat]; }
  gate(m, score, t) { return this.d.gates[m][score][t]; }
  screen(m, score, t, family = false) { return m in this.d.gates && Boolean(this.gate(m, score, t).decision[family ? 'screen_pass_family' : 'screen_pass']); }
  label(m) { return this.d.methods?.[m]?.label ?? m; }
  short(m) { return this.label(m).replace(' (operational)', ''); }
  mark(m, score, t) { return this.screen(m, score, t, true) ? ' ✓✓' : this.screen(m, score, t) ? ' ✓' : ''; }
  cv(m, design, key, t, region) {
    const node = m.startsWith('SEL') ? this.c.targets[t].selection[m] : this.c.targets[t].methods[m];
    return node[design][region ?? this.primary][key];
  }
  confirmed(m, score, t) { return Boolean(this.c?.tests?.[m]?.[score]?.[t]?.decision?.confirmed); }
  cite(key) {
    const r = this.D.references?.[key];
    const label = esc(REF_LABEL[key] ?? key);
    return r?.doi ? `<a href="https://doi.org/${esc(r.doi)}">${label}</a>` : label;
  }
}

const B = (on, x) => (on ? `<strong>${x}</strong>` : x);

export function suggestion(D) {
  const rec = D.recommendation, rule = D.recommendation_rule;
  if (!rec) return null;
  const STATUS = { keep: 'Keep the operational method', candidate: 'Candidate', recommended: 'Recommended', not_supported: 'Not supported by validation' };
  const rows = [];
  for (const [t, prods] of Object.entries(rec.targets)) for (const e of Object.values(prods)) {
    let status = STATUS[e.status];
    if (e.status === 'candidate') status += ` — validation ${e.validation.seasons.length} of ${e.validation.required} seasons`;
    const alts = (e.alternatives ?? []).map((a) => a.label).join(', ');
    rows.push([esc(t), esc(e.product), `<strong>${esc(e.method_label)}</strong>`, esc(status), esc(e.why) + (alts ? ` Also confirmed: ${esc(alts)}.` : '')]);
  }
  const n = Object.values(rec.targets).flatMap((p) => Object.values(p)).filter((e) => e.status !== 'keep').length;
  return { reference: rec.reference_label, n, total: rows.length, rule,
    table: { head: ['Target', 'Product', 'Suggested method', 'Status', 'Evidence'], rows, caption: 'Suggested methods (national aggregate)' } };
}

export function decision(V) {
  const items = [];
  if (V.c) {
    for (const [sc, product, proc] of [['rps', 'published tercile probabilities', 'SEL-P'], ['crps', 'rainfall amounts', 'SEL-A']]) {
      const conf = Object.fromEntries(V.c.methods.filter((m) => m !== V.ref).map((m) => [m, V.targets.filter((t) => V.confirmed(m, sc, t))]).filter(([, t]) => t.length));
      const sel = V.targets.filter((t) => V.c.tests[proc][sc][t].decision.confirmed);
      const P = product[0].toUpperCase() + product.slice(1);
      if (Object.keys(conf).length) {
        const txt = Object.entries(conf).map(([m, t]) => `${V.short(m)} for ${listing(t)}`).join('; ');
        const same = V.targets.some((t) => Object.values(conf).filter((v) => v.includes(t)).length > 1);
        items.push(`<strong>${esc(P)}:</strong> confirmed against ${esc(V.short(V.ref))} (family-wide, full pipeline): ${esc(txt)}. The selection-aware procedure is confirmed for ${esc(listing(sel))}.`
          + (same ? ' These comparisons establish improvement against the reference, not that one candidate is better than another.' : ''));
      } else {
        items.push(`<strong>${esc(P)}:</strong> no tested method demonstrates a statistically significant improvement over ${esc(V.short(V.ref))} under this validation protocol (several have slightly higher point estimates); the selection-aware procedure is confirmed for ${esc(listing(sel))}.`);
      }
    }
  } else items.push('The confirmation run is pending; the screening alone does not support a change.');
  items.push(`The operational method stays ${esc(V.short(V.ref))} until a change is decided by initialization, target and product, and recorded in the docs, on this evidence; confirmed improvements limited to some months may justify a per-target choice.`);
  items.push('If amounts and probabilities come to use different correction paths, the product metadata must record both methods so that every output can be traced.');
  return items;
}

export function dataTable(V, D) {
  const cov = V.targets.map((t) => { const c = V.v(V.ref, 'training', 'coverage', t); return `${esc(t)} ${pct(c.amount_area_share)} / ${pct(c.probability_area_share)}`; }).join('; ');
  const prov = V.d.provenance ?? {};
  const regions = Object.entries(V.cfg.regions).map(([k, r]) => esc(r.label) + (k === V.primary ? ' — primary (national aggregate)' : '')).join('; ');
  return { head: ['Item', 'Details'], caption: 'Data used by the benchmark', rows: [
    ['Forecasts', `ECMWF SEAS5 (system 51), initialized on 1 ${esc(['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'][D.initialization_month - 1])}; 25 members 1993–2016, 51 from 2017; remapped from 1° to the 0.25° CHIRPS grid by conservative remapping (each 1° cell fills a 4 × 4 block). ${V.cite('Johnson et al. 2019')}`],
    ['Observations', esc(D.observations)],
    ['Targets', `${esc(V.months.join(', '))} and the ${esc(V.season)} season; each corrected separately`],
    ['Observed years', `${years(V.cfg.all_years)} (seasons starting in these years)`],
    ['Training / test years', `${V.tr} (clean evidence) / ${V.te} (exploratory)`],
    ['Cells', `${Number(V.d.targets[V.season].cells).toLocaleString('en')} grid cells of Ethiopia (0.25°); a cell is corrected only if CHIRPS is complete in every training year`],
    ['Regions scored', regions],
    ['Score coverage (amounts / probabilities, share of the national area)', `${cov}. Tercile scores need two distinct tercile boundaries defining three categories, a CHIRPS standard deviation of at least 1 mm and a lower boundary above 0 mm, so dry months have fewer probability cells.`],
    ['Dry totals', `≤ ${V.cfg.dry_threshold_mm ?? 1} mm in a month or season (not a dry day); exactly 0 mm is reported separately`],
    ['Weighting', 'Every member is used; each training year has total weight 1/Y (each member of year y weighs 1/(Y·M<sub>y</sub>)), so years with 25 and 51 members count equally. Each observed year weighs 1/Y.'],
    ['Run', `<code>${esc(V.d.config)}</code>; ${esc(String(V.d.created_utc).slice(0, 16).replace('T', ' '))} UTC; commit <code>${esc(String(prov.commit ?? 'unknown').slice(0, 10))}</code>${prov.uncommitted_changes ? ' (with uncommitted changes)' : ''}; scoring version ${prov.scoring_version ?? '1'}`],
  ] };
}

export function methodsTable(V) {
  return { head: ['Method', 'Family', 'Definition (per cell and target)', 'Member-wise', 'Uses the forecast ensemble’s own distribution', 'Parameters', 'References'],
    caption: `${V.candidates.length} methods, the operational reference and the raw baseline`,
    rows: V.methods.map((m) => {
      const i = V.d.methods[m];
      const p = i.parameters && Object.keys(i.parameters).length ? `<code>${esc(JSON.stringify(i.parameters))}</code>` : '—';
      return [`<strong>${esc(i.label)}</strong><br><code>${esc(m)}</code>`, esc(i.family), esc(i.definition),
        i.member_wise ? 'yes' : '<strong>no</strong> (one value per training year)', i.uses_forecast_distribution ? 'yes' : 'no', p,
        (i.references ?? []).map((r) => V.cite(r)).join(', ')];
    }) };
}

export function screening(V, region) {
  const primary = region === V.primary, s = V.season, tr = V.tr, te = V.te;
  const head = ['Method', ...V.targets.map(esc)];
  const scoreRows = (design, key, score = null, d = 3) => V.methods.map((m) => [esc(V.label(m)), ...V.targets.map((t) => {
    const txt = signed(V.v(m, design, key, t, region), d) + (score && design === 'training' && primary ? V.mark(m, score, t) : '');
    return B(m === V.ref, txt);
  })]);
  const g = (m, design, key) => V.v(m, design, key, s, region);
  const glance = V.methods.map((m) => [B(m === V.ref, esc(V.label(m))),
    signed(g(m, 'training', 'crpss')) + (primary ? V.mark(m, 'crps', s) : ''), signed(g(m, 'operational', 'crpss')),
    signed(g(m, 'training', 'rpss')) + (primary ? V.mark(m, 'rps', s) : ''), signed(g(m, 'operational', 'rpss')),
    signed(g(m, 'training', 'mean_bias_mm'), 1), num(g(m, 'training', 'mean_mae_mm'), 1), num(g(m, 'training', 'correlation')),
    num(g(m, 'training', 'spread_error_ratio')), num(g(m, 'training', 'pit_reliability_index')), pct(g(m, 'training', 'dry_fraction'), 1)]);
  const plain = (key) => V.methods.map((m) => [esc(V.label(m)), ...V.targets.map((t) => num(V.v(m, 'training', key, t, region)))]);
  const cov = V.targets.map((t) => { const c = V.v(V.ref, 'training', 'coverage', t, region);
    return [esc(t), num(c.amount_cells, 0), pct(c.amount_area_share), num(c.probability_cells, 0), pct(c.probability_area_share)]; });
  const dry = [];
  for (const t of V.targets) {
    dry.push([`<strong>${esc(t)}</strong>: CHIRPS`, pct(V.dist(V.ref, 'zero_share_obs', t, region, 'area_mean'), 1), pct(V.dist(V.ref, 'dry_share_obs', t, region, 'area_mean'), 1)]);
    for (const m of V.methods) dry.push([esc(V.label(m)), pct(V.dist(m, 'zero_share_corrected', t, region, 'area_mean'), 1), pct(V.dist(m, 'dry_share_corrected', t, region, 'area_mean'), 1)]);
  }
  const dist = [['mean_ratio', 'Mean'], ['sd_ratio', 'Standard deviation'], ['q10_ratio', '10th percentile'], ['q90_ratio', '90th percentile']].map(([k, lab]) => ({
    head, caption: `${lab} of the corrected members / CHIRPS (area-weighted median of cell ratios, ${years(V.cfg.all_years)}; 1 = same)`,
    rows: V.methods.map((m) => [esc(V.label(m)), ...V.targets.map((t) => num(V.dist(m, k, t, region)))]) }));
  return {
    label: V.cfg.regions[region].label, primary,
    glance: { caption: `${esc(s)} season at a glance — ${esc(V.cfg.regions[region].label)}`, rows: glance,
      head: ['Method', `Amount CRPSS ${tr}`, `Amount CRPSS ${te}`, `Tercile RPSS (no blend) ${tr}`, `Tercile RPSS (no blend) ${te}`,
        'Mean bias (mm)', 'MAE (mm)', 'Correlation', 'Spread–error', 'Reliability index', 'Members ≤ 1 mm'] },
    crpss: { head, rows: scoreRows('training', 'crpss', 'crps'), caption: `Amount skill (CRPSS) by target, leave-one-year-out ${tr}` },
    rpss: { head, rows: scoreRows('training', 'rpss', 'rps'), caption: `Tercile skill (RPSS of smoothed counts, no blend) by target, ${tr}` },
    more: [
      { head, rows: scoreRows('operational', 'crpss'), caption: `Amount skill (CRPSS), fit ${tr}, scored ${te}` },
      { head, rows: scoreRows('training', 'crpss_fair', 'crps_fair'), caption: `Amount skill with the fair CRPS (diagnostic), ${tr}` },
      { head, rows: scoreRows('operational', 'rpss'), caption: `Tercile skill (RPSS, no blend), fit ${tr}, scored ${te}` },
      { head, rows: scoreRows('training', 'mean_bias_mm', null, 1), caption: `Ensemble-mean bias (mm), ${tr}` },
      { head, rows: scoreRows('training', 'correlation', null, 2), caption: `Correlation of the ensemble mean with CHIRPS over years, ${tr}` },
      { head, rows: plain('spread_error_ratio'), caption: `Spread–error ratio, ${tr} (1 = spread matches the error)` },
      { head, rows: plain('pit_reliability_index'), caption: `Rank-histogram reliability index, ${tr} (0 = flat)` },
      { head: ['Target', 'Amount cells', 'Amount area', 'Probability cells', 'Probability area'], rows: cov, caption: `Score coverage, mean per year, ${tr} (share of the region’s area)` },
    ],
    dry: { head: ['', 'Exactly 0 mm', '≤ 1 mm'], rows: dry, cls: 'compact nosort', caption: `Area-weighted mean share over cells, pooled leave-one-year-out ${years(V.cfg.all_years)}` },
    dist,
  };
}

export function gates(V) {
  return [['crps', 'mm', 2], ['crps_fair', 'mm', 2], ['rps', '', 4]].map(([score, unit, d]) => {
    const rows = [];
    for (const m of [...V.candidates, ...V.variants]) for (const t of V.targets) {
      const g = V.gate(m, score, t), a = g.training, b = g.operational, dc = g.decision;
      rows.push([esc(V.label(m)), esc(t), signed(a.mean_difference, d), `${signed(a.bootstrap_95[0], d)} to ${signed(a.bootstrap_95[1], d)}`,
        `${a.years_better}/${a.years}`, num(a.p_improvement, 4), num(dc.holm_p, 4), dc.holm_p_family == null ? '— (variant)' : num(dc.holm_p_family, 4),
        signed(b.mean_difference, d), dc.screen_pass_family ? '✓✓' : dc.screen_pass ? '✓' : '—']);
    }
    const label = { crps: 'CRPS', crps_fair: 'fair CRPS', rps: 'RPS (no blend)' }[score];
    return { rows, caption: `Screening statistics, ${label} (method minus ${esc(V.short(V.ref))}; negative favours the method)`,
      head: ['Method', 'Target', `Δ ${label} ${V.tr}` + (unit ? ` (${unit})` : ''), '95% interval', 'Years better', 'p (one-sided)', 'Holm p (method)',
        `Holm p (all ${V.candidates.length * V.targets.length})`, `Δ ${V.te}`, 'Screening'] };
  });
}

export function confirmation(V) {
  if (!V.c) return null;
  const C = V.c, s = V.season, tr = V.tr, te = V.te;
  const rows = [...C.methods, 'SEL-P', 'SEL-A'];
  const lab = (m) => (m.startsWith('SEL') ? `<strong>${m}</strong>` : B(m === V.ref, esc(V.label(m))));
  const mk = (m, score, t) => (m !== V.ref && V.confirmed(m, score, t) ? ' ✓' : '');
  const glance = rows.map((m) => [lab(m), signed(V.cv(m, 'training', 'rpss', s)) + mk(m, 'rps', s), signed(V.cv(m, 'test', 'rpss', s)),
    signed(V.cv(m, 'training', 'bss_below', s)) + mk(m, 'brier_below', s), signed(V.cv(m, 'training', 'bss_above', s)) + mk(m, 'brier_above', s),
    signed(V.cv(m, 'training', 'crpss', s)) + mk(m, 'crps', s), signed(V.cv(m, 'test', 'crpss', s)),
    m.startsWith('SEL') ? '—' : num(C.targets[s].methods[m].lambda_?.training_mean)]);
  const byT = (key, score) => rows.map((m) => [lab(m), ...V.targets.map((t) => signed(V.cv(m, 'training', key, t)) + mk(m, score, t))]);
  const sel = [];
  for (const name of ['SEL-P', 'SEL-A']) for (const t of V.targets) {
    const sl = C.targets[t].selection[name];
    const freq = Object.entries(sl.frequency).filter(([, n]) => n).sort((a, b) => b[1] - a[1]).map(([m, n]) => `${V.short(m)} ${n}`).join(', ');
    const test = C.tests[name][name === 'SEL-P' ? 'rps' : 'crps'][t];
    sel.push([name, esc(t), esc(freq), esc(V.short(sl.chosen_test)), signed(test.training.mean_difference, 4), num(test.decision.holm_p, 4),
      signed(test.test.mean_difference, 4), test.decision.confirmed ? 'yes' : 'no']);
  }
  const head = ['Method', ...V.targets.map(esc)];
  return {
    n: C.methods.length,
    glance: { rows: glance, caption: `${esc(s)} season through the full pipeline (outer leave-one-year-out ${tr}; test years exploratory)`,
      head: ['Method', `Blended RPSS ${tr}`, `Blended RPSS ${te}`, `BSS below ${tr}`, `BSS above ${tr}`, `Amount CRPSS ${tr}`, `Amount CRPSS ${te}`, 'Mean blend weight λ'] },
    rpss: { head, rows: byT('rpss', 'rps'), caption: `Blended tercile RPSS by target, outer leave-one-year-out ${tr}` },
    crpss: { head, rows: byT('crpss', 'crps'), caption: `Amount CRPSS by target, outer leave-one-year-out ${tr}` },
    selection: { rows: sel, caption: 'Selection-aware procedures against the operational method (Δ: RPS for SEL-P, CRPS for SEL-A; negative favours the procedure)',
      head: ['Procedure', 'Target', `Methods chosen (${tr}, years)`, `Chosen for ${te}`, 'Δ score vs MVS', 'Holm p (targets)', `Δ ${te}`, 'Confirmed'] },
  };
}

export function ratio(D) {
  const r = D.ratio_limits;
  if (!r) return null;
  const d = r.data, c = r.confirmation, T = Object.keys(c.targets), ref = c.reference, prim = d.config_contents.primary_region;
  const labels = Object.fromEntries(Object.entries(d.methods).map(([k, v]) => [k, v.label.replace(' (operational)', ' (operational, 0.5–2)')]));
  const conf = (m, sc, t) => m !== ref && Boolean(c.tests[m][sc][t].decision.confirmed);
  const cv = (m, key, t) => c.targets[t].methods[m].training[prim][key];
  const head = ['Method', ...T.map(esc)];
  const rows = (key, sc) => c.methods.map((m) => [esc(labels[m]), ...T.map((t) => signed(cv(m, key, t)) + (conf(m, sc, t) ? ' ✓' : ''))]);
  const act = T.map((t) => {
    const dg = d.targets[t].methods[ref].diagnostics_training.cell_area_share;
    return [esc(t), pct(dg.ratio_lower_limit ?? 0), pct(dg.ratio_upper_limit ?? 0), num(d.targets[t].methods[ref].training[prim].spread_error_ratio),
      'vs' in d.targets[t].methods ? num(d.targets[t].methods.vs.training[prim].spread_error_ratio) : '—'];
  });
  const found = (sc) => listing(c.methods.filter((m) => T.some((t) => conf(m, sc, t))).map((m) => `${labels[m]} (${T.filter((t) => conf(m, sc, t)).join(', ')})`));
  const tr = years(d.config_contents.training_years);
  return { alternatives: c.methods.length - 1, targets: T.length, commit: d.provenance ?? {}, foundRps: found('rps'), foundCrps: found('crps'),
    rpss: { head, rows: rows('rpss', 'rps'), caption: `Blended tercile RPSS through the full pipeline, outer leave-one-year-out ${tr}` },
    crpss: { head, rows: rows('crpss', 'crps'), caption: `Amount CRPSS, leave-one-year-out ${tr}` },
    acting: { rows: act, caption: `Share of the corrected area, mean over the leave-one-year-out folds, ${tr}`,
      head: ['Target', 'Lower limit active (r would be < 0.5)', 'Upper limit active (r would be > 2)', 'Spread–error, operational', 'Spread–error, no limits'] } };
}

export function shadows(D, V) {
  const val = D.validation ?? {}, out = [];
  for (const y of Object.keys(val).sort().reverse()) for (const [t, ms] of Object.entries(val[y])) for (const [m, r] of Object.entries(ms)) {
    const png = `${D.figures}/validation/shadow_${m}_${y}_${t}.png`;
    if (!r.shadow || !D.assets.includes(png)) continue;
    const ref = val[y][t][V.ref];
    const chk = ref?.published_check;
    const rows = [];
    if (r.observed && ref?.observed) for (const [lab, e] of [[ref.label.replace(' (operational)', '') + ' (published)', ref], [r.label + ' (shadow)', r]])
      for (const [rk, sc] of Object.entries(e.scores))
        rows.push([esc(lab), esc(V.cfg.regions[rk].label), signed(sc.rpss), signed(sc.bss_below), signed(sc.bss_above), signed(sc.crpss), pct(sc.favoured_hit_share), num(e.blend_weight)]);
    out.push({ year: y, target: t, label: r.label, png, observed: rows.length > 0,
      check: chk ? `The published method run alongside reproduces the published forecast: largest probability difference ${chk.max_abs_difference.toExponential(1)}, blend weight difference ${(chk.blend_weight_difference ?? 0).toExponential(1)}.` : '',
      table: rows.length ? { head: ['Method', 'Region', 'RPSS', 'BSS below', 'BSS above', 'Amount CRPSS', 'Favoured category observed', 'λ'], rows, caption: `${esc(t)} ${y} against CHIRPS (one season)` } : null });
  }
  return out;
}

export function validation(D, V) {
  const val = D.validation ?? {}, out = [];
  for (const y of Object.keys(val).sort().reverse()) {
    const observed = V.targets.filter((t) => t in val[y] && Object.values(val[y][t]).some((r) => r.observed));
    const methods = [...new Set(observed.flatMap((t) => Object.keys(val[y][t])))].sort((a, b) => (a !== V.ref) - (b !== V.ref) || a.localeCompare(b));
    if (!observed.length || methods.length < 2) continue;
    const label = (m) => observed.map((t) => val[y][t][m]).find(Boolean).label;
    const cell = (m, t, k) => (val[y][t][m]?.observed ? signed(val[y][t][m].scores[V.primary][k]) : '—');
    const head = ['Method', ...observed.map(esc)];
    out.push({ head, rows: methods.map((m) => [esc(label(m)), ...observed.map((t) => cell(m, t, 'rpss'))]), caption: `${y}: blended tercile RPSS against CHIRPS` });
    out.push({ head, rows: methods.map((m) => [esc(label(m)), ...observed.map((t) => cell(m, t, 'crpss'))]), caption: `${y}: amount CRPSS against CHIRPS` });
  }
  return out;
}

export function provenance(V) {
  const p = V.d.provenance;
  if (!p) return null;
  return { head: ['Item', 'Fingerprint'], caption: 'Run provenance (full hashes in benchmark.json and manifest.json)', rows: [
    ['Commit', `<code>${esc(p.commit)}</code>${p.uncommitted_changes ? ' (with uncommitted changes)' : ''}`],
    ['Configuration', `<code>${esc(p.config.path)}</code> sha256 <code>${esc(p.config.sha256.slice(0, 16))}…</code>`],
    ['Project configuration', `<code>${esc(p.project_config.path)}</code> sha256 <code>${esc(p.project_config.sha256.slice(0, 16))}…</code>`],
    ['Masks', Object.entries(p.masks).map(([k, v]) => `${esc(k)}: <code>${esc(v.sha256.slice(0, 16))}…</code>`).join('; ')],
    ['Inputs', Object.entries(p.inputs).map(([t, v]) => `${esc(t)}: ${v.files} files, <code>${esc(v.sha256.slice(0, 16))}…</code>`).join('; ')],
    ['Code', Object.entries(p.code_sha256).map(([k, v]) => `<code>${esc(k.split('/').at(-1))}</code> <code>${esc(v.slice(0, 12))}…</code>`).join('; ')],
    ['Scoring version', esc(p.scoring_version)],
    ['Software', `Python ${esc(p.python)}, NumPy ${esc(p.numpy)}`],
  ] };
}

const GROUP_KEYS = ['all training years exactly 0 mm', 'all training years <= threshold', 'mixed dry and wet years', 'always wet'];
const GROUP_SHORT = ['all 0 mm', 'all ≤ 1 mm', 'mixed', 'always wet'];

export function groups(V) {
  const out = [];
  for (const t of V.targets) {
    const g = V.d.targets[t].dry_groups?.training?.[V.primary];
    if (!g) continue;
    const share = Object.values(g)[0];
    out.push({ caption: `${esc(t)}: contributions to the CRPS difference from ${esc(V.short(V.ref))} (mm)`,
      head: ['Method', 'Total Δ CRPS', ...GROUP_KEYS.map((k, i) => `${GROUP_SHORT[i]}<br><span class="caveat">${pct(share[k].area_share, 1)} of area</span>`)],
      rows: Object.entries(g).filter(([m]) => m !== 'raw').map(([m, x]) => [esc(V.label(m)), signed(x.total_delta_crps_mm), ...GROUP_KEYS.map((k) => signed(x[k].delta_crps_mm))]) });
  }
  return out;
}

export function diagnostics(V) {
  const rows = [];
  for (const m of V.methods) for (const t of V.targets) {
    const dg = V.d.targets[t].methods[m].diagnostics_training ?? {};
    const parts = [...Object.entries(dg.cell_area_share ?? {}).filter(([, v]) => v).map(([k, v]) => `${esc(k.replaceAll('_', ' '))}: ${pct(v, 1)} of the area`),
      ...Object.entries(dg.event_share ?? {}).filter(([, v]) => v).map(([k, v]) => `${esc(k.replaceAll('_', ' '))}: ${pct(v, 1)}`)];
    if (parts.length) rows.push([esc(V.label(m)), esc(t), parts.join('; ')]);
  }
  return { head: ['Method', 'Target', 'Activated (share of the corrected area, or of members / cells for events)'], rows,
    caption: `How often limits, caps and fallbacks act, leave-one-year-out ${V.tr} (mean over folds)` };
}
