"""The DRN pooled over the months of a cycle (docs/54, section 3d): one network for the four month targets, against the
published pipeline, with the per-target DRN and EMOS of the first stage as comparisons.

Same design as dist_benchmark.py, but per year instead of per target, since one fit serves the four months:
  outer leave-one-year-out over the training years: for each year, the samples of the four months over the other
  training years (each month as dist_benchmark.fold makes them, equal total weight per month) are pooled, with the month's
  position in the season as one-hot inputs (target_1..4) and the calendar year of every row (early stopping holds out whole
  years for all four months at once); one network is fitted; every month of the left-out year is forecast and scored;
  test years: one fit on all training years, every month of every test year scored.
References in the same folds and on the same cells, per month: the published probabilities and the MVS-corrected ensemble.
The season target is not pooled (its observations are the sum of the months'). Tests: the pooled DRN against the
references, Holm across its four targets (the method selection uses Benjamini-Hochberg). Comparisons with the per-target
DRN and EMOS read their per-year scores from the first stage (external_models).

  python scripts/pooled_benchmark.py --config config/probability_calibration/may_jjas_neural_pooled.json --workers 5
"""
import argparse
import hashlib
import json
import os
import pickle
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def parse():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--config', default='config/probability_calibration/may_jjas_neural_pooled.json')
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
from bias_methods import correct                                        # noqa: E402
import bias_benchmark as bb                                             # noqa: E402
import prob_calibration as pc                                           # noqa: E402
import dist_calibration as dc                                           # noqa: E402
import dist_benchmark as db                                             # noqa: E402
from prob_benchmark import Records                                      # noqa: E402

CODE = ['scripts/pooled_benchmark.py', *db.CODE]
LEVELS = db.LEVELS
_CTX = {}


def read(p):
    return json.loads((ROOT / p).read_text(encoding='utf-8'))


def months_of(cfg, project):
    return [t for t in cfg['targets'] if t != project['season']['name']]


def context(config_path):
    """Inputs of the four months, loaded once per worker."""
    if config_path in _CTX:
        return _CTX[config_path]
    pcfg = read(config_path)
    cfg = read(pcfg['benchmark_config'])
    project = load_config(cfg['project_config'])
    rng = lambda a, b: list(range(a, b + 1))
    train, test = rng(*cfg['training_years']), rng(*cfg['test_years'])
    ctx = dict(pcfg=pcfg, cfg=cfg, train=train, test=test, months=months_of(cfg, project), t={})
    for t in ctx['months']:
        tag, models, obs, lat, lon = bb.load_target(cfg, project, t)
        if pcfg.get('members'):
            models = {z: m[:pcfg['members']] for z, m in models.items()}
        area_all = cell_area(lat, lon)
        idx = np.flatnonzero(bb.load_mask(cfg['cells'], lat, lon))
        glat, glon = np.meshgrid(lat, lon, indexing='ij')
        mvs = cfg['methods'].get(pcfg['reference_amount_method'], {})
        ctx['t'][t] = dict(tag=tag, models=models, obs=obs, area_all=area_all, idx=idx, area_e=area_all[idx],
                           coords=(glat.ravel()[idx], glon.ravel()[idx]),
                           regions={k: bb.load_mask(v, lat, lon)[idx] for k, v in cfg['regions'].items()},
                           rec=Records(pcfg['reference_amount_method'], mvs, models, obs, train, cfg['smoothing_alpha']), mvs=mvs)
    _CTX[config_path] = ctx
    return ctx


def onehot(i, n):
    return {f'target_{j + 1}': np.full(n, float(j == i)) for j in range(4)}


def pooled_samples(ctx, T):
    """The four months' training samples over the years T, pooled, with the month position and the row's year."""
    parts, stats = [], {}
    for i, t in enumerate(ctx['months']):
        c = ctx['t'][t]
        S, st = db.fold(c['models'], c['obs'], T, c['idx'], c['area_e'], coords=c['coords'])
        n = len(S['y'])
        S.update(onehot(i, n), year_index=np.repeat(np.arange(len(T)), int(st['valid'].sum())))
        parts.append(S)
        stats[t] = st
    keys = [k for k in parts[0] if k not in ('n_years', 'members', 'thresholds')]
    pooled = {k: np.concatenate([np.asarray(S[k]) for S in parts]) for k in keys}
    pooled['n_years'] = len(T)
    return pooled, stats


