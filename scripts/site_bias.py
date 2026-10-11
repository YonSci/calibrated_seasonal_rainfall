"""Site section "Bias correction": the rainfall bias-correction benchmark (scripts/bias_benchmark.py, docs/47).

Reads only the benchmark's result files (outputs/bias_correction_benchmark/<name>/). Every number on the section
comes from benchmark.json; each interpretation statement is shown only while the condition it states still holds
in the current results, so a rerun cannot leave a stale claim on the page.
"""
import html
import json
import shutil
from pathlib import Path

import numpy as np
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / 'outputs/bias_correction_benchmark'
REPO = 'https://github.com/YonSci/calibrated_seasonal_rainfall'
REPO_DOC = 'docs/47_BIAS_CORRECTION_BENCHMARK.md'

REFERENCES = {
    'Boe et al. 2007': ('Boé, J., Terray, L., Habets, F., & Martin, E. (2007). Statistical and dynamical downscaling of the Seine basin climate for hydro-meteorological studies. <em>International Journal of Climatology</em>, 27, 1643–1655.', '10.1002/joc.1602'),
    'Cannon et al. 2015': ('Cannon, A. J., Sobie, S. R., & Murdock, T. Q. (2015). Bias correction of GCM precipitation by quantile mapping: how well do methods preserve changes in quantiles and extremes? <em>Journal of Climate</em>, 28, 6938–6959.', '10.1175/JCLI-D-14-00754.1'),
    'Delle Monache et al. 2006': ('Delle Monache, L., Hacker, J. P., Zhou, Y., Deng, X., & Stull, R. B. (2006). Probabilistic aspects of meteorological and ozone regional ensemble forecasts. <em>Journal of Geophysical Research: Atmospheres</em>, 111, D24307.', '10.1029/2005JD006917'),
    'Ferro 2014': ('Ferro, C. A. T. (2014). Fair scores for ensemble forecasts. <em>Quarterly Journal of the Royal Meteorological Society</em>, 140, 1917–1923.', '10.1002/qj.2270'),
    'Gudmundsson et al. 2012': ('Gudmundsson, L., Bremnes, J. B., Haugen, J. E., & Engen-Skaugen, T. (2012). Technical Note: Downscaling RCM precipitation to the station scale using statistical transformations — a comparison of methods. <em>Hydrology and Earth System Sciences</em>, 16, 3383–3390.', '10.5194/hess-16-3383-2012'),
    'Hay et al. 2000': ('Hay, L. E., Wilby, R. L., & Leavesley, G. H. (2000). A comparison of delta change and downscaled GCM scenarios for three mountainous basins in the United States. <em>JAWRA Journal of the American Water Resources Association</em>, 36, 387–397.', '10.1111/j.1752-1688.2000.tb04276.x'),
    'Johnson et al. 2019': ('Johnson, S. J., Stockdale, T. N., Ferranti, L., et al. (2019). SEAS5: the new ECMWF seasonal forecast system. <em>Geoscientific Model Development</em>, 12, 1087–1117.', '10.5194/gmd-12-1087-2019'),
    'Leander & Buishand 2007': ('Leander, R., & Buishand, T. A. (2007). Resampling of regional climate model output for the simulation of extreme river flows. <em>Journal of Hydrology</em>, 332, 487–496.', '10.1016/j.jhydrol.2006.08.006'),
    'Lenderink et al. 2007': ('Lenderink, G., Buishand, A., & van Deursen, W. (2007). Estimates of future discharges of the river Rhine using two scenario methodologies: direct versus delta approach. <em>Hydrology and Earth System Sciences</em>, 11, 1145–1159.', '10.5194/hess-11-1145-2007'),
    'Manzanas et al. 2019': ('Manzanas, R., Gutiérrez, J. M., Bhend, J., et al. (2019). Bias adjustment and ensemble recalibration methods for seasonal forecasting: a comprehensive intercomparison using the C3S dataset. <em>Climate Dynamics</em>, 53, 1287–1305.', '10.1007/s00382-019-04640-4'),
    'Michelangeli et al. 2009': ('Michelangeli, P.-A., Vrac, M., & Loukos, H. (2009). Probabilistic downscaling approaches: application to wind cumulative distribution functions. <em>Geophysical Research Letters</em>, 36, L11708.', '10.1029/2009GL038401'),
    'Piani et al. 2010': ('Piani, C., Weedon, G. P., Best, M., et al. (2010). Statistical bias correction of global simulated daily precipitation and temperature for the application of hydrological models. <em>Journal of Hydrology</em>, 395, 199–215.', '10.1016/j.jhydrol.2010.10.024'),
    'Schmidli et al. 2006': ('Schmidli, J., Frei, C., & Vidale, P. L. (2006). Downscaling from GCM precipitation: a benchmark for dynamical and statistical downscaling methods. <em>International Journal of Climatology</em>, 26, 679–689.', '10.1002/joc.1287'),
    'Switanek et al. 2017': ('Switanek, M. B., Troch, P. A., Castro, C. L., et al. (2017). Scaled distribution mapping: a bias correction method that preserves raw climate model projected changes. <em>Hydrology and Earth System Sciences</em>, 21, 2649–2666.', '10.5194/hess-21-2649-2017'),
    'Teutschbein & Seibert 2012': ('Teutschbein, C., & Seibert, J. (2012). Bias correction of regional climate model simulations for hydrological climate-change impact studies: review and evaluation of different methods. <em>Journal of Hydrology</em>, 456–457, 12–29.', '10.1016/j.jhydrol.2012.05.052'),
    'Themessl et al. 2011': ('Themeßl, M. J., Gobiet, A., & Leuprecht, A. (2011). Empirical-statistical downscaling and error correction of daily precipitation from regional climate models. <em>International Journal of Climatology</em>, 31, 1530–1544.', '10.1002/joc.2168'),
    'Torralba et al. 2017': ('Torralba, V., Doblas-Reyes, F. J., MacLeod, D., Christel, I., & Davis, M. (2017). Seasonal climate prediction: a new source of information for the management of wind energy resources. <em>Journal of Applied Meteorology and Climatology</em>, 56, 1231–1247.', '10.1175/JAMC-D-16-0204.1'),
    'Vrac et al. 2012': ('Vrac, M., Drobinski, P., Merlo, A., et al. (2012). Dynamical and statistical downscaling of the French Mediterranean climate: uncertainty assessment. <em>Natural Hazards and Earth System Sciences</em>, 12, 2769–2784.', '10.5194/nhess-12-2769-2012'),
}
REF_LABEL = {'Boe et al. 2007': 'Boé et al. 2007', 'Themessl et al. 2011': 'Themeßl et al. 2011'}

