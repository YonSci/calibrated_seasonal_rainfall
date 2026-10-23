"""Shadow rainfall-amount and range forecast from a rainfall-distribution model (docs/48).

Never a published forecast. For one operational cycle file (one forecast year), the model declared in
config/probability_calibration/amount_shadow.json (EMOS, censored shifted gamma) is fitted on the cycle's reference years,
pooled over the national cells exactly as in the Phase 2 benchmark, and predicts each target's rainfall distribution for the
forecast year: the 10%, 50% and 90% quantiles (mm) and the tercile probabilities. The MVS-corrected ensemble (the published
amount correction) gives the same quantiles for comparison.

Once CHIRPS has been prepared for a target (the cycle's verification observations), both are scored — CRPS, coverage of the
10-90% interval, pinball losses — and the shadow's tercile probabilities are scored against the published probabilities
(RPS). These seasons were not used to build or select anything: they are the independent record for the amount/range product.

Results: <output_root>/<year>/<model>__<target>.json (reused while its dependency fingerprint — code, configurations, masks,
model and observation inputs — is unchanged), shadow_<model>_<year>_<target>.nc and .png.

The DRN pooled over the months of a cycle (drn_pooled, docs/54 3d) is fitted once per cycle and run, as in the final fit of its
benchmark (scripts/pooled_benchmark.py): on the samples of the four months over the reference years together, with the month's
position as an input and whole years held out for early stopping; each month is then forecast with its own position. It has
no season shadow (the season total is not pooled). Its fingerprint covers the inputs of all four months, so a change in any
month refits it.

  python scripts/dist_shadow.py --cycle config/cycles/feb_2026_fmam.json
"""
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def parse():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--cycle', default='config/operational.json', help='operational cycle file (one forecast year)')
    p.add_argument('--config', default='config/probability_calibration/amount_shadow.json')
    p.add_argument('--targets', nargs='+')
    p.add_argument('--models', nargs='+', help='only these models (default: the configured model and the selection candidates)')
    p.add_argument('--no-resume', action='store_true')
    return p.parse_args()


ARGS = parse() if __name__ == '__main__' else None
ROOT_DIR = Path(__file__).resolve().parents[1]
if ARGS is not None:
    os.environ.setdefault('CALIBRATION_CYCLE', str((ROOT_DIR / ARGS.cycle).resolve()))

import xarray as xr                                                     # noqa: E402
from common import ROOT, load_config, save_json, save_netcdf            # noqa: E402

CODE = ['scripts/dist_shadow.py', 'scripts/dist_calibration.py', 'scripts/neural_calibration.py', 'scripts/sst_indices.py', 'scripts/dist_benchmark.py', 'scripts/bias_methods.py',
        'scripts/bias_benchmark.py', 'scripts/bias_validation.py', 'scripts/run_calibration.py', 'scripts/calibration_core.py',
        'scripts/common.py', 'scripts/cycle.py']
LEVELS = (.1, .5, .9)
NO_SHADOW = {}                                          # models without a shadow (none since the pooled DRN has one)
POOLED = {'drn_pooled'}                                 # one fit for the months of a cycle (pooled_fit)
_POOLED_FITS = {}
SHORT = {'emos_csg': 'EMOS', 'extended_logistic': 'extended logistic', 'quantile_regression': 'quantile regression', 'bjp': 'BJP',
         'bma_precipitation': 'BMA', 'quantile_regression_forest': 'QRF', 'drn_csg': 'DRN', 'drn_sst': 'DRN + SST',
         'drn_emos_residual': 'neural EMOS correction', 'drn_pooled': 'pooled DRN'}
POSITION_COLOURS = ['#a6611a', '#d9d9d9', '#1a9641']                    # below the interval, inside, above


def read(p):
    return json.loads((ROOT / p).read_text(encoding='utf-8'))


def folder_of(scfg, entry, year):
    return ROOT / scfg['output_root'].format(name=entry['name']) / str(year)


def selection_models(entry):
    """Distribution models the method selection lists as candidates for this cycle (outputs/method_selection/selection.json):
    each gets its own shadow, so its independent validation seasons accumulate."""
    sel = ROOT / 'outputs/method_selection/selection.json'
    if not sel.is_file():
        return []
    c = next((c for c in json.loads(sel.read_text(encoding='utf-8'))['cycles'] if c['name'] == entry['name']), None)
    found = []
    for prods in (c or {}).get('targets', {}).values():
        for e in prods.values():
            for x in [e['selected'], *e['alternatives']]:
                if str(x.get('family', '')).startswith('distribution') and x['method'] not in found:
                    found.append(x['method'])
    return found


