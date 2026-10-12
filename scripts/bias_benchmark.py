"""Benchmark rainfall-amount bias-correction methods member by member, for every grid cell and target (docs/47).

Read-only experiment: never touches the operational forecasts. Configured by config/bias_correction/<name>.json.

Designs (one score per year: area-weighted over a region; years weighted equally):
  training    : leave-one-year-out within the training years; the scored year never enters a fit (clean; screened)
  operational : fit on the training years, scored on the test years (exploratory; these years were seen before)
  full        : leave-one-year-out within all observed years, for per-cell maps and distribution checks (descriptive)
  forecast    : fit on all observed years, corrected forecast-year members of every method (member-by-member comparison)
Scores: ensemble CRPS (mm) of the empirical distribution delivered to users and its CRPSS against the CHIRPS training
climatology (primary); the fair CRPS (Ferro 2014) as a separately labelled diagnostic; ensemble-mean bias, MAE, RMSE
and correlation; spread-error ratio; rank histograms; tercile RPS/RPSS of alpha-smoothed member counts (no
climatology blend); distribution of the pooled corrected members against CHIRPS (mean, standard deviation, 10/50/90th
percentiles, exactly-0 and at-or-below-threshold shares); coverage of the amount and probability scores; how often
each method's limits, caps and fallbacks act.
Screening: each method against the reference (operational MVS) per target and score (CRPS, fair CRPS, RPS):
one-sided sign-flip test on the training-design per-year scores and no harm over the test years. Two
multiplicity families are reported: within one method across the targets ("screen_pass") and across every
declared method and target ("screen_pass_family"; sensitivity variants such as the MVS all-zero guard are screened
within method only). A screening pass is not an adoption decision. For the reference comparison, each cell's
contribution is also split by its climate group in the fold's training years (all 0 mm, all dry, mixed, always wet).
"""
import argparse
import pickle
import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def parse():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--config', default='config/bias_correction/sep_ondj.json')
    p.add_argument('--methods', nargs='+', help='subset of configured methods (default: all)')
    p.add_argument('--targets', nargs='+', help='subset of configured targets (default: all)')
    p.add_argument('--workers', type=int, default=0, help='parallel targets (default: one per target, at most cores - 1)')
    p.add_argument('--no-figures', action='store_true')
    p.add_argument('--no-resume', action='store_true', help='ignore and overwrite the per-target checkpoints')
    return p.parse_args()


ARGS = parse() if __name__ == '__main__' else None
ROOT_DIR = Path(__file__).resolve().parents[1]
if ARGS is not None:                       # member counts and cycle settings come from the benchmark's cycle
    os.environ.setdefault('CALIBRATION_CYCLE', json.loads((ROOT_DIR / ARGS.config).read_text(encoding='utf-8'))['cycle'])

import xarray as xr                                                          # noqa: E402
from common import ROOT, load_config, save_json, save_netcdf, source_path    # noqa: E402
from bias_methods import ALL as METHODS, resolve                                     # noqa: E402
from calibration_core import categories                                     # noqa: E402
from run_calibration import load_inputs, cell_area                          # noqa: E402
from run_monthly import monthly_config                                      # noqa: E402
from significance import paired_summary, holm, ALPHA                        # noqa: E402

MONTHS = {'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6, 'Jul': 7, 'Aug': 8, 'Sep': 9,
          'Oct': 10, 'Nov': 11, 'Dec': 12}
SCORING_VERSION = 3          # 3: + dry-cell group contributions; variants outside the family; complete fingerprint
GATE_SCORES = ('crps', 'crps_fair', 'rps')


# ---------------------------------------------------------------- scores (every function works on all cells at once)

def ensemble_crps(ens, y):
    """CRPS of the empirical distribution of the ensemble per cell: E|X - y| - E|X - X'| / 2 over all pairs."""
    m = len(ens)
    e = np.sort(ens, axis=0)
    rank = (2 * np.arange(1, m + 1) - m - 1)[:, None]
    return np.abs(ens - y[None, :]).mean(0) - (rank * e).sum(0) / (m * m)


def fair_crps(ens, y):
    """Fair ensemble CRPS (Ferro 2014) per cell: E|X - y| - E|X - X'| / 2 over distinct members."""
    m = len(ens)
    e = np.sort(ens, axis=0)
    rank = (2 * np.arange(1, m + 1) - m - 1)[:, None]
    return np.abs(ens - y[None, :]).mean(0) - (rank * e).sum(0) / (m * (m - 1))


