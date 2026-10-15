"""GrazFeediNG calibration against the published pipeline (docs/51), one cycle (here September-initialized ONDJ).

Methods (scripts/grazfeeding.py; 'leung_affine' in bias_methods.py), each fitted inside the folds:
  gf_full          the uploaded pipeline as it is: modified-Leung member-wise affine -> member counts -> IAD Dirichlet, the
                   Dirichlet fitted (as in the script) on the training years' probabilities from the affine fitted on those years
  gf_no_dirichlet  the same without the Dirichlet (the script's --no_dirichlet)
  iad_on_mvs       the published amount correction (MVS) -> member counts -> IAD Dirichlet: the probability calibration alone
  leung_blend      modified-Leung affine -> the published probability stage (smoothed counts, climatology blend with its weight
                   from inner years): the bias correction alone
  leung_affine     (amounts) the modified-Leung corrected ensemble
References in the same folds: the published probabilities (MVS -> smoothed counts -> climatology blend) for tercile RPS, and the
MVS-corrected ensemble for amount CRPS. Design and tests as Phase 2 (dist_benchmark.py): outer leave-one-year-out over the
training years, test years fitted on all training years; paired whole-year sign-flip, Holm across the probability methods and
targets (RPS) and across the targets (CRPS), not worse over the test years.
Also the forecast year: every method fitted on the cycle's observed years and applied to the forecast (never published).

  python scripts/grazfeeding_benchmark.py --config config/grazfeeding/sep_ondj.json
"""
import argparse
import hashlib
import json
import os
import pickle
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def parse():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--config', default='config/grazfeeding/sep_ondj.json')
    p.add_argument('--targets', nargs='+')
    p.add_argument('--workers', type=int, default=2)
    p.add_argument('--no-resume', action='store_true')
    return p.parse_args()


ARGS = parse() if __name__ == '__main__' else None
ROOT_DIR = Path(__file__).resolve().parents[1]
if ARGS is not None:
    _c = json.loads((ROOT_DIR / ARGS.config).read_text(encoding='utf-8'))
    os.environ.setdefault('CALIBRATION_CYCLE', json.loads((ROOT_DIR / _c['benchmark_config']).read_text(encoding='utf-8'))['cycle'])

from common import ROOT, load_config, save_json                          # noqa: E402
from run_calibration import cell_area                                   # noqa: E402
from significance import paired_summary, holm, ALPHA                    # noqa: E402
import bias_benchmark as bb                                             # noqa: E402
import bias_methods as bm                                               # noqa: E402
import prob_calibration as pc                                           # noqa: E402
import dist_benchmark as db                                             # noqa: E402
from prob_benchmark import Records                                      # noqa: E402
from calibration_core import fit_amount, categories, labels             # noqa: E402
from compare_calibration import smooth                                  # noqa: E402
from grazfeeding import IADDirichlet, member_probabilities, observed_category   # noqa: E402

CODE = ['scripts/grazfeeding_benchmark.py', 'scripts/grazfeeding.py', 'scripts/bias_methods.py', 'scripts/dist_benchmark.py',
        'scripts/prob_calibration.py', 'scripts/prob_benchmark.py']
PROB = ['gf_full', 'gf_no_dirichlet', 'iad_on_mvs', 'leung_blend']
AMOUNT = ['leung_affine']
LEVELS = (.1, .5, .9)
BINS = np.linspace(0, 1, 11)                         # reliability: forecast-probability bins of 0.1
PANELS = ['incumbent'] + PROB                        # probability pipelines in the plots, published first
MIN_SHARE = 0.01                                     # reliability bins with fewer forecasts are not drawn
SHORT = dict(gf_full='GrazFeediNG as uploaded', gf_no_dirichlet='Leung + counts (no Dirichlet)', iad_on_mvs='MVS + counts + IAD',
             leung_blend='Leung + published blend', incumbent='Published (MVS + blend)')


def read(p):
    return json.loads((ROOT / p).read_text(encoding='utf-8'))