FIGURES = [  # (file pattern, label, per target)
    ('skill_summary', 'Skill summary: CRPSS and RPSS by method and target, with gate marks', False),
    ('crpss_maps_{t}', 'CRPSS per cell (leave-one-year-out, all observed years)', True),
    ('crpss_minus_mvs_{t}', 'CRPSS difference from the operational MVS per cell', True),
    ('pit_{t}', 'Rank histograms (reliability of the corrected ensemble)', True),
    ('distribution', 'Distribution of the corrected members against CHIRPS', False),
    ('members_{year}_{t}', 'Every {year} member after each correction, at three cells', True),
    ('forecast_{year}_percent_{t}', '{year} corrected ensemble mean, % of normal, by method', True),
]


def esc(x):
    return html.escape(str(x))


def signed(x, d=3):
    return '—' if x is None or not np.isfinite(x) else f'{x:+.{d}f}'


def num(x, d=2):
    return '—' if x is None or not np.isfinite(x) else f'{x:.{d}f}'


def tbl(head, rows, caption='', cls='compact'):
    h = ''.join(f'<th scope="col">{c}</th>' for c in head)
    b = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in rows)
    cap = f'<caption>{caption}</caption>' if caption else ''
    return f'<div class="table-wrap"><table class="{cls}">{cap}<thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>'


def cite(key):
    text, doi = REFERENCES.get(key, (None, None))
    label = esc(REF_LABEL.get(key, key))
    return f'<a href="https://doi.org/{esc(doi)}">{label}</a>' if doi else label


# ---------------------------------------------------------------- export (files) and loading

def load_all():
    out = []
    for path in sorted(BENCH.glob('*/benchmark.json')):
        out.append(dict(name=path.parent.name, folder=path.parent, data=json.loads(path.read_text(encoding='utf-8'))))
    return out


def export(out_dir):
    """Copy figures and data files into the site. Returns [(name, html)] for the section."""
    blocks = []
    for bench in load_all():
        name, folder = bench['name'], bench['folder']
        fig_dest = out_dir / 'assets/bias' / name
        if (folder / 'figures').is_dir():
            shutil.copytree(folder / 'figures', fig_dest, dirs_exist_ok=True)
        files = []
        for fname, label in [('benchmark.json', 'All scores, per-year values and gate statistics (JSON)'),
                             ('cell_scores_full_loyo.nc', 'Per-cell scores and distribution ratios (NetCDF)'),
                             (f'forecast_{bench["data"]["config_contents"]["forecast_year"]}_members.nc',
                              'Corrected forecast members of every method (NetCDF)')]:
            if (folder / fname).is_file():
                dest = out_dir / 'downloads/bias' / name / fname
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(folder / fname, dest)
                files.append((f'downloads/bias/{name}/{fname}', label, (folder / fname).stat().st_size))
        blocks.append((name, block(bench, files)))
    return blocks


# ---------------------------------------------------------------- one benchmark

class View:
    def __init__(self, data):
        self.d = data
        self.cfg = data['config_contents']
        self.targets = list(data['targets'])
        self.season = self.targets[-1]
        self.months = self.targets[:-1]
        self.methods = list(data['targets'][self.targets[0]]['methods'])
        self.ref = self.cfg['reference_method']
        self.candidates = [m for m in self.methods if m != self.ref and m in data['gates']]
        self.primary = self.cfg['primary_region']
        self.year = self.cfg['forecast_year']

    def v(self, m, design, key, t, region=None):
        return self.d['targets'][t]['methods'][m][design][region or self.primary][key]

    def dist(self, m, key, t, region=None):
        return self.d['targets'][t]['methods'][m]['distribution_full'][region or self.primary][key]['area_median']

    def gate(self, m, score, t):
        return self.d['gates'][m][score][t]

    def adopt(self, m, score, t):
        return m in self.d['gates'] and self.gate(m, score, t)['decision']['adopt']

    def passed(self, m, score):
        return [t for t in self.targets if self.adopt(m, score, t)]

    def label(self, m):
        return self.d['methods'][m]['label']