def tercile_limits(train_obs):
    q1, q2 = np.quantile(train_obs, [1 / 3, 2 / 3], axis=0, method='linear')
    ok = (train_obs.std(0) >= 1.0) & (q1 > 0) & ((q2 - q1) > 1e-6)       # as calibration_core.fit_amount
    return q1, q2, ok


def rps(p, y_cat):
    t = np.eye(3)[y_cat]
    return np.sum((np.cumsum(p, -1)[:, :2] - np.cumsum(t, -1)[:, :2]) ** 2, -1)


def count_probabilities(ens, q1, q2, alpha):
    c = categories(ens, q1, q2)
    k = len(ens)
    return np.stack([((c == i).sum(0) + alpha) / (k + 3 * alpha) for i in range(3)], -1)


def pit(ens, y):
    """Interval of the observation's rank in the ensemble, as (lower, upper) in [0, 1].

    The rank is uniform over this interval (ties included): spreading it over the histogram bins is the
    expectation of the randomized PIT, so 26 or 52 rank positions do not alias onto 10 bins.
    """
    below, equal = (ens < y).sum(0), (ens == y).sum(0)
    return np.stack([below / (len(ens) + 1), (below + equal + 1) / (len(ens) + 1)])


def pit_histogram(interval, w, bins):
    """Area-weighted histogram: each cell's rank interval shared among the bins it overlaps."""
    lo, hi = interval
    e = np.linspace(0, 1, bins + 1)
    overlap = np.clip(np.minimum(hi[:, None], e[None, 1:]) - np.maximum(lo[:, None], e[None, :-1]), 0, None)
    return w @ (overlap / (hi - lo)[:, None])


def score_cells(ens, y, train_obs, alpha, threshold):
    """All per-cell scores of one forecast (ens: members x cells) against its observation y."""
    q1, q2, prob_ok = tercile_limits(train_obs)
    y_cat = categories(y, q1, q2)
    clim_cat = categories(train_obs, q1, q2)
    p_clim = np.stack([(clim_cat == i).mean(0) for i in range(3)], -1)
    k = len(ens)
    return dict(
        crps=ensemble_crps(ens, y), crps_clim=ensemble_crps(train_obs, y),
        crps_fair=fair_crps(ens, y), crps_fair_clim=fair_crps(train_obs, y),
        rps=rps(count_probabilities(ens, q1, q2, alpha), y_cat), rps_clim=rps(p_clim, y_cat), prob_ok=prob_ok,
        mean=ens.mean(0), var=ens.var(0, ddof=1) * (k + 1) / k, obs=y, pit=pit(ens, y),
        zero=(ens <= 0).mean(0), dry=(ens <= threshold).mean(0))


# ---------------------------------------------------------------- data

def load_mask(spec, lat, lon):
    with xr.open_dataset(source_path(spec['path'])) as d:
        a = d[spec['variable']].transpose('lat', 'lon')
        if not np.array_equal(a.lat, lat) or not np.array_equal(a.lon, lon):
            raise ValueError(f"Mask grid mismatch: {spec['path']}")
        return (a.values == 1).reshape(-1)


def target_config(project, target):
    return project if target == project['season']['name'] else monthly_config(project, MONTHS[target])


def load_target(cfg, project, target):
    years = list(range(cfg['all_years'][0], cfg['all_years'][1] + 1))
    tag, models, obs, _, lat, lon = load_inputs(target_config(project, target), years + [cfg['forecast_year']], years)
    return tag, models, obs, lat, lon


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def input_fingerprint(cfg, project, target):
    """SHA-256 of every processed input file of a target (one combined digest, and the file count)."""
    tc = target_config(project, target)
    folder = ROOT / 'data/processed' / f"init{tc['initialization_month']:02d}_{tc['season']['name']}"
    years = list(range(cfg['all_years'][0], cfg['all_years'][1] + 1))
    files = [folder / f'ecmwf_{y}_common.nc' for y in years + [cfg['forecast_year']]] + [folder / f'chirps_{y}_common.nc' for y in years]
    h = hashlib.sha256()
    for f in files:
        h.update(f.name.encode() + b'\0' + sha256(f).encode())
    return dict(folder=str(folder.relative_to(ROOT)).replace('\\', '/'), files=len(files), sha256=h.hexdigest())


