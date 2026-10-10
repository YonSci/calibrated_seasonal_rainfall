r"""Compare the CHIRPS v2.0 calibration (this tree) with the CHIRPS v3 track (branch chirps-v3 worktree).

Both trees ran the same scripts and settings; only the observations differ. Each side is scored against its own
observations, so skill numbers say how well the method works with that dataset, not which dataset is right.

Per cycle and target: blend weight (lambda = climatology weight); probability skill (RPSS against climatology) of
the shared blend, cross-validated 1993-2016 and exploratory 2017 onwards, with whole-year 95% intervals; rainfall
amount skill (CRPSS) of the development run; and for the season target the national mean of the 2026 forecast
probabilities. Plus the JJAS decision-gate outcomes. Nothing in either tree is modified.

    python scripts\compare_v3_calibration.py --v3-root ..\calibrated_seasonal_rainfall_v3
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
CYCLES = {'jjas': ('init05', ['Jun', 'Jul', 'Aug', 'Sep', 'JJAS'], 'JJAS'),
          'fmam_jan': ('init01', ['Feb', 'Mar', 'Apr', 'May', 'FMAM'], 'FMAM'),
          'fmam_feb': ('init02', ['Feb', 'Mar', 'Apr', 'May', 'FMAM'], 'FMAM'),
          'ondj': ('init09', ['Oct', 'Nov', 'Dec', 'Jan', 'ONDJ'], 'ONDJ')}
OUT = ROOT / 'outputs/chirps_v3_comparison'


def year_skill(path, draws=5000, seed=20261005):
    """RPSS of the shared blend against climatology with a whole-year bootstrap interval (as on the site)."""
    if not path.is_file():
        return None
    r = json.loads(path.read_text(encoding='utf-8'))
    b = np.array([y['metrics']['shared_blend']['rps'] for y in r['years']])
    c = np.array([y['metrics']['climatology']['rps'] for y in r['years']])
    idx = np.random.default_rng(seed).integers(0, len(b), (draws, len(b)))
    boot = 1 - b[idx].sum(1) / c[idx].sum(1)
    return dict(rpss=float(1 - b.sum() / c.sum()), ci=[float(np.quantile(boot, .025)), float(np.quantile(boot, .975))],
                years_better=int((b < c).sum()), years=len(b), first=int(r['years'][0]['year']), last=int(r['years'][-1]['year']))


def blend_weight(root, tag, target):
    f = root / f'outputs/final_shared_blend/{tag}_{target}/2026/final_report.json'
    return json.loads(f.read_text(encoding='utf-8')).get('climatology_weight') if f.is_file() else None


def amount_skill(root, tag, season):
    f = root / f'outputs/verification/{tag}_{season}/Ethiopia/verification_summary.json'
    if not f.is_file():
        return None
    d = json.loads(f.read_text(encoding='utf-8'))
    s = d['summary']
    return dict(crpss=s['corrected_crps_skill'], corrected_bias_mm=s['corrected_bias_mm'], raw_bias_mm=s['raw_bias_mm'],
                years=[d['evaluation_years'][0], d['evaluation_years'][-1]])


def forecast_2026(root, tag, target, mask):
    f = root / f'outputs/final_shared_blend/{tag}_{target}/2026/forecast_2026.nc'
    if not f.is_file():
        return None
    with xr.open_dataset(f) as d:
        p = d.blend_probability.transpose('lat', 'lon', 'category').values
        cats = [str(c) for c in d.category.values]
        ok = (d.probability_eligible.values == 1) & mask & np.isfinite(p).all(-1)
        w = np.cos(np.deg2rad(d.lat.values))[:, None] * np.ones((1, d.sizes['lon']))
        anom = d.corrected_mean_anomaly.values
    mean = {c: float(np.average(p[..., k][ok], weights=w[ok])) for k, c in enumerate(cats)}
    return dict(mean_probability=mean, mean_anomaly_mm=float(np.average(anom[ok], weights=w[ok])), cells=int(ok.sum()))


def gates(root):
    f = root / 'outputs/decision_gates/decision_gates.json'
    if not f.is_file():
        return None
    g = json.loads(f.read_text(encoding='utf-8'))['gates']
    return {fam: {t: dict(adopt=v['decision']['adopt'], holm_p=v['decision'].get('holm_p'),
                          training_mean_difference=v['training']['mean_difference'])
                  for t, v in tgts.items()} for fam, tgts in g.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--v3-root', default=str(ROOT.parent / 'calibrated_seasonal_rainfall_v3'))
    a = ap.parse_args()
    roots = {'v2': ROOT, 'v3': Path(a.v3_root).resolve()}
    with xr.open_dataset(ROOT / 'data/masks/ethiopia_common.nc') as m:
        country = m.region_mask.values == 1
    res = dict(created_utc=datetime.now(timezone.utc).isoformat(timespec='seconds'), roots={k: str(v) for k, v in roots.items()},
               note='Each side is scored against its own CHIRPS version; skill compares how the method works with each dataset.',
               cycles={}, decision_gates={k: gates(v) for k, v in roots.items()})
    for name, (tag, targets, season) in CYCLES.items():
        rows = {}
        for t in targets:
            rows[t] = {}
            for side, root in roots.items():
                lc = root / f'outputs/local_calibration/{tag}_{t}'
                rows[t][side] = dict(blend_weight=blend_weight(root, tag, t),
                                     cross_validated=year_skill(lc / 'training/local_comparison_summary.json'),
                                     exploratory=year_skill(lc / 'operational/local_comparison_summary.json'))
                if t == season:
                    rows[t][side].update(amount=amount_skill(root, tag, season), forecast_2026=forecast_2026(root, tag, t, country))
        res['cycles'][name] = dict(tag=tag, targets=rows)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'calibration_comparison.json').write_text(json.dumps(res, indent=1), encoding='utf-8')
    f = lambda x: '—' if x is None else f'{x:+.3f}'
    for name, c in res['cycles'].items():
        print(f'== {name} ({c["tag"]})')
        for t, r in c['targets'].items():
            line = []
            for side in ('v2', 'v3'):
                x = r[side]
                cv, op = x['cross_validated'] or {}, x['exploratory'] or {}
                line.append(f'{side}: lambda {x["blend_weight"] if x["blend_weight"] is None else round(x["blend_weight"], 2)} '
                            f'CV {f(cv.get("rpss"))} [{f((cv.get("ci") or [None])[0])},{f((cv.get("ci") or [None, None])[1])}] '
                            f'expl {f(op.get("rpss"))}' + (f' CRPSS {f((x.get("amount") or {}).get("crpss"))}' if 'amount' in x else ''))
            print(f'  {t:5s} ' + ' | '.join(line))
    print('Saved', OUT / 'calibration_comparison.json')


if __name__ == '__main__':
    main()