def years(a):
    return f'{a[0]}–{a[1]}'


def listing(items):
    items = list(items)
    return ', '.join(items[:-1]) + (' and ' if len(items) > 1 else '') + items[-1] if items else 'none'


def region_cells(cfg):
    out = {}
    for k, spec in cfg['regions'].items():
        try:
            with xr.open_dataset(ROOT / spec['path']) as d:
                out[k] = int((d[spec['variable']].values == 1).sum())
        except (OSError, KeyError):
            out[k] = None
    return out


def data_table(V):
    cfg = V.cfg
    project = json.loads((ROOT / cfg['project_config']).read_text(encoding='utf-8'))
    cells = region_cells(cfg)
    regions = '; '.join(f'{esc(r["label"])}' + (f' ({cells[k]:,} cells)' if cells.get(k) else '') +
                        (' — primary' if k == V.primary else '') for k, r in cfg['regions'].items())
    rows = [
        ['Forecasts', f'ECMWF SEAS5 (system 51), initialized on 1 {esc(month_name(project["initialization_month"]))}; '
                      '25 members 1993–2016, 51 from 2017; remapped from 1° to the 0.25° CHIRPS grid by conservative remapping '
                      '(each 1° cell fills a 4 × 4 block). ' + cite('Johnson et al. 2019')],
        ['Observations', 'CHIRPS v3.0 monthly totals, averaged from 0.05° to 0.25°' if project.get('chirps_temporal') == 'monthly'
         else 'CHIRPS v2.0 daily totals'],
        ['Targets', f'{esc(", ".join(V.months))} and the {esc(V.season)} season; each corrected separately'],
        ['Values', 'One total per member, grid cell and year (mm), the same inputs as the operational tool '
                   f'(<code>data/processed/init{project["initialization_month"]:02d}_&lt;target&gt;/</code>)'],
        ['Observed years', f'{years(cfg["all_years"])} (seasons starting in these years)'],
        ['Training / test split', f'{years(cfg["training_years"])} (clean, gated) / {years(cfg["test_years"])} (exploratory)'],
        ['Cells', f'{V.d["targets"][V.season]["cells"]:,} grid cells of Ethiopia (0.25°); a cell is corrected only if CHIRPS '
                  'is complete in every training year'],
        ['Regions scored', regions],
        ['Weighting', 'Every member is used; each training year has total weight 1/Y (each member of year y weighs 1/(Y·M<sub>y</sub>)), '
                      'so years with 25 and 51 members count equally. Each observed year weighs 1/Y.'],
        ['Configuration', f'<code>{esc(V.d["config"])}</code>; run {esc(V.d["created_utc"][:16].replace("T", " "))} UTC'],
    ]
    return tbl(['Item', 'Details'], rows, 'Data used by the benchmark', 'compact')


def month_name(m):
    return ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
            'November', 'December'][m - 1]


def methods_table(V):
    rows = []
    for m in V.methods:
        info = V.d['methods'][m]
        params = {k: v for k, v in info['parameters'].items()}
        rows.append([
            f'<strong>{esc(info["label"])}</strong><br><code>{esc(m)}</code>',
            esc(info['family']),
            esc(info['definition']),
            ('yes' if info['member_wise'] else '<strong>no</strong> (one value per training year)'),
            ('yes' if info['uses_forecast_distribution'] else 'no'),
            '<code>' + esc(json.dumps(params)) + '</code>' if params else '—',
            ', '.join(cite(r) for r in info['references']),
        ])
    return tbl(['Method', 'Family', 'Definition (per cell and target)', 'Member-wise', 'Uses the forecast ensemble’s own distribution',
                'Parameters', 'References'], rows, f'{len(V.candidates)} methods, the operational reference and the raw baseline')