def git(*args):
    try:
        return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


CODE_FILES = ['scripts/bias_methods.py', 'scripts/bias_benchmark.py', 'scripts/bias_confirmation.py', 'scripts/significance.py',
              'scripts/calibration_core.py', 'scripts/compare_calibration.py', 'scripts/local_blend.py', 'scripts/run_calibration.py',
              'scripts/run_monthly.py', 'scripts/cycle.py', 'scripts/common.py']


def dependencies(cfg, project, targets, config_path):
    """Everything a result depends on, hashed: configuration contents (benchmark, project, cycle), masks, every input file
    and the calculation code. The same fingerprint validates checkpoints and is recorded as provenance."""
    return dict(
        code_sha256={c: sha256(ROOT / c) for c in CODE_FILES},
        config=dict(path=config_path, sha256=sha256(ROOT / config_path)),
        project_config=dict(path=cfg['project_config'], sha256=sha256(ROOT / cfg['project_config'])),
        cycle_config=dict(path=cfg['cycle'], sha256=sha256(ROOT / cfg['cycle'])),
        masks={k: dict(path=v['path'], sha256=sha256(source_path(v['path'])))
               for k, v in [('cells', cfg['cells']), *cfg['regions'].items()]},
        inputs={t: input_fingerprint(cfg, project, t) for t in targets},
        scoring_version=SCORING_VERSION)


def dependency_key(dep, target=None):
    """One digest of the dependencies; with a target, only that target's inputs count (other targets may change)."""
    d = dict(dep)
    if target is not None:
        d['inputs'] = {target: dep['inputs'][target]}
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()


def dependency_files(dep, extra=()):
    """The tracked files a result depends on (code and configurations), for the uncommitted-changes check."""
    return sorted({*dep['code_sha256'], dep['config']['path'], dep['project_config']['path'], dep['cycle_config']['path'], *extra})


def provenance(cfg, project, targets, config_path, dep=None, extra=()):
    dep = dep or dependencies(cfg, project, targets, config_path)
    files = dependency_files(dep, extra)
    return dict(commit=git('rev-parse', 'HEAD'), uncommitted_changes=bool(git('status', '--porcelain', '--', *files)),
                uncommitted_check='code and configuration files this result depends on',
                **dep, dependency_sha256=dependency_key(dep), python=sys.version.split()[0], numpy=np.__version__)


# ---------------------------------------------------------------- one method, one design

def run_design(method, params, models, obs, folds, alpha, threshold, area):
    """folds: [(training years, scored years)]. Per-year cell scores, the corrected ensembles and the diagnostics."""
    m, p = resolve(method, params)
    scores, ensembles = {}, {}
    flags, counts = {}, {}
    for train, scored in folds:
        state = m.fit([models[y] for y in train], np.stack([obs[y] for y in train]), **p)
        train_obs = np.stack([obs[y] for y in train])
        group = dry_group(np.where(state['ok'][None, :], train_obs, 1e9), threshold)
        for y in scored:
            ens = np.asarray(m.apply(models[y], state, **p), float)
            ens[:, ~state['ok']] = np.nan
            ok = state['ok'] & np.isfinite(obs[y])
            s = score_cells(np.where(ok, ens, 0.), np.where(ok, obs[y], 0.), np.where(ok, train_obs, 0.), alpha, threshold)
            s['ok'] = ok
            s['prob_ok'] = s['prob_ok'] & ok
            s['group'] = group
            scores[y], ensembles[y] = s, ens
        ok = state['ok']
        w = area[ok] / area[ok].sum()
        for k, v in state.get('flags', {}).items():               # share of the corrected area where a limit acts
            flags.setdefault(k, []).append(float(w @ np.asarray(v, bool)[ok]))
        for k, (e, n) in state.get('counts', {}).items():
            c = counts.setdefault(k, [0, 0])
            c[0] += e
            c[1] += n
    diagnostics = dict(cell_area_share={k: float(np.mean(v)) for k, v in flags.items()},
                       event_share={k: (e / n if n else None) for k, (e, n) in counts.items()})
    return scores, ensembles, diagnostics


