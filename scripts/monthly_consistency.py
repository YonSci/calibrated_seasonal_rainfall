"""Monthly-seasonal consistency of corrected amounts and tercile probabilities (item 10).

Read-only experiment. Member i in June, July, August and September is the same
model run, so corrected monthly members can be summed into a JJAS ensemble
("sum of months") and compared with the directly corrected JJAS ensemble ("direct").

Both use JJAS CHIRPS terciles and eligibility, alpha=0.5 smoothing and no blend,
scored on Ethiopia cells against JJAS CHIRPS:
  training    : leave-one-year-out within 1993-2016 (all fits exclude the year)
  operational : 1993-2016 fits, scored 2017-2025 (exploratory)
2026: compares the frozen final products (JJAS corrected mean vs sum of monthly
corrected means; area-mean JJAS probabilities vs the monthly probabilities).
"""
import argparse
from datetime import datetime, timezone
import numpy as np
import xarray as xr
from common import ROOT, load_config, save_json
from calibration_core import fit_amount, correct_amount, probabilities, labels
from compare_calibration import smooth
from clipping_analysis import fair_crps
from final_shared_blend import load_region
from run_calibration import load_inputs, cell_area
from run_monthly import monthly_config
from significance import paired_summary

TRAIN = list(range(1993, 2017))
TEST = list(range(2017, 2026))
MONTHS = {'Jun': 6, 'Jul': 7, 'Aug': 8, 'Sep': 9}


def rps(p, y):
    t = np.eye(3)[y]
    return np.sum((np.cumsum(p, -1)[:, :2] - np.cumsum(t, -1)[:, :2]) ** 2, -1)


def evaluate(data, train, year, region, area):
    models, obs = data['JJAS']
    pj = fit_amount([models[z] for z in train], np.stack([obs[z] for z in train]), np.ones(obs[year].size, bool))
    direct = correct_amount(models[year], pj)
    total = 0
    for m in MONTHS:
        mm, mo = data[m]
        pm = fit_amount([mm[z] for z in train], np.stack([mo[z] for z in train]), np.ones(mo[year].size, bool))
        total = total + correct_amount(mm[year], pm)
    y = labels(obs[year], pj)
    amount = region & pj['amount_eligible'] & np.isfinite(total).all(0)
    prob = amount & pj['probability_eligible'] & (y >= 0)
    wa, wp = area[amount] / area[amount].sum(), area[prob] / area[prob].sum()
    out = {}
    probs = {}
    for name, ens in (('direct', direct), ('sum_of_months', total)):
        p = smooth(probabilities(ens, pj), len(ens))
        probs[name] = p
        out[name] = dict(crps=float(wa @ fair_crps(ens[:, amount], obs[year][amount])),
                         mean_bias=float(wa @ (ens.mean(0)[amount] - obs[year][amount])),
                         rps=float(wp @ rps(p[prob], y[prob])))
    d = probs['sum_of_months'][prob] - probs['direct'][prob]
    out['mean_abs_probability_difference'] = float(wp @ np.abs(d).mean(1))
    out['dominant_category_agreement'] = float(wp @ (probs['sum_of_months'][prob].argmax(1) == probs['direct'][prob].argmax(1)))
    out['mean_amount_difference_mm'] = float(wa @ (total.mean(0)[amount] - direct.mean(0)[amount]))
    return out


def summarise(rows):
    s = {k: {m: float(np.mean([r[k][m] for r in rows])) for m in rows[0][k]} for k in ('direct', 'sum_of_months')}
    for k in ('mean_abs_probability_difference', 'dominant_category_agreement', 'mean_amount_difference_mm'):
        s[k] = float(np.mean([r[k] for r in rows]))
    for metric in ('crps', 'rps'):
        s[f'{metric}_sum_minus_direct'] = paired_summary([r['sum_of_months'][metric] for r in rows],
                                                         [r['direct'][metric] for r in rows])
    return s


def frozen_2026(region, area_by_grid):
    root = ROOT / 'outputs/final_shared_blend'
    with xr.open_dataset(root / 'init05_JJAS/2026/forecast_2026.nc') as j:
        jm, jp = j.corrected_ensemble_mean.values.ravel(), j.blend_probability.values.reshape(-1, 3)
    months = {}
    for m in MONTHS:
        with xr.open_dataset(root / f'init05_{m}/2026/forecast_2026.nc') as d:
            months[m] = (d.corrected_ensemble_mean.values.ravel(), d.blend_probability.values.reshape(-1, 3))
    msum = sum(v[0] for v in months.values())
    ok = region & np.isfinite(jm) & np.isfinite(msum)
    w = area_by_grid[ok] / area_by_grid[ok].sum()
    probs = {}
    for name, p in [('JJAS', jp)] + [(m, v[1]) for m, v in months.items()]:
        keep = region & np.isfinite(p).all(1)
        ww = area_by_grid[keep] / area_by_grid[keep].sum()
        probs[name] = (ww @ p[keep]).round(4).tolist()
    return dict(jjas_corrected_mean_mm=float(w @ jm[ok]), sum_of_monthly_corrected_means_mm=float(w @ msum[ok]),
                difference_mm=float(w @ (msum[ok] - jm[ok])),
                area_mean_blend_probabilities_below_near_above=probs)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--config', default='config/project.json')
    p.add_argument('--region-mask', default='data/masks/ethiopia_common.nc')
    args = p.parse_args()
    base = load_config(args.config)
    data, member_ids = {}, {}
    for name in ['JJAS'] + list(MONTHS):
        cfg = base if name == 'JJAS' else monthly_config(base, MONTHS[name])
        _, models, obs, members, lat, lon = load_inputs(cfg, TRAIN + TEST, TRAIN + TEST)
        data[name] = (models, obs)
        member_ids[name] = {y: list(map(int, members[y])) for y in TRAIN + TEST}
    for m in MONTHS:
        if member_ids[m] != member_ids['JJAS']:
            raise ValueError(f'Member identifiers differ between {m} and JJAS; summing members is invalid.')
    region, _ = load_region(args.region_mask, lat, lon)
    area = cell_area(lat, lon)
    training = [evaluate(data, [z for z in TRAIN if z != y], y, region, area) for y in TRAIN]
    operational = [evaluate(data, TRAIN, y, region, area) for y in TEST]
    result = dict(training_loyo_1993_2016=summarise(training), operational_2017_2025=summarise(operational),
                  frozen_2026=frozen_2026(region, area))
    for k in ('training_loyo_1993_2016', 'operational_2017_2025'):
        s = result[k]
        print(f"{k}: CRPS direct {s['direct']['crps']:.2f} sum {s['sum_of_months']['crps']:.2f} "
              f"(d={s['crps_sum_minus_direct']['mean_difference']:+.2f}, p={s['crps_sum_minus_direct']['p_improvement']:.3f}) | "
              f"RPS direct {s['direct']['rps']:.4f} sum {s['sum_of_months']['rps']:.4f} "
              f"(d={s['rps_sum_minus_direct']['mean_difference']:+.4f}, p={s['rps_sum_minus_direct']['p_improvement']:.3f}) | "
              f"|dp| {s['mean_abs_probability_difference']:.3f} dominant agree {s['dominant_category_agreement']:.0%} "
              f"amount diff {s['mean_amount_difference_mm']:+.1f} mm")
    print('2026:', result['frozen_2026'])
    out = ROOT / 'outputs/monthly_consistency/monthly_consistency.json'
    save_json(out, dict(created_utc=datetime.now(timezone.utc).isoformat(), protocol=__doc__.strip(), **result))
    print('Saved:', out)


if __name__ == '__main__':
    main()
