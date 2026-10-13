"""Shadow forecasts and independent validation of the bias-correction methods (docs/47).

Never a published forecast. For one operational cycle file (one forecast year), benchmark methods are run through the
operational probability pipeline exactly as the published forecast is (fitted on the cycle's reference years; one blend
weight per target from leave-one-year-out within them):

  * the reference method must reproduce the published forecast (probabilities and blend weight), which validates the run;
  * the shadow method(s) declared in config/bias_correction/validation.json produce the forecast-year probabilities
    (NetCDF and maps) next to the published ones — the ongoing shadow forecast;
  * once CHIRPS has been prepared for a target (the cycle's verification observations), every run method is scored. These
    seasons were not used to build or select anything, so they are the independent validation record that
    bias_recommend.py reads, one season at a time.

Results: <benchmark output>/validation/<year>/<method>__<target>.json (reused while its dependency fingerprint —
code, configurations, masks, model and observation inputs — is unchanged), shadow_<method>_<year>.nc and
shadow_<method>_<year>_<target>.png.

  python scripts/bias_validation.py --cycle config/cycles/feb_2026_fmam.json --methods shadow
  python scripts/bias_validation.py --cycle config/cycles/feb_2026_fmam.json --methods all
"""
import argparse
import hashlib
import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def parse():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--cycle', default='config/operational.json', help='operational cycle file (one forecast year)')
    p.add_argument('--validation-config', default='config/bias_correction/validation.json')
    p.add_argument('--methods', nargs='+', default=['shadow'],
                   help="'shadow' (reference + declared shadow methods), 'all' (every benchmark method) or method keys")
    p.add_argument('--workers', type=int, default=2)
    p.add_argument('--no-resume', action='store_true')
    return p.parse_args()


ARGS = parse() if __name__ == '__main__' else None
ROOT_DIR = Path(__file__).resolve().parents[1]
if ARGS is not None:
    os.environ.setdefault('CALIBRATION_CYCLE', str((ROOT_DIR / ARGS.cycle).resolve()))

import xarray as xr                                                     # noqa: E402
from common import ROOT, load_config, save_json, save_netcdf            # noqa: E402

CATEGORY_COLOURS = ['#a6611a', '#bdbdbd', '#1a9641']                    # below, near, above normal
CODE = ['scripts/bias_validation.py', 'scripts/bias_methods.py', 'scripts/bias_confirmation.py', 'scripts/bias_benchmark.py',
        'scripts/calibration_core.py', 'scripts/compare_calibration.py', 'scripts/local_blend.py', 'scripts/run_calibration.py',
        'scripts/run_monthly.py', 'scripts/cycle.py', 'scripts/common.py']


# ---------------------------------------------------------------- configuration

def read(p):
    return json.loads((ROOT / p).read_text(encoding='utf-8'))


def match(validation, cycle_path):
    """The validation entry of a cycle file: matched by initialization month and season, so future years are covered."""
    cycle = read(cycle_path)
    project = read(cycle['project_config'])
    for entry in validation['cycles']:
        if entry['initialization_month'] == project['initialization_month'] and entry['season'] == project['season']['name']:
            return cycle, project, entry
    return cycle, project, None


def methods_for(request, bench, entry):
    ref = bench['reference_method']
    shadow = [s['method'] for s in entry.get('shadow', [])]
    if request == ['shadow']:
        keys = [ref] + shadow
    elif request == ['all']:
        conf = bench['confirmation']
        keys = [ref] + conf['methods'] + conf.get('variants', []) + shadow
    else:
        keys = [ref] + request
    return list(dict.fromkeys(keys))


def targets_for(method, request, cycle, entry):
    """Shadow-only runs cover the shadow targets; full validation covers every target of the cycle."""
    if request == ['shadow']:
        wanted = sorted({t for s in entry.get('shadow', []) for t in s['targets']}, key=cycle['targets'].index)
        return wanted
    return list(cycle['targets'])


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def observation_path(cycle, target, year):
    return ROOT / cycle['verification_root'] / 'observations' / target / f'chirps_{year}_common.nc'