def corrected(method, params, train_members, O, members):
    m, p = bm.resolve(method, params)
    state = m.fit(train_members, O, **p)
    out = np.asarray(m.apply(np.asarray(members, float), state, **p), float)
    out[:, ~state['ok']] = np.nan
    return out, state, m, p


def fit_iad(method, params, train_members, O, T, obs, idx, q1, q2, iad_cfg):
    """IAD fitted as in the script: the affine fitted on the training years, applied to each of them, member counts against
    the training terciles, observed categories; pooled over every cell with finite values (equal weight per sample)."""
    m, p = bm.resolve(method, params)
    state = m.fit(train_members, O, **p)
    P, Y = [], []
    for z, x in zip(T, train_members):
        c = np.asarray(m.apply(np.asarray(x, float), state, **p), float)
        c[:, ~state['ok']] = np.nan
        P.append(member_probabilities(c, q1, q2))
        Y.append(observed_category(obs[z][idx], q1, q2))
    P, Y = np.concatenate(P), np.concatenate(Y)
    ok = np.isfinite(P).all(1) & (Y >= 0)
    return IADDirichlet(**{k: v for k, v in iad_cfg.items() if v is not None}).fit(P[ok], Y[ok])


def calibrated(cal, p):
    out = np.full_like(p, np.nan)
    ok = np.isfinite(p).all(1)
    out[ok] = cal.predict(p[ok])
    return out


