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
from grazfeeding import IADDirichlet, member_probabilities, observed_category   # noqa: E402

CODE = ['scripts/grazfeeding_benchmark.py', 'scripts/grazfeeding.py', 'scripts/bias_methods.py', 'scripts/dist_benchmark.py',
        'scripts/prob_calibration.py', 'scripts/prob_benchmark.py']
PROB = ['gf_full', 'gf_no_dirichlet', 'iad_on_mvs', 'leung_blend']
AMOUNT = ['leung_affine']
LEVELS = (.1, .5, .9)
SHORT = dict(gf_full='GrazFeediNG as uploaded', gf_no_dirichlet='Leung + counts (no Dirichlet)', iad_on_mvs='MVS + counts + IAD',
             leung_blend='Leung + published blend')


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
    iad_params = {}

    def evaluate(design, y, T, inner_mvs, outer_mvs, inner_leung, outer_leung):
        _, st = db.fold(models, obs, T, idx, area_e)
        y_obs = obs[y][idx]
        q1, q2 = st['q1'], st['q2']
        tr = [models[z][:, idx] for z in T]
        O = np.stack([obs[z][idx] for z in T])
        # references
        score = lambda k, p=None, crps=None, quant=None: db.score_year(y, p, crps, quant, st, y_obs, area_e, regions, store[k][design])
        score('incumbent', p=pc.predict(pc.fit(pc.INCUMBENT, inner_mvs, area_all), outer_mvs)[idx])
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
        score('gf_full', p=calibrated(cal_l, p_leung))
        score('gf_no_dirichlet', p=p_leung)
        score('iad_on_mvs', p=calibrated(cal_m, p_mvs))
        score('leung_blend', p=pc.predict(pc.fit(pc.INCUMBENT, inner_leung, area_all), outer_leung)[idx])
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
    return target, dict(tag=tag, methods=summary, iad=dict(test=iad_params.get('test'),
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
    ens_l, _, _, _ = corrected('leung_affine', leung, tr, O, models[year][:, idx])
    p_nod = member_probabilities(ens_l, q1, q2)
    cal = fit_iad('leung_affine', leung, tr, O, ref, obs, idx, q1, q2, gcfg['iad'])
    full = lambda v: (lambda z: (z.__setitem__(idx, v), z)[1])(np.full(len(lat) * len(lon), np.nan))
    return dict(year=int(year), reference_years=cycle['reference_years'], iad=cal.params(),
                p_full=[full(c) for c in calibrated(cal, p_nod).T], p_no_dirichlet=[full(c) for c in p_nod.T],
                mean_mm=full(np.nanmean(ens_l, 0)), lat=lat, lon=lon)


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
    data = dict(created_utc=datetime.now(timezone.utc).isoformat(), config=args.config, config_contents=gcfg, protocol=__doc__.strip(),
                provenance=bb.provenance(cfg, project, targets, gcfg['benchmark_config'], dep, extra=CODE + [args.config]),
                methods=PROB + AMOUNT, labels=dict(gcfg['methods'], leung_affine='Modified-Leung affine ensemble (amounts)'),
                references=dict(incumbent='Published probabilities: MVS -> smoothed counts -> climatology blend',
                                mvs_ensemble='MVS-corrected ensemble (published amount correction)'),
                regions={k: v['label'] for k, v in cfg['regions'].items()}, primary_region=cfg['primary_region'],
                training_years=cfg['training_years'], test_years=cfg['test_years'], targets=results,
                tests=tests_of(results, cfg['primary_region'], targets))
    save_json(out_root / 'benchmark.json', data)
    save_forecast(out_root, cfg, forecasts)
    figure(out_root, data)
    print('Saved:', out_root)


def save_forecast(out_root, cfg, forecasts):
    """Forecast-year probabilities of the uploaded pipeline (never published), with the published ones for comparison."""
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
        pub = None
        path = ROOT / cycle['forecast_root'] / f'init{cycle["initialization_month"]:02d}_{t}/{f["year"]}/forecast_{f["year"]}.nc'
        if path.is_file():
            with xr.open_dataset(path) as d:
                pub = d.blend_probability.sel(category=['below', 'near', 'above']).transpose('lat', 'lon', 'category').values
        ds = xr.Dataset(coords=dict(lat=lat, lon=lon, category=['below', 'near', 'above']),
                        attrs=dict(description=f'NOT PUBLISHED: GrazFeediNG calibration (docs/51), {t} {f["year"]}, fitted on '
                                               f'{f["reference_years"][0]}-{f["reference_years"][1]}.'))
        ds['gf_full_probability'] = (('lat', 'lon', 'category'), np.stack(f['p_full'], -1).reshape(*shape, 3))
        ds['gf_no_dirichlet_probability'] = (('lat', 'lon', 'category'), np.stack(f['p_no_dirichlet'], -1).reshape(*shape, 3))
        ds['leung_mean_mm'] = (('lat', 'lon'), np.asarray(f['mean_mm']).reshape(shape))
        if pub is not None:
            ds['published_probability'] = (('lat', 'lon', 'category'), pub)
        ds.to_netcdf(folder / f'gf_{f["year"]}_{t}.nc')
        fav = lambda p: np.where(np.isfinite(p).all(-1) & (np.nanmax(p, -1) >= 0.4), np.nanargmax(np.nan_to_num(p, nan=-1), -1), np.nan)
        panels = [('Published (MVS + climatology blend)', pub), ('GrazFeediNG as uploaded (Leung + IAD)', ds['gf_full_probability'].values),
                  ('Leung + member counts (no Dirichlet)', ds['gf_no_dirichlet_probability'].values)]
        panels = [p for p in panels if p[1] is not None]
        edges = lambda c: np.r_[c[0] - (c[1] - c[0]) / 2, (c[:-1] + c[1:]) / 2, c[-1] + (c[-1] - c[-2]) / 2]
        fig, axes = plt.subplots(1, len(panels), figsize=(4.2 * len(panels), 4.4), squeeze=False, layout='constrained')
        for ax, (name, p) in zip(axes[0], panels):
            v = fav(p)
            v[~country] = np.nan
            ax.pcolormesh(edges(lon), edges(lat), v, cmap=ListedColormap(['#a6611a', '#bdbdbd', '#1a9641']), vmin=-.5, vmax=2.5)
            ax.contour(lon, lat, country.astype(float), levels=[.5], colors='#333', linewidths=.6)
            ax.set_title(name, fontsize=9)
            ax.set_aspect('equal'); ax.set_xticks([]); ax.set_yticks([])
        fig.suptitle(f'NOT PUBLISHED · {t} {f["year"]}: favoured tercile (≥ 40%); brown below, grey near, green above normal; white: no tercile reaches 40%', fontsize=10)
        fig.savefig(folder / f'gf_{f["year"]}_{t}.png', dpi=130)
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
