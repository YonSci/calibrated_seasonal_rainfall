"""Site section "Probability and rainfall-distribution calibration" (docs/48).

Reads only the probability-calibration benchmark outputs (outputs/probability_calibration/<cycle>/benchmark.json). Every
number comes from those files; statements about confirmed methods are computed from the tests.
"""
import json
import shutil
from pathlib import Path

from site_bias import esc, tbl, signed, num, pct, listing, years, month_name, REPO

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/probability_calibration'
DOC = 'docs/48_PROBABILITY_CALIBRATION.md'

PLAN = [  # (phase, identifier, method, family, output)
    (1, 'pseudocount', 'Pseudocount smoothing', 'baseline / stabilization', 'tercile probabilities'),
    (1, 'climatology_blend', 'Climatology blending (incumbent)', 'baseline / shrinkage', 'tercile probabilities'),
    (1, 'temperature', 'Temperature scaling', 'tercile calibration', 'tercile probabilities'),
    (1, 'dirichlet', 'Regularized Dirichlet calibration', 'tercile calibration', 'tercile probabilities'),
    (1, 'multinomial_logistic', 'Regularized multinomial logistic regression', 'tercile prediction', 'tercile probabilities'),
    (1, 'ordinal_logistic', 'Ordinal (cumulative-logit) logistic regression', 'tercile prediction', 'tercile probabilities'),
    (2, 'platt_ovr', 'Platt (sigmoid) calibration, one-vs-rest + normalization', 'binary calibration', 'tercile probabilities'),
    (2, 'beta_ovr', 'Beta calibration, one-vs-rest + normalization', 'binary calibration', 'tercile probabilities'),
    (2, 'isotonic_ovr', 'Isotonic regression, one-vs-rest + normalization', 'binary calibration', 'tercile probabilities'),
    (2, 'emos_csg', 'EMOS, censored shifted gamma', 'rainfall distribution', 'CDF, quantiles, terciles'),
    (2, 'extended_logistic', 'Extended logistic regression', 'rainfall distribution', 'CDF, terciles'),
    (2, 'quantile_regression', 'Regularized quantile regression', 'rainfall quantiles', 'quantiles (CDF by interpolation), terciles'),
    (3, 'bjp', 'Bayesian joint probability', 'rainfall distribution', 'CDF, quantiles, terciles'),
    (3, 'bma_precipitation', 'Bayesian model averaging (precipitation)', 'rainfall distribution', 'CDF, quantiles, terciles'),
    (3, 'quantile_regression_forest', 'Quantile regression forest', 'rainfall quantiles', 'conditional distribution, terciles'),
]
REFERENCES = [
    ('Guo, C., Pleiss, G., Sun, Y., & Weinberger, K. Q. (2017). On calibration of modern neural networks. <em>Proceedings of the 34th '
     'International Conference on Machine Learning</em>, PMLR 70, 1321–1330.', 'https://proceedings.mlr.press/v70/guo17a.html'),
    ('Kull, M., Perello-Nieto, M., Kängsepp, M., Silva Filho, T., Song, H., & Flach, P. (2019). Beyond temperature scaling: obtaining '
     'well-calibrated multiclass probabilities with Dirichlet calibration. <em>Advances in Neural Information Processing Systems 32</em> '
     '(NeurIPS 2019).', 'https://arxiv.org/abs/1910.12656'),
    ('McCullagh, P. (1980). Regression models for ordinal data. <em>Journal of the Royal Statistical Society, Series B</em>, 42, 109–127.',
     'https://doi.org/10.1111/j.2517-6161.1980.tb01109.x'),
    ('Rajagopalan, B., Lall, U., & Zebiak, S. E. (2002). Categorical climate forecasts through regularization and optimal combination of '
     'multiple GCM ensembles. <em>Monthly Weather Review</em>, 130, 1792–1811.', 'https://doi.org/10.1175/1520-0493(2002)130<1792:CCFTRA>2.0.CO;2'),
    ('Wilks, D. S. (2019). <em>Statistical Methods in the Atmospheric Sciences</em> (4th ed.). Elsevier.', None),
    ('Platt, J. C. (1999). Probabilistic outputs for support vector machines and comparisons to regularized likelihood methods. In '
     '<em>Advances in Large Margin Classifiers</em> (pp. 61–74). MIT Press.', None),
    ('Kull, M., Silva Filho, T., & Flach, P. (2017). Beta calibration: a well-founded and easily implemented improvement on logistic '
     'calibration for binary classifiers. <em>Proceedings of AISTATS 2017</em>, PMLR 54.', 'https://proceedings.mlr.press/v54/kull17a.html'),
    ('Zadrozny, B., & Elkan, C. (2002). Transforming classifier scores into accurate multiclass probability estimates. <em>Proceedings of '
     'the 8th ACM SIGKDD</em>, 694–699.', 'https://doi.org/10.1145/775047.775151'),
    ('Scheuerer, M., & Hamill, T. M. (2015). Statistical postprocessing of ensemble precipitation forecasts by fitting censored, shifted '
     'gamma distributions. <em>Monthly Weather Review</em>, 143, 4578–4596.', 'https://doi.org/10.1175/MWR-D-15-0061.1'),
    ('Wilks, D. S. (2009). Extending logistic regression to provide full-probability-distribution MOS forecasts. <em>Meteorological '
     'Applications</em>, 16, 361–368.', 'https://doi.org/10.1002/met.134'),
    ('Messner, J. W., Mayr, G. J., Zeileis, A., & Wilks, D. S. (2014). Heteroscedastic extended logistic regression for postprocessing '
     'of ensemble guidance. <em>Monthly Weather Review</em>, 142, 448–456.', 'https://doi.org/10.1175/MWR-D-13-00271.1'),
    ('Koenker, R., & Bassett, G. (1978). Regression quantiles. <em>Econometrica</em>, 46, 33–50.', 'https://doi.org/10.2307/1913643'),
    ('Wang, Q. J., Robertson, D. E., & Chiew, F. H. S. (2009). A Bayesian joint probability modeling approach for seasonal forecasting of '
     'streamflows at multiple sites. <em>Water Resources Research</em>, 45, W05407.', 'https://doi.org/10.1029/2008WR007355'),
    ('Wang, Q. J., & Robertson, D. E. (2011). Multisite probabilistic forecasting of seasonal flows for streams with zero value '
     'occurrences. <em>Water Resources Research</em>, 47, W02546.', 'https://doi.org/10.1029/2010WR009333'),
    ('Wang, Q. J., Shrestha, D. L., Robertson, D. E., & Pokhrel, P. (2012). A log-sinh transformation for data normalization and '
     'variance stabilization. <em>Water Resources Research</em>, 48, W05514.', 'https://doi.org/10.1029/2011WR010973'),
    ('Sloughter, J. M., Raftery, A. E., Gneiting, T., & Fraley, C. (2007). Probabilistic quantitative precipitation forecasting using '
     'Bayesian model averaging. <em>Monthly Weather Review</em>, 135, 3209–3220.', 'https://doi.org/10.1175/MWR3441.1'),
    ('Fraley, C., Raftery, A. E., & Gneiting, T. (2010). Calibrating multimodel forecast ensembles with exchangeable and missing members '
     'using Bayesian model averaging. <em>Monthly Weather Review</em>, 138, 190–202.', 'https://doi.org/10.1175/2009MWR3046.1'),
    ('Meinshausen, N. (2006). Quantile regression forests. <em>Journal of Machine Learning Research</em>, 7, 983–999.',
     'https://jmlr.org/papers/v7/meinshausen06a.html'),
]
SHADOW_CONFIG = 'config/probability_calibration/amount_shadow.json'