def run_target(config_path, target):
    gcfg = read(config_path)
    cfg = read(gcfg['benchmark_config'])
    project = load_config(cfg['project_config'])
    rng = lambda a, b: list(range(a, b + 1))
    train, test = rng(*cfg['training_years']), rng(*cfg['test_years'])
    tag, models, obs, lat, lon = bb.load_target(cfg, project, target)
    area_all = cell_area(lat, lon)
    idx = np.flatnonzero(bb.load_mask(cfg['cells'], lat, lon))
    area_e = area_all[idx]
    regions = {k: bb.load_mask(v, lat, lon)[idx] for k, v in cfg['regions'].items()}
    mvs_params = dict(cfg['methods'].get('mvs', {}))
    leung = dict(gcfg['leung'], ratio_bounds=tuple(gcfg['leung']['ratio_bounds']))
    rec_mvs = Records('mvs', mvs_params, models, obs, train, cfg['smoothing_alpha'])
    rec_leung = Records('leung_affine', leung, models, obs, train, cfg['smoothing_alpha'])
    keys = PROB + AMOUNT + ['incumbent', 'mvs_ensemble']
    store = {k: {'training': {}, 'test': {}} for k in keys}
    rel = {k: {'training': {}, 'test': {}} for k in PANELS}
    primary = regions[cfg['primary_region']]
    iad_params = {}

    def evaluate(design, y, T, inner_mvs, outer_mvs, inner_leung, outer_leung):
        _, st = db.fold(models, obs, T, idx, area_e)
        y_obs = obs[y][idx]
        q1, q2 = st['q1'], st['q2']
        tr = [models[z][:, idx] for z in T]
        O = np.stack([obs[z][idx] for z in T])
        # references
        score = lambda k, p=None, crps=None, quant=None: db.score_year(y, p, crps, quant, st, y_obs, area_e, regions, store[k][design])

        def prob(k, p):
            score(k, p=p)
            reliability_add(rel[k][design], p, categories(y_obs, q1, q2), primary & st['prob_ok'] & st['valid'] & np.isfinite(y_obs), area_e)
        prob('incumbent', pc.predict(pc.fit(pc.INCUMBENT, inner_mvs, area_all), outer_mvs)[idx])
        ens_mvs, _, _, _ = corrected('mvs', mvs_params, tr, O, models[y][:, idx])
        ens_leung, st_l, _, _ = corrected('leung_affine', leung, tr, O, models[y][:, idx])
        for k, ens in (('mvs_ensemble', ens_mvs), ('leung_affine', ens_leung)):
            ok = np.isfinite(ens).all(0)
            e0 = np.where(ok, ens, 0.)
            crps = np.where(ok, bb.ensemble_crps(e0, np.nan_to_num(y_obs)), np.nan)
            score(k, crps=crps, quant={tau: np.where(ok, np.quantile(e0, tau, axis=0), np.nan) for tau in LEVELS})
        # probability methods
        p_leung, p_mvs = member_probabilities(ens_leung, q1, q2), member_probabilities(ens_mvs, q1, q2)
        cal_l = fit_iad('leung_affine', leung, tr, O, T, obs, idx, q1, q2, gcfg['iad'])
        cal_m = fit_iad('mvs', mvs_params, tr, O, T, obs, idx, q1, q2, gcfg['iad'])
        prob('gf_full', calibrated(cal_l, p_leung))
        prob('gf_no_dirichlet', p_leung)
        prob('iad_on_mvs', calibrated(cal_m, p_mvs))
        prob('leung_blend', pc.predict(pc.fit(pc.INCUMBENT, inner_leung, area_all), outer_leung)[idx])
        if design == 'test' and 'test' not in iad_params:
            pooled = st_l.get('counts', {}).get('pooled_climatology_members', [0, 1])
            iad_params['test'] = dict(gf_full=cal_l.params(), iad_on_mvs=cal_m.params(), leung_pooled_member_share=pooled[0] / max(pooled[1], 1))
        iad_params.setdefault(design + '_converged', []).extend([cal_l.converged, cal_m.converged])

    for y in train:                                          # outer leave-one-year-out
        T = [z for z in train if z != y]
        evaluate('training', y, T, [rec_mvs.get(frozenset((y, z)), [y, z])[1] for z in T], rec_mvs.get(frozenset((y,)), [y])[0],
                 [rec_leung.get(frozenset((y, z)), [y, z])[1] for z in T], rec_leung.get(frozenset((y,)), [y])[0])
        print(f'{target} {y}', flush=True)
    oof_m = [rec_mvs.get(frozenset((z,)), [z])[0] for z in train]
    oof_l = [rec_leung.get(frozenset((z,)), [z])[0] for z in train]
    for y, rm, rl in zip(test, rec_mvs.get(frozenset(), test), rec_leung.get(frozenset(), test)):
        evaluate('test', y, train, oof_m, rm, oof_l, rl)
    summary = {}
    for k, dd in store.items():
        summary[k] = {}
        for design, regs in dd.items():
            summary[k][design] = {}
            for reg, d in regs.items():
                m = lambda key: float(np.mean(d['per_year'][key]))
                s = dict(years=d['years'], per_year=d['per_year'])
                if 'rps' in d['per_year']:
                    s.update(rps=m('rps'), rpss=1 - m('rps') / m('rps_clim'))
                if 'crps' in d['per_year']:
                    s.update(crps=m('crps'), crpss=1 - m('crps') / m('crps_clim'), coverage_80=m('coverage_80'),
                             **{f'pinball_{int(t * 100)}': m(f'pinball_{int(t * 100)}') for t in LEVELS})
                summary[k][design][reg] = s
    rel = {k: {d: {c: {q: v.tolist() for q, v in a.items()} for c, a in r.items()} for d, r in dd.items()} for k, dd in rel.items()}
    return target, dict(tag=tag, methods=summary, reliability=rel, iad=dict(test=iad_params.get('test'),
                                                          all_converged=bool(all(iad_params.get('training_converged', []) + iad_params.get('test_converged', [])))),
                        forecast=forecast_year(gcfg, cfg, project, target, models, obs, lat, lon, idx))


