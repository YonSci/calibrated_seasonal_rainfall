"""Historical verification diagnostics for the results site (read-only, no refitting).

From the stored out-of-fold probabilities of the final method
(outputs/local_calibration/<tag>_<target>/{training,operational}/local_probabilities_and_weights.nc)
this computes, per target, evaluation period and area (all Ethiopia and the cycle's
rainfall domain):

- performance by year: area-weighted RPS of the blended probabilities and of
  climatology, and the year's RPSS;
- reliability diagrams: forecast probability bins (width 0.1) per tercile with the
  observed frequency and the number of cell-years;
- probability histogram: how often the leading tercile probability is weak
  (< 40%), moderate (40-50%), strong (50-60%) or very strong (>= 60%);
- category Brier scores of the blend and of climatology, and Brier skill.

Training = nested leave-one-year-out 1993-2016 (cross-validated); operational =
parameters fitted on 1993-2016 applied to later years (exploratory). Cell-years are
spatially correlated, so counts overstate the independent sample (one season per
year). Rainfall-amount diagnostics are included only where the pipeline already
produced them (May-initialized JJAS, 2017-2025, all Ethiopia).

    python scripts/historical_diagnostics.py --cycle config/cycles/sep_2026_ondj.json
"""
import argparse
import json
from datetime import datetime, timezone
import numpy as np
import xarray as xr
from common import ROOT, save_json
from run_calibration import cell_area

BINS = np.linspace(0, 1, 11)
LEAD = [(1 / 3, .4, 'weak (<40%)'), (.4, .5, 'moderate (40–50%)'), (.5, .6, 'strong (50–60%)'), (.6, 1.0001, 'very strong (≥60%)')]


def rps(p, y):
    t = np.eye(3)[np.maximum(y, 0)]
    return np.sum((np.cumsum(p, -1)[..., :2] - np.cumsum(t, -1)[..., :2]) ** 2, -1)


def areas(cycle):
    with xr.open_dataset(ROOT / cycle.raw['regime_mask']) as m:
        country = m.region_mask.values == 1
        r12 = m.github_jjas_r12_rainfall_cleaned.values == 1
        lat, lon = m.lat.values, m.lon.values
    if cycle.season_name == 'JJAS':
        return {'all_ethiopia': country, 'jjas_r12_rainfall_domain': country & r12}, lat, lon
    with xr.open_dataset(cycle.root('season_domain_mask')) as d:
        if not (np.array_equal(d.lat.values, lat) and np.array_equal(d.lon.values, lon)):
            raise ValueError('Season domain grid differs from the regime mask')
        domain = country & (d.season_domain.values == 1)
    out = {'all_ethiopia': country, f'{cycle.season_name.lower()}_rainfall_domain': domain}
    for view, path in cycle.extra_domains():         # extra presentation views (cycle "extra_domain_masks")
        with xr.open_dataset(path) as d:
            if not (np.array_equal(d.lat.values, lat) and np.array_equal(d.lon.values, lon)):
                raise ValueError(f'{path}: grid differs from the regime mask')
            out[view] = country & (d.season_domain.values == 1)
    return out, lat, lon