def load_all():
    out = []
    for p in OUT.glob('*/benchmark.json'):
        d = json.loads(p.read_text(encoding='utf-8'))
        bench = json.loads((ROOT / d['config_contents']['benchmark_config']).read_text(encoding='utf-8'))
        project = json.loads((ROOT / bench['project_config']).read_text(encoding='utf-8'))
        extra = {}
        for key, sub in (('binary', 'phase2_binary'), ('distribution', 'distribution'), ('phase3', 'phase3')):   # later phases, when run
            f = p.parent / sub / 'benchmark.json'
            extra[key] = json.loads(f.read_text(encoding='utf-8')) if f.is_file() else None
        extra['shadow'] = {}                                   # amount/range shadow: {year: {target: record}}
        for f in sorted(p.parent.glob('amount_shadow/*/*__*.json')):
            r = json.loads(f.read_text(encoding='utf-8'))
            extra['shadow'].setdefault(int(f.parent.name), {})[r['target']] = dict(r, folder=f.parent)
        out.append(dict(name=p.parent.name, folder=p.parent, data=d, init=project['initialization_month'], season=project['season']['name'],
                        **extra))
    return sorted(out, key=lambda b: b['init'])


def export(out_dir):
    blocks = []
    for b in load_all():
        dest = out_dir / 'assets/probcal' / b['name']
        if (b['folder'] / 'figures').is_dir():
            shutil.copytree(b['folder'] / 'figures', dest, dirs_exist_ok=True)
        for sub in ('phase2_binary', 'distribution', 'phase3'):
            if (b['folder'] / sub / 'figures').is_dir():
                shutil.copytree(b['folder'] / sub / 'figures', dest / sub, dirs_exist_ok=True)
        files = []
        for year, rows in b['shadow'].items():                 # shadow maps and NetCDF files
            for t, r in rows.items():
                for ext, kind in (('png', 'assets'), ('nc', 'downloads')):
                    src = r['folder'] / f"shadow_{r['model']}_{year}_{t}.{ext}"
                    if src.is_file():
                        d = out_dir / f'{kind}/probcal' / b['name'] / f'amount_shadow/{year}' / src.name
                        d.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, d)
                        if ext == 'nc':
                            files.append((f'downloads/probcal/{b["name"]}/amount_shadow/{year}/{src.name}',
                                          f'Shadow amounts and ranges, {t} {year} (NetCDF; not a published forecast)', d.stat().st_size))
        for rel, label in (('benchmark.json', 'Phase 1: all scores, per-year values, tests and fitted parameters (JSON)'),
                           ('phase2_binary/benchmark.json', 'Phase 2, binary calibrators (JSON)'),
                           ('distribution/benchmark.json', 'Phase 2, rainfall-distribution models (JSON)'),
                           ('phase3/benchmark.json', 'Phase 3, rainfall-distribution models (JSON)')):
            if (b['folder'] / rel).is_file():
                d = out_dir / 'downloads/probcal' / b['name'] / rel
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(b['folder'] / rel, d)
                files.append((f'downloads/probcal/{b["name"]}/{rel}', label, d.stat().st_size))
        blocks.append((b['name'], block(b, files)))
    return blocks


