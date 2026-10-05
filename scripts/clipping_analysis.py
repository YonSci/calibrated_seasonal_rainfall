"""Diagnose zero-clipping in the mean-variance amount correction and test alternatives.

Read-only experiment: never touches final_shared_blend outputs or frozen forecasts.

Methods (all per cell, fitted on training years only):
  affine        current: mu_o + r (x - mu_h), r = clip(sd_o/sd_h, .5, 2), then max(0, .)
  multiplicative x * mu_o / mu_h (mean match, never negative)
  sqrt_affine   affine correction in square-root space, clipped at 0, squared back
  quantile_map  empirical quantile mapping of pooled training members onto training CHIRPS

Evaluation on Ethiopia cells, spherical area weights, equal year weights:
  training  : leave-one-year-out within 1993-2016 (clean)
  operational: 1993-2016 fit, scored 2017-2025 (exploratory; years seen before)
Metrics: fair ensemble CRPS (mm), ensemble-mean bias and MAE (mm), tercile RPS of
alpha=0.5 smoothed member counts using the training-fold CHIRPS terciles, clip fraction.
"""
import argparse
from datetime import datetime, timezone
import numpy as np
from common import ROOT, load_config, save_json
from calibration_core import fit_amount, categories
from compare_calibration import smooth
from final_shared_blend import TARGETS, load_region
from run_calibration import load_inputs, load_land, cell_area

TRAIN = list(range(1993, 2017))
TEST = list(range(2017, 2026))
METHODS = ['affine', 'multiplicative', 'sqrt_affine', 'quantile_map']


def fit_extra(models, obs, pars):
    """Statistics for the alternative methods, on the same training years."""
    pooled = np.concatenate(models)                       # (all members, pixel)
    sm = [np.sqrt(m) for m in models]
    mu_hs = np.mean([m.mean(0) for m in sm], axis=0)
    sd_hs = np.sqrt(np.maximum(np.mean([(m * m).mean(0) for m in sm], axis=0) - mu_hs ** 2, 0))
    so = np.sqrt(np.where(np.isfinite(obs), obs, 0))
    mu_os, sd_os = so.mean(0), so.std(0)
    r = np.ones_like(mu_hs)
    np.divide(sd_os, sd_hs, out=r, where=sd_hs >= 0.1)
    return dict(pooled=np.sort(pooled, axis=0), obs_sorted=np.sort(np.where(np.isfinite(obs), obs, 0), axis=0),
                mu_hs=mu_hs, mu_os=mu_os, r_s=np.clip(r, .5, 2.))


def correct(method, x, pars, extra):
    raw = pars['mu_obs'] + pars['scale'] * (x - pars['mu_model'])
    if method == 'affine':
        out = np.maximum(raw, 0)
    elif method == 'multiplicative':
        ratio = np.divide(pars['mu_obs'], pars['mu_model'], out=np.ones_like(pars['mu_obs']),
                          where=pars['mu_model'] > 0.1)
        out = x * ratio
    elif method == 'sqrt_affine':
        s = extra['mu_os'] + extra['r_s'] * (np.sqrt(x) - extra['mu_hs'])
        out = np.maximum(s, 0) ** 2
    elif method == 'quantile_map':
        model_sorted, obs_sorted = extra['pooled'], extra['obs_sorted']
        n_m, n_o = len(model_sorted), len(obs_sorted)
        pm = (np.arange(n_m) + .5) / n_m
        po = (np.arange(n_o) + .5) / n_o
        out = np.empty_like(x, dtype=float)
        for j in range(x.shape[1]):
            prob = np.interp(x[:, j], model_sorted[:, j], pm)
            out[:, j] = np.interp(prob, po, obs_sorted[:, j])
    else:
        raise ValueError(method)
    out = np.asarray(out, float)
    out[:, ~pars['amount_eligible']] = np.nan
    return out, raw


def fair_crps(ens, y):
    m = len(ens)
    e = np.sort(ens, axis=0)
    term1 = np.abs(ens - y[None, :]).mean(0)
    rank = (2 * np.arange(1, m + 1) - m - 1)[:, None]
    spread = 2 * (rank * e).sum(0) / (m * (m - 1))      # mean |xi - xj| over i != j
    return term1 - spread / 2


def tercile_rps(ens, y, pars):
    c = categories(ens, pars['q1'], pars['q2'])
    p = smooth(np.stack([(c == k).mean(0) for k in range(3)], axis=-1), len(ens))
    t = np.eye(3)[categories(y, pars['q1'], pars['q2'])]
    return np.sum((np.cumsum(p, -1)[:, :2] - np.cumsum(t, -1)[:, :2]) ** 2, -1)


