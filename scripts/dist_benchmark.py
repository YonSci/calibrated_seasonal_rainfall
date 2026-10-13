"""Phase 2, Pathway B: rainfall-distribution models against the published pipeline (docs/48).

Each model (dist_calibration.py) predicts a full rainfall distribution from the raw ensemble; terciles, quantiles and intervals
are derived from it. Design per target (national cells), as in Phase 1:
  outer leave-one-year-out over the training years: every model is fitted on the other training years only (pooled over cells,
  equal weight per year); the left-out year is predicted and scored.
  test years: fitted on all training years, scored on the test years (exploratory).
References, computed in the same folds:
  probabilities: the incumbent published pipeline (MVS -> smoothed counts -> climatology blend, blend weight from the inner
                 out-of-fold years, as in Phase 1);
  amounts:       the MVS-corrected ensemble (CRPS of its empirical distribution, empirical quantiles).
Scores (per year, area-weighted over a region; equal years): tercile RPS/RPSS, CRPS/CRPSS (training CHIRPS climatology),
pinball loss at 10/50/90% and coverage of the 10-90% interval. Tests: RPS of each model against the incumbent and CRPS of
each model against the MVS ensemble, paired whole-year sign-flip, Holm across the models and targets, no harm over the test
years.

  python scripts/dist_benchmark.py --config config/probability_calibration/sep_ondj_distribution.json
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
    p.add_argument('--config', default='config/probability_calibration/sep_ondj_distribution.json')
    p.add_argument('--targets', nargs='+')
    p.add_argument('--workers', type=int, default=2)
    p.add_argument('--no-resume', action='store_true')
    p.add_argument('--no-figures', action='store_true')
    return p.parse_args()


ARGS = parse() if __name__ == '__main__' else None
ROOT_DIR = Path(__file__).resolve().parents[1]
if ARGS is not None:
    _c = json.loads((ROOT_DIR / ARGS.config).read_text(encoding='utf-8'))
    os.environ.setdefault('CALIBRATION_CYCLE', json.loads((ROOT_DIR / _c['benchmark_config']).read_text(encoding='utf-8'))['cycle'])

from common import ROOT, load_config, save_json                          # noqa: E402
from calibration_core import categories                                 # noqa: E402
from run_calibration import cell_area                                   # noqa: E402
from significance import paired_summary, holm, ALPHA                    # noqa: E402
from bias_methods import correct                                        # noqa: E402
import bias_benchmark as bb                                             # noqa: E402
import prob_calibration as pc                                           # noqa: E402
import dist_calibration as dc                                           # noqa: E402
from prob_benchmark import Records                                      # noqa: E402

CODE = ['scripts/dist_benchmark.py', 'scripts/dist_calibration.py', 'scripts/prob_calibration.py', 'scripts/prob_benchmark.py']
LEVELS = (.1, .5, .9)


def read(p):
    return json.loads((ROOT / p).read_text(encoding='utf-8'))


def pinball(q, y, tau):
    r = y - q
    return np.where(r >= 0, tau * r, (tau - 1) * r)


def fold(models, obs, T, idx, area_e, valid_min=1.0):
    """Training samples (relative units) and per-cell statistics from the training years T, on the national cells idx."""
    O = np.stack([obs[z][idx] for z in T])
    mu_o = O.mean(0)
    mu_m = np.mean([models[z][:, idx].mean(0) for z in T], axis=0)          # equal-year weights
    q1, q2 = np.quantile(O, [1 / 3, 2 / 3], axis=0, method='linear')
    prob_ok = (O.std(0) >= 1.0) & (q1 > 0) & ((q2 - q1) > 1e-6)
    valid = np.isfinite(O).all(0) & (mu_o >= valid_min) & (mu_m >= valid_min)
    thr = np.quantile(O, dc.THRESHOLD_LEVELS, axis=0).T / np.where(valid, mu_o, 1)[:, None]
    S = {k: [] for k in ('y', 'm', 's', 'md', 'w', 'thresholds')}
    for z in T:
        F = dc.features(models[z][:, idx], mu_o, mu_m, valid)
        w = np.where(valid, area_e, 0.)
        S['y'].append(np.where(valid, obs[z][idx] / np.where(valid, mu_o, 1), 0)[valid])
        for k in ('m', 's', 'md'):
            S[k].append(F[k][valid])
        S['w'].append((w / w.sum())[valid] / len(T))
        S['thresholds'].append(thr[valid])
    S = {k: np.concatenate(v) for k, v in S.items()}
    clim_cat = categories(O, q1, q2)
    p_clim = np.stack([(clim_cat == k).mean(0) for k in range(3)], -1)
    return S, dict(mu_o=mu_o, mu_m=mu_m, q1=q1, q2=q2, prob_ok=prob_ok, valid=valid, O=O, p_clim=p_clim)


def score_year(name, p, crps, quant, stats, y_obs, area_e, regions, store):
    """Region scores of one method for one year (p: terciles; crps: per cell; quant: {tau: per-cell quantile})."""
    y_cat = categories(y_obs, stats['q1'], stats['q2'])
    t = np.eye(3)[y_cat]
    rps = lambda q, mask: np.sum((np.cumsum(q[mask], -1)[:, :2] - np.cumsum(t[mask], -1)[:, :2]) ** 2, -1)
    crps_clim = bb.ensemble_crps(np.where(stats['valid'], stats['O'], 0), np.where(stats['valid'], y_obs, 0))
    for reg, mask in regions.items():
        pv = mask & stats['prob_ok'] & stats['valid'] & np.isfinite(y_obs) & (np.isfinite(p).all(-1) if p is not None else True)
        av = mask & stats['valid'] & np.isfinite(y_obs) & (np.isfinite(crps) if crps is not None else True)
        d = store.setdefault(reg, dict(years=[], per_year={}))
        rec = {}
        if p is not None and pv.any():
            w = area_e[pv] / area_e[pv].sum()
            rec.update(rps=float(w @ rps(p, pv)), rps_clim=float(w @ rps(stats['p_clim'], pv)))
        if crps is not None and av.any():
            w = area_e[av] / area_e[av].sum()
            rec.update(crps=float(w @ crps[av]), crps_clim=float(w @ crps_clim[av]))
            for tau in LEVELS:
                rec[f'pinball_{int(tau * 100)}'] = float(w @ pinball(quant[tau][av], y_obs[av], tau))
            rec['coverage_80'] = float(w @ ((y_obs[av] >= quant[.1][av]) & (y_obs[av] <= quant[.9][av])))
        for k, v in rec.items():
            d['per_year'].setdefault(k, []).append(v)
        d['years'].append(name)


def run_target(config_path, target):
    pcfg = read(config_path)
    cfg = read(pcfg['benchmark_config'])
    project = load_config(cfg['project_config'])
    rng = lambda a, b: list(range(a, b + 1))
    train, test = rng(*cfg['training_years']), rng(*cfg['test_years'])
    tag, models, obs, lat, lon = bb.load_target(cfg, project, target)
    area_all = cell_area(lat, lon)
    idx = np.flatnonzero(bb.load_mask(cfg['cells'], lat, lon))
    area_e = area_all[idx]
    regions = {k: bb.load_mask(v, lat, lon)[idx] for k, v in cfg['regions'].items()}
    rec = Records(pcfg['reference_amount_method'], cfg['methods'].get(pcfg['reference_amount_method'], {}), models, obs, train,
                  cfg['smoothing_alpha'])
    keys = pcfg['models']
    store = {k: {'training': {}, 'test': {}} for k in keys + ['incumbent', 'mvs_ensemble']}
    diag = {k: dict(crossings=[], converged=[]) for k in keys}

    def evaluate(design, y, T, inner_records, outer_record, fitted=None):
        S, st = fold(models, obs, T, idx, area_e)
        y_obs = obs[y][idx]
        lam_fit = pc.fit(pc.INCUMBENT, inner_records, area_all)               # incumbent: blend weight from inner years
        p_inc = pc.predict(lam_fit, outer_record)[idx]
        score_year(y, p_inc, None, None, st, y_obs, area_e, regions, store['incumbent'][design])
        ens = correct(pcfg['reference_amount_method'], [models[z][:, idx] for z in T], np.stack([obs[z][idx] for z in T]),
                      models[y][:, idx], {k: v for k, v in cfg['methods'].get(pcfg['reference_amount_method'], {}).items()})
        ens_ok = np.isfinite(ens).all(0)
        e0 = np.where(ens_ok, ens, 0.)
        crps_ens = np.where(ens_ok, bb.ensemble_crps(e0, np.nan_to_num(y_obs)), np.nan)
        quant = {tau: np.quantile(e0, tau, axis=0) for tau in LEVELS}
        score_year(y, None, crps_ens, quant, st, y_obs, area_e, regions, store['mvs_ensemble'][design])
        F = dc.features(models[y][:, idx], st['mu_o'], st['mu_m'], st['valid'])
        for k in keys:
            m = dc.MODELS[k]
            model = (fitted or {}).get(k) or m.fit(S, **{**m.defaults, **pcfg.get('parameters', {}).get(k, {})})
            if fitted is not None:
                fitted[k] = model
            d = m.predict(F, model)
            if hasattr(d, 'crossings'):
                diag[k]['crossings'].append(d.crossings)
            diag[k]['converged'].append(model.get('converged', True))
            p = d.terciles(st['q1'], st['q2'])
            crps = d.crps(np.nan_to_num(y_obs))
            q = {tau: d.quantile(np.full(len(idx), tau)) for tau in LEVELS}
            score_year(y, p, crps, q, st, y_obs, area_e, regions, store[k][design])
    for y in train:                                         # outer leave-one-year-out
        T = [z for z in train if z != y]
        inner = [rec.get(frozenset((y, z)), [y, z])[1] for z in T]
        evaluate('training', y, T, inner, rec.get(frozenset((y,)), [y])[0])
        print(f'{target} {y}', flush=True)
    oof = [rec.get(frozenset((z,)), [z])[0] for z in train]
    fitted = {}
    for y, r in zip(test, rec.get(frozenset(), test)):      # test years: fitted once on all training years
        evaluate('test', y, train, oof, r, fitted)
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
    return target, dict(tag=tag, methods=summary, fitted=fitted,
                        diagnostics={k: dict(mean_crossing_share=float(np.mean(v['crossings'])) if v['crossings'] else None,
                                             all_converged=bool(all(v['converged']))) for k, v in diag.items()})


def tests_of(results, keys, region, targets):
    out = {}
    for score, ref in (('rps', 'incumbent'), ('crps', 'mvs_ensemble')):
        stats = {(k, t): {d: paired_summary(results[t]['methods'][k][d][region]['per_year'][score],
                                            results[t]['methods'][ref][d][region]['per_year'][score]) for d in ('training', 'test')}
                 for k in keys for t in targets}
        adj = holm({f'{k}|{t}': s['training']['p_improvement'] for (k, t), s in stats.items()})
        for (k, t), s in stats.items():
            s['decision'] = dict(reference=ref, holm_p_family=float(adj[f'{k}|{t}']), no_harm=s['test']['mean_difference'] <= 0,
                                 confirmed=bool(s['training']['mean_difference'] < 0 and adj[f'{k}|{t}'] < ALPHA
                                                and s['test']['mean_difference'] <= 0))
            out.setdefault(k, {}).setdefault(score, {})[t] = s
    return out


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(args):
    pcfg = read(args.config)
    cfg = read(pcfg['benchmark_config'])
    project = load_config(cfg['project_config'])
    targets = args.targets or cfg['targets']
    out_root = ROOT / pcfg['output_root']
    parts = out_root / 'parts'
    parts.mkdir(parents=True, exist_ok=True)
    dep = bb.dependencies(cfg, project, targets, pcfg['benchmark_config'])
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
            failed = []
            for job in as_completed(jobs):
                t = jobs[job]
                try:
                    _, value = job.result()
                except Exception as exc:
                    failed.append(f'{t}: {exc!r}')
                    continue
                (parts / f'{t}.pkl').write_bytes(pickle.dumps(dict(key=keys[t], value=value)))
                results[t] = value
            if failed:
                raise RuntimeError('Targets failed (completed targets are checkpointed): ' + '; '.join(failed))
    results = {t: results[t] for t in targets}
    model_keys = pcfg['models']
    data = dict(created_utc=datetime.now(timezone.utc).isoformat(), config=args.config, config_contents=pcfg, protocol=__doc__.strip(),
                provenance=bb.provenance(cfg, project, targets, pcfg['benchmark_config'], dep, extra=CODE + [args.config]),
                phase=2, pathway='B: rainfall-distribution models from the raw ensemble', models=model_keys,
                registry={k: dict(name=dc.MODELS[k].name, estimates=dc.MODELS[k].estimates, predictors=dc.MODELS[k].predictors,
                                  fitting=dc.MODELS[k].fitting, references=dc.MODELS[k].references,
                                  outputs='CDF, quantiles, tercile probabilities') for k in model_keys},
                references=dict(incumbent='MVS -> smoothed counts -> climatology blend (published probabilities)',
                                mvs_ensemble='MVS-corrected ensemble (empirical distribution)'),
                regions={k: v['label'] for k, v in cfg['regions'].items()}, primary_region=cfg['primary_region'],
                training_years=cfg['training_years'], test_years=cfg['test_years'], targets=results,
                tests=tests_of(results, model_keys, cfg['primary_region'], targets))
    save_json(out_root / 'benchmark.json', data)
    if not args.no_figures:
        figure(out_root, data)
    print('Saved:', out_root)


def figure(out, data):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    reg = data['primary_region']
    T = list(data['targets'])
    tr, te = data['training_years'], data['test_years']
    rows = [('incumbent', 'Published pipeline (incumbent / MVS ensemble)')] + [(k, data['registry'][k]['name']) for k in data['models']]
    fig, axes = plt.subplots(1, 3, figsize=(17, 0.55 * len(rows) + 2.4), sharey=True)
    for ax, (design, key, title) in zip(axes, [('training', 'rpss', f'Tercile RPSS, leave-one-year-out {tr[0]}-{tr[1]}'),
                                               ('training', 'crpss', f'CRPSS (amounts), {tr[0]}-{tr[1]}'),
                                               ('test', 'rpss', f'Tercile RPSS, fit {tr[0]}-{tr[1]}, scored {te[0]}-{te[1]}')]):
        def val(k, t):
            src = 'mvs_ensemble' if (k == 'incumbent' and key == 'crpss') else k
            return data['targets'][t]['methods'][src][design][reg][key]
        v = np.array([[val(k, t) for t in T] for k, _ in rows])
        lim = max(np.nanmax(np.abs(v)), .02)
        ax.imshow(v, cmap='RdBu', vmin=-lim, vmax=lim, aspect='auto')
        for i, (k, _) in enumerate(rows):
            for j, t in enumerate(T):
                mark = ''
                if design == 'training' and k != 'incumbent':
                    tt = data['tests'][k]['rps' if key == 'rpss' else 'crps'][t]['decision']
                    mark = ' *' if tt['confirmed'] else ''
                ax.text(j, i, f'{v[i, j]:+.3f}{mark}', ha='center', va='center', fontsize=8, fontweight='bold' if k == 'incumbent' else 'normal')
        ax.set_xticks(range(len(T)), T)
        ax.set_title(title, fontsize=10)
    axes[0].set_yticks(range(len(rows)), [n for _, n in rows])
    fig.suptitle(f'Rainfall-distribution models (Phase 2, Pathway B) against the published pipeline ({data["regions"][reg]})', fontsize=12)
    fig.text(.5, .005, '* better than the reference (RPS: the published probabilities; CRPS: the MVS-corrected ensemble), Holm across the '
             'models and targets, and not worse over the test years.', ha='center', fontsize=8)
    fig.tight_layout(rect=(0, .03, 1, .95))
    (out / 'figures').mkdir(parents=True, exist_ok=True)
    fig.savefig(out / 'figures/distribution_summary.png', dpi=150)
    plt.close(fig)


if __name__ == '__main__':
    main(ARGS)