def fingerprint(cycle_path, config_path, cycle, project, entry, target, model):
    """Everything a target's shadow file depends on: code, configurations, masks, model and observation inputs."""
    from bias_benchmark import target_config, sha256
    from bias_validation import observation_path
    bench = read(entry['benchmark_config'])
    year, ref = cycle['forecast_year'], list(range(cycle['reference_years'][0], cycle['reference_years'][1] + 1))
    files = [*CODE, cycle_path, config_path, entry['benchmark_config'], cycle['project_config'], bench['cells']['path'],
             *[v['path'] for v in bench['regions'].values()]]
    h = hashlib.sha256(json.dumps(dict(target=target, entry=entry, model=model), sort_keys=True).encode())
    for f in files:
        h.update(f.encode() + sha256(ROOT / f).encode())
    for t in (months_of(cycle, project) if model in POOLED else [target]):     # the pooled fit uses every month
        tc = target_config(project, t)
        folder = ROOT / cycle.get('processed_root', 'data/processed') / f"init{tc['initialization_month']:02d}_{tc['season']['name']}"
        for f in [folder / f'ecmwf_{y}_common.nc' for y in ref + [year]] + [folder / f'chirps_{y}_common.nc' for y in ref]:
            h.update(f.name.encode() + sha256(f).encode())
    o = observation_path(cycle, target, year)
    h.update((sha256(o) if o.is_file() else 'not observed').encode())
    return h.hexdigest()


def months_of(cycle, project):
    """The month targets of a cycle (its targets without the season), in the order of the pooled network's month inputs."""
    return [t for t in cycle['targets'] if t != project['season']['name']]


def onehot(i, n):
    return {f'target_{j + 1}': np.full(n, float(j == i)) for j in range(4)}


def pooled_fit(cycle_path, scfg, entry, model):
    """The pooled DRN of a cycle, fitted once on the four months' samples over the reference years (as the final fit of
    pooled_benchmark.py: month position one-hot, the row's year for early stopping), cached for the months of this run."""
    key = (cycle_path, entry['name'], model)
    if key in _POOLED_FITS:
        return _POOLED_FITS[key]
    from bias_benchmark import load_mask, target_config
    from run_calibration import load_inputs, cell_area
    from dist_benchmark import fold
    import dist_calibration as dc
    cycle, bench = read(cycle_path), read(entry['benchmark_config'])
    project = load_config(cycle['project_config'])
    ref = list(range(cycle['reference_years'][0], cycle['reference_years'][1] + 1))
    bench_months = [t for t in bench['targets'] if t != project['season']['name']]
    if months_of(cycle, project) != bench_months:                    # the month inputs must mean what they meant in the benchmark
        raise ValueError(f'{cycle_path}: months {months_of(cycle, project)} differ from the benchmark order {bench_months}')
    members = (scfg.get('members') or {}).get(model)
    parts = []
    for i, t in enumerate(months_of(cycle, project)):
        _, models, obs, _, lat, lon = load_inputs(target_config(project, t), ref, ref)
        if members:
            models = {z: m[:members] for z, m in models.items()}
        idx = np.flatnonzero(load_mask(bench['cells'], lat, lon))
        glat, glon = np.meshgrid(lat, lon, indexing='ij')
        S, st = fold(models, obs, ref, idx, cell_area(lat, lon)[idx], coords=(glat.ravel()[idx], glon.ravel()[idx]))
        S.update(onehot(i, len(S['y'])), year_index=np.repeat(np.arange(len(ref)), int(st['valid'].sum())))
        parts.append(S)
    keys = [k for k in parts[0] if k not in ('n_years', 'members', 'thresholds')]
    pooled = {k: np.concatenate([np.asarray(S[k]) for S in parts]) for k in keys}
    pooled['n_years'] = len(ref)
    mdl = dc.MODELS[model]
    _POOLED_FITS[key] = mdl.fit(pooled, **mdl.defaults)
    return _POOLED_FITS[key]


def weighted_mean(v, area, mask):
    ok = mask & np.isfinite(v)
    return float(area[ok] @ v[ok] / area[ok].sum()) if ok.any() else None


