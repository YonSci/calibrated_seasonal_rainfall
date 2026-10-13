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
]


def load_all():
    out = []
    for p in OUT.glob('*/benchmark.json'):
        d = json.loads(p.read_text(encoding='utf-8'))
        bench = json.loads((ROOT / d['config_contents']['benchmark_config']).read_text(encoding='utf-8'))
        project = json.loads((ROOT / bench['project_config']).read_text(encoding='utf-8'))
        out.append(dict(name=p.parent.name, folder=p.parent, data=d, init=project['initialization_month'], season=project['season']['name']))
    return sorted(out, key=lambda b: b['init'])


def export(out_dir):
    blocks = []
    for b in load_all():
        dest = out_dir / 'assets/probcal' / b['name']
        if (b['folder'] / 'figures').is_dir():
            shutil.copytree(b['folder'] / 'figures', dest, dirs_exist_ok=True)
        d = out_dir / 'downloads/probcal' / b['name'] / 'benchmark.json'
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(b['folder'] / 'benchmark.json', d)
        blocks.append((b['name'], block(b, (f'downloads/probcal/{b["name"]}/benchmark.json', d.stat().st_size))))
    return blocks


def block(b, download):
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
  <ul class="dl"><li><a href="{esc(download[0])}" download>All scores, per-year values, tests and fitted parameters (JSON)</a><span>{download[1] / 1e6:.1f} MB</span></li></ul>
</div>'''


def section(blocks):
    if not blocks:
        return ''
    import re
    title = lambda h: re.search(r'<h3>(.*?)</h3>', h).group(1)
    last = len(blocks) - 1
    picker = ('<div class="map-controls"><label>Forecast cycle <select id="pc-bench">' +
              ''.join(f'<option value="{esc(n)}"{" selected" if i == last else ""}>{title(h)}</option>' for i, (n, h) in enumerate(blocks)) +
              '</select></label></div>')
    body = ''.join(h if i == last else h.replace('<div class="pcb"', '<div class="pcb" hidden', 1) for i, (_, h) in enumerate(blocks))
    plan = tbl(['Phase', 'Identifier', 'Method', 'Family', 'Output', 'Status'],
               [[str(ph), f'<code>{esc(k)}</code>', esc(m), esc(fam), esc(o), 'implemented, results below' if ph == 1 else 'planned']
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