def diagnose(path, masks):
    with xr.open_dataset(path) as d:
        d = d.load()
    lat, lon = d.lat.values.astype(float), d.lon.values.astype(float)
    area = cell_area(lat, lon).reshape(len(lat), len(lon))
    years = [int(y) for y in d.year.values]
    y = d.observed_category.values.astype(int)
    pb, pc = d.shared_blend_probability.values, d.climatology_probability.values
    valid = (y >= 0) & np.isfinite(pb).all(-1) & np.isfinite(pc).all(-1)
    rb, rc = np.where(valid, rps(pb, y), np.nan), np.where(valid, rps(pc, y), np.nan)
    onehot = np.eye(3)[np.maximum(y, 0)]
    out = {}
    for name, mask in masks.items():
        per_year, keep_all = [], []
        for i, yr in enumerate(years):
            keep = valid[i] & mask
            if not keep.any():
                per_year.append(dict(year=yr, cells=0))
                continue
            w = area[keep] / area[keep].sum()
            b, c = float(w @ rb[i][keep]), float(w @ rc[i][keep])
            per_year.append(dict(year=yr, cells=int(keep.sum()), rps_blend=b, rps_climatology=c, rpss=1 - b / c if c > 0 else None,
                                 coverage=float(area[keep].sum() / area[mask].sum())))
            keep_all.append(i)
        sel = valid & mask[None]
        # Area weights per cell-year, each year weighted equally (as in the skill scores).
        wy = np.zeros(sel.shape)
        for i in range(len(years)):
            s = area * sel[i]
            if s.sum() > 0:
                wy[i] = s / s.sum()
        wv, P, O, C = wy[sel], pb[sel], onehot[sel], pc[sel]
        reliability = []
        for k in range(3):
            rows = []
            idx = np.clip(np.digitize(P[:, k], BINS) - 1, 0, 9)
            for j in range(10):
                m = idx == j
                if m.sum() == 0:
                    continue
                rows.append(dict(bin=[float(BINS[j]), float(BINS[j + 1])], forecast=float(np.average(P[m, k], weights=wv[m])),
                                 observed=float(np.average(O[m, k], weights=wv[m])), count=int(m.sum())))
            reliability.append(rows)
        lead = P.max(-1)
        hist = [dict(label=lab, share=float(wv[(lead >= a) & (lead < b)].sum() / wv.sum()), count=int(((lead >= a) & (lead < b)).sum()))
                for a, b, lab in LEAD]
        bs_b = [float(np.average((P[:, k] - O[:, k]) ** 2, weights=wv)) for k in range(3)]
        bs_c = [float(np.average((C[:, k] - O[:, k]) ** 2, weights=wv)) for k in range(3)]
        out[name] = dict(per_year=per_year, reliability=reliability, histogram=hist,
                         brier=dict(blend=bs_b, climatology=bs_c, bss=[1 - b / c if c > 0 else None for b, c in zip(bs_b, bs_c)]),
                         cell_years=int(sel.sum()), years=len(keep_all), first=years[0], last=years[-1],
                         coverage=float(np.mean([r['coverage'] for r in per_year if r.get('cells')])) if keep_all else 0.)
    return out


def amount_records(cycle):
    """Cross-validated rainfall-amount scores that the pipeline already produced (May JJAS only)."""
    f = ROOT / 'outputs/verification/init05_JJAS/Ethiopia/verification_summary.json'
    if cycle.tag != 'init05' or not f.is_file():
        return {}
    s = json.loads(f.read_text(encoding='utf-8'))['summary']
    return {'JJAS': {'all_ethiopia': dict(period='2017–2025 (exploratory; parameters fitted on 1993–2016)',
                                          corrected_crps_mm=s['corrected_crps_mm'], climatology_crps_mm=s['climatology_crps_mm'],
                                          crpss=s['corrected_crps_skill'], corrected_bias_mm=s['corrected_bias_mm'],
                                          raw_bias_mm=s['raw_bias_mm'], corrected_rmse_mm=s['corrected_rmse_mm'],
                                          climatology_rmse_mm=s['climatology_rmse_mm'])}}


def main():
    from cycle import load_cycle
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--cycle', required=True)
    a = p.parse_args()
    c = load_cycle(ROOT / a.cycle)
    masks, _, _ = areas(c)
    result = {}
    for t in c.targets:
        result[t] = {}
        for mode in ('training', 'operational'):
            path = ROOT / f'outputs/local_calibration/{c.tag}_{t}/{mode}/local_probabilities_and_weights.nc'
            if path.is_file():
                result[t][mode] = diagnose(path, masks)
        tr = result[t].get('training', {})
        print(t, '  '.join(f"{k}: {sum(1 for r in v['per_year'] if (r.get('rpss') or 0) > 0)}/{v['years']} years better, "
                           f"BSS below/near/above {', '.join(f'{x:+.3f}' for x in v['brier']['bss'])}" for k, v in tr.items()))
    out = ROOT / f'outputs/historical_diagnostics/{c.tag}_diagnostics.json'
    save_json(out, dict(created_utc=datetime.now(timezone.utc).isoformat(), protocol=__doc__.strip(), cycle=str(a.cycle),
                        season=c.season_name, areas=list(masks), targets=result, amount=amount_records(c)))
    print('Saved:', out)


if __name__ == '__main__':
    main()