def run_target(cycle_path, scfg, entry, target):
    from bias_benchmark import load_mask, target_config
    from bias_methods import correct
    from bias_validation import observation_path
    from run_calibration import load_inputs, cell_area
    from dist_benchmark import fold, score_year
    import dist_calibration as dc
    cycle, bench = read(cycle_path), read(entry['benchmark_config'])
    project = load_config(cycle['project_config'])
    year = cycle['forecast_year']
    ref = list(range(cycle['reference_years'][0], cycle['reference_years'][1] + 1))
    tag, models, obs, _, lat, lon = load_inputs(target_config(project, target), ref + [year], ref)
    members = (scfg.get('members') or {}).get(scfg['model'])          # as in the model's benchmark (the DRN: 25, docs/54)
    if members:
        models = {z: m[:members] for z, m in models.items()}
    area = cell_area(lat, lon)
    idx = np.flatnonzero(load_mask(bench['cells'], lat, lon))
    glat, glon = np.meshgrid(lat, lon, indexing='ij')
    coords = (glat.ravel()[idx], glon.ravel()[idx])                     # location predictors of the DRN
    area_e = area[idx]
    regions = {k: load_mask(v, lat, lon)[idx] for k, v in bench['regions'].items()}
    n = len(idx)
    names = (scfg.get('extra_inputs') or {}).get(scfg['model'])          # SST indices and regions of some neural models
    extra = None
    if names:
        import sst_indices
        extra = sst_indices.extra_inputs(names, target_config(project, target), ref + [year], lat, lon, idx)
    S, st = fold(models, obs, ref, idx, area_e, coords=coords, extra=extra)
    mdl = dc.MODELS[scfg['model']]
    F = dc.features(models[year][:, idx], st['mu_o'], st['mu_m'], st['valid'], st['cv'], *coords)
    F.update({k: v[year] for k, v in (extra or {}).items()})
    if scfg['model'] in POOLED:                              # one fit for the cycle's months; this month's position
        fit = pooled_fit(cycle_path, scfg, entry, scfg['model'])
        F.update(onehot(months_of(cycle, project).index(target), n))
    else:
        fit = mdl.fit(S, **mdl.defaults)
    d = mdl.predict(F, fit)
    valid = st['valid']
    q = {u: np.where(valid, d.quantile(np.full(n, u)), np.nan) for u in LEVELS}
    p = np.where((valid & st['prob_ok'])[:, None], d.terciles(st['q1'], st['q2']), np.nan)
    method = scfg['reference_amount_method']
    ens = correct(method, [models[z][:, idx] for z in ref], np.stack([obs[z][idx] for z in ref]), models[year][:, idx],
                  dict(bench['methods'].get(method, {})))
    ens_ok = np.isfinite(ens).all(0) & valid
    e0 = np.where(np.isfinite(ens), ens, 0.)
    eq = {u: np.where(ens_ok, np.quantile(e0, u, axis=0), np.nan) for u in LEVELS}
    pub_file = ROOT / cycle['forecast_root'] / tag / str(year) / f'forecast_{year}.nc'
    published = None
    if pub_file.is_file():
        with xr.open_dataset(pub_file) as ds:
            published = ds.blend_probability.transpose('lat', 'lon', 'category').values.reshape(-1, 3)[idx].astype(float)
    prim = regions[bench['primary_region']]
    forecast = {}
    for name, qq in (('shadow', q), ('mvs_ensemble', eq)):
        both = valid & ens_ok
        forecast[name] = dict(q10_mm=weighted_mean(qq[.1], area_e, prim & both), q50_mm=weighted_mean(qq[.5], area_e, prim & both),
                              q90_mm=weighted_mean(qq[.9], area_e, prim & both),
                              width_relative=weighted_mean((qq[.9] - qq[.1]) / st['mu_o'], area_e, prim & both))
    forecast['climatology_mm'] = weighted_mean(st['mu_o'], area_e, prim & valid & ens_ok)
    o = observation_path(cycle, target, year)
    observed = None
    if o.is_file():
        with xr.open_dataset(o) as ds:
            a = ds.precip_season.transpose('lat', 'lon')
            if not np.array_equal(a.lat, lat) or not np.array_equal(a.lon, lon):
                raise ValueError(f'Observation grid mismatch: {o}')
            observed = a.values.reshape(-1).astype(float)[idx]
    row = dict(tag=tag, model=scfg['model'], fitted=fit, observed=observed is not None, primary_region=bench['primary_region'],
               observation=str(o.relative_to(ROOT)).replace('\\', '/') if observed is not None else None,
               cells=dict(national=int(n), modelled=int(valid.sum()), tercile=int((valid & st['prob_ok']).sum())),
               forecast=forecast, published_probabilities=str(pub_file.relative_to(ROOT)).replace('\\', '/') if published is not None else None)
    if observed is not None:
        stores = {k: {} for k in ('shadow', 'mvs_ensemble', 'published')}
        y = np.nan_to_num(observed)
        score_year(year, p, np.where(valid, d.crps(y), np.nan), q, st, observed, area_e, regions, stores['shadow'])
        import bias_benchmark as bb
        crps_e = np.where(ens_ok, bb.ensemble_crps(e0, y), np.nan)
        score_year(year, None, crps_e, eq, st, observed, area_e, regions, stores['mvs_ensemble'])
        if published is not None:
            score_year(year, np.where((valid & st['prob_ok'])[:, None], published, np.nan), None, None, st, observed, area_e, regions,
                       stores['published'])
        row['scores'] = {}
        for k, regs in stores.items():
            for reg, dd in regs.items():
                r = {kk: v[0] for kk, v in dd['per_year'].items()}
                if 'rps' in r:
                    r['rpss'] = 1 - r['rps'] / r['rps_clim']
                if 'crps' in r:
                    r['crpss'] = 1 - r['crps'] / r['crps_clim']
                row['scores'].setdefault(reg, {})[k] = r
    def full(v):                                            # national cells back onto the full grid
        z = np.full(len(area), np.nan)
        z[idx] = v
        return z
    arrays = dict(lat=lat, lon=lon, country=load_mask(bench['regions'][bench['primary_region']], lat, lon),
                  q={u: full(q[u]) for u in LEVELS}, eq={u: full(eq[u]) for u in LEVELS}, mu=full(np.where(valid, st['mu_o'], np.nan)),
                  observed=full(observed) if observed is not None else None,
                  p=np.stack([full(p[:, k]) for k in range(3)], -1))
    return row, arrays