def forecast_year(gcfg, cfg, project, target, models, obs, lat, lon, idx):
    """The forecast year (never published): every method fitted on the cycle's observed years, as the published forecast."""
    cycle = read(cfg['cycle'])
    year = cycle['forecast_year']
    ref = [z for z in range(cycle['reference_years'][0], cycle['reference_years'][1] + 1) if z in obs]
    if year not in models or not ref:
        return None
    O = np.stack([obs[z][idx] for z in ref])
    q1, q2 = np.quantile(O, [1 / 3, 2 / 3], axis=0, method='linear')
    tr = [models[z][:, idx] for z in ref]
    leung = dict(gcfg['leung'], ratio_bounds=tuple(gcfg['leung']['ratio_bounds']))
    mvs_params = dict(cfg['methods'].get('mvs', {}))
    ens_l, _, _, _ = corrected('leung_affine', leung, tr, O, models[year][:, idx])
    ens_m, _, _, _ = corrected('mvs', mvs_params, tr, O, models[year][:, idx])
    p_nod, p_mvs = member_probabilities(ens_l, q1, q2), member_probabilities(ens_m, q1, q2)
    cal = fit_iad('leung_affine', leung, tr, O, ref, obs, idx, q1, q2, gcfg['iad'])
    cal_m = fit_iad('mvs', mvs_params, tr, O, ref, obs, idx, q1, q2, gcfg['iad'])
    area_all = cell_area(lat, lon)

    def blend(method, params):                       # the published probability stage, fitted as for the published forecast
        rec = Records(method, params, models, obs, ref, cfg['smoothing_alpha'])
        fit = pc.fit(pc.INCUMBENT, [rec.get(frozenset((z,)), [z])[0] for z in ref], area_all)
        return pc.predict(fit, forecast_record(method, params, models, obs, ref, year, cfg['smoothing_alpha']))[idx]
    full = lambda v: (lambda z: (z.__setitem__(idx, v), z)[1])(np.full(len(lat) * len(lon), np.nan))
    probs = dict(gf_full=calibrated(cal, p_nod), gf_no_dirichlet=p_nod, iad_on_mvs=calibrated(cal_m, p_mvs),
                 leung_blend=blend('leung_affine', leung), incumbent_recomputed=blend('mvs', mvs_params))
    primary = bb.load_mask(cfg['regions'][cfg['primary_region']], lat, lon)[idx]
    return dict(year=int(year), reference_years=cycle['reference_years'], iad=cal.params(),
                p={k: [full(c) for c in v.T] for k, v in probs.items()}, mean_mm=full(np.nanmean(ens_l, 0)), lat=lat, lon=lon,
                validation=validate(cycle, target, year, lat, lon, idx, O, q1, q2, probs, dict(leung_affine=ens_l, mvs_ensemble=ens_m),
                                    primary, cell_area(lat, lon)[idx]))


def validate(cycle, target, year, lat, lon, idx, O, q1, q2, probs, ensembles, primary, area):
    """The forecast year scored against its CHIRPS observation once it exists (the cycle's verification observations): an
    independent season for every pipeline. All pipelines on the same cells: the primary region where every pipeline has
    probabilities and the terciles are defined (as in the benchmark); the published probabilities are the recomputed ones."""
    import xarray as xr
    path = ROOT / cycle.get('verification_root', '') / 'observations' / target / f'chirps_{year}_common.nc'
    if not cycle.get('verification_root') or not path.is_file():
        return None
    with xr.open_dataset(path) as d:
        a = d.precip_season.transpose('lat', 'lon')
        if not (np.allclose(a.lat, lat) and np.allclose(a.lon, lon)):
            raise ValueError(f'Observation grid mismatch: {path}')
        y_obs = a.values.reshape(-1).astype(float)[idx]
    prob_ok = (O.std(0) >= 1.0) & (q1 > 0) & ((q2 - q1) > 1e-6)
    cells = primary & prob_ok & np.isfinite(y_obs) & np.all([np.isfinite(v).all(-1) for v in probs.values()], axis=0)
    w = area[cells] / area[cells].sum()
    t = np.eye(3)[categories(y_obs, q1, q2)][cells]
    rps = lambda q: float(w @ np.sum((np.cumsum(q[cells], -1)[:, :2] - np.cumsum(t, -1)[:, :2]) ** 2, -1))
    clim = np.stack([(categories(O, q1, q2) == k).mean(0) for k in range(3)], -1)
    out = dict(year=int(year), observation=str(path.relative_to(ROOT)).replace('\\', '/'), cells=int(cells.sum()),
               rps={('incumbent' if k == 'incumbent_recomputed' else k): rps(v) for k, v in probs.items()}, rps_clim=rps(clim))
    acells = primary & np.isfinite(y_obs) & np.all([np.isfinite(e).all(0) for e in ensembles.values()], axis=0)
    wa = area[acells] / area[acells].sum()
    out['crps'] = {k: float(wa @ bb.ensemble_crps(e[:, acells], y_obs[acells])) for k, e in ensembles.items()}
    out['crps_clim'] = float(wa @ bb.ensemble_crps(O[:, acells], y_obs[acells]))
    out['amount_cells'] = int(acells.sum())
    return out