DRY_GROUPS = ['all training years exactly 0 mm', 'all training years <= threshold', 'mixed dry and wet years', 'always wet']


def dry_group(train_obs, threshold):
    """Climate group of every cell from one fold's training observations only (0-3, see DRY_GROUPS)."""
    dry = train_obs <= threshold
    return np.where((train_obs == 0).all(0), 0, np.where(dry.all(0), 1, np.where(dry.any(0), 2, 3))).astype('int8')


def group_contributions(kept, ref, area, region):
    """Each group's contribution to the mean CRPS difference from the reference (mm); contributions add up to the
    area-weighted national difference. Groups come from each fold's training years."""
    out = {}
    for m, by_year in kept.items():
        if m == ref:
            continue
        contrib, share = np.zeros(4), np.zeros(4)
        for y, (crps, group, ok) in by_year.items():
            a = region & ok & kept[ref][y][2]
            w = np.where(a, area, 0.) / area[a].sum()
            d = np.where(a, crps - kept[ref][y][0], 0.)
            contrib += np.bincount(group, w * d, 4)
            share += np.bincount(group, w, 4)
        n = len(by_year)
        out[m] = {g: dict(delta_crps_mm=float(contrib[i] / n), area_share=float(share[i] / n)) for i, g in enumerate(DRY_GROUPS)}
        out[m]['total_delta_crps_mm'] = float(contrib.sum() / n)
    return out


def summarise(scores, area, region, bins):
    """Area-weighted region scores, one per year, then equal-year averages."""
    years = sorted(scores)
    keys = ('crps', 'crps_clim', 'crps_fair', 'crps_fair_clim', 'rps', 'rps_clim', 'bias', 'mae', 'mse', 'var', 'zero', 'dry',
            'obs_dry', 'amount_area_share', 'probability_area_share')
    per_year = {k: [] for k in keys}
    cells = {'amount': [], 'probability': []}
    hist = np.zeros(bins)
    means, obs = [], []
    region_area = area[region].sum()
    for y in years:
        s = scores[y]
        a = region & s['ok']
        w = area[a] / area[a].sum()
        wp_mask = region & s['prob_ok']
        wp = area[wp_mask] / area[wp_mask].sum()
        err = s['mean'][a] - s['obs'][a]
        for k in ('crps', 'crps_clim', 'crps_fair', 'crps_fair_clim'):
            per_year[k].append(float(w @ s[k][a]))
        per_year['rps'].append(float(wp @ s['rps'][wp_mask]))
        per_year['rps_clim'].append(float(wp @ s['rps_clim'][wp_mask]))
        per_year['bias'].append(float(w @ err))
        per_year['mae'].append(float(w @ np.abs(err)))
        per_year['mse'].append(float(w @ err ** 2))
        per_year['var'].append(float(w @ s['var'][a]))
        per_year['zero'].append(float(w @ s['zero'][a]))
        per_year['dry'].append(float(w @ s['dry'][a]))
        per_year['obs_dry'].append(float(w @ (s['obs'][a] <= THRESHOLD)))
        per_year['amount_area_share'].append(float(area[a].sum() / region_area))
        per_year['probability_area_share'].append(float(area[wp_mask].sum() / region_area))
        cells['amount'].append(int(a.sum()))
        cells['probability'].append(int(wp_mask.sum()))
        hist += pit_histogram(s['pit'][:, a], w, bins)
        means.append(np.where(a, s['mean'], np.nan))
        obs.append(np.where(a, s['obs'], np.nan))
    hist /= len(years)
    mean = lambda k: float(np.mean(per_year[k]))
    means, obs = np.array(means), np.array(obs)
    corr = cell_correlation(means, obs)
    good = region & np.isfinite(corr)
    return dict(
        years=years, per_year=per_year,
        crps=mean('crps'), crpss=1 - mean('crps') / mean('crps_clim'),
        crps_fair=mean('crps_fair'), crpss_fair=1 - mean('crps_fair') / mean('crps_fair_clim'),
        rps=mean('rps'), rpss=1 - mean('rps') / mean('rps_clim'),
        mean_bias_mm=mean('bias'), mean_mae_mm=mean('mae'), mean_rmse_mm=float(np.sqrt(mean('mse'))),
        spread_error_ratio=float(np.sqrt(mean('var') / mean('mse'))),
        zero_fraction=mean('zero'), dry_fraction=mean('dry'), observed_dry_fraction=mean('obs_dry'),
        correlation=float(area[good] @ corr[good] / area[good].sum()) if good.any() else None,
        coverage=dict(region_cells=int(region.sum()),
                      amount_cells=float(np.mean(cells['amount'])), amount_area_share=mean('amount_area_share'),
                      probability_cells=float(np.mean(cells['probability'])),
                      probability_area_share=mean('probability_area_share')),
        pit_histogram=hist.round(5).tolist(),
        pit_reliability_index=float(np.abs(hist - 1 / bins).sum()))


