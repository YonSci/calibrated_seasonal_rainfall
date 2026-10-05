"""Sensitivity of the shared climatology-blend weight to the fitting domain.

Read-only experiment: never touches outputs/final_shared_blend or the frozen 2026
forecasts. Amount correction, terciles and eligibility are per cell, so the fitting
domain only changes the pooled blend weight (lambda). For each target this compares:

  full_domain : lambda fitted on every eligible cell (current operational choice)
  ethiopia    : lambda fitted only on cells inside data/masks/ethiopia_common.nc

Protocol as docs 16-17: lambda from leave-one-year-out records within 1993-2016,
scored on 2017-2025 with 1993-2016 fits. Scores use Ethiopia cells only, spherical
area weights, equal year weights. Exploratory: 2017-2025 has been seen before.
"""
import argparse
from datetime import datetime, timezone
import numpy as np
from common import ROOT, load_config, save_json
from compare_calibration import make_record
from final_shared_blend import TARGETS, load_region
from local_blend import fit_weights
from run_calibration import load_inputs, load_land, cell_area

TRAIN = list(range(1993, 2017))
TEST = list(range(2017, 2026))


def rps(p, y):
    """Ranked probability score per cell (sum over the two cumulative categories)."""
    truth = np.eye(3)[np.maximum(y, 0)]
    return np.sum((np.cumsum(p, axis=-1)[..., :2] - np.cumsum(truth, axis=-1)[..., :2]) ** 2, axis=-1)


def restrict(records, keep):
    """Mark cells outside `keep` as invalid so fit_weights ignores them."""
    return [dict(r, y=np.where(keep, r['y'], -1)) for r in records]


def year_scores(records, lam, region, area):
    rows = []
    for r in records:
        valid = region & (r['y'] >= 0) & np.isfinite(r['s']).all(-1) & np.isfinite(r['clim']).all(-1)
        w = area[valid] / area[valid].sum()
        blend = (1 - lam) * r['s'] + lam * r['clim']
        rows.append({k: float(w @ rps(p[valid], r['y'][valid]))
                     for k, p in [('blend', blend), ('smooth', r['s']), ('climatology', r['clim'])]})
    return rows


def bootstrap_diff(a, b, draws=5000, seed=0):
    """Year-block bootstrap of mean(a - b); negative favours a."""
    d = np.asarray(a) - np.asarray(b)
    idx = np.random.default_rng(seed).integers(0, len(d), (draws, len(d)))
    m = d[idx].mean(axis=1)
    return dict(mean=float(d.mean()), ci95=[float(np.quantile(m, .025)), float(np.quantile(m, .975))],
                years_better=int((d < 0).sum()), years=len(d))


def run_target(cfg, region_path):
    tag, models, obs, members, lat, lon = load_inputs(cfg, TRAIN + TEST, TRAIN + TEST)
    land, _ = load_land(None, lat, lon)
    region, _ = load_region(region_path, lat, lon)
    area = cell_area(lat, lon)
    train_records = [make_record([z for z in TRAIN if z != y], y, models, obs, land) for y in TRAIN]
    test_records = [make_record(TRAIN, y, models, obs, land) for y in TEST]
    eligible = np.isfinite(train_records[0]['clim']).all(-1)
    lam = {'full_domain': fit_weights(train_records, area)['shared_lambda'],
           'ethiopia': fit_weights(restrict(train_records, region), area)['shared_lambda']}
    scores = {k: year_scores(test_records, v, region, area) for k, v in lam.items()}
    mean = {k: {m: float(np.mean([s[m] for s in v])) for m in v[0]} for k, v in scores.items()}
    clim = mean['full_domain']['climatology']
    return dict(
        tag=tag,
        eligible_cells_full_domain=int(eligible.sum()),
        eligible_cells_ethiopia=int((eligible & region).sum()),
        share_of_fit_area_outside_ethiopia=float(area[eligible & ~region].sum() / area[eligible].sum()),
        climatology_weight=lam,
        rps_2017_2025_ethiopia={k: v['blend'] for k, v in mean.items()},
        rpss_2017_2025_ethiopia={k: 1 - v['blend'] / clim for k, v in mean.items()},
        smooth_only_rpss=1 - mean['full_domain']['smooth'] / clim,
        ethiopia_minus_full=bootstrap_diff([s['blend'] for s in scores['ethiopia']],
                                           [s['blend'] for s in scores['full_domain']]),
        per_year_rps={k: [round(s['blend'], 5) for s in v] for k, v in scores.items()},
    )


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
        results[t] = run_target(cfg, args.region_mask)
        r = results[t]
        print(f"{t}: lambda full={r['climatology_weight']['full_domain']:.3f} "
              f"eth={r['climatology_weight']['ethiopia']:.3f} | RPSS full={r['rpss_2017_2025_ethiopia']['full_domain']:+.4f} "
              f"eth={r['rpss_2017_2025_ethiopia']['ethiopia']:+.4f} | diff CI {r['ethiopia_minus_full']['ci95']}", flush=True)
    out = ROOT / 'outputs/mask_sensitivity/blend_domain_sensitivity.json'
    save_json(out, dict(created_utc=datetime.now(timezone.utc).isoformat(), protocol=__doc__.strip(), targets=results))
    print('Saved:', out)


if __name__ == '__main__':
    main()