def forecast_record(method, params, models, obs, ref, year, alpha):
    """The forecast year's record for the probability stage (as prob_benchmark.Records, without an observation)."""
    m, p = bm.resolve(method, params)
    O = np.stack([obs[z] for z in ref])
    pars = fit_amount([models[z] for z in ref], O, np.ones(O.shape[1], bool))
    state = m.fit([models[z] for z in ref], O, **p)
    lab = np.stack([labels(obs[z], pars) for z in ref])
    clim = np.stack([(lab == k).mean(0) for k in range(3)], -1)
    elig = state['ok'] & pars['probability_eligible']
    clim[~elig] = np.nan
    mu, sd = O.mean(0), O.std(0)
    ens = np.asarray(m.apply(models[year], state, **p), float)
    c = categories(np.where(state['ok'], ens, 0.), pars['q1'], pars['q2'])
    prob = np.stack([(c == k).mean(0) for k in range(3)], -1)
    prob[~elig] = np.nan
    with np.errstate(divide='ignore', invalid='ignore'):
        zmean = np.where(elig & (sd > 0), (ens.mean(0) - mu) / sd, np.nan)
        lspread = np.where(elig & (sd > 0) & (ens.std(0) > 0), np.log(ens.std(0) / sd), np.nan)
    return dict(s=smooth(prob, len(ens), alpha=alpha), clim=clim, y=np.full(len(mu), -1, 'int8'), zmean=zmean, lspread=lspread)


def reliability_add(acc, p, y_cat, mask, area):
    """Area-weighted reliability sums of one year (below and above normal), each year weighted equally."""
    ok = mask & np.isfinite(p).all(-1)
    if not ok.any():
        return
    w = area[ok] / area[ok].sum()
    for c, cat in ((0, 'below'), (2, 'above')):
        f = p[ok, c]
        b = np.clip(np.digitize(f, BINS) - 1, 0, len(BINS) - 2)
        a = acc.setdefault(cat, dict(w=np.zeros(len(BINS) - 1), f=np.zeros(len(BINS) - 1), o=np.zeros(len(BINS) - 1)))
        np.add.at(a['w'], b, w)
        np.add.at(a['f'], b, w * f)
        np.add.at(a['o'], b, w * (y_cat[ok] == c))