def steps_html(V):
    cfg = V.cfg
    steps = [
        ('Load', f'Per-member totals of every target and year, and CHIRPS for {years(cfg["all_years"])}.', 'bias_benchmark.py · run_calibration.load_inputs'),
        ('Fit', 'For each cell and target, the method’s statistics from the training years only, with equal-year weights.', 'bias_methods.METHODS[key].fit'),
        ('Apply', 'Correct every member of the scored year individually (member-wise).', 'bias_methods.METHODS[key].apply'),
        ('Score', 'Fair CRPS, ensemble-mean errors, spread–error, rank histograms, tercile RPS and distribution ratios, per cell; then area-weighted per year.', 'bias_benchmark.score_cells · summarise'),
        ('Gate', f'Each method against {V.label(V.ref)}: per-year scores, one-sided sign-flip test, Holm across the {len(V.targets)} targets, no harm in {years(cfg["test_years"])}.', 'significance.paired_summary · holm · gate'),
        ('Forecast', f'Fit on {years(cfg["all_years"])} and correct the {V.year} members of every method for member-by-member comparison.', 'bias_benchmark.save_forecast'),
    ]
    flow = ''.join(f'<li class="step"><span class="step-n">{i}</span><div><h4>{a}</h4><p>{b}</p><code>{c}</code></div></li>'
                   for i, (a, b, c) in enumerate(steps, 1))
    designs = tbl(['Design', 'Fits', 'Scored', 'Role'], [
        ['Training', f'leave-one-year-out within {years(cfg["training_years"])}', f'each {years(cfg["training_years"])} year', 'clean evidence; <strong>gated</strong>'],
        ['Operational', years(cfg['training_years']), years(cfg['test_years']), 'exploratory (these years were seen before)'],
        ['Full', f'leave-one-year-out within {years(cfg["all_years"])}', 'each year', 'per-cell maps and distribution checks (descriptive)'],
        ['Forecast', years(cfg['all_years']), f'{V.year} members', 'member-by-member comparison'],
    ], 'Evaluation designs (no method has a parameter tuned on scores, so leave-one-year-out is out-of-sample)')
    scores = tbl(['Score', 'What it measures', 'Reference'], [
        ['CRPS / CRPSS', 'Error of the whole corrected ensemble in mm (fair version, so ensembles of 25, 31 and 51 values compare); skill against the CHIRPS training climatology', cite('Ferro 2014')],
        ['Ensemble mean', 'Bias, MAE, RMSE and correlation over years', ''],
        ['Spread–error ratio', '√(mean ensemble variance·(K+1)/K) / RMSE of the ensemble mean; 1 = spread matches the error, &lt; 1 too narrow', ''],
        ['Rank histogram, reliability index', 'Position of CHIRPS within the ensemble (10 bins; each rank interval shared among the bins it overlaps); index Σ|f<sub>i</sub> − 1/10|, 0 = flat', cite('Delle Monache et al. 2006')],
        ['Tercile RPS / RPSS', f'α = {V.cfg["smoothing_alpha"]} smoothed member counts against the training CHIRPS terciles, <strong>without</strong> the climatology blend', ''],
        ['Distribution ratios', 'Pooled out-of-fold corrected members (equal-year weights) over CHIRPS of the same years: mean, standard deviation, 10th and 90th percentiles; area-weighted median over cells', ''],
        ['Gate', 'Adopt only if the 1993–2016 per-year improvement is significant (Holm-adjusted one-sided p &lt; 0.05 across targets) and the method is not worse over the test years (rule of docs/36)', ''],
    ], 'Scores')
    return f'<ol class="flow">{flow}</ol>{designs}{scores}'


def score_table(V, design, key, region, score=None, d=3):
    rows = []
    for m in V.methods:
        cells = []
        for t in V.targets:
            x = V.v(m, design, key, t, region)
            mark = ' ✓' if score and design == 'training' and V.adopt(m, score, t) and region == V.primary else ''
            txt = signed(x, d) + mark
            cells.append(f'<strong>{txt}</strong>' if m == V.ref else txt)
        rows.append([esc(V.label(m))] + cells)
    return rows


