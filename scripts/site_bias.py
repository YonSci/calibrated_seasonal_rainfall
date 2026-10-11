"""Site section "Bias correction": the rainfall bias-correction benchmark (scripts/bias_benchmark.py,
scripts/bias_confirmation.py, docs/47).

Reads only the benchmark's result files (outputs/bias_correction_benchmark/<name>/). Every number on the section
comes from benchmark.json or confirmation.json; each interpretation statement is shown only while the condition it
states still holds in the current results, so a rerun cannot leave a stale claim on the page. Statements and
figures refer to the national aggregate (the primary region); the region switch changes the result tables only.
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

FIGURES = [  # (file pattern, label, per target); scope: national (primary region) unless a map
    ('skill_summary', 'Screening summary: CRPSS and RPSS by method and target, with screening marks', False),
    ('confirmation/confirmation_summary', 'Confirmation: blended RPSS and amount CRPSS through the full pipeline', False),
    ('confirmation/confirmation_reliability', 'Confirmation: reliability of the blended probabilities (season)', False),
    ('confirmation/confirmation_selection', 'Confirmation: method chosen each year by the selection-aware procedures', False),
    ('crpss_maps_{t}', 'CRPSS per cell (leave-one-year-out, all observed years; descriptive)', True),
    ('crpss_minus_mvs_{t}', 'CRPSS difference from the operational MVS per cell (descriptive)', True),
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


def pct(x, d=0):
    return '—' if x is None or not np.isfinite(x) else f'{100 * x:.{d}f}%'


def tbl(head, rows, caption='', cls='compact', head_html=None):
    h = head_html or ('<tr>' + ''.join(f'<th scope="col">{c}</th>' for c in head) + '</tr>')
    b = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in rows)
    cap = f'<caption>{caption}</caption>' if caption else ''
    return f'<div class="table-wrap"><table class="{cls}">{cap}<thead>{h}</thead><tbody>{b}</tbody></table></div>'


def cite(key):
    text, doi = REFERENCES.get(key, (None, None))
    label = esc(REF_LABEL.get(key, key))
    return f'<a href="https://doi.org/{esc(doi)}">{label}</a>' if doi else label


def listing(items):
    items = list(items)
    return ', '.join(items[:-1]) + (' and ' if len(items) > 1 else '') + items[-1] if items else 'none'


def years(a):
    return f'{a[0]}–{a[1]}'


def month_name(m):
    return ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
            'November', 'December'][m - 1]


# ---------------------------------------------------------------- export (files) and loading

def load_all():
    out = []
    for path in sorted(BENCH.glob('*/benchmark.json')):
        conf = path.parent / 'confirmation/confirmation.json'
        out.append(dict(name=path.parent.name, folder=path.parent, data=json.loads(path.read_text(encoding='utf-8')),
                        confirmation=json.loads(conf.read_text(encoding='utf-8')) if conf.is_file() else None))
    return out


def export(out_dir):
    """Copy figures and data files into the site. Returns [(name, html)] for the section."""
    blocks = []
    for bench in load_all():
        name, folder = bench['name'], bench['folder']
        fig_dest = out_dir / 'assets/bias' / name
        if (folder / 'figures').is_dir():
            shutil.copytree(folder / 'figures', fig_dest, dirs_exist_ok=True)
        if (folder / 'confirmation/figures').is_dir():
            shutil.copytree(folder / 'confirmation/figures', fig_dest / 'confirmation', dirs_exist_ok=True)
        files = []
        year = bench['data']['config_contents']['forecast_year']
        for fname, label in [('benchmark.json', 'Screening: all scores, per-year values, diagnostics and screening statistics (JSON)'),
                             ('confirmation/confirmation.json', 'Confirmation: full-pipeline scores, selections and tests (JSON)'),
                             ('cell_scores_full_loyo.nc', 'Per-cell scores and distribution ratios (NetCDF)'),
                             (f'forecast_{year}_members.nc', 'Corrected forecast members of every method (NetCDF)'),
                             ('manifest.json', 'Output manifest: SHA-256 of every screening output file (JSON)')]:
            if (folder / fname).is_file():
                dest = out_dir / 'downloads/bias' / name / fname
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(folder / fname, dest)
                files.append((f'downloads/bias/{name}/{fname}', label, (folder / fname).stat().st_size))
        blocks.append((name, block(bench, files)))
    return blocks


# ---------------------------------------------------------------- one benchmark

class View:
    def __init__(self, data, confirmation=None):
        self.d = data
        self.c = confirmation
        self.cfg = data['config_contents']
        self.targets = list(data['targets'])
        self.season = self.targets[-1]
        self.months = self.targets[:-1]
        self.methods = list(data['targets'][self.targets[0]]['methods'])
        self.ref = self.cfg['reference_method']
        self.candidates = [m for m in self.methods if m != self.ref and m in data['gates']]
        self.primary = self.cfg['primary_region']
        self.year = self.cfg['forecast_year']
        self.tr, self.te = years(self.cfg['training_years']), years(self.cfg['test_years'])
        self.national = self.cfg['regions'][self.primary]['label']

    def v(self, m, design, key, t, region=None):
        return self.d['targets'][t]['methods'][m][design][region or self.primary][key]

    def dist(self, m, key, t, region=None, stat='area_median'):
        return self.d['targets'][t]['methods'][m]['distribution_full'][region or self.primary][key][stat]

    def gate(self, m, score, t):
        return self.d['gates'][m][score][t]

    def screen(self, m, score, t, family=False):
        return m in self.d['gates'] and self.gate(m, score, t)['decision']['screen_pass_family' if family else 'screen_pass']

    def passed(self, m, score, family=False):
        return [t for t in self.targets if self.screen(m, score, t, family)]

    def label(self, m):
        return self.d['methods'][m]['label'] if m in self.d['methods'] else m

    def short(self, m):
        return self.label(m).replace(' (operational)', '')

    def mark(self, m, score, t):
        return ' ✓✓' if self.screen(m, score, t, True) else (' ✓' if self.screen(m, score, t) else '')

    # confirmation
    def cv(self, m, design, key, t, region=None):
        node = self.c['targets'][t]['selection'][m] if m.startswith('SEL') else self.c['targets'][t]['methods'][m]
        return node[design][region or self.primary][key]

    def confirmed(self, m, score, t):
        try:
            return self.c['tests'][m][score][t]['decision']['confirmed']
        except (KeyError, TypeError):
            return False


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
                        (' — primary (national aggregate)' if k == V.primary else '') for k, r in cfg['regions'].items())
    cov = {t: V.v(V.ref, 'training', 'coverage', t) for t in V.targets}
    coverage = '; '.join(f'{esc(t)} {pct(cov[t]["amount_area_share"])} / {pct(cov[t]["probability_area_share"])}' for t in V.targets)
    prov = V.d.get('provenance', {})
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
        ['Training / test years', f'{V.tr} (clean evidence) / {V.te} (exploratory)'],
        ['Cells', f'{V.d["targets"][V.season]["cells"]:,} grid cells of Ethiopia (0.25°); a cell is corrected only if CHIRPS '
                  'is complete in every training year'],
        ['Regions scored', regions],
        ['Score coverage (amounts / probabilities, share of the national area)',
         coverage + '. Tercile scores need three distinct tercile limits (standard deviation ≥ 1 mm and a lower limit above 0), '
                    'so dry months have fewer probability cells.'],
        ['Dry totals', f'≤ {cfg.get("dry_threshold_mm", 1.0):g} mm in a month or season (not a dry day); exactly 0 mm is reported separately'],
        ['Weighting', 'Every member is used; each training year has total weight 1/Y (each member of year y weighs 1/(Y·M<sub>y</sub>)), '
                      'so years with 25 and 51 members count equally. Each observed year weighs 1/Y.'],
        ['Run', f'<code>{esc(V.d["config"])}</code>; {esc(V.d["created_utc"][:16].replace("T", " "))} UTC; commit '
                f'<code>{esc((prov.get("commit") or "unknown")[:10])}</code>'
                + (' (with uncommitted changes)' if prov.get('uncommitted_changes') else '')
                + f'; scoring version {prov.get("scoring_version", "1")}'],
    ]
    return tbl(['Item', 'Details'], rows, 'Data used by the benchmark')


def methods_table(V):
    rows = []
    for m in V.methods:
        info = V.d['methods'][m]
        params = info['parameters']
        rows.append([
            f'<strong>{esc(info["label"])}</strong><br><code>{esc(m)}</code>', esc(info['family']), esc(info['definition']),
            ('yes' if info['member_wise'] else '<strong>no</strong> (one value per training year)'),
            ('yes' if info['uses_forecast_distribution'] else 'no'),
            '<code>' + esc(json.dumps(params)) + '</code>' if params else '—',
            ', '.join(cite(r) for r in info['references'])])
    return tbl(['Method', 'Family', 'Definition (per cell and target)', 'Member-wise', 'Uses the forecast ensemble’s own distribution',
                'Parameters', 'References'], rows, f'{len(V.candidates)} methods, the operational reference and the raw baseline')


def steps_html(V):
    cfg = V.cfg
    steps = [
        ('Load', f'Per-member totals of every target and year, and CHIRPS for {years(cfg["all_years"])}.', 'bias_benchmark.py · run_calibration.load_inputs'),
        ('Fit', 'For each cell and target, the method’s statistics from the training years only, with equal-year weights.', 'bias_methods.METHODS[key].fit'),
        ('Apply', 'Correct every member of the scored year individually (member-wise).', 'bias_methods.METHODS[key].apply'),
        ('Score', 'Ensemble CRPS (and fair CRPS), ensemble-mean errors, spread–error, rank histograms, tercile RPS, dry shares and distribution ratios, per cell; then area-weighted per year.', 'bias_benchmark.score_cells · summarise'),
        ('Screen', f'Each method against {V.short(V.ref)} per target: one-sided sign-flip test on whole years, Holm within the method and across all methods, no harm in {V.te}.', 'bias_benchmark.make_gates'),
        ('Confirm', 'Every method through the full probability pipeline (blend weight fitted inside the folds), and selection-aware procedures that choose the method each year from training-only scores.', 'bias_confirmation.py'),
    ]
    flow = ''.join(f'<li class="step"><span class="step-n">{i}</span><div><h4>{a}</h4><p>{b}</p><code>{c}</code></div></li>'
                   for i, (a, b, c) in enumerate(steps, 1))
    designs = tbl(['Design', 'Fits', 'Scored', 'Role'], [
        ['Screening: training', f'leave-one-year-out within {V.tr}', f'each {V.tr} year', 'clean evidence for the screening'],
        ['Screening: test', V.tr, V.te, 'exploratory (these years were seen before)'],
        ['Screening: full', f'leave-one-year-out within {years(cfg["all_years"])}', 'each year', 'per-cell maps and distribution checks (descriptive)'],
        ['Confirmation', f'outer leave-one-year-out within {V.tr}; inside each fold the blend weight (inner leave-one-year-out) and, for SEL-P/SEL-A, the method choice', f'each {V.tr} year', 'full pipeline; accounts for the method choice'],
        ['Confirmation: test', f'{V.tr} (fits, blend weight and method choice)', V.te, 'exploratory'],
        ['Forecast', years(cfg['all_years']), f'{V.year} members', 'member-by-member comparison'],
    ], 'Evaluation designs (no amount method has a parameter tuned on scores)')
    scores = tbl(['Score', 'What it measures', 'Reference'], [
        ['CRPS / CRPSS', 'Error of the corrected ensemble’s empirical distribution, as delivered, in mm; skill against the CHIRPS training climatology (the training years as an ensemble). Primary amount score.', ''],
        ['Fair CRPS / CRPSS', 'The same under the interpretation that the members are a sample of an underlying distribution; reported as a diagnostic and screened separately. The justification assumes exchangeable members, which DC’s rescaled years and methods tied to the forecast mean or ranks only approximate.', cite('Ferro 2014')],
        ['Ensemble mean', 'Bias, MAE, RMSE and correlation over years', ''],
        ['Spread–error ratio', '√(mean ensemble variance·(K+1)/K) / RMSE of the ensemble mean; 1 = spread matches the error, &lt; 1 too narrow', ''],
        ['Rank histogram, reliability index', 'Position of CHIRPS within the ensemble (10 bins; each rank interval shared among the bins it overlaps); index Σ|f<sub>i</sub> − 1/10|, 0 = flat', cite('Delle Monache et al. 2006')],
        ['Tercile RPS / RPSS (screening)', f'α = {cfg["smoothing_alpha"]} smoothed member counts against the training CHIRPS terciles, <strong>without</strong> the blend: isolates the amount correction', ''],
        ['Blended RPSS, Brier skill, reliability (confirmation)', 'The published probability product: counts, smoothing and the climatology blend with its weight fitted inside the folds; category Brier skill for below and above normal; reliability tables', ''],
        ['Dry shares and distribution ratios', 'Pooled out-of-fold corrected members (equal-year weights) against CHIRPS of the same years: shares at exactly 0 mm and at ≤ 1 mm; mean, standard deviation, 10th and 90th percentile ratios (area-weighted medians)', ''],
    ], 'Scores')
    return f'<ol class="flow">{flow}</ol>{designs}{scores}'


def score_rows(V, design, key, region, score=None, d=3):
    rows = []
    for m in V.methods:
        cells = []
        for t in V.targets:
            txt = signed(V.v(m, design, key, t, region), d)
            if score and design == 'training' and region == V.primary:
                txt += V.mark(m, score, t)
            cells.append(f'<strong>{txt}</strong>' if m == V.ref else txt)
        rows.append([esc(V.label(m))] + cells)
    return rows


def results_html(V):
    cfg = V.cfg
    tr, te = V.tr, V.te
    out = []
    head_t = ['Method'] + [esc(t) for t in V.targets]
    for region, spec in cfg['regions'].items():
        hidden = '' if region == V.primary else ' hidden'
        primary = region == V.primary
        note = ('✓ = screening pass within the method (Holm across its targets); ✓✓ = also passes with Holm across all methods '
                'and targets. A pass is screening evidence, not an adoption decision.' if primary
                else f'Screening marks are computed for the national aggregate ({esc(V.national)}) only.')
        s = V.season
        glance = []
        for m in V.methods:
            g = lambda design, key: V.v(m, design, key, s, region)
            glance.append([f'<strong>{esc(V.label(m))}</strong>' if m == V.ref else esc(V.label(m)),
                           signed(g('training', 'crpss')) + (V.mark(m, 'crps', s) if primary else ''),
                           signed(g('operational', 'crpss')),
                           signed(g('training', 'rpss')) + (V.mark(m, 'rps', s) if primary else ''),
                           signed(g('operational', 'rpss')),
                           signed(g('training', 'mean_bias_mm'), 1), num(g('training', 'mean_mae_mm'), 1),
                           num(g('training', 'correlation')), num(g('training', 'spread_error_ratio')),
                           num(g('training', 'pit_reliability_index')), pct(g('training', 'dry_fraction'), 1)])
        head_html = (f'<tr><th scope="col" rowspan="2">Method</th><th scope="colgroup" colspan="2">Amount CRPSS</th>'
                     f'<th scope="colgroup" colspan="2">Tercile RPSS (no blend)</th>'
                     f'<th scope="colgroup" colspan="6">Diagnostics, leave-one-year-out {tr}</th></tr>'
                     f'<tr><th scope="col">{tr}</th><th scope="col">{te}</th><th scope="col">{tr}</th><th scope="col">{te}</th>'
                     '<th scope="col">Mean bias (mm)</th><th scope="col">MAE (mm)</th><th scope="col">Correlation</th>'
                     '<th scope="col">Spread–error</th><th scope="col">Reliability index</th><th scope="col">Members ≤ 1 mm</th></tr>')
        cov = [[esc(t), f'{V.v(V.ref, "training", "coverage", t, region)["amount_cells"]:.0f}',
                pct(V.v(V.ref, 'training', 'coverage', t, region)['amount_area_share']),
                f'{V.v(V.ref, "training", "coverage", t, region)["probability_cells"]:.0f}',
                pct(V.v(V.ref, 'training', 'coverage', t, region)['probability_area_share'])] for t in V.targets]
        more = [
            tbl(head_t, score_rows(V, 'operational', 'crpss', region), f'Amount skill (CRPSS), fit {tr}, scored {te}'),
            tbl(head_t, score_rows(V, 'training', 'crpss_fair', region, 'crps_fair'), f'Amount skill with the fair CRPS (diagnostic), {tr}'),
            tbl(head_t, score_rows(V, 'operational', 'rpss', region), f'Tercile skill (RPSS, no blend), fit {tr}, scored {te}'),
            tbl(head_t, score_rows(V, 'training', 'mean_bias_mm', region, d=1), f'Ensemble-mean bias (mm), {tr}'),
            tbl(head_t, score_rows(V, 'training', 'correlation', region, d=2), f'Correlation of the ensemble mean with CHIRPS over years, {tr}'),
            tbl(head_t, [[esc(V.label(m))] + [num(V.v(m, 'training', 'spread_error_ratio', t, region)) for t in V.targets] for m in V.methods],
                f'Spread–error ratio, {tr} (1 = spread matches the error)'),
            tbl(head_t, [[esc(V.label(m))] + [num(V.v(m, 'training', 'pit_reliability_index', t, region)) for t in V.targets] for m in V.methods],
                f'Rank-histogram reliability index, {tr} (0 = flat)'),
            tbl(['Target', 'Amount cells', 'Amount area', 'Probability cells', 'Probability area'], cov,
                f'Score coverage, mean per year, {tr} (share of the region’s area)'),
        ]
        dry = []
        for t in V.targets:
            obs0, obs1 = V.dist(V.ref, 'zero_share_obs', t, region, 'area_mean'), V.dist(V.ref, 'dry_share_obs', t, region, 'area_mean')
            dry.append([f'<strong>{esc(t)}</strong>: CHIRPS', pct(obs0, 1), pct(obs1, 1)] + [''] * 0)
            for m in V.methods:
                dry.append([esc(V.label(m)), pct(V.dist(m, 'zero_share_corrected', t, region, 'area_mean'), 1),
                            pct(V.dist(m, 'dry_share_corrected', t, region, 'area_mean'), 1)])
        dist = ''.join(tbl(head_t, [[esc(V.label(m))] + [num(V.dist(m, k, t, region)) for t in V.targets] for m in V.methods],
                           f'{lab} of the corrected members / CHIRPS (area-weighted median of cell ratios, {years(cfg["all_years"])}; 1 = same)')
                       for k, lab in [('mean_ratio', 'Mean'), ('sd_ratio', 'Standard deviation'), ('q10_ratio', '10th percentile'),
                                      ('q90_ratio', '90th percentile')])
        out.append(f'''<div data-region="{esc(region)}"{hidden}>
  <p class="caveat">Tables for: <strong>{esc(spec["label"])}</strong>. {note} Bold: the operational method. Skill is against the CHIRPS training climatology (0 = no better than climatology).</p>
  {tbl([], glance, f'{esc(s)} season at a glance — {esc(spec["label"])}', head_html=head_html)}
  {tbl(head_t, score_rows(V, 'training', 'crpss', region, 'crps'), f'Amount skill (CRPSS) by target, leave-one-year-out {tr}')}
  {tbl(head_t, score_rows(V, 'training', 'rpss', region, 'rps'), f'Tercile skill (RPSS of smoothed counts, no blend) by target, {tr}')}
  <details><summary>More scores by target: test years, fair CRPS, bias, correlation, spread, reliability, coverage</summary>{''.join(more)}</details>
  <details><summary>Dry months: shares of totals at exactly 0 mm and at ≤ 1 mm, CHIRPS and corrected</summary>
    {tbl(['', 'Exactly 0 mm', '≤ 1 mm'], dry, f'Area-weighted mean share over cells, pooled leave-one-year-out {years(cfg["all_years"])}')}</details>
  <details><summary>Distribution of the corrected members (mean, spread, 10th and 90th percentiles)</summary>{dist}</details>
</div>''')
    seg = ''.join(f'<button type="button" data-bc-region="{esc(k)}" aria-pressed="{str(k == V.primary).lower()}">{esc(r["label"])}</button>'
                  for k, r in cfg['regions'].items())
    return (f'<div class="map-controls"><span class="caveat">Region for the result tables</span><div class="seg" role="group" '
            f'aria-label="Region for the result tables">{seg}</div></div>' + ''.join(out))


def diagnostics_html(V):
    rows = []
    for m in V.methods:
        for t in V.targets:
            dg = V.d['targets'][t]['methods'][m].get('diagnostics_training', {})
            parts = [f'{esc(k.replace("_", " "))}: {pct(v, 1)} of the area' for k, v in dg.get('cell_area_share', {}).items() if v]
            parts += [f'{esc(k.replace("_", " "))}: {pct(v, 1)}' for k, v in dg.get('event_share', {}).items() if v]
            if parts:
                rows.append([esc(V.label(m)), esc(t), '; '.join(parts)])
    return tbl(['Method', 'Target', 'Activated (share of the corrected area, or of members / cells for events)'], rows,
               f'How often limits, caps and fallbacks act, leave-one-year-out {V.tr} (mean over folds)')


def gates_html(V):
    parts = []
    for score, unit, d in [('crps', 'mm', 2), ('crps_fair', 'mm', 2), ('rps', '', 4)]:
        rows = []
        for m in V.candidates:
            for t in V.targets:
                g = V.gate(m, score, t)
                a, b, dc = g['training'], g['operational'], g['decision']
                rows.append([esc(V.label(m)), esc(t), f'{a["mean_difference"]:+.{d}f}',
                             f'{a["bootstrap_95"][0]:+.{d}f} to {a["bootstrap_95"][1]:+.{d}f}', f'{a["years_better"]}/{a["years"]}',
                             f'{a["p_improvement"]:.4f}', f'{dc["holm_p"]:.4f}', f'{dc["holm_p_family"]:.4f}',
                             f'{b["mean_difference"]:+.{d}f}', '✓✓' if dc['screen_pass_family'] else ('✓' if dc['screen_pass'] else '—')])
        label = {'crps': 'CRPS', 'crps_fair': 'fair CRPS', 'rps': 'RPS (no blend)'}[score]
        parts.append(tbl(['Method', 'Target', f'Δ {label} {V.tr}' + (f' ({unit})' if unit else ''), '95% interval', 'Years better',
                          'p (one-sided)', 'Holm p (method)', f'Holm p (all {len(V.candidates) * len(V.targets)})', f'Δ {V.te}', 'Screening'],
                         rows, f'Screening statistics, {label} (method minus {esc(V.short(V.ref))}; negative favours the method)'))
    return f'<p class="caveat">{esc(V.d["gate_rule"])}</p>' + ''.join(parts)


def confirmation_html(V):
    if not V.c:
        return '<p class="notice">The confirmation run has not been produced for this benchmark yet (<code>scripts/bias_confirmation.py</code>).</p>'
    C, s, tr, te = V.c, V.season, V.tr, V.te
    rows_all = C['methods'] + ['SEL-P', 'SEL-A']
    lab = lambda m: f'<strong>{m}</strong>' if m.startswith('SEL') else (f'<strong>{esc(V.label(m))}</strong>' if m == V.ref else esc(V.label(m)))
    mk = lambda m, score, t: ' ✓' if m != V.ref and V.confirmed(m, score, t) else ''
    glance = [[lab(m), signed(V.cv(m, 'training', 'rpss', s)) + mk(m, 'rps', s), signed(V.cv(m, 'test', 'rpss', s)),
               signed(V.cv(m, 'training', 'bss_below', s)) + mk(m, 'brier_below', s), signed(V.cv(m, 'training', 'bss_above', s)) + mk(m, 'brier_above', s),
               signed(V.cv(m, 'training', 'crpss', s)) + mk(m, 'crps', s), signed(V.cv(m, 'test', 'crpss', s)),
               num(C['targets'][s]['methods'][m]['lambda_']['training_mean']) if not m.startswith('SEL') else '—'] for m in rows_all]
    by_target = [[lab(m)] + [signed(V.cv(m, 'training', 'rpss', t)) + mk(m, 'rps', t) for t in V.targets] for m in rows_all]
    by_target_amt = [[lab(m)] + [signed(V.cv(m, 'training', 'crpss', t)) + mk(m, 'crps', t) for t in V.targets] for m in rows_all]
    sel_rows = []
    for name in ('SEL-P', 'SEL-A'):
        for t in V.targets:
            sl = C['targets'][t]['selection'][name]
            freq = sorted(((n, m) for m, n in sl['frequency'].items() if n), reverse=True)
            test = C['tests'][name][('rps' if name == 'SEL-P' else 'crps')][t]
            sel_rows.append([name, esc(t), esc(', '.join(f'{V.short(m)} {n}' for n, m in freq)), esc(V.short(sl['chosen_test'])),
                             f'{test["training"]["mean_difference"]:+.4f}', f'{test["decision"]["holm_p"]:.4f}',
                             f'{test["test"]["mean_difference"]:+.4f}', 'yes' if test['decision']['confirmed'] else 'no'])
    head = ['Method', f'Blended RPSS {tr}', f'Blended RPSS {te}', f'BSS below {tr}', f'BSS above {tr}', f'Amount CRPSS {tr}',
            f'Amount CRPSS {te}', 'Mean blend weight λ']
    return f'''<p>The screening isolates the amount correction. The confirmation evaluates what the site publishes: each method’s
  corrected members go through the full probability pipeline (tercile counts, smoothing and the climatology blend), with every fit and
  the blend weight inside the cross-validation folds. Two <strong>selection-aware procedures</strong> then choose a method for each
  left-out year using only the other training years — <strong>SEL-P</strong> by the lowest inner blended RPS (probabilities),
  <strong>SEL-A</strong> by the lowest inner CRPS (amounts) — so their scores include the effect of choosing among the
  {len(C["methods"])} declared methods. ✓ = better than {esc(V.short(V.ref))} with Holm-adjusted p &lt; 0.05 (methods: across all
  methods and targets; SEL-P/SEL-A: across the targets) and not worse over {te}. Scope: {esc(V.national)}.</p>
  {tbl(head, glance, f'{esc(s)} season through the full pipeline (outer leave-one-year-out {tr}; test years exploratory)')}
  {tbl(['Method'] + [esc(t) for t in V.targets], by_target, f'Blended tercile RPSS by target, outer leave-one-year-out {tr}')}
  <details><summary>Amount CRPSS by target in the confirmation design, and the selection-aware procedures</summary>
  {tbl(['Method'] + [esc(t) for t in V.targets], by_target_amt, f'Amount CRPSS by target, outer leave-one-year-out {tr}')}
  {tbl(['Procedure', 'Target', f'Methods chosen ({tr}, years)', f'Chosen for {te}', 'Δ score vs MVS', 'Holm p (targets)',
        f'Δ {te}', 'Confirmed'], sel_rows, 'Selection-aware procedures against the operational method (Δ: RPS for SEL-P, CRPS for SEL-A; negative favours the procedure)')}
  </details>'''


def figures_html(V, name):
    kinds = ''.join(f'<option value="{esc(p.format(year=V.year, t="{t}"))}" data-per-target="{str(per).lower()}">{esc(l.format(year=V.year))}</option>'
                    for p, l, per in FIGURES if V.c or not p.startswith('confirmation'))
    targets = ''.join(f'<option{" selected" if t == V.season else ""}>{esc(t)}</option>' for t in V.targets)
    return f'''<p class="caveat">Figures show the national aggregate ({esc(V.national)}) or per-cell maps of the whole country, whatever region is selected for the tables.</p>
<div class="bc-figs" data-figs="assets/bias/{esc(name)}">
  <div class="map-controls">
    <label>Figure <select class="bc-kind">{kinds}</select></label>
    <label>Target <select class="bc-target">{targets}</select></label>
    <a class="bc-open" href="#" target="_blank" rel="noopener">Open full size</a>
  </div>
  <figure class="map-figure wide"><img class="bc-img" loading="lazy" alt="" style="max-width:100%;height:auto"><figcaption class="caveat bc-cap"></figcaption></figure>
</div>'''


def consistent(V, m):
    """At least one screening pass, and never worse than the reference in the national aggregate (any target, period, score)."""
    return bool(V.passed(m, 'crps') or V.passed(m, 'rps')) and all(
        V.v(m, d, k, t) >= V.v(V.ref, d, k, t) - 1e-9 for d in ('training', 'operational') for k in ('crpss', 'rpss') for t in V.targets)


def findings(V):
    """(condition, text) pairs: a statement is shown only while its condition holds in the current results. Scope: national."""
    s, ref = V.season, V.ref
    tr, te = V.tr, V.te
    L = V.short
    cand = V.candidates
    out = []

    def add(cond, text_fn):
        try:
            ok = bool(cond())
            out.append((ok, text_fn() if ok else None))
        except (KeyError, ValueError, TypeError, IndexError, ZeroDivisionError):
            out.append((False, None))

    # 1. raw model
    def raw_text():
        worse = [(m, t) for m in cand + [ref] for t in V.months if V.v(m, 'training', 'rpss', t) < V.v('raw', 'training', 'rpss', t)]
        ex = f' ({esc(listing([f"{L(m)} in {t}" for m, t in worse[:4]]))}{" and others" if len(worse) > 4 else ""})' if worse else ''
        return (f'<strong>All tested corrections improve national {esc(s)} rainfall-amount CRPSS over raw ECMWF in {tr}</strong> '
                f'(raw {signed(V.v("raw", "training", "crpss", s))}; corrected {signed(min(V.v(m, "training", "crpss", s) for m in cand + [ref]))} '
                f'to {signed(max(V.v(m, "training", "crpss", s) for m in cand + [ref]))}). Performance varies for monthly tercile '
                f'probabilities: {len(worse)} method–month combinations score below the raw model on RPSS{ex}.')
    add(lambda: 'raw' in V.methods and all(V.v(m, 'training', 'crpss', s) > V.v('raw', 'training', 'crpss', s) for m in cand + [ref]), raw_text)

    # 2. multiplicity
    def mult_text():
        def pairs(score, family):
            return [f'{L(m)} ({", ".join(V.passed(m, score, family))})' for m in cand if V.passed(m, score, family)]
        lost = [f'{L(m)} {t}' for m in cand for t in V.targets for sc in ('crps', 'rps') if V.screen(m, sc, t) and not V.screen(m, sc, t, True)]
        return (f'<strong>Accounting for the whole search.</strong> With Holm adjustment across all {len(cand) * len(V.targets)} '
                f'method–target comparisons, the amount (CRPS) screening passes are {esc(listing(pairs("crps", True)))}, and the tercile '
                f'(RPS) passes are {esc(listing(pairs("rps", True)))}. Within-method passes that do not survive this check: '
                f'{esc(listing(sorted(set(lost))))}.')
    add(lambda: True, mult_text)

    # 3. consistent improvement (national aggregate)
    for m in [x for x in cand if consistent(V, x)]:
        def cons_text(m=m):
            z_ref = [V.v(ref, 'training', 'zero_fraction', t) for t in V.months]
            z_m = [V.v(m, 'training', 'zero_fraction', t) for t in V.months]
            fam = 'survives' if V.screen(m, 'crps', s, True) else 'does not survive'
            return (f'<strong>{esc(L(m))} is at least as good as {esc(L(ref))} in the national aggregate for every tested target and '
                    f'period</strong>, on amounts and unblended terciles ({esc(s)} CRPSS {signed(V.v(m, "training", "crpss", s))} vs '
                    f'{signed(V.v(ref, "training", "crpss", s))} in {tr}, {signed(V.v(m, "operational", "crpss", s))} vs '
                    f'{signed(V.v(ref, "operational", "crpss", s))} in {te}). Its {esc(s)} amount screening pass {fam} the '
                    f'family-wide correction. Members clipped to 0 mm in the months: {pct(min(z_ref), 1)}–{pct(max(z_ref), 1)} with '
                    f'{esc(L(ref))}, {pct(min(z_m), 1)}–{pct(max(z_m), 1)} with this method. This need not hold in each region; see the '
                    f'tables for the {esc(listing([r["label"] for k, r in V.cfg["regions"].items() if k != V.primary]))}.')
        add(lambda: True, cons_text)

    # 4. ratio limits (VS has the same fallback as MVS)
    if 'vs' in cand:
        hit = [t for t in V.targets if V.screen('vs', 'crps', t) or V.screen('vs', 'rps', t)]
        def vs_text():
            dg = lambda t: V.d['targets'][t]['methods'][ref]['diagnostics_training']['cell_area_share']
            return (f'<strong>The 0.5–2 limits of {esc(L(ref))} matter most where the raw model is far too narrow</strong> ({esc(listing(hit))}). '
                    f'With the same 1 mm fallback in both, removing the limits is the only difference: there the upper limit is active over '
                    f'{listing([pct(dg(t).get("ratio_upper_limit", 0)) for t in hit])} of the area and {esc(L(ref))} stays too narrow '
                    f'(spread–error {listing([num(V.v(ref, "training", "spread_error_ratio", t)) for t in hit])}), while the unbounded form '
                    f'reaches {listing([num(V.v("vs", "training", "spread_error_ratio", t)) for t in hit])}.')
        add(lambda: bool(hit) and all(V.v(ref, 'training', 'spread_error_ratio', t) < .9 for t in hit), vs_text)

    # 5. EQM
    if 'eqm' in cand:
        def eqm_text():
            dm = [t for t in V.months if V.dist(ref, 'dry_share_obs', t, stat='area_mean') > .1]
            dry = '; '.join(f'{t} {pct(V.dist("eqm", "dry_share_corrected", t, stat="area_mean"), 1)} vs CHIRPS '
                            f'{pct(V.dist("eqm", "dry_share_obs", t, stat="area_mean"), 1)}' for t in dm)
            p = sorted(set(V.passed('eqm', 'crps') + V.passed('eqm', 'rps')), key=V.targets.index)
            return (f'<strong>{esc(L("eqm"))} reproduces the CHIRPS distribution and, with the dry policy, its dry share</strong> '
                    f'(totals ≤ 1 mm: {esc(dry) or "—"}); it passes the screening for {esc(listing(p))}, but its {esc(s)} amount skill is '
                    f'lower than {esc(L(ref))} ({signed(V.v("eqm", "training", "crpss", s))} vs {signed(V.v(ref, "training", "crpss", s))}). '
                    f'A possible explanation is sampling noise in an empirical quantile function built from '
                    f'{V.cfg["training_years"][1] - V.cfg["training_years"][0]} CHIRPS values per fold; the results do not isolate it.')
        add(lambda: V.v('eqm', 'training', 'crpss', s) < V.v(ref, 'training', 'crpss', s), eqm_text)

    # 6. SDM
    if 'sdm' in cand:
        def sdm_dry():
            return [t for t in V.months if V.v('raw', 'training', 'dry_fraction', t) - V.v(ref, 'training', 'observed_dry_fraction', t) > .1]
        def sdm_text():
            t = max(sdm_dry(), key=lambda x: V.v('raw', 'training', 'dry_fraction', x))
            return (f'<strong>{esc(L("sdm"))} follows the published algorithm</strong> (Switanek et al. 2017, steps 1–7; checked numerically '
                    f'against an independent implementation of the steps). Where the model is drier than CHIRPS it cannot add rain: in '
                    f'{esc(t)} {pct(1 - V.v("raw", "training", "dry_fraction", t))} of model members exceed 1 mm against '
                    f'{pct(1 - V.v(ref, "training", "observed_dry_fraction", t))} of CHIRPS years, and SDM, by design, keeps the model’s '
                    f'number of rain members, so its corrected dry share is {pct(V.v("sdm", "training", "dry_fraction", t))} '
                    f'(CHIRPS {pct(V.v(ref, "training", "observed_dry_fraction", t))}).')
        add(lambda: bool(sdm_dry()), sdm_text)

    # 7. Delta Change
    if 'dc' in cand:
        add(lambda: V.v('dc', 'training', 'crpss', s) > V.v(ref, 'training', 'crpss', s) and not V.screen('dc', 'crps', s)
            and V.v('dc', 'operational', 'crpss', s) < V.v(ref, 'operational', 'crpss', s),
            lambda: (f'<strong>{esc(L("dc"))}</strong> has a high {esc(s)} CRPSS in {tr} ({signed(V.v("dc", "training", "crpss", s))}) but the '
                     f'gain does not pass the screening (Holm p = {V.gate("dc", "crps", s)["decision"]["holm_p"]:.2f}), it is lower in {te} '
                     f'({signed(V.v("dc", "operational", "crpss", s))} vs {signed(V.v(ref, "operational", "crpss", s))}), its ensemble is too '
                     f'wide (spread–error {num(V.v("dc", "training", "spread_error_ratio", s))}) and its tercile skill is low. It is the '
                     'CHIRPS climatology rescaled by the forecast’s mean: historical scenarios, not corrected members.'))

    # 8. change-preserving methods
    cp = [m for m in cand if V.d['methods'][m]['uses_forecast_distribution'] and m != 'dc']
    if cp:
        def cp_text():
            vals = sorted(V.v(m, 'training', 'rpss', s) for m in cp)
            q = V.d['targets']
            low = [f'{t} {pct(q[t]["methods"]["qdm"]["diagnostics_training"]["event_share"].get("low_denominator", 0))}' for t in V.months
                   if 'qdm' in cp and (q[t]['methods']['qdm']['diagnostics_training']['event_share'].get('low_denominator') or 0) > .1]
            return (f'<strong>The methods that use the forecast’s own distribution ({esc(", ".join(L(m) for m in cp))}) score lower on '
                    f'{esc(s)} terciles</strong> ({signed(vals[0])} to {signed(vals[-1])} vs {signed(V.v(ref, "training", "rpss", s))}) and none '
                    'passes the season screening. A possible explanation is that the distribution of a single forecast’s 25–51 members is a '
                    'noisy estimate of the “future” distribution these methods were designed for; the results do not isolate the cause.'
                    + (f' Where model quantiles are dry, QDM falls back to the CHIRPS quantile (members affected: {esc(listing(low))}), so '
                       'its quantile changes are only partly preserved.' if low else ''))
        add(lambda: all(V.v(m, 'training', 'rpss', s) < V.v(ref, 'training', 'rpss', s) for m in cp)
            and not any(V.screen(m, sc, s) for m in cp for sc in ('crps', 'rps')), cp_text)

    # 9. mean-only methods
    mo = [m for m in ('ls', 'loci') if m in cand]
    if mo:
        add(lambda: all(V.v(m, 'training', 'spread_error_ratio', s) < .85 for m in mo),
            lambda: (f'<strong>{esc(" and ".join(L(m) for m in mo))}</strong> correct the mean only (LOCI nearly so for totals that are '
                     f'always wet), so the ensemble stays too narrow (spread–error '
                     f'{listing([num(V.v(m, "training", "spread_error_ratio", s)) for m in mo])} for {esc(s)}).'))

    # 10. hard months
    hard = [t for t in V.months if all(V.v(m, 'operational', 'crpss', t) < 0 for m in cand + [ref])]
    add(lambda: bool(hard), lambda: (f'<strong>{esc(listing(hard))} {"remains" if len(hard) == 1 else "remain"} hard:</strong> every '
                                     f'method has negative amount skill over {te}.'))

    # 11-12. confirmation
    if V.c:
        def conf_text():
            C = V.c
            p_ok = [t for t in V.targets if C['tests']['SEL-P']['rps'][t]['decision']['confirmed']]
            a_ok = [t for t in V.targets if C['tests']['SEL-A']['crps'][t]['decision']['confirmed']]
            meth = {sc: [f'{L(m)} ({", ".join(t for t in V.targets if V.confirmed(m, sc, t))})' for m in C['methods']
                         if m != ref and any(V.confirmed(m, sc, t) for t in V.targets)] for sc in ('rps', 'crps')}
            sp, sa = V.cv('SEL-P', 'training', 'rpss', s), V.cv('SEL-A', 'training', 'crpss', s)
            return (f'<strong>Confirmation through the full pipeline.</strong> Choosing the method each year from training-only scores, the '
                    f'probability procedure (SEL-P) scores {esc(s)} blended RPSS {signed(sp)} against {signed(V.cv(ref, "training", "rpss", s))} '
                    f'for {esc(L(ref))}, and is confirmed better for {esc(listing(p_ok))}; the amount procedure (SEL-A) scores CRPSS '
                    f'{signed(sa)} against {signed(V.cv(ref, "training", "crpss", s))}, confirmed for {esc(listing(a_ok))}. Individual methods '
                    f'confirmed against the family of all methods and targets — blended RPS: {esc(listing(meth["rps"]))}; amount CRPS: '
                    f'{esc(listing(meth["crps"]))}.')
        add(lambda: True, conf_text)

        def ranges():
            ms = V.c['methods']
            after = [V.cv(m, 'training', 'rpss', s) for m in ms]
            before = [V.v(m, 'training', 'rpss', s) for m in ms]
            return max(after) - min(after), max(before) - min(before)
        def blend_text():
            lam = lambda m, t: V.c['targets'][t]['methods'][m]['lambda_']['training_mean']
            after, before = ranges()
            jt = max(V.months, key=lambda t: lam(ref, t) - lam('sqrt_mvs', t)) if 'sqrt_mvs' in V.c['methods'] else None
            return (f'<strong>The climatology blend narrows the differences.</strong> Across the methods, {esc(s)} RPSS ({tr}) spans '
                    f'{after:.3f} after the blend against {before:.3f} for the unblended screening counts. A better amount correction is '
                    'trusted more by the blend' + (f': in {esc(jt)} the fitted weight on climatology is {lam("sqrt_mvs", jt):.2f} with '
                    f'{esc(L("sqrt_mvs"))} against {lam(ref, jt):.2f} with {esc(L(ref))}.' if jt else '.'))
        add(lambda: ranges()[0] < ranges()[1], blend_text)

        def risky():
            out_ = []
            for name, sc in (('SEL-P', 'rps'), ('SEL-A', 'crps')):
                for t in V.targets:
                    test = V.c['tests'][name][sc][t]
                    chosen = V.c['targets'][t]['selection'][name]['chosen_test']
                    if test['test']['mean_difference'] > 0 and chosen != ref:
                        out_.append((name, t, chosen, test['test']['mean_difference'], sc))
            return out_
        add(lambda: bool(risky()), lambda: (
            '<strong>Choosing by training scores can backfire.</strong> For ' + '; for '.join(
                f'{esc(t)}, {name} chose {esc(L(m))} from the {tr} scores, and over {te} it is worse than {esc(L(ref))} '
                f'(Δ {sc.upper()} {d:+.3f}{" mm" if sc == "crps" else ""})' for name, t, m, d, sc in risky()) +
            '. This is why a method that ranks first on the training years is not, on that alone, a replacement.'))
    return out


def decision_html(V):
    """What the current evidence supports, computed from the screening and the confirmation."""
    items = []
    if V.c:
        C, ref = V.c, V.ref
        for sc, product, proc in [('rps', 'published tercile probabilities', 'SEL-P'), ('crps', 'rainfall amounts', 'SEL-A')]:
            conf = {m: [t for t in V.targets if V.confirmed(m, sc, t)] for m in C['methods'] if m != ref}
            conf = {m: t for m, t in conf.items() if t}
            sel = [t for t in V.targets if C['tests'][proc][sc][t]['decision']['confirmed']]
            if conf:
                txt = '; '.join(f'{V.short(m)} for {listing(t)}' for m, t in conf.items())
                items.append(f'<li><strong>{esc(product.capitalize())}:</strong> confirmed against {esc(V.short(ref))} (family-wide, '
                             f'full pipeline): {esc(txt)}. The selection-aware procedure is confirmed for {esc(listing(sel))}.</li>')
            else:
                items.append(f'<li><strong>{esc(product.capitalize())}:</strong> no method is confirmed better than {esc(V.short(ref))} '
                             f'after accounting for the whole search; the selection-aware procedure is confirmed for {esc(listing(sel))}.</li>')
    else:
        items.append('<li>The confirmation run is pending; the screening alone does not support a change.</li>')
    items.append(f'<li>The operational method stays {esc(V.short(V.ref))} until a change is decided by initialization, target and product, '
                 'and recorded in the docs, on this evidence; confirmed improvements limited to some months may justify a per-target choice.</li>')
    items.append('<li>The same screening and confirmation run for the other cycles with one configuration file each '
                 '(<code>config/bias_correction/</code>).</li>')
    return '<ul class="findings">' + ''.join(items) + '</ul>'


def provenance_html(V):
    p = V.d.get('provenance')
    if not p:
        return ''
    rows = [['Commit', f'<code>{esc(p.get("commit"))}</code>' + (' (with uncommitted changes)' if p.get('uncommitted_changes') else '')],
            ['Configuration', f'<code>{esc(p["config"]["path"])}</code> sha256 <code>{esc(p["config"]["sha256"][:16])}…</code>'],
            ['Project configuration', f'<code>{esc(p["project_config"]["path"])}</code> sha256 <code>{esc(p["project_config"]["sha256"][:16])}…</code>'],
            ['Masks', '; '.join(f'{esc(k)}: <code>{esc(v["sha256"][:16])}…</code>' for k, v in p['masks'].items())],
            ['Inputs', '; '.join(f'{esc(t)}: {v["files"]} files, <code>{esc(v["sha256"][:16])}…</code>' for t, v in p['inputs'].items())],
            ['Code', '; '.join(f'<code>{esc(k.split("/")[-1])}</code> <code>{esc(v[:12])}…</code>' for k, v in p['code_sha256'].items())],
            ['Scoring version', esc(p.get('scoring_version'))],
            ['Software', f'Python {esc(p.get("python"))}, NumPy {esc(p.get("numpy"))}']]
    return tbl(['Item', 'Fingerprint'], rows, 'Run provenance (full hashes in benchmark.json and manifest.json)')


def block(bench, files):
    V = View(bench['data'], bench.get('confirmation'))
    name = bench['name']
    cfg = V.cfg
    found = findings(V)
    shown = [t for ok, t in found if ok and t]
    withheld = sum(1 for ok, _ in found if not ok)
    dl = ''.join(f'<li><a href="{esc(h)}" download>{esc(l)}</a><span>{s / 1e6:.1f} MB</span></li>' for h, l, s in files)
    refs = ''.join(f'<li>{REFERENCES[k][0]} <a href="https://doi.org/{esc(REFERENCES[k][1])}">doi:{esc(REFERENCES[k][1])}</a></li>'
                   for k in sorted(REFERENCES))
    project = json.loads((ROOT / cfg['project_config']).read_text(encoding='utf-8'))
    title = f'{month_name(project["initialization_month"])} initialization · {V.season} and its months'
    summary = [t for t in shown if 'Accounting for the whole search' in t or 'Confirmation through the full pipeline' in t or 'All tested corrections' in t]
    return f'''<div class="bc" data-bench="{esc(name)}">
  <h3>{esc(title)}</h3>
  <p class="notice"><strong>Research benchmark.</strong> The published forecasts still use {esc(V.label(V.ref))}. This section
  compares {len(V.candidates)} other rainfall-amount bias-correction methods with it, member by member, for every grid cell and target:
  a <em>screening</em> of the amount correction alone, then a <em>confirmation</em> through the full probability pipeline that also
  accounts for how a method is chosen.</p>

  <h3>Summary <span class="caveat">— national aggregate ({esc(V.national)})</span></h3>
  <ul class="findings">{''.join(f'<li>{t}</li>' for t in summary)}</ul>
  <div class="box"><h4>What the evidence supports</h4>{decision_html(V)}</div>

  <h3>Data</h3>
  {data_table(V)}

  <h3>Methods</h3>
  <p>Each method is fitted per grid cell and target from the training years only and applied to each member of the scored year.
  Methods that keep a “change signal” (DC, DQM, QDM, SDM, CDF-t) were designed for climate change, where a model’s reference period is
  compared with a future period; here the “future” is the forecast itself: the target year’s ensemble against the model climatology.</p>
  <details open><summary>How overlapping names were resolved</summary><ul class="findings">
    <li><strong>Delta Change</strong> appeared twice in the requested list; it is one method.</li>
    <li><strong>Mean–Variance Scaling</strong> is the operational method, with the project’s 0.5–2 ratio limits. <strong>Variance Scaling</strong> uses the same algebra and the same fallback (ratio 1 where the model spread is below 1 mm) without the limits, so the comparison isolates the limits.</li>
    <li><strong>Delta Change</strong> returns the CHIRPS training years rescaled by the forecast signal (ensemble mean / model climatology): historical scenarios, not corrected members. Applied to each member instead it would be identical to Linear Scaling.</li>
    <li><strong>Square-root-space MVS</strong> (a mean–variance scaling of √x) is distinct from <strong>Power Transformation</strong> (a·x<sup>b</sup> with b fitted to the coefficient of variation).</li>
    <li>The <strong>raw model</strong> is scored as a baseline, not screened.</li>
  </ul></details>
  <details><summary>Dry totals and tied values</summary><p>A total at or below 1 mm in the month or season is “dry” (not a dry day).
  For the quantile-mapping methods (EQM, Gamma QM, DQM, QDM) the dry shares of the model climatology and of CHIRPS are estimated with
  the equal-year weights; a forecast’s dry members are spread evenly over the model’s dry probability by rank (ties by member order, the
  expected value of random tie-breaking), and a probability within the CHIRPS dry share maps to 0 mm. Without this, tied zeros share one
  probability and the corrected dry share does not follow CHIRPS. Tests cover repeated zeros, all-dry samples and very few wet values;
  the dry-month table under Results compares the shares. CDF-t, LOCI and the scaling methods have no occurrence adjustment; SDM uses its
  own rain-member rule (Switanek et al. 2017).</p></details>
  {methods_table(V)}

  <h3>Steps</h3>
  {steps_html(V)}

  <h3>Screening results</h3>
  {results_html(V)}
  <details><summary>Screening statistics for every method, target and score (within-method and family-wide Holm)</summary>{gates_html(V)}</details>
  <details><summary>How often limits, caps and fallbacks act</summary>{diagnostics_html(V)}</details>

  <h3>Confirmation: full pipeline and method selection</h3>
  {confirmation_html(V)}

  <h4>Figures</h4>
  {figures_html(V, name)}

  <h3>Interpretation <span class="caveat">— national aggregate ({esc(V.national)})</span></h3>
  <ol class="findings">{''.join(f'<li>{t}</li>' for t in shown)}</ol>
  {f'<p class="caveat">{withheld} statement(s) of the written interpretation no longer hold for the current results and are not shown.</p>' if withheld else ''}
  <details><summary>Caveats</summary><ul class="findings">
    <li>Screening skill is from {V.tr} leave-one-year-out (clean) and {V.te} (exploratory: these years were seen while the operational method was chosen).</li>
    <li>Screening tercile scores use smoothed member counts <strong>without</strong> the climatology blend; the confirmation scores the blended product.</li>
    <li>Two multiplicity families are shown: within one method across its targets (✓) and across all methods and targets (✓✓). The confirmation’s selection-aware procedures include the method choice in the evaluation itself.</li>
    <li>Scores are area-weighted over many correlated cells but tested year by year, so each year counts once.</li>
    <li>The ordinary CRPS scores the delivered ensemble; the fair CRPS is a diagnostic under a sampling interpretation that DC’s rescaled years and methods tied to the forecast mean or ranks only approximate.</li>
    <li>Results are national aggregates unless a table says otherwise; a method can rank differently in a region (switch the tables to the regional view).</li>
  </ul></details>

  <h3>Downloads, provenance and code</h3>
  <ul class="dl">{dl}
    <li><a href="{REPO}/blob/main/{REPO_DOC}">Full write-up (docs/47)</a><span>Definitions, design, all result tables and the references</span></li>
    <li><a href="{REPO}/blob/main/scripts/bias_methods.py">Code</a><span><code>scripts/bias_methods.py</code> (methods), <code>scripts/bias_benchmark.py</code> (screening), <code>scripts/bias_confirmation.py</code> (confirmation), <code>config/bias_correction/{esc(name)}.json</code> (settings)</span></li>
  </ul>
  <details><summary>Run provenance</summary>{provenance_html(V)}</details>

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
  operational one: the data, every method’s definition, the steps, the screening and confirmation results, and what they mean.</p>
  {picker}{body}
</section>'''
