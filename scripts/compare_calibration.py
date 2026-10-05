"""Training-period cross-fitted comparison; never reads 2017-2026 data.

Uses existing common.py, calibration_core.py and run_calibration.py.
Run from the project root; see docs/15_TRAINING_ONLY_COMPARISON.md.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
import xarray as xr
from scipy.optimize import minimize_scalar
from scipy.special import softmax
from common import ROOT, load_config, source_path, save_json, save_netcdf
from calibration_core import (fit_amount, correct_amount, probabilities, labels,
                              fit_dirichlet, apply_dirichlet, log_inputs, EPS)
from run_calibration import load_inputs, load_land, cell_area

NAMES = ['climatology', 'base', 'smooth', 'temperature', 'blend',
         'dirichlet_original', 'dirichlet_smooth']


def smooth(p, members, alpha=0.5):
    """Symmetric additive count smoothing: (count + alpha)/(M + 3 alpha)."""
    return (members * p + alpha) / (members + 3 * alpha)


def make_record(train, target, models, obs, land):
    pars = fit_amount([models[y] for y in train], np.stack([obs[y] for y in train]), land)
    p = probabilities(correct_amount(models[target], pars), pars)
    train_labels = np.stack([labels(obs[y], pars) for y in train])
    clim = np.stack([(train_labels == k).mean(axis=0) for k in range(3)], axis=-1)
    clim[~pars['probability_eligible']] = np.nan
    return dict(p=p, s=smooth(p, len(models[target])), clim=clim,
                y=labels(obs[target], pars), q1=pars['q1'], q2=pars['q2'])


def pack(records, area):
    arrays = {k: [] for k in ('p', 's', 'clim', 'y')}
    weights = []
    for r in records:
        valid = (r['y'] >= 0) & np.isfinite(r['p']).all(axis=1)
        if not valid.any():
            raise ValueError('A calibration year has no valid pairs.')
        for k in arrays:
            arrays[k].append(r[k][valid])
        weights.append(area[valid] / area[valid].sum() / len(records))
    return {k: np.concatenate(v) for k, v in arrays.items()}, np.concatenate(weights)


def fit_maps(records, area):
    a, w = pack(records, area)
    x = log_inputs(a['s'])
    # One temperature, bounded a priori. Fit log(T) to avoid nonpositive T.
    def loss(log_t):
        p = softmax(x / np.exp(log_t), axis=1)
        return float(-w @ np.log(np.maximum(p[np.arange(len(p)), a['y']], EPS)))
    result = minimize_scalar(loss, bounds=(np.log(0.25), np.log(4.0)),
                             method='bounded', options={'xatol': 1e-7})
    if not result.success:
        raise RuntimeError('Temperature fit failed.')
    candidates = [(float(result.fun), float(result.x)),
                  (loss(np.log(.25)), float(np.log(.25))),
                  (loss(np.log(4.)), float(np.log(4.)))]
    _, log_t = min(candidates)
    # Analytic constrained minimum of RPS for (1-lambda)*smooth + lambda*clim.
    truth = np.eye(3)[a['y']]
    residual = np.cumsum(a['s'] - truth, axis=1)[:, :2]
    direction = np.cumsum(a['clim'] - a['s'], axis=1)[:, :2]
    denom = float(w @ np.sum(direction**2, axis=1))
    lam = float(np.clip(-(w @ np.sum(residual*direction, axis=1))/denom, 0, 1)) if denom > 0 else 0.
    return dict(temperature=float(np.exp(log_t)), blend_lambda=lam,
                dirichlet_original=fit_dirichlet([r['p'] for r in records], [r['y'] for r in records], area),
                dirichlet_smooth=fit_dirichlet([r['s'] for r in records], [r['y'] for r in records], area))


def predict(r, fitted):
    return dict(climatology=r['clim'], base=r['p'], smooth=r['s'],
                temperature=softmax(log_inputs(r['s']) / fitted['temperature'], axis=1),
                blend=(1-fitted['blend_lambda'])*r['s'] + fitted['blend_lambda']*r['clim'],
                dirichlet_original=apply_dirichlet(r['p'], fitted['dirichlet_original']),
                dirichlet_smooth=apply_dirichlet(r['s'], fitted['dirichlet_smooth']))


def score(pred, y, area, region):
    valid = region & (y >= 0)
    for p in pred.values():
        valid &= np.isfinite(p).all(axis=1)
    if not valid.any():
        raise ValueError('No common valid evaluation cells inside the region.')
    w = area[valid] / area[valid].sum()
    truth = np.eye(3)[y[valid]]
    rows = {}
    for name, p in pred.items():
        p = p[valid]
        if (p < 0).any() or not np.allclose(p.sum(axis=1), 1, atol=1e-10):
            raise ValueError('Invalid probabilities: ' + name)
        rows[name] = dict(rps=float(w @ np.sum(np.cumsum(p-truth, axis=1)[:, :2]**2, axis=1)),
                          log_loss=float(-w @ np.log(np.maximum(p[np.arange(len(p)), y[valid]], EPS))),
                          brier_by_category=(w @ ((p-truth)**2)).tolist(),
                          mean_max_probability=float(w @ p.max(axis=1)), cells=int(valid.sum()))
    return rows


def compare(models, obs, land, area, region, progress=None):
    """Outer validation year is absent even from INNER preprocessing fits."""
    years = sorted(models)
    if years != sorted(obs) or len(years) < 22:
        raise ValueError('Need at least 22 matched years for two-level cross-fitting.')
    rows, records, fits = [], [], []
    for i, year in enumerate(years):
        train = [y for y in years if y != year]
        inner = [make_record([z for z in train if z != y], y, models, obs, land) for y in train]
        fitted = fit_maps(inner, area)
        outer = make_record(train, year, models, obs, land)
        pred = predict(outer, fitted)
        rows.append(dict(year=year, metrics=score(pred, outer['y'], area, region)))
        records.append(dict(pred=pred, y=outer['y'], q1=outer['q1'], q2=outer['q2']))
        fits.append(dict(held_out_year=year, training_years=train, **fitted))
        if progress:
            progress(i+1, len(years), year)
    return rows, records, fits


def summarize(rows, bootstrap=2000):
    means = {}
    reference = np.array([r['metrics']['dirichlet_original']['rps'] for r in rows])
    rng = np.random.default_rng(20261003)
    indices = rng.integers(len(rows), size=(bootstrap, len(rows)))
    for name in NAMES:
        means[name] = {k: np.mean([r['metrics'][name][k] for r in rows], axis=0).tolist()
                       for k in ('rps', 'log_loss', 'brier_by_category', 'mean_max_probability')}
        delta = np.array([r['metrics'][name]['rps'] for r in rows]) - reference
        means[name]['rps_difference_vs_original'] = float(delta.mean())
        means[name]['paired_year_bootstrap_95_range'] = np.quantile(delta[indices].mean(axis=1), [.025, .975]).tolist()
    baseline = means['climatology']
    for name in NAMES:
        means[name]['rpss'] = 1-means[name]['rps']/baseline['rps'] if baseline['rps'] > 0 else None
        bs, ref = np.array(means[name]['brier_by_category']), np.array(baseline['brier_by_category'])
        means[name]['bss_by_category'] = np.where(ref > 0, 1-bs/ref, np.nan).tolist()
    return means


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/project.json')
    parser.add_argument('--region-mask', required=True)
    parser.add_argument('--land-mask')
    args = parser.parse_args()
    cfg = load_config(args.config)
    years = list(range(1993, 2017))
    tag, models, obs, members, lat, lon = load_inputs(cfg, years, years)
    land, land_info = load_land(args.land_mask, lat, lon)
    mask_path = source_path(args.region_mask)
    with xr.open_dataset(mask_path) as d:
        mask = d.region_mask.transpose('lat', 'lon')
        if not np.array_equal(mask.lat, lat) or not np.array_equal(mask.lon, lon):
            raise ValueError('Region mask grid differs from common grid.')
        if not np.isin(mask.values, [0, 1]).all() or not (mask.values == 1).any():
            raise ValueError('Expected nonempty binary region_mask.')
        region = mask.values.reshape(-1) == 1
    area = cell_area(lat, lon)
    out = ROOT/'outputs/model_comparison'/tag/'training_only'
    if out.exists():
        raise FileExistsError(f'{out} already exists. Rename that output folder before rerunning.')
    print('Using ONLY 1993-2016. Global calibration fit; region-only evaluation.', flush=True)
    print('24 outer folds, each with 23 inner preprocessing fits. Please allow time.', flush=True)
    rows, records, fits = compare(models, obs, land, area, region,
        lambda i, n, y: print(f'Completed outer fold {i}/{n}: held out {y}', flush=True))
    summary = summarize(rows)
    ranking = sorted(NAMES, key=lambda n: summary[n]['rps'])
    report = dict(training_years=years, category_order=['below', 'near', 'above'],
                  ranking_by_rps=ranking, provisional_candidate=ranking[0], equal_year_summary=summary,
                  years=rows, land_mask=land_info,
                  region_mask=dict(path=str(mask_path), sha256=hashlib.sha256(mask_path.read_bytes()).hexdigest(),
                                   cells=int(region.sum()), use='evaluation only; global fit retained'),
                  members={str(y): len(members[y]) for y in years}, alpha_per_category=.5,
                  note='Fixed candidate comparison. Winner score is selection-biased; this is not an unbiased estimate of the selected procedure. 2017-2025 already inspected; future comparison there is exploratory.',
                  uncertainty='Paired resampling of outer-year scores, fixed fits. Ignores serial dependence and overlapping-training-fit uncertainty; descriptive only.')
    attrs = dict(config_json=json.dumps(cfg), training_years='1993-2016',
                 note='Each outer year excluded from all fitting. Global fits, region-only ranking. Fold-specific thresholds.')
    d = xr.Dataset(coords=dict(year=years, lat=lat, lon=lon, category=['below', 'near', 'above']), attrs=attrs)
    for name in NAMES:
        d[name + '_probability'] = (('year', 'lat', 'lon', 'category'),
            np.stack([r['pred'][name] for r in records]).reshape(len(years), len(lat), len(lon), 3))
    for key in ('y', 'q1', 'q2'):
        d['observed_category' if key == 'y' else key] = (('year', 'lat', 'lon'),
            np.stack([r[key] for r in records]).reshape(len(years), len(lat), len(lon)))
    d['region_mask'] = (('lat', 'lon'), region.reshape(len(lat), len(lon)).astype('int8'))
    save_netcdf(d, out/'cross_validated_probabilities.nc')
    save_json(out/'comparison_summary.json', report)
    save_json(out/'fold_parameters.json', fits)
    with (out/'comparison_table.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['method', 'RPS', 'RPSS', 'log_loss', 'mean_max_probability', 'RPS_difference_vs_original'])
        for name in ranking:
            writer.writerow([name] + [summary[name][k] for k in ('rps', 'rpss', 'log_loss', 'mean_max_probability', 'rps_difference_vs_original')])
    for name in ranking:
        print(f"{name:22s} RPS={summary[name]['rps']:.5f} RPSS={summary[name]['rpss']:.4f}")
    print('Provisional candidate:', ranking[0])
    print('Comparison complete:', out)
    print('No operational model replaced. Review uncertainty and annual consistency before proceeding.')


if __name__ == '__main__':
    main()
