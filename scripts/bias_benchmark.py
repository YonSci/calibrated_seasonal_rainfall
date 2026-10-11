"""Benchmark rainfall-amount bias-correction methods member by member, for every grid cell and target (docs/47).

Read-only experiment: never touches the operational forecasts. Configured by config/bias_correction/<name>.json.

Designs (one score per year: area-weighted over a region; years weighted equally):
  training    : leave-one-year-out within 1993-2016; the target year never enters a fit (clean, gated)
  operational : fit on 1993-2016, scored on 2017-2024 (exploratory; these years were seen before)
  full        : leave-one-year-out within 1993-2024, for per-cell maps and distribution checks (descriptive)
  forecast    : fit on 1993-2024, corrected 2026 members of every method (member-by-member comparison)
Scores: fair ensemble CRPS (mm) and CRPSS against the CHIRPS training climatology; ensemble-mean bias, MAE,
RMSE and correlation; spread-error ratio; rank (PIT) histograms; tercile RPS/RPSS of alpha-smoothed member
counts (no climatology blend); distribution of the pooled corrected members against CHIRPS (mean, standard
deviation, 10/50/90th percentiles and zero fraction).
Gate: each method against the reference (operational MVS), the docs/36 rule: CRPS (amounts) and RPS
(probabilities) per year, one-sided sign-flip p, Holm across the targets, no harm in 2017-2024.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def parse():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--config', default='config/bias_correction/sep_ondj.json')
    p.add_argument('--methods', nargs='+', help='subset of configured methods (default: all)')
    p.add_argument('--targets', nargs='+', help='subset of configured targets (default: all)')
    p.add_argument('--no-figures', action='store_true')
    return p.parse_args()


ARGS = parse() if __name__ == '__main__' else None
ROOT_DIR = Path(__file__).resolve().parents[1]
if ARGS is not None:                       # member counts and cycle settings come from the benchmark's cycle
    os.environ.setdefault('CALIBRATION_CYCLE', json.loads((ROOT_DIR / ARGS.config).read_text(encoding='utf-8'))['cycle'])

import xarray as xr                                                          # noqa: E402
from common import ROOT, load_config, save_json, save_netcdf, source_path    # noqa: E402
from bias_methods import ALL as METHODS                                             # noqa: E402
from calibration_core import categories                                     # noqa: E402
from run_calibration import load_inputs, cell_area                          # noqa: E402
from run_monthly import monthly_config                                      # noqa: E402
from significance import paired_summary, holm, gate                         # noqa: E402

MONTHS = {'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6, 'Jul': 7, 'Aug': 8, 'Sep': 9,
          'Oct': 10, 'Nov': 11, 'Dec': 12}


# ---------------------------------------------------------------- scores (every function works on all cells at once)

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


def score_cells(ens, y, train_obs, alpha):
    """All per-cell scores of one forecast (ens: members x cells) against its observation y."""
    q1, q2, prob_ok = tercile_limits(train_obs)
    y_cat = categories(y, q1, q2)
    clim_cat = categories(train_obs, q1, q2)
    p_clim = np.stack([(clim_cat == i).mean(0) for i in range(3)], -1)
    k = len(ens)
    return dict(
        crps=fair_crps(ens, y), crps_clim=fair_crps(train_obs, y),
        rps=rps(count_probabilities(ens, q1, q2, alpha), y_cat), rps_clim=rps(p_clim, y_cat), prob_ok=prob_ok,
        mean=ens.mean(0), var=ens.var(0, ddof=1) * (k + 1) / k, obs=y, pit=pit(ens, y), zero=(ens <= 0).mean(0))


# ---------------------------------------------------------------- data

def load_mask(spec, lat, lon):
    with xr.open_dataset(source_path(spec['path'])) as d:
        a = d[spec['variable']].transpose('lat', 'lon')
        if not np.array_equal(a.lat, lat) or not np.array_equal(a.lon, lon):
            raise ValueError(f"Mask grid mismatch: {spec['path']}")
        return (a.values == 1).reshape(-1)


def load_target(cfg, project, target):
    tc = project if target == project['season']['name'] else monthly_config(project, MONTHS[target])
    years = list(range(cfg['all_years'][0], cfg['all_years'][1] + 1))
    tag, models, obs, _, lat, lon = load_inputs(tc, years + [cfg['forecast_year']], years)
    return tag, models, obs, lat, lon


# ---------------------------------------------------------------- one method, one design

def run_design(method, params, models, obs, folds, alpha):
    """folds: [(training years, scored years)]. Returns per-year cell scores and the corrected ensembles."""
    m = METHODS[method]
    p = {**m.defaults, **params}
    scores, ensembles = {}, {}
    for train, scored in folds:
        state = m.fit([models[y] for y in train], np.stack([obs[y] for y in train]), **p)
        train_obs = np.stack([obs[y] for y in train])
        for y in scored:
            ens = np.asarray(m.apply(models[y], state, **p), float)
            ens[:, ~state['ok']] = np.nan
            ok = state['ok'] & np.isfinite(obs[y])
            s = score_cells(np.where(ok, ens, 0.), np.where(ok, obs[y], 0.), np.where(ok, train_obs, 0.), alpha)
            s['ok'] = ok
            s['prob_ok'] = s['prob_ok'] & ok
            scores[y], ensembles[y] = s, ens
    return scores, ensembles


def summarise(scores, area, region, bins):
    """Area-weighted region scores, one per year, then equal-year averages."""
    years = sorted(scores)
    per_year = {k: [] for k in ('crps', 'crps_clim', 'rps', 'rps_clim', 'bias', 'mae', 'mse', 'var', 'zero')}
    hist = np.zeros(bins)
    means, obs = [], []
    for y in years:
        s = scores[y]
        a = region & s['ok']
        w = area[a] / area[a].sum()
        wp_mask = region & s['prob_ok']
        wp = area[wp_mask] / area[wp_mask].sum()
        err = s['mean'][a] - s['obs'][a]
        per_year['crps'].append(float(w @ s['crps'][a]))
        per_year['crps_clim'].append(float(w @ s['crps_clim'][a]))
        per_year['rps'].append(float(wp @ s['rps'][wp_mask]))
        per_year['rps_clim'].append(float(wp @ s['rps_clim'][wp_mask]))
        per_year['bias'].append(float(w @ err))
        per_year['mae'].append(float(w @ np.abs(err)))
        per_year['mse'].append(float(w @ err ** 2))
        per_year['var'].append(float(w @ s['var'][a]))
        per_year['zero'].append(float(w @ s['zero'][a]))
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
        rps=mean('rps'), rpss=1 - mean('rps') / mean('rps_clim'),
        mean_bias_mm=mean('bias'), mean_mae_mm=mean('mae'), mean_rmse_mm=float(np.sqrt(mean('mse'))),
        spread_error_ratio=float(np.sqrt(mean('var') / mean('mse'))),
        zero_fraction=mean('zero'),
        correlation=float(area[good] @ corr[good] / area[good].sum()) if good.any() else None,
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


def distribution(ensembles, obs, years):
    """Pooled corrected members (equal-year weights) against the CHIRPS values of the same years, per cell."""
    q = [.1, .5, .9]
    stats = {}
    vals = [ensembles[y] for y in years]
    w = np.concatenate([np.full(len(v), 1. / (len(years) * len(v))) for v in vals])
    x = np.concatenate(vals)
    o = np.stack([obs[y] for y in years])
    mu = w @ np.nan_to_num(x)
    sd = np.sqrt(np.maximum(w @ np.nan_to_num(x) ** 2 - mu ** 2, 0))
    order = np.argsort(np.nan_to_num(x), axis=0)
    xs = np.take_along_axis(np.nan_to_num(x), order, 0)
    cw = np.cumsum(w[order], 0) - w[order] / 2
    qx = np.array([[np.interp(p, cw[:, j], xs[:, j]) for j in range(x.shape[1])] for p in q])
    qo = np.quantile(o, q, axis=0)
    with np.errstate(divide='ignore', invalid='ignore'):
        stats.update(mean_ratio=mu / o.mean(0), sd_ratio=sd / o.std(0),
                     **{f'q{int(100 * p)}_ratio': qx[i] / qo[i] for i, p in enumerate(q)})
    stats['zero_fraction_difference'] = (w @ (np.nan_to_num(x) <= 0)) - (o <= 0).mean(0)
    return stats


def region_distribution(stats, area, region, ok):
    out = {}
    for k, v in stats.items():
        good = region & ok & np.isfinite(v)
        w = area[good] / area[good].sum()
        order = np.argsort(v[good])
        median = float(v[good][order][np.searchsorted(np.cumsum(w[order]), .5)])
        if k.endswith('ratio'):            # medians: a mean of ratios is dominated by near-zero CHIRPS values in dry cells
            out[k] = dict(area_median=median, area_mean_abs_log=float(w @ np.abs(np.log(np.maximum(v[good], 1e-6)))))
        else:
            out[k] = dict(area_median=median, area_mean=float(w @ v[good]))
    return out


# ---------------------------------------------------------------- main

def main(args):
    cfg = json.loads((ROOT / args.config).read_text(encoding='utf-8'))
    project = load_config(cfg['project_config'])
    methods = args.methods or list(cfg['methods'])
    targets = args.targets or cfg['targets']
    ref = cfg['reference_method']
    if ref not in methods:
        methods = [ref] + methods
    rng = lambda a, b: list(range(a, b + 1))
    train_years, test_years, all_years = rng(*cfg['training_years']), rng(*cfg['test_years']), rng(*cfg['all_years'])
    designs = {
        'training': [([z for z in train_years if z != y], [y]) for y in train_years],
        'operational': [(train_years, test_years)],
        'full': [([z for z in all_years if z != y], [y]) for y in all_years],
    }
    out_root = ROOT / cfg['output_root']
    alpha, bins = cfg['smoothing_alpha'], cfg['pit_bins']
    results, cell_maps, forecasts = {}, {}, {}
    lat = lon = None
    for target in targets:
        tag, models_full, obs_full, lat, lon = load_target(cfg, project, target)
        cells = load_mask(cfg['cells'], lat, lon)
        idx = np.flatnonzero(cells)
        models = {y: m[:, idx] for y, m in models_full.items()}
        obs = {y: o[idx] for y, o in obs_full.items()}
        area = cell_area(lat, lon)[idx]
        regions = {k: load_mask(v, lat, lon)[idx] for k, v in cfg['regions'].items()}
        results[target] = dict(tag=tag, cells=int(len(idx)), methods={})
        cell_maps[target] = {}
        forecasts[target] = {}
        for method in methods:
            params = cfg['methods'].get(method, {})
            row = {}
            for design, folds in designs.items():
                scores, ens = run_design(method, params, models, obs, folds, alpha)
                row[design] = {r: summarise(scores, area, mask, bins) for r, mask in regions.items()}
                if design == 'full':
                    ok = np.all([scores[y]['ok'] for y in all_years], 0)
                    dist = distribution(ens, obs, all_years)
                    row['distribution_full'] = {r: region_distribution(dist, area, mask, ok) for r, mask in regions.items()}
                    crps = np.sum([scores[y]['crps'] for y in all_years], 0)
                    crps_c = np.sum([scores[y]['crps_clim'] for y in all_years], 0)
                    rps_ = np.sum([scores[y]['rps'] for y in all_years], 0)
                    rps_c = np.sum([scores[y]['rps_clim'] for y in all_years], 0)
                    prob_ok = np.all([scores[y]['prob_ok'] for y in all_years], 0)
                    with np.errstate(divide='ignore', invalid='ignore'):
                        maps = dict(crpss=np.where(ok, 1 - crps / crps_c, np.nan),
                                    rpss=np.where(prob_ok, 1 - rps_ / rps_c, np.nan),
                                    bias_mm=np.where(ok, np.mean([scores[y]['mean'] - scores[y]['obs'] for y in all_years], 0), np.nan),
                                    correlation=cell_correlation(np.array([scores[y]['mean'] for y in all_years]),
                                                                 np.array([scores[y]['obs'] for y in all_years])),
                                    **{k: np.where(ok, v, np.nan) for k, v in dist.items()})
                    cell_maps[target][method] = maps
            # Forecast: fit on all observed years, correct the forecast-year members
            m = METHODS[method]
            p = {**m.defaults, **params}
            state = m.fit([models[y] for y in all_years], np.stack([obs[y] for y in all_years]), **p)
            fc = np.asarray(m.apply(models[cfg['forecast_year']], state, **p), float)
            fc[:, ~state['ok']] = np.nan
            forecasts[target][method] = fc
            results[target]['methods'][method] = row
            tr = row['training'][cfg['primary_region']]
            print(f"{target:4s} {method:9s} train CRPSS {tr['crpss']:+.4f} RPSS {tr['rpss']:+.4f} "
                  f"bias {tr['mean_bias_mm']:+7.2f} spread/err {tr['spread_error_ratio']:.2f} "
                  f"zero {tr['zero_fraction']:.3f}", flush=True)
        clim_mean = np.mean([obs[y] for y in all_years], 0)
        forecasts[target]['_raw'] = models[cfg['forecast_year']]
        forecasts[target]['_clim'] = clim_mean
        forecasts[target]['_terciles'] = np.quantile(np.stack([obs[y] for y in all_years]), [1 / 3, 2 / 3], axis=0)
        forecasts[target]['_idx'] = idx

    gates = make_gates(results, methods, ref, cfg['primary_region'], targets)
    out_root.mkdir(parents=True, exist_ok=True)
    meta = dict(created_utc=datetime.now(timezone.utc).isoformat(), config=args.config, config_contents=cfg,
                protocol=__doc__.strip(), gate_rule=gate.__doc__.strip(),
                methods={k: dict(label=METHODS[k].label, family=METHODS[k].family, definition=METHODS[k].definition,
                                 references=METHODS[k].references, member_wise=METHODS[k].member_wise,
                                 uses_forecast_distribution=METHODS[k].uses_forecast_distribution,
                                 parameters={**METHODS[k].defaults, **cfg['methods'].get(k, {})}) for k in methods})
    save_json(out_root / 'benchmark.json', dict(**meta, targets=results, gates=gates))
    save_cells(out_root / 'cell_scores_full_loyo.nc', cell_maps, lat, lon, methods, targets, cells)
    save_forecast(out_root / f"forecast_{cfg['forecast_year']}_members.nc", forecasts, lat, lon, methods, targets, cfg)
    if not args.no_figures:
        import bias_benchmark_figures as figs
        figs.make_all(out_root, results, gates, cell_maps, forecasts, lat, lon, methods, targets, cfg)
    print('Saved:', out_root)


def make_gates(results, methods, ref, region, targets):
    gates = {}
    for method in methods:
        if method == ref or METHODS[method].family == 'baseline':
            continue
        gates[method] = {}
        for score in ('crps', 'rps'):
            stats = {}
            for t in targets:
                rows = results[t]['methods']
                stats[t] = {d: paired_summary(rows[method][d][region]['per_year'][score], rows[ref][d][region]['per_year'][score])
                            for d in ('training', 'operational')}
            adjusted = holm({t: s['training']['p_improvement'] for t, s in stats.items()})
            gates[method][score] = {t: dict(**stats[t], decision=gate(stats[t]['training'], stats[t]['operational'], adjusted[t]))
                                    for t in targets}
    return gates


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
    member_wise = [m for m in methods if METHODS[m].member_wise and m != 'raw']
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