def block(b, files):
    d = b['data']
    reg = d['primary_region']
    order = json.loads((ROOT / d['config_contents']['benchmark_config']).read_text(encoding='utf-8'))['targets']
    T = [t for t in order if t in d['targets']]           # calendar order
    methods = d['methods']
    rows_all = methods + (['SEL'] if 'SEL' in d['targets'][T[0]]['methods'] else [])
    inc = d['incumbent']
    name = lambda m: 'SEL (method chosen each year by inner cross-validation)' if m == 'SEL' else d['registry'][m]['name']
    v = lambda m, design, key, t: d['targets'][t]['methods'][m][design][reg][key]
    conf = lambda m, t: m != inc and t in d['tests'].get(m, {}).get('rps', {}) and d['tests'][m]['rps'][t]['decision']['confirmed']
    mark = lambda m, t: ' ✓' if conf(m, t) else ''
    head = ['Method'] + [esc(t) for t in T]
    bold = lambda m, x: f'<strong>{x}</strong>' if m == inc else x
    t_rpss = [[bold(m, esc(name(m)))] + [bold(m, signed(v(m, 'training', 'rpss', t)) + mark(m, t)) for t in T] for m in rows_all]
    t_test = [[bold(m, esc(name(m)))] + [bold(m, signed(v(m, 'test', 'rpss', t))) for t in T] for m in rows_all]
    t_ll = [[bold(m, esc(name(m)))] + [bold(m, signed(v(m, 'training', 'log_loss_skill', t))) for t in T] for m in rows_all]
    t_bb = [[bold(m, esc(name(m)))] + [bold(m, signed(v(m, 'training', 'bss_below', t))) for t in T] for m in rows_all]
    t_ba = [[bold(m, esc(name(m)))] + [bold(m, signed(v(m, 'training', 'bss_above', t))) for t in T] for m in rows_all]
    confirmed = [f'{name(m)} ({", ".join(t for t in T if conf(m, t))})' for m in rows_all if any(conf(m, t) for t in T)]
    tests_rows = []
    for m in methods:
        if m == inc:
            continue
        for t in T:
            x = d['tests'][m]['rps'][t]
            a, te, dc = x['training'], x['test'], x['decision']
            tests_rows.append([esc(name(m)), esc(t), f'{a["mean_difference"]:+.4f}', f'{a["years_better"]}/{a["years"]}', f'{dc["holm_p_family"]:.4f}',
                               f'{te["mean_difference"]:+.4f}', f'{te["years_better"]}/{te["years"]}', 'yes' if dc['confirmed'] else 'no'])
    if 'SEL' in d['tests']:
        for t in T:
            x = d['tests']['SEL']['rps'][t]
            a, te, dc = x['training'], x['test'], x['decision']
            tests_rows.append(['SEL', esc(t), f'{a["mean_difference"]:+.4f}', f'{a["years_better"]}/{a["years"]}', f'{dc["holm_p"]:.4f} (targets)',
                               f'{te["mean_difference"]:+.4f}', f'{te["years_better"]}/{te["years"]}', 'yes' if dc['confirmed'] else 'no'])
    fit_rows = []
    for t in T:
        f = d['targets'][t]['fitted']
        s = d['targets'][t].get('selection', {})
        lam = f.get('climatology_blend', {}).get('test_fit', {}).get('lam')
        temp = f.get('temperature', {}).get('test_fit', {}).get('temperature')
        ordi = f.get('ordinal_logistic', {}).get('test_fit', {})
        freq = ', '.join(f'{name(m)} {n}' for m, n in sorted(s.get('frequency', {}).items(), key=lambda x: -x[1]) if n)
        fb = sum(x['fallbacks'] for x in f.values())
        fit_rows.append([esc(t), num(lam), num(temp), esc(', '.join(f'{c:+.2f}' for c in ordi.get('cutpoints', []))),
                         esc(', '.join(f'{c:+.2f}' for c in ordi.get('beta', []))), esc(freq), str(fb)])
    tr, te = years(d['training_years']), years(d['test_years'])
    prov = d.get('provenance', {})
    title = f'{month_name(b["init"])} initialization · {b["season"]} and its months'
    return f'''<div class="pcb" data-bench="{esc(b["name"])}">
  <h3>{esc(title)}</h3>
  <p><strong>Confirmed better than the incumbent climatology blend for the published tercile probabilities (RPS): {esc(listing(confirmed))}.</strong>
  ✓ = better than the incumbent with Holm-adjusted p &lt; 0.05 across every method and target (SEL: across the targets) and not worse
  over {te}. Amount correction fixed: {esc(d['amount_method'].upper())}. National aggregate ({esc(d['regions'][reg])}). Run at commit
  <code>{esc((prov.get('commit') or '')[:7])}</code>{' (with uncommitted changes)' if prov.get('uncommitted_changes') else ''}.</p>
  {tbl(head, t_rpss, f'Tercile RPSS, outer leave-one-year-out {tr} (bold: incumbent)')}
  {tbl(head, t_test, f'Tercile RPSS, fit {tr}, scored {te} (exploratory)')}
  <details><summary>Log loss, Brier skill, tests, fitted parameters and the selection</summary>
  {tbl(head, t_ll, f'Log-loss skill against climatology, {tr}')}
  {tbl(head, t_bb, f'Brier skill, below normal, {tr}')}
  {tbl(head, t_ba, f'Brier skill, above normal, {tr}')}
  {tbl(['Method', 'Target', f'Δ RPS {tr}', 'Years better', 'Holm p', f'Δ RPS {te}', 'Years better', 'Confirmed'], tests_rows,
       'Each method against the incumbent (negative Δ favours the method)')}
  {tbl(['Target', 'Blend weight λ', 'Temperature T', 'Ordinal cutpoints', 'Ordinal slopes (mean, log spread)', f'SEL choices ({tr} folds)', 'Fallbacks'],
       fit_rows, f'Fitted parameters (fit on {tr}) and the selection-aware choices')}
  </details>
  <figure class="map-figure wide"><img loading="lazy" src="assets/probcal/{esc(b["name"])}/probability_summary.png" alt="Probability calibration skill summary" style="max-width:100%;height:auto"><figcaption class="caveat">RPSS and log-loss skill by method and target.</figcaption></figure>
  <figure class="map-figure wide"><img loading="lazy" src="assets/probcal/{esc(b["name"])}/probability_reliability.png" alt="Reliability by method" style="max-width:100%;height:auto"><figcaption class="caveat">Reliability of each method for the season (below and above normal).</figcaption></figure>
  {binary_html(b)}
  {distribution_html(b)}
  {distribution_html(b, 'phase3')}
  {shadow_html(b)}
  <ul class="dl">{''.join(f'<li><a href="{esc(h)}" download>{esc(l)}</a><span>{n / 1e6:.1f} MB</span></li>' for h, l, n in files)}</ul>
</div>'''