def results_html(V):
    cfg = V.cfg
    tr, te = years(cfg['training_years']), years(cfg['test_years'])
    out = []
    for region, spec in cfg['regions'].items():
        hidden = '' if region == V.primary else ' hidden'
        note = ('✓ = passes the gate against ' + esc(V.label(V.ref)) + '.' if region == V.primary
                else 'Gates are computed for the primary region (' + esc(cfg['regions'][V.primary]['label']) + ') only.')
        s = V.season
        glance = []
        for m in V.methods:
            g = lambda design, key: V.v(m, design, key, s, region)
            glance.append([esc(V.label(m)) if m != V.ref else f'<strong>{esc(V.label(m))}</strong>',
                           signed(g('training', 'crpss')) + (' ✓' if V.adopt(m, 'crps', s) and region == V.primary else ''),
                           signed(g('operational', 'crpss')),
                           signed(g('training', 'rpss')) + (' ✓' if V.adopt(m, 'rps', s) and region == V.primary else ''),
                           signed(g('operational', 'rpss')),
                           signed(g('training', 'mean_bias_mm'), 1), num(g('training', 'mean_mae_mm'), 1),
                           num(g('training', 'correlation')), num(g('training', 'spread_error_ratio')),
                           num(g('training', 'pit_reliability_index')), num(100 * g('training', 'zero_fraction'), 1)])
        head_t = ['Method'] + [esc(t) for t in V.targets]
        more = [
            tbl(head_t, score_table(V, 'operational', 'crpss', region), f'Amount skill (CRPSS), fit {tr}, scored {te}'),
            tbl(head_t, score_table(V, 'operational', 'rpss', region), f'Tercile skill (RPSS), fit {tr}, scored {te}'),
            tbl(head_t, score_table(V, 'training', 'mean_bias_mm', region, d=1), f'Ensemble-mean bias (mm), {tr}'),
            tbl(head_t, score_table(V, 'training', 'correlation', region, d=2), f'Correlation of the ensemble mean with CHIRPS over years, {tr}'),
            tbl(head_t, [[esc(V.label(m))] + [num(V.v(m, 'training', 'spread_error_ratio', t, region)) for t in V.targets] for m in V.methods],
                f'Spread–error ratio, {tr} (1 = spread matches the error)'),
            tbl(head_t, [[esc(V.label(m))] + [num(V.v(m, 'training', 'pit_reliability_index', t, region)) for t in V.targets] for m in V.methods],
                f'Rank-histogram reliability index, {tr} (0 = flat)'),
            tbl(head_t, [[esc(V.label(m))] + [num(100 * V.v(m, 'training', 'zero_fraction', t, region), 1) for t in V.targets] for m in V.methods],
                f'Share of corrected member values at 0 mm (%), {tr}'),
        ]
        dist = ''.join(tbl(head_t, [[esc(V.label(m))] + [num(V.dist(m, k, t, region)) for t in V.targets] for m in V.methods],
                           f'{lab} of the corrected members / CHIRPS (area-weighted median of cell ratios, {years(cfg["all_years"])}; 1 = same)')
                       for k, lab in [('mean_ratio', 'Mean'), ('sd_ratio', 'Standard deviation'), ('q10_ratio', '10th percentile'),
                                      ('q90_ratio', '90th percentile')])
        out.append(f'''<div data-region="{esc(region)}"{hidden}>
  <p class="caveat">{note} Bold: the operational method. Skill is against the CHIRPS training climatology (0 = no better than climatology).</p>
  {tbl(['Method', f'CRPSS {tr}', f'CRPSS {te}', f'RPSS {tr}', f'RPSS {te}', 'Mean bias (mm)', 'MAE (mm)', 'Correlation',
        'Spread–error', 'Reliability index', 'Zero values (%)'], glance, f'{esc(s)} season at a glance — {esc(spec["label"])}')}
  {tbl(head_t, score_table(V, 'training', 'crpss', region, 'crps'), f'Amount skill (CRPSS) by target, leave-one-year-out {tr} — gated on CRPS')}
  {tbl(head_t, score_table(V, 'training', 'rpss', region, 'rps'), f'Tercile skill (RPSS of smoothed counts, no blend) by target, {tr} — gated on RPS')}
  <details><summary>More scores by target: test years, bias, correlation, spread, reliability, zero values</summary>{''.join(more)}</details>
  <details><summary>Distribution of the corrected members (mean, spread, 10th and 90th percentiles)</summary>{dist}</details>
</div>''')
    seg = ''.join(f'<button type="button" data-bc-region="{esc(k)}" aria-pressed="{str(k == V.primary).lower()}">{esc(r["label"])}</button>'
                  for k, r in cfg['regions'].items())
    return f'<div class="map-controls"><span class="caveat">Region</span><div class="seg" role="group" aria-label="Region">{seg}</div></div>' + ''.join(out)


def gates_html(V):
    tr, te = years(V.cfg['training_years']), years(V.cfg['test_years'])
    parts = []
    for score, unit in [('crps', 'mm'), ('rps', '')]:
        rows = []
        for m in V.candidates:
            for t in V.targets:
                g = V.gate(m, score, t)
                a, b, dcs = g['training'], g['operational'], g['decision']
                d = 2 if score == 'crps' else 4
                rows.append([esc(V.label(m)), esc(t), f'{a["mean_difference"]:+.{d}f}',
                             f'{a["bootstrap_95"][0]:+.{d}f} to {a["bootstrap_95"][1]:+.{d}f}', f'{a["years_better"]}/{a["years"]}',
                             f'{a["p_improvement"]:.3f}', f'{dcs["holm_p"]:.3f}', f'{b["mean_difference"]:+.{d}f}',
                             f'{b["years_better"]}/{b["years"]}', '<strong>yes</strong>' if dcs['adopt'] else 'no'])
        parts.append(tbl(['Method', 'Target', f'Δ {score.upper()} {tr}' + (f' ({unit})' if unit else ''), '95% interval', 'Years better',
                          'p (one-sided)', 'Holm p', f'Δ {score.upper()} {te}', 'Years better', 'Passes'],
                         rows, f'Gate statistics, {score.upper()} (method minus {esc(V.label(V.ref))}; negative favours the method)'))
    return ''.join(parts)


def figures_html(V, name):
    kinds = ''.join(f'<option value="{esc(p.format(year=V.year, t="{t}"))}" data-per-target="{str(per).lower()}">{esc(l.format(year=V.year))}</option>'
                    for p, l, per in FIGURES)
    targets = ''.join(f'<option{" selected" if t == V.season else ""}>{esc(t)}</option>' for t in V.targets)
    return f'''<div class="bc-figs" data-figs="assets/bias/{esc(name)}">
  <div class="map-controls">
    <label>Figure <select class="bc-kind">{kinds}</select></label>
    <label>Target <select class="bc-target">{targets}</select></label>
    <a class="bc-open" href="#" target="_blank" rel="noopener">Open full size</a>
  </div>
  <figure class="map-figure wide"><img class="bc-img" loading="lazy" alt="" style="max-width:100%;height:auto"><figcaption class="caveat bc-cap"></figcaption></figure>
</div>'''


