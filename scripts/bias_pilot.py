"""Shadow pilot: alternative amount corrections through the operational probability pipeline for one forecast year (docs/47).

Not an operational product and never shown as one. For the configured cycle and targets, every pilot method is fitted the
way the operational forecast is (all reference years; one blend weight per target from leave-one-year-out within them) and
produces the forecast-year probabilities. The reference method's probabilities are checked against the published forecast,
which validates the pipeline. When the target period has been observed, every method is scored against CHIRPS: one season,
an illustration of what the change would have meant, not evidence (the evidence is the benchmark's confirmation).

Configured by config/bias_correction/<name>_pilot.json: {"benchmark_config": ..., "methods": [...], "targets": [...],
"output_root": ...}; the cycle, years, regions and method parameters come from the benchmark configuration.
"""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def parse():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--config', default='config/bias_correction/feb_fmam_pilot.json')
    return p.parse_args()


ARGS = parse() if __name__ == '__main__' else None
ROOT_DIR = Path(__file__).resolve().parents[1]
if ARGS is not None:
    _pilot = json.loads((ROOT_DIR / ARGS.config).read_text(encoding='utf-8'))
    os.environ.setdefault('CALIBRATION_CYCLE', json.loads((ROOT_DIR / _pilot['benchmark_config']).read_text(encoding='utf-8'))['cycle'])

import xarray as xr                                                     # noqa: E402
import matplotlib                                                       # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt                                         # noqa: E402
from matplotlib.colors import ListedColormap, TwoSlopeNorm              # noqa: E402
from common import ROOT, load_config, save_json                         # noqa: E402
from local_blend import fit_weights                                     # noqa: E402
from run_calibration import cell_area                                   # noqa: E402
from bias_methods import resolve                                        # noqa: E402
import bias_benchmark as bb                                             # noqa: E402
from bias_confirmation import Pipeline, blend, prob_scores              # noqa: E402

CATEGORY_COLOURS = ['#a6611a', '#bdbdbd', '#1a9641']                    # below, near, above normal


def cell_rps(p, y):
    ok = (y >= 0) & np.isfinite(p).all(-1)
    t = np.eye(3)[np.maximum(y, 0)]
    r = np.sum((np.cumsum(p, -1)[:, :2] - np.cumsum(t, -1)[:, :2]) ** 2, -1)
    return np.where(ok, r, np.nan)


def favoured(p, minimum=0.4):
    """Favoured category where its probability reaches the site's display threshold, else -1."""
    ok = np.isfinite(p).all(-1)
    k = np.argmax(np.where(ok[:, None], p, 0), -1)
    return np.where(ok & (np.max(np.where(ok[:, None], p, 0), -1) >= minimum), k, -1)


def observation(cycle, target, year, lat, lon):
    path = ROOT / cycle['verification_root'] / 'observations' / target / f'chirps_{year}_common.nc'
    if not path.is_file():
        return None, None
    with xr.open_dataset(path) as d:
        a = d.precip_season.transpose('lat', 'lon')
        if not np.array_equal(a.lat, lat) or not np.array_equal(a.lon, lon):
            raise ValueError(f'Observation grid mismatch: {path}')
        return a.values.reshape(-1).astype(float), str(path.relative_to(ROOT)).replace('\\', '/')


def published(cycle, tag, year):
    folder = ROOT / cycle['forecast_root'] / tag / str(year)
    if not (folder / f'forecast_{year}.nc').is_file():
        return None, None
    with xr.open_dataset(folder / f'forecast_{year}.nc') as d:
        p = d.blend_probability.transpose('lat', 'lon', 'category').values.reshape(-1, 3)
    lam = json.loads((folder / 'blend_parameters.json').read_text(encoding='utf-8')) if (folder / 'blend_parameters.json').is_file() else {}
    return p, lam