def binary_html(b):
    """Phase 2, Pathway A: the one-vs-rest binary calibrators against the incumbent (their own family)."""
    d = b.get('binary')
    if not d:
        return ''
    reg = d['primary_region']
    order = json.loads((ROOT / d['config_contents']['benchmark_config']).read_text(encoding='utf-8'))['targets']
    T = [t for t in order if t in d['targets']]
    rows = d['methods'] + (['SEL'] if 'SEL' in d['targets'][T[0]]['methods'] else [])
    inc = d['incumbent']
    name = lambda m: 'SEL (chosen each year)' if m == 'SEL' else d['registry'][m]['name']
    conf = lambda m, t: m != inc and d['tests'].get(m, {}).get('rps', {}).get(t, {}).get('decision', {}).get('confirmed')
    cell = lambda m, t, design: (signed(d['targets'][t]['methods'][m][design][reg]['rpss']) + (' ✓' if design == 'training' and conf(m, t) else ''))
    bold = lambda m, x: f'<strong>{x}</strong>' if m == inc else x
    tr, te = years(d['training_years']), years(d['test_years'])
    found = [f'{name(m)} ({", ".join(t for t in T if conf(m, t))})' for m in rows if any(conf(m, t) for t in T)]
    head = ['Method'] + [esc(t) for t in T]
    return f'''<h4>Phase 2 · binary calibrators (one-vs-rest, normalized)</h4>
  <p>Platt, beta and isotonic calibration of each category against the rest, divided by their sum inside the pipeline, against the
  incumbent (their own family: Holm across these methods and the targets). <strong>Confirmed better: {esc(listing(found))}.</strong></p>
  {tbl(head, [[bold(m, esc(name(m)))] + [bold(m, cell(m, t, 'training')) for t in T] for m in rows], f'Tercile RPSS, outer leave-one-year-out {tr}')}
  <details><summary>Test years</summary>{tbl(head, [[bold(m, esc(name(m)))] + [bold(m, cell(m, t, 'test')) for t in T] for m in rows],
                                             f'Tercile RPSS, fit {tr}, scored {te} (exploratory)')}</details>'''