def save_shadow(folder, model, label, year, target, row, a, cycle_path):
    shape = (len(a['lat']), len(a['lon']))
    ds = xr.Dataset(coords=dict(lat=a['lat'], lon=a['lon'], category=['below', 'near', 'above']),
                    attrs=dict(description=f'SHADOW FORECAST, not published: {label} rainfall distribution, {target} {year} '
                                           f'(cycle {cycle_path}). Quantiles in mm; the MVS-corrected ensemble for comparison.',
                               model=model, target=target, year=year))
    for u in LEVELS:
        ds[f'shadow_q{int(u * 100)}'] = (('lat', 'lon'), a['q'][u].reshape(shape))
        ds[f'mvs_ensemble_q{int(u * 100)}'] = (('lat', 'lon'), a['eq'][u].reshape(shape))
    ds['shadow_tercile_probability'] = (('lat', 'lon', 'category'), a['p'].reshape(*shape, 3))
    ds['climatology_mean'] = (('lat', 'lon'), a['mu'].reshape(shape))
    if a['observed'] is not None:
        ds['observed'] = (('lat', 'lon'), a['observed'].reshape(shape))
    for v in ds.data_vars:
        if v != 'shadow_tercile_probability':
            ds[v].attrs['units'] = 'mm'
    save_netcdf(ds, folder / f'shadow_{model}_{year}_{target}.nc')
    figure(folder / f'shadow_{model}_{year}_{target}.png', a, label, target, year, row)


def figure(path, a, label, target, year, row):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    lat, lon, country = a['lat'], a['lon'], a['country']
    shape = (len(lat), len(lon))
    edges = lambda c: np.r_[c[0] - (c[1] - c[0]) / 2, (c[:-1] + c[1:]) / 2, c[-1] + (c[-1] - c[-2]) / 2]
    observed = a['observed'] is not None
    short = SHORT.get(row['model'], row['model'])
    rows = [('shadow', f'Shadow ({short})', a['q']), ('mvs_ensemble', 'MVS-corrected ensemble', a['eq'])]
    fig, axes = plt.subplots(2 + observed, 3, figsize=(10.5, 3.5 * (2 + observed)), squeeze=False, layout='constrained')
    vmax = np.nanpercentile(np.r_[a['q'][.9][country], a['eq'][.9][country]], 95)
    mask = lambda v: np.where(country, v, np.nan).reshape(shape)
    prim = row['primary_region']
    for i, (key, name, qq) in enumerate(rows):
        for j, u in enumerate(LEVELS):
            ax = axes[i, j]
            im = ax.pcolormesh(edges(lon), edges(lat), mask(qq[u]), cmap='YlGnBu', vmin=0, vmax=vmax)
            t = f'{name}: ' + ('median' if u == .5 else f'{int(u * 100)}% quantile')
            if j == 2 and observed and prim in row['scores']:
                t += f"\ncoverage {100 * row['scores'][prim][key]['coverage_80']:.0f}%, CRPSS {row['scores'][prim][key]['crpss']:+.3f}"
            ax.set_title(t, fontsize=8.5)
        fig.colorbar(im, ax=axes[i, :].tolist(), shrink=.85, label='mm')
    if observed:
        ax = axes[2, 0]
        im = ax.pcolormesh(edges(lon), edges(lat), mask(a['observed']), cmap='YlGnBu', vmin=0, vmax=vmax)
        ax.set_title(f'Observed (CHIRPS), {target} {year}', fontsize=8.5)
        cmap = ListedColormap(POSITION_COLOURS)
        for ax, (key, name, qq) in zip(axes[2, 1:], rows):
            pos = np.where(a['observed'] < qq[.1], 0., np.where(a['observed'] > qq[.9], 2., 1.))
            pos[~np.isfinite(qq[.1]) | ~np.isfinite(a['observed'])] = np.nan
            ax.pcolormesh(edges(lon), edges(lat), mask(pos), cmap=cmap, vmin=-.5, vmax=2.5)
            ax.set_title(f"Observed vs the {short if key == 'shadow' else 'MVS'} 10–90% range", fontsize=8.5)
        fig.text(.5, 0, 'Bottom row, right: brown below the range, grey inside, green above. White: not modelled '
                 '(training mean below 1 mm) or outside Ethiopia.', ha='center', va='top', fontsize=8)
    for ax in axes.ravel():
        ax.contour(lon, lat, country.reshape(shape).astype(float), levels=[.5], colors='#333', linewidths=.6)
        ax.set_aspect('equal')
        ax.set_xticks([])
        ax.set_yticks([])
    fig.suptitle(f'SHADOW FORECAST (not published): rainfall amounts and ranges, {target} {year}. '
                 + ('Scored against CHIRPS: one season.' if observed else 'Awaiting CHIRPS observations.'), fontsize=10)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=130, bbox_inches='tight')
    plt.close(fig)