def tests_of(results, region, targets):
    out = {}
    for score, keys, ref in (('rps', PROB, 'incumbent'), ('crps', AMOUNT, 'mvs_ensemble')):
        stats = {(k, t): {d: paired_summary(results[t]['methods'][k][d][region]['per_year'][score],
                                            results[t]['methods'][ref][d][region]['per_year'][score]) for d in ('training', 'test')}
                 for k in keys for t in targets}
        adj = holm({f'{k}|{t}': s['training']['p_improvement'] for (k, t), s in stats.items()})
        for (k, t), s in stats.items():
            s['decision'] = dict(reference=ref, holm_p_family=float(adj[f'{k}|{t}']), no_harm=s['test']['mean_difference'] <= 0,
                                 confirmed=bool(s['training']['mean_difference'] < 0 and adj[f'{k}|{t}'] < ALPHA and s['test']['mean_difference'] <= 0))
            out.setdefault(k, {}).setdefault(score, {})[t] = s
    return out


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(args):
    gcfg = read(args.config)
    cfg = read(gcfg['benchmark_config'])
    project = load_config(cfg['project_config'])
    targets = args.targets or cfg['targets']
    out_root = ROOT / gcfg['output_root']
    parts = out_root / 'parts'
    parts.mkdir(parents=True, exist_ok=True)
    dep = bb.dependencies(cfg, project, targets, gcfg['benchmark_config'])
    extra = hashlib.sha256(''.join(sha256(ROOT / f) for f in CODE + [args.config]).encode()).hexdigest()
    keys = {t: bb.dependency_key(dep, t) + '|' + extra for t in targets}
    results = {}
    for t in targets:
        f = parts / f'{t}.pkl'
        if not args.no_resume and f.is_file():
            saved = pickle.loads(f.read_bytes())
            if saved['key'] == keys[t]:
                results[t] = saved['value']
                print(f'{t}: loaded from checkpoint', flush=True)
    todo = [t for t in targets if t not in results]
    if todo:
        with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
            jobs = {pool.submit(run_target, args.config, t): t for t in todo}
            for job in as_completed(jobs):
                t = jobs[job]
                _, value = job.result()
                (parts / f'{t}.pkl').write_bytes(pickle.dumps(dict(key=keys[t], value=value)))
                results[t] = value
    results = {t: results[t] for t in targets}
    forecasts = {t: results[t].pop('forecast', None) for t in targets}
    validation = {t: f.pop('validation', None) for t, f in forecasts.items() if f}
    data = dict(created_utc=datetime.now(timezone.utc).isoformat(), config=args.config, config_contents=gcfg, protocol=__doc__.strip(),
                provenance=bb.provenance(cfg, project, targets, gcfg['benchmark_config'], dep, extra=CODE + [args.config]),
                methods=PROB + AMOUNT, labels=dict(gcfg['methods'], leung_affine='Modified-Leung affine ensemble (amounts)'),
                references=dict(incumbent='Published probabilities: MVS -> smoothed counts -> climatology blend',
                                mvs_ensemble='MVS-corrected ensemble (published amount correction)'),
                regions={k: v['label'] for k, v in cfg['regions'].items()}, primary_region=cfg['primary_region'],
                training_years=cfg['training_years'], test_years=cfg['test_years'], targets=results,
                tests=tests_of(results, cfg['primary_region'], targets),
                validation={t: v for t, v in validation.items() if v})     # the forecast year, once observed
    save_json(out_root / 'benchmark.json', data)
    save_forecast(out_root, cfg, forecasts)
    figure(out_root, data)
    reliability_figure(out_root, data)
    print('Saved:', out_root)