def distribution_html(b, key='distribution'):
    """Pathway B (Phase 2 or 3): rainfall-distribution models against the published probabilities and the MVS-corrected ensemble."""
    d = b.get(key)
    if not d:
        return ''
    phase = d.get('phase', 2)
    reg = d['primary_region']
    order = json.loads((ROOT / d['config_contents']['benchmark_config']).read_text(encoding='utf-8'))['targets']
    T = [t for t in order if t in d['targets']]
    head = ['Method'] + [esc(t) for t in T]
    v = lambda k, design, key, t: d['targets'][t]['methods'][k][design][reg].get(key)
    conf = lambda k, sc, t: d['tests'][k][sc][t]['decision']['confirmed']
    name = lambda k: d['registry'][k]['name']
    tr, te = years(d['training_years']), years(d['test_years'])
    rps_rows = [['<strong>Published probabilities (incumbent)</strong>'] + [f"<strong>{signed(v('incumbent', 'training', 'rpss', t))}</strong>" for t in T]]
    rps_rows += [[esc(name(k))] + [signed(v(k, 'training', 'rpss', t)) + (' ✓' if conf(k, 'rps', t) else '') for t in T] for k in d['models']]
    crps_rows = [['<strong>MVS-corrected ensemble</strong>'] + [f"<strong>{signed(v('mvs_ensemble', 'training', 'crpss', t))}</strong>" for t in T]]
    crps_rows += [[esc(name(k))] + [signed(v(k, 'training', 'crpss', t)) + (' ✓' if conf(k, 'crps', t) else '') for t in T] for k in d['models']]
    cov_rows = [[esc('MVS-corrected ensemble')] + [pct(v('mvs_ensemble', 'training', 'coverage_80', t)) for t in T]]
    cov_rows += [[esc(name(k))] + [pct(v(k, 'training', 'coverage_80', t)) for t in T] for k in d['models']]
    pin_rows = [[esc('MVS-corrected ensemble')] + [num(v('mvs_ensemble', 'training', 'pinball_50', t)) for t in T]]
    pin_rows += [[esc(name(k))] + [num(v(k, 'training', 'pinball_50', t)) for t in T] for k in d['models']]
    test_rows = [[esc(name(k)) + ' (RPSS / CRPSS)'] + [f"{signed(v(k, 'test', 'rpss', t))} / {signed(v(k, 'test', 'crpss', t))}" for t in T] for k in d['models']]
    test_rows.insert(0, ['Published probabilities / MVS ensemble'] + [f"{signed(v('incumbent', 'test', 'rpss', t))} / {signed(v('mvs_ensemble', 'test', 'crpss', t))}" for t in T])
    found = {sc: [f'{name(k)} ({", ".join(t for t in T if conf(k, sc, t))})' for k in d['models'] if any(conf(k, sc, t) for t in T)] for sc in ('rps', 'crps')}
    reg_rows = [[esc(name(k)), esc(r['estimates']), esc(r['predictors']), esc(r['fitting']), esc(r['outputs'])] for k, r in d['registry'].items()]
    return f'''<h4>Phase {phase} · rainfall-distribution models (Pathway B)</h4>
  <p>Each model predicts a full rainfall distribution from the raw ensemble (pooled over cells in units relative to each cell's
  climatology); terciles at the training CHIRPS boundaries, quantiles and intervals come from it. References, in the same folds:
  the published probabilities (tercile RPS) and the MVS-corrected ensemble (CRPS, quantiles). ✓ = better than the reference with
  Holm-adjusted p &lt; 0.05 across the models and targets, and not worse over {te}. <strong>Confirmed better — tercile probabilities:
  {esc(listing(found['rps']))}; rainfall amounts (CRPS): {esc(listing(found['crps']))}.</strong></p>
  {tbl(head, rps_rows, f'Tercile RPSS, outer leave-one-year-out {tr}')}
  {tbl(head, crps_rows, f'Amount CRPSS against the CHIRPS climatology, {tr}')}
  <details><summary>Interval coverage, median pinball loss, test years and the model definitions</summary>
  {tbl(head, cov_rows, f'Share of observations inside the 10–90% interval, {tr} (80% is calibrated)')}
  {tbl(head, pin_rows, f'Pinball loss of the median (mm), {tr} (lower is better)')}
  {tbl(head, test_rows, f'Fit {tr}, scored {te} (exploratory)')}
  {tbl(['Model', 'Estimates', 'Predictors', 'Fitting', 'Outputs'], reg_rows, 'Models')}</details>
  <figure class="map-figure wide"><img loading="lazy" src="assets/probcal/{esc(b["name"])}/{key}/distribution_summary.png" alt="Distribution models summary, Phase {phase}" style="max-width:100%;height:auto"><figcaption class="caveat">Tercile RPSS and amount CRPSS of the Phase {phase} distribution models against the published pipeline.</figcaption></figure>'''