def cell_correlation(a, b):
    """Correlation over years for every cell (NaN where a cell is not scored in every year)."""
    ok = np.isfinite(a).all(0) & np.isfinite(b).all(0)
    a, b = np.where(ok, a, 0.), np.where(ok, b, 0.)
    a, b = a - a.mean(0), b - b.mean(0)
    with np.errstate(invalid='ignore', divide='ignore'):
        r = (a * b).sum(0) / np.sqrt((a * a).sum(0) * (b * b).sum(0))
    return np.where(ok, r, np.nan)


def distribution(ensembles, obs, years, threshold):
    """Pooled corrected members (equal-year weights) against the CHIRPS values of the same years, per cell."""
    q = [.1, .5, .9]
    stats = {}
    vals = [ensembles[y] for y in years]
    w = np.concatenate([np.full(len(v), 1. / (len(years) * len(v))) for v in vals])
    x = np.nan_to_num(np.concatenate(vals))
    o = np.stack([obs[y] for y in years])
    mu = w @ x
    sd = np.sqrt(np.maximum(w @ x ** 2 - mu ** 2, 0))
    order = np.argsort(x, axis=0)
    xs = np.take_along_axis(x, order, 0)
    cw = np.cumsum(w[order], 0) - w[order] / 2
    qx = np.array([[np.interp(p, cw[:, j], xs[:, j]) for j in range(x.shape[1])] for p in q])
    qo = np.quantile(o, q, axis=0)
    with np.errstate(divide='ignore', invalid='ignore'):
        stats.update(mean_ratio=mu / o.mean(0), sd_ratio=sd / o.std(0),
                     **{f'q{int(100 * p)}_ratio': qx[i] / qo[i] for i, p in enumerate(q)})
    stats.update(zero_share_obs=(o <= 0).mean(0), zero_share_corrected=w @ (x <= 0),
                 dry_share_obs=(o <= threshold).mean(0), dry_share_corrected=w @ (x <= threshold))
    return stats


def region_distribution(stats, area, region, ok):
    out = {}
    for k, v in stats.items():
        good = region & ok & np.isfinite(v)
        w = area[good] / area[good].sum()
        order = np.argsort(v[good])
        median = float(v[good][order][min(np.searchsorted(np.cumsum(w[order]), .5), good.sum() - 1)])
        if k.endswith('ratio'):            # medians: a mean of ratios is dominated by near-zero CHIRPS values in dry cells
            out[k] = dict(area_median=median, area_mean_abs_log=float(w @ np.abs(np.log(np.maximum(v[good], 1e-6)))))
        else:
            out[k] = dict(area_median=median, area_mean=float(w @ v[good]))
    return out


THRESHOLD = 1.0       # dry total (mm); set from the configuration in run_target


# ---------------------------------------------------------------- one target (runs in a worker process)