def fingerprint(cycle_path, bench_path, cycle, project, bench, method, targets):
    """Everything a method's validation file depends on: code, configurations, masks, model and observation inputs."""
    from bias_benchmark import target_config
    year, ref = cycle['forecast_year'], list(range(cycle['reference_years'][0], cycle['reference_years'][1] + 1))
    files = [*CODE, cycle_path, bench_path, cycle['project_config'], *[v['path'] for v in bench['regions'].values()]]
    h = hashlib.sha256(json.dumps(dict(method=method, targets=targets, params=bench['methods'].get(method)), sort_keys=True).encode())
    for f in files:
        h.update(f.encode() + sha256(ROOT / f).encode())
    for t in targets:
        tc = target_config(project, t)
        folder = ROOT / cycle.get('processed_root', 'data/processed') / f"init{tc['initialization_month']:02d}_{tc['season']['name']}"
        for f in [folder / f'ecmwf_{y}_common.nc' for y in ref + [year]] + [folder / f'chirps_{y}_common.nc' for y in ref]:
            h.update(f.name.encode() + sha256(f).encode())
        o = observation_path(cycle, t, year)
        h.update((sha256(o) if o.is_file() else 'not observed').encode())
    return h.hexdigest()


# ---------------------------------------------------------------- one method (worker process)

def favoured(p, minimum=0.4):
    ok = np.isfinite(p).all(-1)
    k = np.argmax(np.where(ok[:, None], p, 0), -1)
    return np.where(ok & (np.max(np.where(ok[:, None], p, 0), -1) >= minimum), k, -1)


def cell_rps(p, y):
    ok = (y >= 0) & np.isfinite(p).all(-1)
    t = np.eye(3)[np.maximum(y, 0)]
    r = np.sum((np.cumsum(p, -1)[:, :2] - np.cumsum(t, -1)[:, :2]) ** 2, -1)
    return np.where(ok, r, np.nan)


def run_method(cycle_path, bench_path, method, targets):
    from bias_benchmark import load_mask, target_config
    from bias_confirmation import Pipeline, blend, prob_scores
    from bias_methods import resolve
    from local_blend import fit_weights
    from run_calibration import load_inputs, cell_area
    cycle, bench = read(cycle_path), read(bench_path)
    project = load_config(cycle['project_config'])
    year = cycle['forecast_year']
    train = list(range(cycle['reference_years'][0], cycle['reference_years'][1] + 1))
    out = dict(method=method, label=resolve(method, bench['methods'].get(method))[0].label, targets={})
    arrays = {}
    for t in targets:
        tag, models, obs, _, lat, lon = load_inputs(target_config(project, t), train + [year], train)
        area = cell_area(lat, lon)
        regions = {k: load_mask(v, lat, lon) for k, v in bench['regions'].items()}
        o = observation_path(cycle, t, year)
        observed = None
        if o.is_file():
            with xr.open_dataset(o) as d:
                a = d.precip_season.transpose('lat', 'lon')
                if not np.array_equal(a.lat, lat) or not np.array_equal(a.lon, lon):
                    raise ValueError(f'Observation grid mismatch: {o}')
                observed = a.values.reshape(-1).astype(float)
        obs = {**obs, year: observed if observed is not None else np.full(len(area), np.nan)}   # labels and scores only
        pipe = Pipeline(method, bench['methods'].get(method, {}), models, obs, train, bench['smoothing_alpha'],
                        regions if observed is not None else {}, area)
        oof = [pipe.fit_apply(frozenset((z,)), [z])[0] for z in train]
        lam = fit_weights(oof, area)['shared_lambda']
        rec = pipe.fit_apply(frozenset(), [year])[0]
        p = blend(rec, lam)
        row = dict(tag=tag, blend_weight=lam, observed=observed is not None,
                   observation=str(o.relative_to(ROOT)).replace('\\', '/') if observed is not None else None)
        if method == bench['reference_method']:              # the run must reproduce the published forecast
            pub = ROOT / cycle['forecast_root'] / tag / str(year)
            if (pub / f'forecast_{year}.nc').is_file():
                with xr.open_dataset(pub / f'forecast_{year}.nc') as d:
                    pp = d.blend_probability.transpose('lat', 'lon', 'category').values.reshape(-1, 3)
                both = np.isfinite(p).all(-1) & np.isfinite(pp).all(-1)
                bp = json.loads((pub / 'blend_parameters.json').read_text(encoding='utf-8')) if (pub / 'blend_parameters.json').is_file() else {}
                row['published_check'] = dict(max_abs_difference=float(np.abs(p[both] - pp[both]).max()), cells=int(both.sum()),
                                              published_blend_weight=bp.get('climatology_weight'),
                                              blend_weight_difference=abs(lam - bp['climatology_weight']) if 'climatology_weight' in bp else None)
        if observed is not None:
            row['scores'] = {}
            for name, mask in regions.items():
                s, _ = prob_scores(p, rec, area, mask, 10)
                am = rec['amount'][name]
                fav = favoured(p)
                valid = mask & (fav >= 0) & (rec['y'] >= 0)
                row['scores'][name] = dict(
                    rps=s['rps'], rps_clim=s['rps_clim'], rpss=1 - s['rps'] / s['rps_clim'],
                    bss_below=1 - s['brier_below'] / s['brier_below_clim'], bss_above=1 - s['brier_above'] / s['brier_above_clim'],
                    crps=am['crps'], crps_clim=am['crps_clim'], crpss=1 - am['crps'] / am['crps_clim'],
                    favoured_hit_share=float(area[valid & (fav == rec['y'])].sum() / area[valid].sum()) if valid.any() else None)
        out['targets'][t] = row
        arrays[t] = dict(p=p.astype('float32'), y=rec['y'], lat=lat, lon=lon, country=regions[bench['primary_region']])
    return method, out, arrays