def findings(V):
    """(condition, text) pairs: a statement is shown only while its condition holds in the current results."""
    s, ref, P = V.season, V.ref, V.primary
    tr, te = years(V.cfg['training_years']), years(V.cfg['test_years'])
    L = lambda m: V.label(m).replace(' (operational)', '')        # prose: the method's name only
    cand = V.candidates
    out = []

    def add(cond, text):
        try:
            ok = bool(cond())
        except (KeyError, ValueError, TypeError):
            ok = False
        out.append((ok, text if ok else None))

    # 1. raw model
    def raw_text():
        mr = V.dist('raw', 'mean_ratio', s)
        worst = min(V.targets, key=lambda t: V.dist('raw', 'mean_ratio', t))
        return (f'<strong>Every method is far better than the raw model.</strong> Raw ECMWF scores CRPSS '
                f'{signed(V.v("raw", "training", "crpss", s))} for {esc(s)} ({tr}): its ensemble mean is '
                f'{100 * (1 - mr):.0f}% below CHIRPS for the season ({100 * (1 - V.dist("raw", "mean_ratio", worst)):.0f}% in {esc(worst)}) '
                f'and its spread is far too narrow (spread–error ratio {num(V.v("raw", "training", "spread_error_ratio", s))}).')
    add(lambda: 'raw' in V.methods and all(V.v(m, 'training', 'crpss', s) > V.v('raw', 'training', 'crpss', s) for m in cand + [ref]),
        raw_text() if 'raw' in V.methods else '')

    # 2. the consistent improvement: passes gates and is never worse than the reference
    best = [m for m in cand if consistent(V, m)]
    for m in best:
        z_ref = [100 * V.v(ref, 'training', 'zero_fraction', t) for t in V.months]
        z_m = [100 * V.v(m, 'training', 'zero_fraction', t) for t in V.months]
        add(lambda m=m: True,
            f'<strong>{esc(L(m))} is the consistent improvement.</strong> It passes the amount gate for '
            f'{esc(listing(V.passed(m, "crps")))} and the tercile gate for {esc(listing(V.passed(m, "rps")))}, and it is at least as good '
            f'as {esc(L(ref))} for every target in both periods and on both scores ({esc(s)} CRPSS '
            f'{signed(V.v(m, "training", "crpss", s))} vs {signed(V.v(ref, "training", "crpss", s))} in {tr}, '
            f'{signed(V.v(m, "operational", "crpss", s))} vs {signed(V.v(ref, "operational", "crpss", s))} in {te}). '
            f'Members clipped to 0 mm in the months: {min(z_ref):.1f}–{max(z_ref):.1f}% with {esc(L(ref))}, '
            f'{min(z_m):.1f}–{max(z_m):.1f}% with this method.')
    if not best:
        out.append((True, f'No method is at least as good as {esc(L(ref))} for every target in both periods; see the gate table.'))

    # 3. best test-period amount skill for the season
    top = max(cand, key=lambda m: V.v(m, 'operational', 'crpss', s))
    if top not in best:
        add(lambda: True,
            f'<strong>{esc(L(top))}</strong> has the best {esc(s)} amount skill over {te} ({signed(V.v(top, "operational", "crpss", s))} vs '
            f'{signed(V.v(ref, "operational", "crpss", s))}); it passes the amount gate for {esc(listing(V.passed(top, "crps")))} '
            f'and the tercile gate for {esc(listing(V.passed(top, "rps")))}.')

    # 4. EQM: matches the distribution, but loses skill for the season
    if 'eqm' in cand:
        add(lambda: V.v('eqm', 'training', 'crpss', s) < V.v(ref, 'training', 'crpss', s) and abs(V.dist('eqm', 'sd_ratio', s) - 1) < .05,
            f'<strong>{esc(L("eqm"))} reproduces the CHIRPS distribution best</strong> (standard-deviation ratio '
            f'{num(V.dist("eqm", "sd_ratio", s))} for {esc(s)}), and passes for {esc(listing(sorted(set(V.passed("eqm", "crps") + V.passed("eqm", "rps")), key=V.targets.index)))}, '
            f'but its {esc(s)} amount skill is lower than {esc(L(ref))} ({signed(V.v("eqm", "training", "crpss", s))} vs '
            f'{signed(V.v(ref, "training", "crpss", s))}): with {V.cfg["training_years"][1] - V.cfg["training_years"][0]} training '
            'years per fold, the CHIRPS quantile function has that many points and the mapping follows their noise.')

    # 5. the ratio limits
    if 'vs' in cand:
        hit = [t for t in V.targets if V.adopt('vs', 'crps', t) or V.adopt('vs', 'rps', t)]
        add(lambda: bool(hit) and all(V.v(ref, 'training', 'spread_error_ratio', t) < .9 for t in hit),
            f'<strong>The 0.5–2 limits of {esc(L(ref))} matter most where the raw model is far too narrow</strong> '
            f'({esc(listing(hit))}): there the upper limit binds and {esc(L(ref))} stays too narrow (spread–error '
            f'{listing([num(V.v(ref, "training", "spread_error_ratio", t)) for t in hit])}), while the unbounded form reaches '
            f'{listing([num(V.v("vs", "training", "spread_error_ratio", t)) for t in hit])} and passes the gate.')

    # 6. Delta Change
    if 'dc' in cand:
        add(lambda: V.v('dc', 'training', 'crpss', s) > V.v(ref, 'training', 'crpss', s) and not V.adopt('dc', 'crps', s)
            and V.v('dc', 'operational', 'crpss', s) < V.v(ref, 'operational', 'crpss', s),
            f'<strong>{esc(L("dc"))}</strong> has a high {esc(s)} CRPSS in {tr} ({signed(V.v("dc", "training", "crpss", s))}) but the gain is '
            f'not significant (Holm p = {V.gate("dc", "crps", s)["decision"]["holm_p"]:.2f}), it is worse in {te} '
            f'({signed(V.v("dc", "operational", "crpss", s))} vs {signed(V.v(ref, "operational", "crpss", s))}), its ensemble is too wide '
            f'(spread–error {num(V.v("dc", "training", "spread_error_ratio", s))}) and its tercile skill is low: it is essentially the '
            'CHIRPS climatology shifted by the forecast’s mean.')

    # 7. change-preserving methods
    cp = [m for m in cand if V.d['methods'][m]['uses_forecast_distribution'] and m != 'dc']
    if cp:
        add(lambda: all(V.v(m, 'training', 'rpss', s) < V.v(ref, 'training', 'rpss', s) for m in cp)
            and not any(V.adopt(m, sc, s) for m in cp for sc in ('crps', 'rps')),
            f'<strong>The methods that keep the forecast’s own distribution ({esc(", ".join(L(m) for m in cp))}) do not help here.</strong> '
            f'Their {esc(s)} tercile skill is lower ({" to ".join(signed(x) for x in sorted([V.v(m, "training", "rpss", s) for m in cp])[::len(cp) - 1 or 1])} '
            f'vs {signed(V.v(ref, "training", "rpss", s))}) and none passes a gate for the season. They were built to keep a climate-change '
            'signal over 30-year periods; here they rely on the distribution of a single forecast’s 25–51 members, which is too noisy. '
            'See the difference maps: they lose most where the season’s signal is.')

    # 8. mean-only methods
    mo = [m for m in ('ls', 'loci') if m in cand]
    if mo:
        add(lambda: all(V.v(m, 'training', 'spread_error_ratio', s) < .85 for m in mo),
            f'<strong>{esc(" and ".join(L(m) for m in mo))}</strong> correct the mean only (LOCI nearly so for totals that are always wet), '
            f'so the ensemble stays too narrow (spread–error {listing([num(V.v(m, "training", "spread_error_ratio", s)) for m in mo])} for {esc(s)}).')

    # 9. hard months
    hard = [t for t in V.months if all(V.v(m, 'operational', 'crpss', t) < 0 for m in cand + [ref])]
    add(lambda: bool(hard),
        f'<strong>{esc(listing(hard))} {"remains" if len(hard) == 1 else "remain"} hard:</strong> every method has negative amount skill '
        f'over {te}.')
    return out