def save_forecast(out_root, cfg, forecasts):
    """Forecast-year probabilities of every pipeline (never published) next to the published ones: NetCDF, favoured-tercile
    maps and tercile-probability maps (rows: pipelines; columns: below, near, above normal)."""
    import xarray as xr
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    cycle = read(cfg['cycle'])
    folder = out_root / 'forecast'
    folder.mkdir(parents=True, exist_ok=True)
    country = None
    for t, f in forecasts.items():
        if not f:
            continue
        lat, lon = f['lat'], f['lon']
        shape = (len(lat), len(lon))
        if country is None:
            country = bb.load_mask(cfg['regions'][cfg['primary_region']], lat, lon).reshape(shape)
        grid = lambda k: np.stack(f['p'][k], -1).reshape(*shape, 3)
        pub = None
        path = ROOT / cycle['forecast_root'] / f'init{cycle["initialization_month"]:02d}_{t}/{f["year"]}/forecast_{f["year"]}.nc'
        if path.is_file():
            with xr.open_dataset(path) as d:
                pub = d.blend_probability.sel(category=['below', 'near', 'above']).transpose('lat', 'lon', 'category').values
        # the published stage recomputed here should match the published file (else the Leung + blend panel is not comparable)
        rec = grid('incumbent_recomputed')
        both = country & np.isfinite(rec).all(-1) & (np.isfinite(pub).all(-1) if pub is not None else False)
        check = float(np.abs(rec[both] - pub[both]).max()) if pub is not None and both.any() else None
        ds = xr.Dataset(coords=dict(lat=lat, lon=lon, category=['below', 'near', 'above']),
                        attrs=dict(description=f'NOT PUBLISHED: GrazFeediNG calibration (docs/51), {t} {f["year"]}, fitted on '
                                               f'{f["reference_years"][0]}-{f["reference_years"][1]}.',
                                   published_recomputed_max_abs_difference=check if check is not None else 'n/a'))
        for k in PROB:
            ds[f'{k}_probability'] = (('lat', 'lon', 'category'), grid(k))
            ds[f'{k}_probability'].attrs['long_name'] = SHORT[k]
        ds['leung_mean_mm'] = (('lat', 'lon'), np.asarray(f['mean_mm']).reshape(shape))
        if pub is not None:
            ds['published_probability'] = (('lat', 'lon', 'category'), pub)
        ds.to_netcdf(folder / f'gf_{f["year"]}_{t}.nc')
        print(f'{t} {f["year"]}: published stage recomputed vs published file, max |difference| {check}', flush=True)

        panels = [(SHORT[k], pub if k == 'incumbent' else grid(k)) for k in PANELS]
        panels = [(n, np.where(country[..., None], p, np.nan)) for n, p in panels if p is not None]
        edges = lambda c: np.r_[c[0] - (c[1] - c[0]) / 2, (c[:-1] + c[1:]) / 2, c[-1] + (c[-1] - c[-2]) / 2]
        E = (edges(lon), edges(lat))

        def frame(ax, title):
            ax.contour(lon, lat, country.astype(float), levels=[.5], colors='#333', linewidths=.6)
            ax.set_title(title, fontsize=9)
            ax.set_aspect('equal'); ax.set_xticks([]); ax.set_yticks([])
        # favoured tercile
        fav = lambda p: np.where(np.isfinite(p).all(-1) & (np.nan_to_num(p, nan=-1).max(-1) >= 0.4), np.nan_to_num(p, nan=-1).argmax(-1), np.nan)
        fig, axes = plt.subplots(1, len(panels), figsize=(3.4 * len(panels), 3.9), squeeze=False, layout='constrained')
        for ax, (name, p) in zip(axes[0], panels):
            ax.pcolormesh(*E, fav(p), cmap=ListedColormap(['#a6611a', '#bdbdbd', '#1a9641']), vmin=-.5, vmax=2.5)
            frame(ax, name)
        fig.suptitle(f'NOT PUBLISHED · {t} {f["year"]}: favoured tercile (≥ 40%); brown below, grey near, green above normal; '
                     'white: no tercile reaches 40%', fontsize=10)
        fig.savefig(folder / f'gf_{f["year"]}_{t}.png', dpi=130)
        plt.close(fig)
        # tercile probabilities
        cats = [('Below normal', 'YlOrBr'), ('Near normal', 'Greys'), ('Above normal', 'YlGn')]
        fig, axes = plt.subplots(len(panels), 3, figsize=(10.5, 3.1 * len(panels)), squeeze=False, layout='constrained')
        for i, (name, p) in enumerate(panels):
            for j, (cat, cmap) in enumerate(cats):
                ax = axes[i, j]
                im = ax.pcolormesh(*E, p[..., j], cmap=cmap, vmin=0, vmax=.8)
                frame(ax, f'{name}\n{cat}: national mean {np.nanmean(p[..., j]):.0%}')
                if i == len(panels) - 1:
                    fig.colorbar(im, ax=axes[:, j], orientation='horizontal', fraction=.025, pad=.01, label=f'{cat} probability',
                                 ticks=[0, .2, 1 / 3, .6, .8], format=lambda x, _: f'{x:.0%}')
        fig.suptitle(f'NOT PUBLISHED · {t} {f["year"]}: tercile probabilities of each pipeline (climatology 33%)', fontsize=11)
        fig.savefig(folder / f'gf_{f["year"]}_{t}_probabilities.png', dpi=110)
        plt.close(fig)