# ---------------------------------------------------------------- outputs

def save_shadow(folder, method, label, year, arrays, ref_arrays, entries, ref_entries, bench, cycle):
    for t, a in arrays.items():
        lat, lon = a['lat'], a['lon']
        shape = (len(lat), len(lon))
        ds = xr.Dataset(coords=dict(lat=lat, lon=lon, category=['below', 'near', 'above']),
                        attrs=dict(description=f'SHADOW FORECAST, not published: {label}, {t} {year}, through the operational '
                                               f'probability pipeline (cycle {cycle}).', method=method, target=t, year=year,
                                   blend_weight=entries[t]['blend_weight']))
        ds['shadow_probability'] = (('lat', 'lon', 'category'), a['p'].reshape(*shape, 3))
        ds['published_method_probability'] = (('lat', 'lon', 'category'), ref_arrays[t]['p'].reshape(*shape, 3))
        save_netcdf(ds, folder / f'shadow_{method}_{year}_{t}.nc')
        figure(folder / f'shadow_{method}_{year}_{t}.png', a, ref_arrays[t], label, t, year, entries[t], ref_entries[t], bench)


def figure(path, a, r, label, target, year, e, er, bench):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap, TwoSlopeNorm
    lat, lon, country = a['lat'], a['lon'], a['country']
    shape = (len(lat), len(lon))
    edges = lambda c: np.r_[c[0] - (c[1] - c[0]) / 2, (c[:-1] + c[1:]) / 2, c[-1] + (c[-1] - c[-2]) / 2]
    observed = e['observed']
    panels = ['published', 'shadow'] + (['observed', 'difference'] if observed else [])
    fig, axes = plt.subplots(1, len(panels), figsize=(4.2 * len(panels), 4.6), squeeze=False)
    cmap = ListedColormap(CATEGORY_COLOURS)
    prim = bench['primary_region']
    for ax, kind in zip(axes[0], panels):
        if kind in ('published', 'shadow'):
            src, ent = (r, er) if kind == 'published' else (a, e)
            fav = favoured(src['p'].astype(float)).astype(float)
            fav[(fav < 0) | ~country] = np.nan
            ax.pcolormesh(edges(lon), edges(lat), fav.reshape(shape), cmap=cmap, vmin=-.5, vmax=2.5)
            name = 'Published method' if kind == 'published' else f'Shadow: {label}'
            title = f"{name}\nfavoured category (≥ 40%), λ {ent['blend_weight']:.2f}"
            if observed:
                title += f"\nRPSS {ent['scores'][prim]['rpss']:+.3f}"
        elif kind == 'observed':
            y = a['y'].astype(float)
            y[(y < 0) | ~country] = np.nan
            ax.pcolormesh(edges(lon), edges(lat), y.reshape(shape), cmap=cmap, vmin=-.5, vmax=2.5)
            title = f'Observed category, {target} {year}\n(CHIRPS against the reference terciles)'
        else:
            d = cell_rps(a['p'].astype(float), a['y']) - cell_rps(r['p'].astype(float), r['y'])
            d[~country] = np.nan
            im = ax.pcolormesh(edges(lon), edges(lat), d.reshape(shape), cmap='RdBu_r', norm=TwoSlopeNorm(0, -.2, .2))
            fig.colorbar(im, ax=ax, shrink=.75, label='RPS difference (blue: shadow better)')
            title = 'RPS: shadow minus published method'
        ax.contour(lon, lat, country.reshape(shape).astype(float), levels=[.5], colors='#333', linewidths=.6)
        ax.set_title(title, fontsize=9)
        ax.set_aspect('equal')
        ax.set_xticks([])
        ax.set_yticks([])
    fig.suptitle(f'SHADOW FORECAST (not published), {target} {year}: brown below, grey near, green above normal. '
                 + ('Scored against CHIRPS: one season.' if observed else 'Awaiting CHIRPS observations.'), fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, .9))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main(args):
    validation = read(args.validation_config)
    cycle, project, entry = match(validation, args.cycle)
    if entry is None:
        print(f'No bias-correction validation is configured for {args.cycle}.')
        return
    bench = read(entry['benchmark_config'])
    year = cycle['forecast_year']
    folder = ROOT / bench['output_root'] / 'validation' / str(year)
    folder.mkdir(parents=True, exist_ok=True)
    methods = methods_for(args.methods, bench, entry)
    shadow = {s['method']: s for s in entry.get('shadow', [])}
    ref = bench['reference_method']
    # one file per method and target, reused while its dependency fingerprint is unchanged
    need = {}
    for m in methods:
        for t in targets_for(m, args.methods, cycle, entry):
            key = fingerprint(args.cycle, entry['benchmark_config'], cycle, project, bench, m, [t])
            f = folder / f'{m}__{t}.json'
            if args.no_resume or not f.is_file() or json.loads(f.read_text(encoding='utf-8')).get('key') != key:
                need.setdefault(m, {})[t] = key
    for m, s in shadow.items():                              # shadow files need both runs of their targets
        for t in s['targets']:
            if not (folder / f'shadow_{m}_{year}_{t}.nc').is_file() or t in need.get(m, {}):
                for mm in (m, ref):
                    need.setdefault(mm, {})[t] = fingerprint(args.cycle, entry['benchmark_config'], cycle, project, bench, mm, [t])
    if not need:
        print('All validation files are up to date.')
        return
    from bias_benchmark import git
    prov = dict(commit=git('rev-parse', 'HEAD'),
                uncommitted_changes=bool(git('status', '--porcelain', '--', *CODE, args.cycle, entry['benchmark_config'], args.validation_config)))
    results, arrays = {}, {}
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
        jobs = {pool.submit(run_method, args.cycle, entry['benchmark_config'], m, list(ts)): m for m, ts in need.items()}
        for job in as_completed(jobs):
            m, out, arr = job.result()
            for t, row in out['targets'].items():
                save_json(folder / f'{m}__{t}.json', dict(key=need[m][t], method=m, label=out['label'], target=t,
                                                          cycle=Path(args.cycle).as_posix(), forecast_year=year,
                                                          reference_years=cycle['reference_years'], shadow=m in shadow,
                                                          created_utc=datetime.now(timezone.utc).isoformat(), provenance=prov, **row))
            results[m], arrays[m] = out, arr
            line = ' '.join(f"{t}: lambda {r['blend_weight']:.2f}" + (f" RPSS {r['scores'][bench['primary_region']]['rpss']:+.3f}" if r['observed'] else ' (awaiting)')
                            for t, r in out['targets'].items())
            print(f'{m}: {line}', flush=True)
            for t, r in out['targets'].items():
                if 'published_check' in r:
                    print(f"  {t}: reproduces the published forecast to {r['published_check']['max_abs_difference']:.1e}", flush=True)
    for m, s in shadow.items():                              # the shadow forecast files (with the reference run)
        ts = [t for t in s['targets'] if t in arrays.get(m, {}) and t in arrays.get(ref, {})]
        if ts:
            save_shadow(folder, m, results[m]['label'], year, {t: arrays[m][t] for t in ts}, arrays[ref],
                        results[m]['targets'], results[ref]['targets'], bench, args.cycle)
    print('Saved:', folder)


if __name__ == '__main__':
    main(ARGS)