def main(args):
    pilot = json.loads((ROOT / args.config).read_text(encoding='utf-8'))
    cfg = json.loads((ROOT / pilot['benchmark_config']).read_text(encoding='utf-8'))
    cycle = json.loads((ROOT / cfg['cycle']).read_text(encoding='utf-8'))
    project = load_config(cfg['project_config'])
    ref = cfg['reference_method']
    methods = pilot['methods'] if ref in pilot['methods'] else [ref] + pilot['methods']
    year = cycle['forecast_year']
    train = list(range(cycle['reference_years'][0], cycle['reference_years'][1] + 1))
    out_root = ROOT / pilot['output_root']
    results = {}
    for target in pilot['targets']:
        tag, models, obs, lat, lon = bb.load_target(cfg, project, target)
        area = cell_area(lat, lon)
        regions = {k: bb.load_mask(v, lat, lon) for k, v in cfg['regions'].items()}
        observed, obs_path = observation(cycle, target, year, lat, lon)
        scored = observed is not None
        obs = {**obs, year: observed if scored else np.full(len(area), np.nan)}   # labels and scores only; never fitted
        pub_p, pub_lam = published(cycle, tag, year)
        row = dict(tag=tag, observation=obs_path, methods={})
        maps = {}
        for method in methods:
            pipe = Pipeline(method, cfg['methods'].get(method, {}), models, obs, train, cfg['smoothing_alpha'],
                            regions if scored else {}, area)
            oof = [pipe.fit_apply(frozenset((z,)), [z])[0] for z in train]
            lam = fit_weights(oof, area)['shared_lambda']
            rec = pipe.fit_apply(frozenset(), [year])[0]
            p = blend(rec, lam)
            entry = dict(label=resolve(method, cfg['methods'].get(method))[0].label, blend_weight=lam)
            if method == ref and pub_p is not None:          # the pipeline must reproduce the published forecast
                both = np.isfinite(p).all(-1) & np.isfinite(pub_p).all(-1)
                entry['published_check'] = dict(max_abs_difference=float(np.abs(p[both] - pub_p[both]).max()), cells=int(both.sum()),
                                                published_blend_weight=pub_lam.get('climatology_weight'),
                                                blend_weight_difference=abs(lam - pub_lam['climatology_weight']) if 'climatology_weight' in pub_lam else None)
            if scored:
                entry['scores'] = {}
                for name, mask in regions.items():
                    s, _ = prob_scores(p, rec, area, mask, 10)
                    a = rec['amount'][name]
                    fav = favoured(p)
                    valid = mask & (fav >= 0) & (rec['y'] >= 0)
                    hit = float(area[valid & (fav == rec['y'])].sum() / area[valid].sum()) if valid.any() else None
                    entry['scores'][name] = dict(rps=s['rps'], rpss=1 - s['rps'] / s['rps_clim'],
                                                 bss_below=1 - s['brier_below'] / s['brier_below_clim'],
                                                 bss_above=1 - s['brier_above'] / s['brier_above_clim'],
                                                 crps_mm=a['crps'], crpss=1 - a['crps'] / a['crps_clim'],
                                                 favoured_area_share=float(area[mask & (fav >= 0)].sum() / area[mask].sum()),
                                                 favoured_hit_share=hit)
            maps[method] = dict(p=p, y=rec['y'])
            row['methods'][method] = entry
            print(f'{target} {method:9s} lambda {lam:.2f}' + (f"  check {entry['published_check']['max_abs_difference']:.2e}" if 'published_check' in entry else '')
                  + (f"  RPSS {entry['scores'][cfg['primary_region']]['rpss']:+.3f}" if scored else ''), flush=True)
        results[target] = row
        figure(out_root / f'pilot_{year}_{target}.png', maps, methods, ref, lat, lon, regions[cfg['primary_region']], target, year,
               scored, {m: row['methods'][m] for m in methods}, cfg)
    save_json(out_root / f'pilot_{year}.json', dict(
        created_utc=datetime.now(timezone.utc).isoformat(), config=args.config, protocol=__doc__.strip(), forecast_year=year,
        reference_years=cycle['reference_years'], reference_method=ref, methods=methods,
        provenance=bb.provenance(cfg, project, pilot['targets'], pilot['benchmark_config'],
                                 extra=[args.config, 'scripts/bias_pilot.py']),
        targets=results))
    print('Saved:', out_root)


def figure(path, maps, methods, ref, lat, lon, country, target, year, scored, entries, cfg):
    shape = (len(lat), len(lon))
    edges = lambda c: np.r_[c[0] - (c[1] - c[0]) / 2, (c[:-1] + c[1:]) / 2, c[-1] + (c[-1] - c[-2]) / 2]
    panels = [(m, 'favoured') for m in methods] + ([('_obs', 'observed'), ('_diff', 'rps')] if scored else [])
    fig, axes = plt.subplots(1, len(panels), figsize=(4.2 * len(panels), 4.6), squeeze=False)
    cmap = ListedColormap(CATEGORY_COLOURS)
    for ax, (m, kind) in zip(axes[0], panels):
        if kind == 'favoured':
            fav = favoured(maps[m]['p']).astype(float)
            fav[(fav < 0) | ~country] = np.nan
            ax.pcolormesh(edges(lon), edges(lat), fav.reshape(shape), cmap=cmap, vmin=-.5, vmax=2.5)
            e = entries[m]
            title = f"{e['label'].replace(' (operational)', '')}\nfavoured category (≥ 40%), λ {e['blend_weight']:.2f}"
            if scored:
                title += f"\nRPSS {e['scores'][cfg['primary_region']]['rpss']:+.3f}"
        elif kind == 'observed':
            y = maps[ref]['y'].astype(float)
            y[(y < 0) | ~country] = np.nan
            ax.pcolormesh(edges(lon), edges(lat), y.reshape(shape), cmap=cmap, vmin=-.5, vmax=2.5)
            title = f'Observed category, {target} {year}\n(CHIRPS against the reference terciles)'
        else:
            other = [x for x in methods if x != ref][0]
            d = cell_rps(maps[other]['p'], maps[other]['y']) - cell_rps(maps[ref]['p'], maps[ref]['y'])
            d[~country] = np.nan
            im = ax.pcolormesh(edges(lon), edges(lat), d.reshape(shape), cmap='RdBu_r', norm=TwoSlopeNorm(0, -.2, .2))
            fig.colorbar(im, ax=ax, shrink=.75, label='RPS difference (blue: alternative better)')
            title = f"RPS: {entries[other]['label'].replace(' (operational)', '')}\nminus {entries[ref]['label'].replace(' (operational)', '')}"
        ax.contour(lon, lat, country.reshape(shape).astype(float), levels=[.5], colors='#333', linewidths=.6)
        ax.set_title(title, fontsize=9)
        ax.set_aspect('equal')
        ax.set_xticks([])
        ax.set_yticks([])
    fig.suptitle(f'Shadow pilot, {target} {year}: published method against an alternative amount correction through the same '
                 f'probability pipeline (brown below, grey near, green above normal). One season: an illustration, not evidence.',
                 fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, .9))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


if __name__ == '__main__':
    main(ARGS)