def shadow_html(b):
    """The ongoing shadow rainfall-amount and range forecast (never published) and its season-by-season scores."""
    if not b.get('shadow'):
        return ''
    cfg = json.loads((ROOT / SHADOW_CONFIG).read_text(encoding='utf-8'))
    parts = []
    for year in sorted(b['shadow'], reverse=True):
        rows = b['shadow'][year]
        order = json.loads((ROOT / next(iter(rows.values()))['cycle']).read_text(encoding='utf-8'))['targets']
        T = [t for t in order if t in rows]
        fc, sc = [], []
        for t in T:
            r = rows[t]
            f = r['forecast']
            rng = lambda k: f"{f[k]['q50_mm']:.0f} ({f[k]['q10_mm']:.0f}–{f[k]['q90_mm']:.0f})"
            fc.append([esc(t), f"{f['climatology_mm']:.0f}", rng('shadow'), rng('mvs_ensemble'),
                       f"{f['shadow']['width_relative']:.2f} / {f['mvs_ensemble']['width_relative']:.2f}"])
            if r['observed']:
                s = r['scores'][r['primary_region']]
                sh, mv, pu = s['shadow'], s['mvs_ensemble'], s.get('published', {})
                sc.append([esc(t), pct(sh['coverage_80']), pct(mv['coverage_80']), signed(sh['crpss']), signed(mv['crpss']),
                           f"{sh['pinball_50']:.1f}", f"{mv['pinball_50']:.1f}",
                           signed(sh['rpss']) if 'rpss' in sh else '–', signed(pu['rpss']) if 'rpss' in pu else '–'])
        observed = [t for t in T if rows[t]['observed']]
        prov = next(iter(rows.values()))['provenance']
        figs = ''.join(f'''<details><summary>{esc(t)} {year}: maps</summary><figure class="map-figure wide"><img loading="lazy" src="assets/probcal/{esc(b["name"])}/amount_shadow/{year}/shadow_{esc(rows[t]["model"])}_{year}_{esc(t)}.png" alt="Shadow amounts and ranges {esc(t)} {year}" style="max-width:100%;height:auto"></figure></details>'''
                       for t in T)
        scored = (tbl(['Target', 'Coverage, shadow', 'Coverage, MVS', 'CRPSS, shadow', 'CRPSS, MVS', 'Median pinball, shadow (mm)',
                       'Median pinball, MVS (mm)', 'RPSS, shadow terciles', 'RPSS, published'], sc,
                      f'Scored against CHIRPS {year} (one season each; 80% coverage is calibrated)')
                  if sc else '<p class="caveat">Awaiting CHIRPS observations.</p>')
        parts.append(f'''<h5>{year} forecast · {len(observed)} of {len(T)} targets observed so far</h5>
  {tbl(['Target', 'Climatology (mm)', 'Shadow: median (10–90%), mm', 'MVS ensemble: median (10–90%), mm', 'Range width / climatology (shadow / MVS)'],
       fc, f'Forecast {year}: national area-weighted means over the modelled cells (fitted on {years(rows[T[0]]["reference_years"])})')}
  {scored}
  {figs}
  <p class="caveat">Run at commit <code>{esc((prov.get('commit') or '')[:7])}</code>{' (with uncommitted changes)' if prov.get('uncommitted_changes') else ''}.</p>''')
    return f'''<h4>Shadow forecast · rainfall amounts and ranges (EMOS), not published</h4>
  <p><strong>Not a published forecast.</strong> Since {esc(cfg['since'])}, each cycle also runs the EMOS distribution model (censored
  shifted gamma, fitted on the cycle's reference years) and records its median and 10–90% range for every target next to the
  MVS-corrected ensemble. {esc(cfg['reason'])} Each season is scored once its CHIRPS observations exist; any change to what is
  published is a separate decision after several seasons.</p>
  {''.join(parts)}'''