def run_design(config_path, design, y):
    """One outer fold (design 'training', left-out year y) or the test design (y None): per month, its score records."""
    ctx = context(config_path)
    pcfg, cfg, train, test = ctx['pcfg'], ctx['cfg'], ctx['train'], ctx['test']
    T = [z for z in train if z != y] if design == 'training' else train
    scored = [y] if design == 'training' else test
    S, stats = pooled_samples(ctx, T)
    models = {}
    for k in pcfg['models']:
        m = dc.MODELS[k]
        models[k] = m.fit(S, **{**m.defaults, **pcfg.get('parameters', {}).get(k, {})})
    out = {}
    for i, t in enumerate(ctx['months']):
        c, st = ctx['t'][t], stats[t]
        store = {k: {} for k in pcfg['models'] + ['incumbent', 'mvs_ensemble']}
        rel = {k: {} for k in pcfg['models'] + ['incumbent']}
        primary = c['regions'][cfg['primary_region']]
        if design == 'training':
            inner = [c['rec'].get(frozenset((y, z)), [y, z])[1] for z in T]
            outer = [c['rec'].get(frozenset((y,)), [y])[0]]
        else:
            inner = [c['rec'].get(frozenset((z,)), [z])[0] for z in train]
            outer = c['rec'].get(frozenset(), test)
        lam_fit = pc.fit(pc.INCUMBENT, inner, c['area_all'])
        O = np.stack([c['obs'][z][c['idx']] for z in T])
        for yy, outer_record in zip(scored, outer):
            y_obs = c['obs'][yy][c['idx']]
            ycat = categories(y_obs, st['q1'], st['q2'])
            rmask = primary & st['prob_ok'] & st['valid'] & np.isfinite(y_obs)
            p_inc = pc.predict(lam_fit, outer_record)[c['idx']]
            db.score_year(yy, p_inc, None, None, st, y_obs, c['area_e'], c['regions'], store['incumbent'])
            db.reliability_add(rel['incumbent'], p_inc, ycat, rmask, c['area_e'])
            ens = correct(pcfg['reference_amount_method'], [c['models'][z][:, c['idx']] for z in T], O, c['models'][yy][:, c['idx']],
                          dict(c['mvs']))
            ok = np.isfinite(ens).all(0)
            e0 = np.where(ok, ens, 0.)
            db.score_year(yy, None, np.where(ok, bb.ensemble_crps(e0, np.nan_to_num(y_obs)), np.nan),
                          {tau: np.quantile(e0, tau, axis=0) for tau in LEVELS}, st, y_obs, c['area_e'], c['regions'], store['mvs_ensemble'])
            F = dc.features(c['models'][yy][:, c['idx']], st['mu_o'], st['mu_m'], st['valid'], st['cv'], *c['coords'])
            F.update(onehot(i, len(c['idx'])))
            for k, model in models.items():
                d = dc.MODELS[k].predict(F, model)
                p = d.terciles(st['q1'], st['q2'])
                db.score_year(yy, p, d.crps(np.nan_to_num(y_obs)), {tau: d.quantile(np.full(len(c['idx']), tau)) for tau in LEVELS},
                              st, y_obs, c['area_e'], c['regions'], store[k])
                db.reliability_add(rel[k], p, ycat, rmask, c['area_e'])
        out[t] = dict(store=store, reliability=rel)
    fitted = {k: {kk: vv for kk, vv in v.items() if kk in ('hidden', 'decay', 'steps', 'validation_crps', 'tuning')}
              for k, v in models.items()} if design == 'test' else None
    return design, y, out, fitted


