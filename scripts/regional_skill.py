"""Regional skill tables from stored out-of-fold probabilities (item 9).

Read-only: uses outputs/local_calibration/init05_<target>/{training,operational}/
local_probabilities_and_weights.nc (no refitting) and the rainfall-regime mask in
evidence/followup_regime_comparison_and_masks.nc (github_regime_cleaned).

Per target, mode and region: RPS of the shared blend, smoothed counts and
climatology; RPSS of the blend with a whole-year bootstrap interval and the
one-sided sign-flip p-value for "blend better than climatology". Per-cell blend
RPSS fields are saved for mapping.

With --cycle (any season), the same scores are computed for that cycle's
targets, the regimes R0-R3 and the cycle's own rainfall domain (region
"season_domain", from season_domain_mask; JJAS uses R1+R2), written to
outputs/regional_skill/<tag>_regional_skill.json:

    python scripts/regional_skill.py --cycle config/cycles/sep_2026_ondj.json
"""
import argparse
import warnings
from datetime import datetime, timezone
import numpy as np
import xarray as xr
from common import ROOT, save_json, save_netcdf
from final_shared_blend import TARGETS
from run_calibration import cell_area
from significance import paired_summary

REGIONS = {'ethiopia': None, 'R0_arid_marginal': 0, 'R1_western_unimodal': 1,
           'R2_belg_kiremt': 2, 'R3_gu_deyr': 3, 'R1_R2_jjas_domain': 'r12'}
METHODS = ['shared_blend', 'smooth', 'climatology']


def rps(p, y):
    t = np.eye(3)[np.maximum(y, 0)]
    return np.sum((np.cumsum(p, -1)[..., :2] - np.cumsum(t, -1)[..., :2]) ** 2, -1)


def region_masks(path, domain_path=None):
    with xr.open_dataset(path) as m:
        country = m.region_mask.values == 1
        regime = m.github_regime_cleaned.values
        r12 = m.github_jjas_r12_rainfall_cleaned.values == 1
        lat, lon = m.lat.values, m.lon.values
    out = {}
    for name, code in REGIONS.items():
        out[name] = country if code is None else (country & r12 if code == 'r12' else country & (regime == code))
    if domain_path is not None:                     # the cycle's own rainfall domain
        with xr.open_dataset(domain_path) as d:
            if not (np.array_equal(d.lat.values, lat) and np.array_equal(d.lon.values, lon)):
                raise ValueError(f'{domain_path}: grid differs from the regime mask')
            out['season_domain'] = country & (d.season_domain.values == 1)
            label = d.attrs.get('view_label', 'season rainfall domain')
        del out['R1_R2_jjas_domain']
        return out, label
    return out