def run_target(config_path, target, methods):
    global THRESHOLD
    cfg = json.loads((ROOT / config_path).read_text(encoding='utf-8'))
    THRESHOLD = cfg.get('dry_threshold_mm', 1.0)
    project = load_config(cfg['project_config'])
    rng = lambda a, b: list(range(a, b + 1))
    train_years, test_years, all_years = rng(*cfg['training_years']), rng(*cfg['test_years']), rng(*cfg['all_years'])
    designs = {
        'training': [([z for z in train_years if z != y], [y]) for y in train_years],
        'operational': [(train_years, test_years)],
        'full': [([z for z in all_years if z != y], [y]) for y in all_years],
    }
    alpha, bins = cfg['smoothing_alpha'], cfg['pit_bins']
    tag, models_full, obs_full, lat, lon = load_target(cfg, project, target)
    cells = load_mask(cfg['cells'], lat, lon)
    idx = np.flatnonzero(cells)
    models = {y: m[:, idx] for y, m in models_full.items()}
    obs = {y: o[idx] for y, o in obs_full.items()}
    area = cell_area(lat, lon)[idx]
    regions = {k: load_mask(v, lat, lon)[idx] for k, v in cfg['regions'].items()}
    result = dict(tag=tag, cells=int(len(idx)), methods={})
    maps_t, forecast_t = {}, {}
    kept = {'training': {}, 'operational': {}}            # per-cell CRPS and dry groups, for the group contributions
    for method in methods:
        params = cfg['methods'].get(method, {})
        row = {}
        for design, folds in designs.items():
            scores, ens, diag = run_design(method, params, models, obs, folds, alpha, THRESHOLD, area)
            row[design] = {r: summarise(scores, area, mask, bins) for r, mask in regions.items()}
            if design in kept:
                kept[design][method] = {y: (scores[y]['crps'], scores[y]['group'], scores[y]['ok']) for y in scores}
            if design == 'training':
                row['diagnostics_training'] = diag
            if design == 'full':
                ok = np.all([scores[y]['ok'] for y in all_years], 0)
                dist = distribution(ens, obs, all_years, THRESHOLD)
                row['distribution_full'] = {r: region_distribution(dist, area, mask, ok) for r, mask in regions.items()}
                total = lambda k: np.sum([scores[y][k] for y in all_years], 0)
                prob_ok = np.all([scores[y]['prob_ok'] for y in all_years], 0)
                with np.errstate(divide='ignore', invalid='ignore'):
                    maps_t[method] = dict(
                        crpss=np.where(ok, 1 - total('crps') / total('crps_clim'), np.nan),
                        crpss_fair=np.where(ok, 1 - total('crps_fair') / total('crps_fair_clim'), np.nan),
                        rpss=np.where(prob_ok, 1 - total('rps') / total('rps_clim'), np.nan),
                        bias_mm=np.where(ok, np.mean([scores[y]['mean'] - scores[y]['obs'] for y in all_years], 0), np.nan),
                        correlation=cell_correlation(np.array([scores[y]['mean'] for y in all_years]),
                                                     np.array([scores[y]['obs'] for y in all_years])),
                        **{k: np.where(ok, v, np.nan) for k, v in dist.items()})
        m, p = resolve(method, params)          # forecast: fit on all observed years, correct the forecast-year members
        state = m.fit([models[y] for y in all_years], np.stack([obs[y] for y in all_years]), **p)
        fc = np.asarray(m.apply(models[cfg['forecast_year']], state, **p), float)
        fc[:, ~state['ok']] = np.nan
        forecast_t[method] = fc
        result['methods'][method] = row
        tr = row['training'][cfg['primary_region']]
        print(f"{target:4s} {method:9s} train CRPSS {tr['crpss']:+.4f} (fair {tr['crpss_fair']:+.4f}) RPSS {tr['rpss']:+.4f} "
              f"spread/err {tr['spread_error_ratio']:.2f} dry {tr['dry_fraction']:.3f} (CHIRPS {tr['observed_dry_fraction']:.3f})",
              flush=True)
    ref = cfg['reference_method']
    if ref in methods:
        result['dry_groups'] = {d: {r: group_contributions(kept[d], ref, area, mask) for r, mask in regions.items()} for d in kept}
    forecast_t['_raw'] = models[cfg['forecast_year']]
    forecast_t['_clim'] = np.mean([obs[y] for y in all_years], 0)
    forecast_t['_terciles'] = np.quantile(np.stack([obs[y] for y in all_years]), [1 / 3, 2 / 3], axis=0)
    forecast_t['_idx'] = idx
    return target, result, maps_t, forecast_t, lat, lon, cells


# ---------------------------------------------------------------- main

def gate_rule(cfg):
    tr, te = cfg['training_years'], cfg['test_years']
    return (f"Screening rule (docs/36 rule applied as a screen): a method passes for a target and score if, on the "
            f"leave-one-year-out {tr[0]}-{tr[1]} per-year scores, its mean improvement over {cfg['reference_method']} has a "
            f"one-sided sign-flip p-value below {ALPHA} after Holm adjustment, and its mean score over {te[0]}-{te[1]} "
            f"(fits on {tr[0]}-{tr[1]}) is not worse. 'screen_pass': Holm across the {len(cfg['targets'])} targets of one "
            f"method. 'screen_pass_family': Holm across every method and target of the benchmark for that score. "
            f"A screening pass is not an operational adoption decision (see the confirmation run).")


