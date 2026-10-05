"""Ensemble-size transfer and hindcast/operational consistency checks (item 8).

Read-only experiment: never touches final_shared_blend outputs or frozen forecasts.

1. Ensemble size. The blend weight is fitted on 25-member hindcast probabilities
   (1993-2016) and applied to 51-member forecasts. On 2017-2025 the final-method
   chain (affine correction, alpha=0.5 smoothing, shared blend) is scored with all
   51 members and with repeated random 25-member subsets (one subset per year,
   shared by all cells). If 51-member RPS is no worse, the transfer is safe.
2. System consistency. Raw-model statistics on Ethiopia cells, per year:
   bias of the ensemble mean against CHIRPS, member spread (unbiased SD), and the
   corrected-ensemble spread/error ratio. Hindcast years (1993-2016) are compared
   with operational years (2017-2025) with a permutation test on year means.
"""
import argparse
from datetime import datetime, timezone
import numpy as np
from common import ROOT, load_config, save_json
from compare_calibration import make_record, smooth
from calibration_core import fit_amount, correct_amount, probabilities, labels
from final_shared_blend import TARGETS, load_region
from local_blend import fit_weights
from run_calibration import load_inputs, load_land, cell_area

TRAIN = list(range(1993, 2017))
TEST = list(range(2017, 2026))


def rps(p, y):
    t = np.eye(3)[y]
    return np.sum((np.cumsum(p, -1)[:, :2] - np.cumsum(t, -1)[:, :2]) ** 2, -1)


def blend_rps(members, pars, clim, lam, y, keep, w):
    p = probabilities(correct_amount(members, pars), pars)
    b = (1 - lam) * smooth(p, len(members)) + lam * clim
    return float(w @ rps(b[keep], y[keep]))


def perm_p_two_sided(a, b, draws=20000, seed=20261005):
    a, b = np.asarray(a, float), np.asarray(b, float)
    pooled = np.r_[a, b]
    obs = abs(a.mean() - b.mean())
    rng = np.random.default_rng(seed)
    hits = 0
    for _ in range(draws):
        rng.shuffle(pooled)
        hits += abs(pooled[:len(a)].mean() - pooled[len(a):].mean()) >= obs - 1e-12
    return hits / draws


def run_target(cfg, region_path, repeats):
    _, models, obs, members, lat, lon = load_inputs(cfg, TRAIN + TEST, TRAIN + TEST)
    region, _ = load_region(region_path, lat, lon)
    land, _ = load_land(None, lat, lon)
    area = cell_area(lat, lon)
    records = [make_record([z for z in TRAIN if z != y], y, models, obs, land) for y in TRAIN]
    lam = fit_weights(records, area)['shared_lambda']
    pars = fit_amount([models[y] for y in TRAIN], np.stack([obs[y] for y in TRAIN]), land)
    cats = np.stack([labels(obs[y], pars) for y in TRAIN])
    clim = np.stack([(cats == k).mean(0) for k in range(3)], -1)
    clim[~pars['probability_eligible']] = np.nan

    rng = np.random.default_rng(20261005)
    full, subs = [], []
    for y in TEST:
        lab = labels(obs[y], pars)
        keep = region & (lab >= 0) & pars['probability_eligible']
        w = area[keep] / area[keep].sum()
        full.append(blend_rps(models[y], pars, clim, lam, lab, keep, w))
        subs.append([blend_rps(models[y][rng.choice(len(models[y]), 25, replace=False)], pars, clim, lam, lab, keep, w)
                     for _ in range(repeats)])
    subs = np.array(subs)
    size = dict(climatology_weight=lam, members_test=sorted({len(models[y]) for y in TEST}),
                rps_51=float(np.mean(full)), rps_25_mean=float(subs.mean()),
                rps_25_p2_5=float(np.quantile(subs.mean(0), .025)), rps_25_p97_5=float(np.quantile(subs.mean(0), .975)),
                subset_minus_full=float(subs.mean() - np.mean(full)))

    stats = {}
    amount = region & pars['amount_eligible']
    wa = area[amount] / area[amount].sum()
    for y in TRAIN + TEST:
        m = models[y][:, amount]
        corr = correct_amount(models[y], pars)[:, amount] if y in TEST else None
        if y in TRAIN:  # leave-one-year-out correction for hindcast years
            p_loo = fit_amount([models[z] for z in TRAIN if z != y], np.stack([obs[z] for z in TRAIN if z != y]), land)
            corr = correct_amount(models[y], p_loo)[:, amount]
        err = corr.mean(0) - obs[y][amount]
        stats[y] = dict(members=len(m), raw_bias=float(wa @ (m.mean(0) - obs[y][amount])),
                        raw_spread=float(wa @ m.std(0, ddof=1)),
                        corrected_spread=float(wa @ corr.std(0, ddof=1)),
                        corrected_rmse=float(np.sqrt(wa @ err ** 2)))
    groups = {}
    for key in ('raw_bias', 'raw_spread', 'corrected_spread', 'corrected_rmse'):
        a, b = [stats[y][key] for y in TRAIN], [stats[y][key] for y in TEST]
        groups[key] = dict(hindcast_mean=float(np.mean(a)), operational_mean=float(np.mean(b)),
                           difference=float(np.mean(b) - np.mean(a)), permutation_p=perm_p_two_sided(a, b))
    for label, years in (('hindcast', TRAIN), ('operational', TEST)):
        groups[f'spread_error_ratio_{label}'] = float(np.mean([stats[y]['corrected_spread'] for y in years]) /
                                                      np.sqrt(np.mean([stats[y]['corrected_rmse'] ** 2 for y in years])))
    return dict(ensemble_size=size, system_consistency=groups, per_year=stats)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--config', default='config/project.json')
    p.add_argument('--targets', nargs='+', choices=TARGETS, default=TARGETS)
    p.add_argument('--region-mask', default='data/masks/ethiopia_common.nc')
    p.add_argument('--repeats', type=int, default=100)
    args = p.parse_args()
    from run_monthly import monthly_config
    base = load_config(args.config)
    month = {'Jun': 6, 'Jul': 7, 'Aug': 8, 'Sep': 9}
    results = {}
    for t in args.targets:
        cfg = base if t == 'JJAS' else monthly_config(base, month[t])
        r = results[t] = run_target(cfg, args.region_mask, args.repeats)
        s, g = r['ensemble_size'], r['system_consistency']
        print(f"{t}: RPS 51={s['rps_51']:.4f} 25-subsets={s['rps_25_mean']:.4f} [{s['rps_25_p2_5']:.4f},{s['rps_25_p97_5']:.4f}] | "
              + ' '.join(f"{k} {v['hindcast_mean']:.1f}->{v['operational_mean']:.1f} (p={v['permutation_p']:.3f})"
                         for k, v in g.items() if isinstance(v, dict))
              + f" | spread/error {g['spread_error_ratio_hindcast']:.2f}->{g['spread_error_ratio_operational']:.2f}", flush=True)
    out = ROOT / 'outputs/ensemble_checks/ensemble_checks.json'
    save_json(out, dict(created_utc=datetime.now(timezone.utc).isoformat(), protocol=__doc__.strip(), targets=results))
    print('Saved:', out)


if __name__ == '__main__':
    main()