def reliability_figure(out, data):
    """Reliability diagrams of every probability pipeline (below and above normal), per target and design."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    T = list(data['targets'])
    colours = dict(incumbent='#000000', gf_full='#d95f02', gf_no_dirichlet='#7570b3', iad_on_mvs='#1b9e77', leung_blend='#e7298a')
    for design in ('training', 'test'):
        fig, axes = plt.subplots(2, len(T), figsize=(3.3 * len(T), 6.9), sharex=True, sharey=True, squeeze=False, layout='constrained')
        for j, t in enumerate(T):
            for i, cat in enumerate(('below', 'above')):
                ax = axes[i, j]
                ax.plot([0, 1], [0, 1], color='#999', lw=.8, ls='--')
                ax.axhline(1 / 3, color='#ccc', lw=.6)
                ax.axvline(1 / 3, color='#ccc', lw=.6)
                for k in PANELS:
                    a = data['targets'][t].get('reliability', {}).get(k, {}).get(design, {}).get(cat)
                    if not a:
                        continue
                    w, fs, ob = (np.asarray(a[q]) for q in ('w', 'f', 'o'))
                    ok = w >= MIN_SHARE * w.sum()                # bins with too few forecasts are not shown
                    share = w[ok] / w.sum()
                    ax.plot(fs[ok] / w[ok], ob[ok] / w[ok], '-', color=colours[k], lw=1.2, label=SHORT[k], zorder=2)
                    ax.scatter(fs[ok] / w[ok], ob[ok] / w[ok], s=6 + 400 * share, color=colours[k], alpha=.75, zorder=3)
                ax.set_xlim(0, 1)
                ax.set_ylim(0, 1)
                ax.set_aspect('equal')
                ax.set_title(f'{t}: {cat} normal', fontsize=9)
                if i == 1:
                    ax.set_xlabel('Forecast probability')
                if j == 0:
                    ax.set_ylabel('Observed frequency')
        axes[0, 0].legend(fontsize=7, loc='upper left')
        yrs = data['training_years' if design == 'training' else 'test_years']
        how = 'leave-one-year-out ' if design == 'training' else 'fitted on the training years, scored '
        fig.suptitle(f'Reliability of the tercile probabilities, {data["regions"][data["primary_region"]]}, {how}{yrs[0]}–{yrs[1]}. '
                     f'Marker area: share of forecasts in the bin (bins under {MIN_SHARE:.0%} not shown); on the diagonal = reliable', fontsize=10)
        (out / 'figures').mkdir(parents=True, exist_ok=True)
        fig.savefig(out / f'figures/grazfeeding_reliability_{design}.png', dpi=120)
        plt.close(fig)


def figure(out, data):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    reg = data['primary_region']
    T = list(data['targets'])
    rows = [('incumbent', 'rpss', 'Published probabilities')] + [(k, 'rpss', SHORT[k]) for k in PROB] + \
           [('mvs_ensemble', 'crpss', 'MVS ensemble (CRPSS)'), ('leung_affine', 'crpss', 'Modified-Leung ensemble (CRPSS)')]
    fig, axes = plt.subplots(1, 2, figsize=(15, 0.5 * len(rows) + 2.2), sharey=True, layout='constrained')
    for ax, design in zip(axes, ('training', 'test')):
        v = np.array([[data['targets'][t]['methods'][k][design][reg][key] for t in T] for k, key, _ in rows])
        lim = max(np.nanmax(np.abs(v)), .02)
        ax.imshow(v, cmap='RdBu', vmin=-lim, vmax=lim, aspect='auto')
        for i, (k, key, _) in enumerate(rows):
            for j, t in enumerate(T):
                mark = ''
                if design == 'training' and k in data['tests']:
                    mark = ' *' if data['tests'][k]['rps' if key == 'rpss' else 'crps'][t]['decision']['confirmed'] else ''
                ax.text(j, i, f'{v[i, j]:+.3f}{mark}', ha='center', va='center', fontsize=8)
        ax.set_xticks(range(len(T)), T)
        ax.set_title(('Leave-one-year-out ' if design == 'training' else 'Fit on training years, scored ') +
                     '–'.join(map(str, data['training_years' if design == 'training' else 'test_years'])), fontsize=10)
    axes[0].set_yticks(range(len(rows)), [n for *_, n in rows])
    fig.suptitle(f'GrazFeediNG calibration against the published pipeline ({data["regions"][reg]}); RPSS rows: tercile '
                 'probabilities, CRPSS rows: amounts. * confirmed better than the reference', fontsize=10)
    (out / 'figures').mkdir(parents=True, exist_ok=True)
    fig.savefig(out / 'figures/grazfeeding_summary.png', dpi=140)
    plt.close(fig)


if __name__ == '__main__':
    main(ARGS)