def make_gates(results, methods, ref, region, targets, cfg_methods=None):
    """Within-method and family-wide Holm screening, per score."""
    gates = {}
    family_of = {m: resolve(m, (cfg_methods or {}).get(m))[0].family for m in methods}
    cand = [m for m in methods if m != ref and family_of[m] != 'baseline']
    declared = [m for m in cand if family_of[m] != 'variant']         # variants stay outside the family-wide correction
    for score in GATE_SCORES:
        stats = {}
        for method in cand:
            for t in targets:
                rows = results[t]['methods']
                stats[method, t] = {d: paired_summary(rows[method][d][region]['per_year'][score],
                                                      rows[ref][d][region]['per_year'][score]) for d in ('training', 'operational')}
        family = holm({f'{m}|{t}': s['training']['p_improvement'] for (m, t), s in stats.items() if m in declared})
        for method in cand:
            within = holm({t: stats[method, t]['training']['p_improvement'] for t in targets})
            for t in targets:
                s = stats[method, t]
                better = s['training']['mean_difference'] < 0
                no_harm = s['operational']['mean_difference'] <= 0
                fam = family.get(f'{method}|{t}')
                s['decision'] = dict(
                    holm_p=float(within[t]), holm_p_family=None if fam is None else float(fam), no_harm=bool(no_harm),
                    in_family=method in declared, screen_pass=bool(better and within[t] < ALPHA and no_harm),
                    screen_pass_family=bool(fam is not None and better and fam < ALPHA and no_harm))
                gates.setdefault(method, {}).setdefault(score, {})[t] = s
    return gates


def main(args):
    cfg = json.loads((ROOT / args.config).read_text(encoding='utf-8'))
    project = load_config(cfg['project_config'])
    methods = args.methods or list(cfg['methods'])
    targets = args.targets or cfg['targets']
    ref = cfg['reference_method']
    if ref not in methods:
        methods = [ref] + methods
    out_root = ROOT / cfg['output_root']
    results, cell_maps, forecasts = {}, {}, {}
    dep = dependencies(cfg, project, targets, args.config)       # one fingerprint: checkpoints and provenance
    parts = out_root / 'parts'
    parts.mkdir(parents=True, exist_ok=True)
    done = {}
    for t in targets:                                            # per-target checkpoints, valid for the same dependencies
        f = parts / f'screening_{t}.pkl'
        key = dependency_key(dep, t) + '|' + ','.join(methods)
        if not args.no_resume and f.is_file():
            saved = pickle.loads(f.read_bytes())
            if saved['key'] == key:
                done[t] = saved['value']
                print(f'{t}: loaded from checkpoint', flush=True)
    todo = [t for t in targets if t not in done]
    workers = args.workers or min(max(len(todo), 1), max(1, (os.cpu_count() or 2) - 1))
    if todo:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            jobs = {pool.submit(run_target, args.config, t, methods): t for t in todo}
            failed = []
            for job in as_completed(jobs):                    # save each target as soon as it finishes
                t = jobs[job]
                try:
                    value = job.result()
                except Exception as exc:                      # keep the other targets; rerun resumes from the checkpoints
                    failed.append(f'{t}: {exc!r}')
                    continue
                (parts / f'screening_{t}.pkl').write_bytes(pickle.dumps(dict(key=dependency_key(dep, t) + '|' + ','.join(methods),
                                                                             value=value)))
                done[t] = value
            if failed:
                raise RuntimeError('Targets failed (completed targets are checkpointed): ' + '; '.join(failed))
    for t in targets:
        _, result, maps_t, forecast_t, lat, lon, cells = done[t]
        results[t], cell_maps[t], forecasts[t] = result, maps_t, forecast_t
    gates = make_gates(results, methods, ref, cfg['primary_region'], targets, cfg['methods'])
    out_root.mkdir(parents=True, exist_ok=True)
    meta = dict(created_utc=datetime.now(timezone.utc).isoformat(), config=args.config, config_contents=cfg,
                provenance=provenance(cfg, project, targets, args.config, dep),
                protocol=__doc__.strip(), gate_rule=gate_rule(cfg),
                methods={k: dict(label=m.label, family=m.family, definition=m.definition, references=m.references,
                                 member_wise=m.member_wise, uses_forecast_distribution=m.uses_forecast_distribution,
                                 parameters=p, base=cfg['methods'].get(k, {}).get('base'))
                         for k in methods for m, p in [resolve(k, cfg['methods'].get(k))]})
    save_json(out_root / 'benchmark.json', dict(**meta, targets=results, gates=gates))
    save_cells(out_root / 'cell_scores_full_loyo.nc', cell_maps, lat, lon, methods, targets, cells)
    save_forecast(out_root / f"forecast_{cfg['forecast_year']}_members.nc", forecasts, lat, lon, methods, targets, cfg)
    if not args.no_figures:
        import bias_benchmark_figures as figs
        figs.make_all(out_root, results, gates, cell_maps, forecasts, lat, lon, methods, targets, cfg)
    outputs = sorted(p for p in out_root.rglob('*') if p.is_file() and p.name != 'manifest.json'
                     and 'confirmation' not in p.parts and 'parts' not in p.parts)
    save_json(out_root / 'manifest.json', dict(created_utc=meta['created_utc'], commit=meta['provenance']['commit'],
                                               files={str(p.relative_to(out_root)).replace('\\', '/'): sha256(p) for p in outputs}))
    print('Saved:', out_root)