def merge(parts, months, keys):
    """Per month: the per-design stores of every fold, in year order, as dist_benchmark.run_target makes them."""
    results = {}
    for t in months:
        store = {k: {'training': {}, 'test': {}} for k in keys}
        rel = {k: {'training': {}, 'test': {}} for k in keys if k != 'mvs_ensemble'}
        for (design, y), (out, _) in sorted(parts.items(), key=lambda kv: (kv[0][0] == 'test', kv[0][1] or 0)):
            for k in keys:
                for reg, d in out[t]['store'][k].items():
                    a = store[k][design].setdefault(reg, dict(years=[], per_year={}))
                    a['years'] += d['years']
                    for kk, v in d['per_year'].items():
                        a['per_year'].setdefault(kk, []).extend(v)
            for k in rel:
                for cat, a in out[t]['reliability'][k].items():
                    acc = rel[k][design].setdefault(cat, {q: np.zeros_like(v) for q, v in a.items()})
                    for q, v in a.items():
                        acc[q] += v
        rel = {k: {d: {c: {q: v.tolist() for q, v in a.items()} for c, a in r.items()} for d, r in dd.items()} for k, dd in rel.items()}
        fitted = next((f for (design, _), (_, f) in parts.items() if design == 'test'), None)
        results[t] = dict(methods=db.summarise(store), reliability=rel, fitted=fitted or {})
    return results


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(args):
    pcfg = read(args.config)
    cfg = read(pcfg['benchmark_config'])
    project = load_config(cfg['project_config'])
    months = months_of(cfg, project)
    out_root = ROOT / pcfg['output_root']
    (out_root / 'parts').mkdir(parents=True, exist_ok=True)
    dep = bb.dependencies(cfg, project, months, pcfg['benchmark_config'])
    key = bb.dependency_key(dep) + '|' + hashlib.sha256(''.join(sha256(ROOT / f) for f in CODE + [args.config]).encode()).hexdigest()
    # the code the workers import is the code at the start of the run (dist_benchmark.provenance)
    start = dict(commit=bb.git('rev-parse', 'HEAD'), uncommitted_changes=bool(bb.git('status', '--porcelain', '--', *CODE, args.config)),
                 code_sha256={f: sha256(ROOT / f) for f in CODE + [args.config]}, utc=datetime.now(timezone.utc).isoformat())
    train = list(range(cfg['training_years'][0], cfg['training_years'][1] + 1))
    jobs = [('training', y) for y in train] + [('test', None)]
    parts = {}
    for d, y in jobs:
        f = out_root / 'parts' / f'{d}_{y}.pkl'
        if not args.no_resume and f.is_file():
            saved = pickle.loads(f.read_bytes())
            if saved['key'] == key:
                parts[(d, y)] = saved['value']
    todo = [j for j in jobs if j not in parts]
    print(f'{len(parts)} folds from checkpoints, {len(todo)} to run', flush=True)
    if todo:
        with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {pool.submit(run_design, args.config, d, y): (d, y) for d, y in todo}
            failed = []
            for job in as_completed(futures):
                d, y = futures[job]
                try:
                    _, _, out, fitted = job.result()
                except Exception as exc:
                    failed.append(f'{d} {y}: {exc!r}')
                    print(f'{d} {y} FAILED:\n' + ''.join(traceback.format_exception(exc)), flush=True)
                    continue
                parts[(d, y)] = (out, fitted)
                (out_root / 'parts' / f'{d}_{y}.pkl').write_bytes(pickle.dumps(dict(key=key, value=(out, fitted))))
                print(f'{d} {y if y else ""}', flush=True)
            if failed:
                raise RuntimeError('Folds failed (completed folds are checkpointed): ' + '; '.join(failed))
    keys = pcfg['models'] + ['incumbent', 'mvs_ensemble']
    results = merge(parts, months, keys)
    region = cfg['primary_region']
    data = dict(created_utc=datetime.now(timezone.utc).isoformat(), config=args.config, config_contents=pcfg, protocol=__doc__.strip(),
                provenance=db.provenance(cfg, project, months, pcfg, dep, start, {m: key for m in months}, args.config),
                scoring_version=dc.SCORING_VERSION,
                phase=pcfg.get('phase', 4), pathway='B: rainfall-distribution models from the raw ensemble, pooled over the months',
                models=pcfg['models'], decision_models=pcfg.get('decision_models', pcfg['models']),
                registry={k: dict(name=dc.MODELS[k].name, estimates=dc.MODELS[k].estimates, predictors=dc.MODELS[k].predictors,
                                  fitting=dc.MODELS[k].fitting, references=dc.MODELS[k].references,
                                  outputs='CDF, quantiles, tercile probabilities') for k in pcfg['models']},
                references=dict(incumbent='MVS -> smoothed counts -> climatology blend (published probabilities)',
                                mvs_ensemble='MVS-corrected ensemble (empirical distribution)'),
                regions={k: v['label'] for k, v in cfg['regions'].items()}, primary_region=region,
                training_years=cfg['training_years'], test_years=cfg['test_years'], targets=results,
                tests=db.tests_of(results, pcfg.get('decision_models', pcfg['models']), region, months),
                comparisons=db.comparisons_of(results, pcfg.get('comparisons', []), region, months, db.external_methods(pcfg, cfg, months)),
                external_models={k: dict(file=v.format(name=Path(cfg['output_root']).name),
                                         sha256=sha256(ROOT / v.format(name=Path(cfg['output_root']).name)),
                                         scoring_version=json.loads((ROOT / v.format(name=Path(cfg['output_root']).name)).read_text(encoding='utf-8')).get('scoring_version', 1))
                                 for k, v in (pcfg.get('external_models') or {}).items()})
    save_json(out_root / 'benchmark.json', data)
    if not args.no_figures:
        db.figure(out_root, data)
        db.reliability_figure(out_root, data)
    print('Saved:', out_root)


if __name__ == '__main__':
    main(ARGS)