def evaluate(models, obs, train, target, region, area):
    pars = fit_amount([models[y] for y in train], np.stack([obs[y] for y in train]), np.ones(obs[target].size, bool))
    extra = fit_extra([models[y] for y in train], np.stack([obs[y] for y in train]), pars)
    amount = region & pars['amount_eligible'] & np.isfinite(obs[target])
    prob = region & pars['probability_eligible'] & np.isfinite(obs[target])
    wa, wp = area[amount] / area[amount].sum(), area[prob] / area[prob].sum()
    y = obs[target]
    row = {}
    for method in METHODS:
        ens, raw = correct(method, models[target], pars, extra)
        mean = ens.mean(0)
        row[method] = dict(
            crps=float(wa @ fair_crps(ens[:, amount], y[amount])),
            mean_bias=float(wa @ (mean[amount] - y[amount])),
            mean_mae=float(wa @ np.abs(mean[amount] - y[amount])),
            rps=float(wp @ tercile_rps(ens[:, prob], y[prob], {k: pars[k][prob] for k in ('q1', 'q2')})),
        )
        if method == 'affine':
            clipped = raw[:, amount] < 0
            row['clip'] = dict(
                fraction=float(clipped.mean()),
                mean_inflation_mm=float(wa @ (mean[amount] - raw[:, amount].mean(0))),
            )
            row['clip_by_climate'] = {}
            for lo, hi in [(0, 50), (50, 150), (150, 300), (300, 1e9)]:
                band = (pars['mu_obs'][amount] >= lo) & (pars['mu_obs'][amount] < hi)
                if band.any():
                    row['clip_by_climate'][f'{lo}-{int(hi) if hi < 1e9 else "inf"}mm'] = dict(
                        cells=int(band.sum()), clip_fraction=float(clipped[:, band].mean()),
                        median_scale=float(np.median(pars['scale'][amount][band])))
    return row


def summarise(rows):
    out = {}
    for m in METHODS:
        out[m] = {k: float(np.mean([r[m][k] for r in rows])) for k in rows[0][m]}
    out['clip_fraction'] = float(np.mean([r['clip']['fraction'] for r in rows]))
    out['clip_mean_inflation_mm'] = float(np.mean([r['clip']['mean_inflation_mm'] for r in rows]))
    bands = rows[0]['clip_by_climate'].keys()
    out['clip_by_climate'] = {b: dict(cells=rows[0]['clip_by_climate'][b]['cells'],
                                      clip_fraction=float(np.mean([r['clip_by_climate'][b]['clip_fraction'] for r in rows if b in r['clip_by_climate']])),
                                      median_scale=float(np.mean([r['clip_by_climate'][b]['median_scale'] for r in rows if b in r['clip_by_climate']])))
                              for b in bands}
    base = out['affine']
    for m in METHODS[1:]:
        out[m]['crps_skill_vs_affine'] = 1 - out[m]['crps'] / base['crps']
        out[m]['rps_skill_vs_affine'] = 1 - out[m]['rps'] / base['rps']
    out['per_year_crps'] = {m: [round(r[m]['crps'], 3) for r in rows] for m in METHODS}
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--config', default='config/project.json')
    p.add_argument('--targets', nargs='+', choices=TARGETS, default=TARGETS)
    p.add_argument('--region-mask', default='data/masks/ethiopia_common.nc')
    args = p.parse_args()
    from run_monthly import monthly_config
    base = load_config(args.config)
    month = {'Jun': 6, 'Jul': 7, 'Aug': 8, 'Sep': 9}
    results = {}
    for t in args.targets:
        cfg = base if t == 'JJAS' else monthly_config(base, month[t])
        tag, models, obs, members, lat, lon = load_inputs(cfg, TRAIN + TEST, TRAIN + TEST)
        region, _ = load_region(args.region_mask, lat, lon)
        area = cell_area(lat, lon)
        training = [evaluate(models, obs, [z for z in TRAIN if z != y], y, region, area) for y in TRAIN]
        operational = [evaluate(models, obs, TRAIN, y, region, area) for y in TEST]
        results[t] = dict(tag=tag, training_loyo_1993_2016=summarise(training),
                          operational_2017_2025=summarise(operational))
        tr = results[t]['training_loyo_1993_2016']
        print(f"{t}: clip {tr['clip_fraction']:.3f}, mean inflation {tr['clip_mean_inflation_mm']:+.2f} mm | CRPS "
              + ' '.join(f"{m}={tr[m]['crps']:.2f}" for m in METHODS) + ' | RPS '
              + ' '.join(f"{m}={tr[m]['rps']:.4f}" for m in METHODS), flush=True)
    out = ROOT / 'outputs/clipping_analysis/amount_correction_alternatives.json'
    save_json(out, dict(created_utc=datetime.now(timezone.utc).isoformat(), protocol=__doc__.strip(), targets=results))
    print('Saved:', out)


if __name__ == '__main__':
    main()