def grid(values, idx, shape):
    out = np.full(int(np.prod(shape)), np.nan)
    out[idx] = values
    return out.reshape(shape)


def save_cells(path, cell_maps, lat, lon, methods, targets, cells):
    idx = np.flatnonzero(cells)
    shape = (len(lat), len(lon))
    names = list(next(iter(next(iter(cell_maps.values())).values())))
    d = xr.Dataset(coords=dict(method=methods, target=targets, lat=lat, lon=lon),
                   attrs=dict(description='Per-cell scores, leave-one-year-out over all observed years (descriptive). '
                                          'Ratios: pooled corrected members over CHIRPS of the same years.'))
    for n in names:
        d[n] = (('method', 'target', 'lat', 'lon'),
                np.array([[grid(cell_maps[t][m][n], idx, shape) for t in targets] for m in methods]).astype('float32'))
    save_netcdf(d, path)


def save_forecast(path, forecasts, lat, lon, methods, targets, cfg):
    shape = (len(lat), len(lon))
    member_wise = [m for m in methods if resolve(m, cfg['methods'].get(m))[0].member_wise and m != 'raw']
    n = max(len(forecasts[t]['_raw']) for t in targets)
    d = xr.Dataset(coords=dict(method=member_wise, target=targets, member=np.arange(n), lat=lat, lon=lon),
                   attrs=dict(description=f"{cfg['forecast_year']} forecast members corrected by every method, fitted on "
                                          f"{cfg['all_years'][0]}-{cfg['all_years'][1]} (benchmark output; not the operational product)."))
    d['raw'] = (('target', 'member', 'lat', 'lon'),
                np.array([[grid(v, forecasts[t]['_idx'], shape) for v in forecasts[t]['_raw']] for t in targets]).astype('float32'))
    d['corrected'] = (('method', 'target', 'member', 'lat', 'lon'),
                      np.array([[[grid(v, forecasts[t]['_idx'], shape) for v in forecasts[t][m]] for t in targets]
                                for m in member_wise]).astype('float32'))
    d['chirps_climatology'] = (('target', 'lat', 'lon'),
                               np.array([grid(forecasts[t]['_clim'], forecasts[t]['_idx'], shape) for t in targets]).astype('float32'))
    if 'dc' in methods:
        years = list(range(cfg['all_years'][0], cfg['all_years'][1] + 1))
        d = d.assign_coords(sample_year=years)
        d['delta_change'] = (('target', 'sample_year', 'lat', 'lon'),
                             np.array([[grid(v, forecasts[t]['_idx'], shape) for v in forecasts[t]['dc']] for t in targets]).astype('float32'))
    for v in d.data_vars:
        d[v].attrs['units'] = 'mm'
    save_netcdf(d, path)


if __name__ == '__main__':
    main(ARGS)