def main(args):
    from bias_validation import match
    from bias_benchmark import git
    import dist_calibration as dc
    scfg = read(args.config)
    cycle, project, entry = match(scfg, args.cycle)
    if entry is None:
        print(f'No amount shadow is configured for {args.cycle}.')
        return
    year = cycle['forecast_year']
    folder = folder_of(scfg, entry, year)
    folder.mkdir(parents=True, exist_ok=True)
    models = [scfg['model']] + ([m for m in selection_models(entry) if m != scfg['model']] if scfg.get('models_from_selection') else [])
    if args.models:
        models = [m for m in models if m in args.models]
    targets = args.targets or cycle['targets']
    prov = dict(commit=git('rev-parse', 'HEAD'),
                uncommitted_changes=bool(git('status', '--porcelain', '--', *CODE, args.cycle, args.config, entry['benchmark_config'])))
    done = 0
    for model in [m for m in models if m in NO_SHADOW]:
        print(f'{model}: {NO_SHADOW[model]}', flush=True)
    season = project['season']['name']
    for model, t in [(m, t) for m in models if m not in NO_SHADOW for t in targets if not (m in POOLED and t == season)]:
        label = dc.MODELS[model].name
        key = fingerprint(args.cycle, args.config, cycle, project, entry, t, model)
        f = folder / f'{model}__{t}.json'
        if not args.no_resume and f.is_file() and json.loads(f.read_text(encoding='utf-8')).get('key') == key \
                and (folder / f'shadow_{model}_{year}_{t}.png').is_file():
            continue
        row, arrays = run_target(args.cycle, dict(scfg, model=model), entry, t)
        save_json(f, dict(key=key, label=label, target=t, cycle=Path(args.cycle).as_posix(), forecast_year=year,
                          reference_years=cycle['reference_years'], shadow=True, since=scfg['since'],
                          created_utc=datetime.now(timezone.utc).isoformat(), provenance=prov, **row))
        save_shadow(folder, model, label, year, t, row, arrays, Path(args.cycle).as_posix())
        fc = row['forecast']
        line = (f"{SHORT.get(model, model)} {t}: median {fc['shadow']['q50_mm']:.0f} mm, 10-90% {fc['shadow']['q10_mm']:.0f}-{fc['shadow']['q90_mm']:.0f} mm "
                f"(MVS {fc['mvs_ensemble']['q10_mm']:.0f}-{fc['mvs_ensemble']['q90_mm']:.0f})")
        if row['observed']:
            s = row['scores'][row['primary_region']]
            line += (f"; coverage {100 * s['shadow']['coverage_80']:.0f}% (MVS {100 * s['mvs_ensemble']['coverage_80']:.0f}%), "
                     f"CRPSS {s['shadow']['crpss']:+.3f} (MVS {s['mvs_ensemble']['crpss']:+.3f})")
        print(line, flush=True)
        done += 1
    print(f'Saved: {folder} ({done} updated)' if done else 'All amount-shadow files are up to date.')


if __name__ == '__main__':
    main(ARGS)