def consistent(V, m):
    """Passes at least one gate and is never worse than the reference, for any target, period or score."""
    return bool(V.passed(m, 'crps') or V.passed(m, 'rps')) and all(
        V.v(m, d, k, t) >= V.v(V.ref, d, k, t) - 1e-9 for d in ('training', 'operational') for k in ('crpss', 'rpss') for t in V.targets)


def shortlist(V):
    """Consistent methods, then the best test-period season amount skill among methods that pass any gate;
    and the other methods that pass a gate for some targets only, with those targets."""
    passing = [m for m in V.candidates if V.passed(m, 'crps') or V.passed(m, 'rps')]
    best = [m for m in passing if consistent(V, m)]
    if passing:
        top = max(passing, key=lambda m: V.v(m, 'operational', 'crpss', V.season))
        if top not in best:
            best.append(top)
    partial = [(m, sorted(set(V.passed(m, 'crps') + V.passed(m, 'rps')), key=V.targets.index)) for m in passing if m not in best]
    return best, partial


def block(bench, files):
    V = View(bench['data'])
    name = bench['name']
    cfg = V.cfg
    found = findings(V)
    shown = [t for ok, t in found if ok and t]
    withheld = sum(1 for ok, _ in found if not ok)
    best, partial = shortlist(V)
    partial_txt = '; '.join(f'{esc(V.label(m))} ({esc(listing(t))})' for m, t in partial)
    dl = ''.join(f'<li><a href="{esc(h)}" download>{esc(l)}</a><span>{s / 1e6:.1f} MB</span></li>' for h, l, s in files)
    refs = ''.join(f'<li>{REFERENCES[k][0]} <a href="https://doi.org/{esc(REFERENCES[k][1])}">doi:{esc(REFERENCES[k][1])}</a></li>'
                   for k in sorted(REFERENCES))
    title = f'{month_name(json.loads((ROOT / cfg["project_config"]).read_text(encoding="utf-8"))["initialization_month"])} initialization · {V.season} and its months'
    return f'''<div class="bc" data-bench="{esc(name)}">
  <h3>{esc(title)}</h3>
  <p class="notice"><strong>Research benchmark.</strong> The published forecasts still use {esc(V.label(V.ref))}. This section compares
  {len(V.candidates)} other rainfall-amount bias-correction methods with it, member by member, for every grid cell and every target,
  under one protocol. A method that passes the gate here is a <em>candidate</em>: before it can replace the operational method it needs a
  confirmation run with the climatology blend, because the site’s probabilities are blended and {len(V.candidates)} methods were screened.</p>

  <h3>Summary</h3>
  <ul class="findings">{''.join(f'<li>{t}</li>' for t in shown[:3])}</ul>
  <p><strong>Shortlist for a confirmation run:</strong> {esc(listing([V.label(m) for m in best])) if best else 'none'}.
  {f'Passing the gate for some targets only: {partial_txt}.' if partial else ''}</p>

  <h3>Data</h3>
  {data_table(V)}

  <h3>Methods</h3>
  <p>Each method is fitted per grid cell and target from the training years only and applied to each member of the scored year.
  Methods that keep a “change signal” (DC, DQM, QDM, SDM, CDF-t) were designed for climate change, where a model’s reference period is
  compared with a future period; here the “future” is the forecast itself: the target year’s ensemble against the model climatology.</p>
  <details open><summary>How overlapping names were resolved</summary><ul class="findings">
    <li><strong>Delta Change</strong> appeared twice in the requested list; it is one method.</li>
    <li><strong>Mean–Variance Scaling</strong> is the operational method, with the project’s limits (ratio 0.5–2; mean-only where the model spread is below 1 mm). <strong>Variance Scaling</strong> is the textbook form with the same algebra and no limits, kept only to test those limits.</li>
    <li><strong>Delta Change</strong> is defined as the CHIRPS training years rescaled by the forecast signal (ensemble mean / model climatology), so it is the only method that is not member-wise; applied to each member it would be identical to Linear Scaling.</li>
    <li><strong>Square-root-space MVS</strong> (a mean–variance scaling of √x) is distinct from <strong>Power Transformation</strong> (a·x<sup>b</sup> with b fitted to the coefficient of variation).</li>
    <li>The <strong>raw model</strong> is scored as a baseline, not gated.</li>
  </ul></details>
  {methods_table(V)}

  <h3>Steps</h3>
  {steps_html(V)}

  <h3>Results</h3>
  {results_html(V)}
  <details><summary>Gate statistics for every method and target</summary>{gates_html(V)}</details>
  <h4>Figures</h4>
  {figures_html(V, name)}

  <h3>Interpretation</h3>
  <ol class="findings">{''.join(f'<li>{t}</li>' for t in shown)}</ol>
  {f'<p class="caveat">{withheld} statement(s) of the written interpretation no longer hold for the current results and are not shown.</p>' if withheld else ''}
  <div class="box"><h4>What this means</h4><ul class="findings">
    <li>Shortlist: {esc(listing([V.label(m) for m in best])) if best else 'none'} (a method at least as good as the operational one everywhere, then the best season skill over the test years among methods that pass a gate). The next step is a confirmation run with the climatology blend (nested λ, the <code>decision_gates.py</code> protocol), then a decision recorded in the docs.</li>
    <li>The operational method is unchanged until a candidate passes that confirmation.</li>
    <li>The same benchmark runs for the other cycles with one configuration file each (<code>config/bias_correction/</code>).</li>
  </ul></div>
  <details><summary>Caveats</summary><ul class="findings">
    <li>Skill is from {years(cfg["training_years"])} leave-one-year-out (clean) and {years(cfg["test_years"])} (exploratory: these years were seen while the operational method was chosen).</li>
    <li>Tercile scores here use smoothed member counts <strong>without</strong> the climatology blend, so they are lower than the blended skill shown under Historical performance.</li>
    <li>The gate is applied per method with Holm adjustment across targets, not across the {len(V.candidates)} methods; treat a pass as screening evidence.</li>
    <li>Scores are area-weighted over many correlated cells but tested year by year, so each year counts once.</li>
    <li>Delta Change has one value per training year instead of members; the fair CRPS makes its scores comparable.</li>
  </ul></details>

  <h3>Downloads and code</h3>
  <ul class="dl">{dl}
    <li><a href="{REPO}/blob/main/{REPO_DOC}">Full write-up (docs/47)</a><span>Definitions, design, all result tables and the references</span></li>
    <li><a href="{REPO}/blob/main/scripts/bias_methods.py">Code</a><span><code>scripts/bias_methods.py</code> (methods), <code>scripts/bias_benchmark.py</code> (runner), <code>config/bias_correction/{esc(name)}.json</code> (settings)</span></li>
  </ul>

  <details><summary>References</summary><ol class="findings">{refs}</ol>
  <p class="caveat">DOIs checked against Crossref, 11 October 2026.</p></details>
</div>'''


def section(blocks):
    if not blocks:
        return ''
    picker = ''
    if len(blocks) > 1:
        picker = ('<div class="map-controls"><label>Benchmark <select id="bc-bench">' +
                  ''.join(f'<option value="{esc(n)}">{esc(n)}</option>' for n, _ in blocks) + '</select></label></div>')
    body = ''.join(h if i == 0 else h.replace('<div class="bc"', '<div class="bc" hidden', 1) for i, (_, h) in enumerate(blocks))
    return f'''<section id="bias" class="wrap">
  <h2>Bias correction</h2>
  <p>How the model’s rainfall amounts are corrected toward CHIRPS, and how alternative bias-correction methods compare with the
  operational one: the data, every method’s definition, the steps, the results by target and region, and what they mean.</p>
  {picker}{body}
</section>'''