def score_mode(path, masks):
    with xr.open_dataset(path) as d:
        d = d.load()
    lat, lon = d.lat.values.astype(float), d.lon.values.astype(float)
    area = cell_area(lat, lon).reshape(len(lat), len(lon))
    y = d.observed_category.values.astype(int)
    probs = {m: d[f'{m}_probability'].values for m in METHODS}
    valid = (y >= 0)
    for p in probs.values():
        valid &= np.isfinite(p).all(-1)
    cell = {m: np.where(valid, rps(probs[m], y), np.nan) for m in METHODS}
    table = {}
    for name, mask in masks.items():
        per_year = {m: [] for m in METHODS}
        coverage = []
        for i in range(len(d.year)):
            keep = valid[i] & mask
            coverage.append(float(area[keep].sum() / area[mask].sum()) if mask.any() else 0.)
            if not keep.any():
                break
            w = area[keep] / area[keep].sum()
            for m in METHODS:
                per_year[m].append(float(w @ cell[m][i][keep]))
        if len(per_year['climatology']) < len(d.year):
            table[name] = dict(status='insufficient probability coverage')
            continue
        mean = {m: float(np.mean(v)) for m, v in per_year.items()}
        boot = paired_summary(per_year['shared_blend'], per_year['climatology'])
        clim = mean['climatology']
        table[name] = dict(
            rps=mean, rpss_blend=1 - mean['shared_blend'] / clim, rpss_smooth=1 - mean['smooth'] / clim,
            rpss_blend_95=[-b / clim for b in boot['bootstrap_95'][::-1]],
            p_blend_better_than_climatology=boot['p_improvement'],
            years_blend_better=boot['years_better'], years=boot['years'],
            probability_coverage=float(np.mean(coverage)))
    with warnings.catch_warnings(), np.errstate(invalid='ignore', divide='ignore'):
        warnings.simplefilter('ignore', RuntimeWarning)  # cells never valid stay NaN
        field = 1 - np.nanmean(cell['shared_blend'], 0) / np.nanmean(cell['climatology'], 0)
    return table, field, lat, lon


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--targets', nargs='+', help='Default: all targets (of the cycle)')
    p.add_argument('--regime-mask', default='evidence/followup_regime_comparison_and_masks.nc')
    p.add_argument('--cycle', help='Cycle file: score its targets and its own rainfall domain')
    args = p.parse_args()
    if args.cycle:
        return cycle_main(args)
    targets = args.targets or TARGETS
    if not set(targets) <= set(TARGETS):
        p.error('targets must be among ' + ', '.join(TARGETS))
    masks = region_masks(ROOT / args.regime_mask)
    results, fields = {}, {}
    for t in targets:
        results[t] = {}
        for mode in ('training', 'operational'):
            path = ROOT / f'outputs/local_calibration/init05_{t}/{mode}/local_probabilities_and_weights.nc'
            table, field, lat, lon = score_mode(path, masks)
            results[t][mode] = table
            fields[f'{t}_{mode}_blend_rpss'] = (('lat', 'lon'), field)
        print(f'\n{t}  (RPSS blend vs climatology: training nested 1993-2016 | operational 2017-2025)')
        for name in REGIONS:
            tr, op = results[t]['training'][name], results[t]['operational'][name]
            if 'rpss_blend' not in tr or 'rpss_blend' not in op:
                print(f'  {name:22s} insufficient coverage')
                continue
            print(f"  {name:22s} {tr['rpss_blend']:+.3f} (p={tr['p_blend_better_than_climatology']:.2f}) | "
                  f"{op['rpss_blend']:+.3f} (p={op['p_blend_better_than_climatology']:.2f}, {op['years_blend_better']}/9) "
                  f"coverage {op['probability_coverage']:.0%}")
    out = ROOT / 'outputs/regional_skill'
    save_json(out / 'regional_skill.json', dict(created_utc=datetime.now(timezone.utc).isoformat(),
                                                protocol=__doc__.strip(), regions=list(REGIONS), targets=results))
    ds = xr.Dataset(fields, coords=dict(lat=lat, lon=lon),
                    attrs=dict(note='Per-cell RPSS of the shared blend vs climatology; descriptive, single-cell values are noisy.'))
    save_netcdf(ds, out / 'regional_skill_fields.nc')
    print('\nSaved:', out)


def cycle_main(args):
    from cycle import load_cycle
    c = load_cycle(ROOT / args.cycle)
    season = c.season_name
    if season == 'JJAS':
        masks, label = region_masks(ROOT / args.regime_mask), 'JJAS R1+R2 rainfall domain'
        masks['season_domain'] = masks.pop('R1_R2_jjas_domain')
    else:
        masks, label = region_masks(ROOT / args.regime_mask, c.root('season_domain_mask'))
    targets = args.targets or list(c.targets)
    results = {}
    for t in targets:
        results[t] = {}
        for mode in ('training', 'operational'):
            path = ROOT / f'outputs/local_calibration/{c.tag}_{t}/{mode}/local_probabilities_and_weights.nc'
            results[t][mode] = score_mode(path, masks)[0]
        tr, op = results[t]['training'].get('season_domain', {}), results[t]['operational'].get('season_domain', {})
        if 'rpss_blend' in tr and 'rpss_blend' in op:
            print(f"{t:5s} {label}: {tr['rpss_blend']:+.3f} [{tr['rpss_blend_95'][0]:+.3f}, {tr['rpss_blend_95'][1]:+.3f}] "
                  f"{tr['years_blend_better']}/{tr['years']} | exploratory {op['rpss_blend']:+.3f} "
                  f"({op['years_blend_better']}/{op['years']}), coverage {tr['probability_coverage']:.0%}")
        else:
            print(f'{t:5s} {label}: insufficient coverage')
    out = ROOT / f'outputs/regional_skill/{c.tag}_regional_skill.json'
    save_json(out, dict(created_utc=datetime.now(timezone.utc).isoformat(), protocol=__doc__.strip(), cycle=str(args.cycle),
                        season=season, domain_label=label, regions=list(masks), targets=results))
    print('Saved:', out)


if __name__ == '__main__':
    main()