def section(blocks):
    if not blocks:
        return ''
    done = {1, 2} | ({3} if any(OUT.glob('*/phase3/benchmark.json')) else set())
    import re
    title = lambda h: re.search(r'<h3>(.*?)</h3>', h).group(1)
    last = len(blocks) - 1
    picker = ('<div class="map-controls"><label>Forecast cycle <select id="pc-bench">' +
              ''.join(f'<option value="{esc(n)}"{" selected" if i == last else ""}>{title(h)}</option>' for i, (n, h) in enumerate(blocks)) +
              '</select></label></div>')
    body = ''.join(h if i == last else h.replace('<div class="pcb"', '<div class="pcb" hidden', 1) for i, (_, h) in enumerate(blocks))
    plan = tbl(['Phase', 'Identifier', 'Method', 'Family', 'Output', 'Status'],
               [[str(ph), f'<code>{esc(k)}</code>', esc(m), esc(fam), esc(o), 'implemented, results below' if ph in done else 'planned']
                for ph, k, m, fam, o in PLAN], 'Implementation plan (the order is a plan, not a ranking of performance)')
    refs = ''.join(f'<li>{t}' + (f' <a href="{esc(u)}">{esc(u.replace("https://", ""))}</a>' if u else '') + '</li>' for t, u in REFERENCES)
    return f'''<section id="probcal" class="wrap">
  <h2>Probability and rainfall-distribution calibration</h2>
  <p>Can a different <em>probability</em> method improve the tercile probabilities users receive? The published pipeline is MVS-corrected
  members → smoothed member counts → climatology blend (the incumbent). <strong>Phase 1</strong> keeps the amount correction fixed
  (Pathway A) and replaces only the probability stage: every method starts from the same smoothed, unblended probabilities, except the
  logistic models, which use declared ensemble predictors (standardized ensemble mean and log spread ratio). Every parameter — the
  blend weight, the temperature, the Dirichlet map, the logistic coefficients — is fitted only on inner out-of-fold years within each
  left-out year, and a selection-aware procedure (SEL) chooses the method for each year by inner cross-validation. Later phases add
  binary-calibration extensions and full rainfall-distribution models (Pathway B). The published forecasts are unchanged.</p>
  {plan}
  <details><summary>Definitions kept distinct</summary><ul class="findings">
    <li><strong>Pseudocount smoothing</strong> p<sub>k</sub> = (n<sub>k</sub> + α)/(M + 3α) stabilizes count probabilities; the <strong>climatology
    blend</strong> p = (1 − λ)·p<sub>smooth</sub> + λ·p<sub>clim</sub> learns how much forecast information to keep. Both are kept as references.</li>
    <li><strong>Dirichlet calibration</strong> (a regularized linear map of the log probabilities, then softmax) is not pseudocount smoothing.</li>
    <li><strong>Dirichlet</strong> uses only the log probabilities; <strong>multinomial logistic</strong> uses only the ensemble predictors, so
    they are different models. <strong>Ordinal logistic</strong> uses the same predictors with ordered cutpoints (below → near → above).</li>
    <li>All methods are pooled over the grid cells of a target with equal weight per year; a method that cannot be fitted falls back to
    the incumbent and the fallback is counted.</li>
  </ul></details>
  {picker}{body}
  <p class="caveat">Full write-up: <a href="{REPO}/blob/main/{DOC}">{DOC}</a>. Code: <code>scripts/prob_calibration.py</code>,
  <code>scripts/prob_benchmark.py</code>.</p>
  <details><summary>References</summary><ol class="findings">{refs}</ol></details>
</section>'''
