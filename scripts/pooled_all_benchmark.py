"""The DRN pooled over the months of all four cycles (docs/54, 3g): one network for the 16 month targets of the January- and
February-initialized FMAM, May-initialized JJAS and September-initialized ONDJ cycles, with the month's position and the cycle
as inputs (one-hot), against the published pipeline of each cycle.

Same design as scripts/pooled_benchmark.py, whose sample building and per-month scoring it reuses: outer leave-one-year-out
over the training years (the left-out year is removed from every cycle at once; ONDJ years are season years, as everywhere),
then one fit on all training years for the test years. Each fold fits one network on the samples of all 16 months; every
month of every cycle is then forecast and scored with that cycle's published references computed in the same fold. The
results are written per cycle (<cycle>/neural_all/benchmark.json, the same format as the pooled benchmark), so the method
selection, the summary and the site treat them as one more family per cycle (tests: the cycle's four months).

  python scripts/pooled_all_benchmark.py --config config/probability_calibration/all_neural_pooled_all.json --workers 6
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
    p.add_argument('--config', default='config/probability_calibration/all_neural_pooled_all.json')
    p.add_argument('--workers', type=int, default=2)
    p.add_argument('--no-resume', action='store_true')
    p.add_argument('--no-figures', action='store_true')
    return p.parse_args()


ARGS = parse() if __name__ == '__main__' else None

from common import ROOT, load_config, save_json                          # noqa: E402
import bias_benchmark as bb                                             # noqa: E402
import dist_calibration as dc                                           # noqa: E402
import dist_benchmark as db                                             # noqa: E402
import pooled_benchmark as pb                                           # noqa: E402

CODE = ['scripts/pooled_all_benchmark.py', *pb.CODE]
_ALL = {}


def read(p):
    return json.loads((ROOT / p).read_text(encoding='utf-8'))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def contexts(config_path):
    """The four cycles' contexts (pooled_benchmark.context), with this run's models and prediction saving."""
    if config_path in _ALL:
        return _ALL[config_path]
    acfg = read(config_path)
    ctxs = []
    for p in acfg['cycles']:
        ctx = pb.context(p)
        ctx['pcfg'] = dict(ctx['pcfg'], models=acfg['models'], save_predictions=bool(acfg.get('save_predictions')))
        ctx['name'] = Path(ctx['cfg']['output_root']).name
        ctxs.append(ctx)
    if any(c['train'] != ctxs[0]['train'] or c['test'] != ctxs[0]['test'] for c in ctxs):
        raise ValueError('the cycles must share the training and test years')
    _ALL[config_path] = (acfg, ctxs)
    return _ALL[config_path]


def cycle_onehot(ci):
    return {f'cycle_{j + 1}': float(j == ci) for j in range(4)}


def run_design(config_path, design, y):
    """One fold: one network on the samples of the 16 months of the four cycles, every month of every cycle scored."""
    acfg, ctxs = contexts(config_path)
    train = ctxs[0]['train']
    T = [z for z in train if z != y] if design == 'training' else train
    parts, stats = [], []
    for ci, ctx in enumerate(ctxs):
        S, st = pb.pooled_samples(ctx, T, extra=cycle_onehot(ci))
        parts.append(S)
        stats.append(st)
    keys = [k for k in parts[0] if k != 'n_years' and all(k in S for S in parts)]
    S = {k: np.concatenate([np.asarray(P[k]) for P in parts]) for k in keys}
    S['n_years'] = len(T)
    models = {}
    for k in acfg['models']:
        m = dc.MODELS[k]
        models[k] = m.fit(S, **{**m.defaults, **acfg.get('parameters', {}).get(k, {})})
    out = {ctx['name']: pb.score_cycle(ctx, models, stats[ci], T, design, y, extra=cycle_onehot(ci)) for ci, ctx in enumerate(ctxs)}
    fitted = {k: {kk: vv for kk, vv in v.items() if kk in ('hidden', 'decay', 'steps', 'validation_crps', 'training')}
              for k, v in models.items()} if design == 'test' else None
    return design, y, out, fitted


def main(args):
    acfg, ctxs = contexts(args.config)
    root = ROOT / acfg['output_root']
    (root / 'parts').mkdir(parents=True, exist_ok=True)
    deps = {c['name']: bb.dependencies(c['cfg'], load_config(c['cfg']['project_config']), c['months'], c['pcfg']['benchmark_config'])
            for c in ctxs}
    key = hashlib.sha256(('|'.join(bb.dependency_key(deps[n]) for n in sorted(deps)) + '|' +
                          ''.join(sha256(ROOT / f) for f in CODE + [args.config, *acfg['cycles']])).encode()).hexdigest()
    start = dict(commit=bb.git('rev-parse', 'HEAD'), uncommitted_changes=bool(bb.git('status', '--porcelain', '--', *CODE, args.config, *acfg['cycles'])),
                 code_sha256={f: sha256(ROOT / f) for f in CODE + [args.config]}, utc=datetime.now(timezone.utc).isoformat())
    train = ctxs[0]['train']
    jobs = [('training', y) for y in train] + [('test', None)]
    parts = {}
    for d, y in jobs:
        f = root / 'parts' / f'{d}_{y}.pkl'
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
                (root / 'parts' / f'{d}_{y}.pkl').write_bytes(pickle.dumps(dict(key=key, value=(out, fitted))))
                print(f'{d} {y if y else ""}', flush=True)
            if failed:
                raise RuntimeError('Folds failed (completed folds are checkpointed): ' + '; '.join(failed))
    keys = acfg['models'] + ['incumbent', 'mvs_ensemble']
    for i, ctx in enumerate(ctxs):                           # one result file per cycle
        name, cfg = ctx['name'], ctx['cfg']
        project = load_config(cfg['project_config'])
        months = ctx['months']
        results = pb.merge({k: (out[name], fitted) for k, (out, fitted) in parts.items()}, months, keys)
        out_root = ROOT / acfg['cycle_output'].format(name=name)
        out_root.mkdir(parents=True, exist_ok=True)
        if acfg.get('save_predictions'):
            for t in months:
                saved = results[t].pop('_saved')
                saved.update(area_e=ctx['t'][t]['area_e'].astype(np.float32), regions=ctx['t'][t]['regions'])
                db.save_predictions(out_root, t, saved)
        region = cfg['primary_region']
        ext = {k: v for k, v in (acfg.get('external_models') or {}).items()}
        pcfg = dict(acfg, external_models=ext)
        data = dict(created_utc=datetime.now(timezone.utc).isoformat(), config=args.config, config_contents=acfg, protocol=__doc__.strip(),
                    provenance=db.provenance(cfg, project, months, pcfg, deps[name], start, {m: key for m in months}, args.config),
                    scoring_version=dc.SCORING_VERSION, phase=acfg.get('phase', 4),
                    pathway='B: rainfall-distribution models from the raw ensemble, pooled over the months of all four cycles',
                    models=acfg['models'], decision_models=acfg.get('decision_models', acfg['models']),
                    registry={k: dict(name=dc.MODELS[k].name, estimates=dc.MODELS[k].estimates, predictors=dc.MODELS[k].predictors,
                                      fitting=dc.MODELS[k].fitting, references=dc.MODELS[k].references,
                                      outputs='CDF, quantiles, tercile probabilities') for k in acfg['models']},
                    references=dict(incumbent='MVS -> smoothed counts -> climatology blend (published probabilities)',
                                    mvs_ensemble='MVS-corrected ensemble (empirical distribution)'),
                    regions={k: v['label'] for k, v in cfg['regions'].items()}, primary_region=region,
                    training_years=cfg['training_years'], test_years=cfg['test_years'], targets=results,
                    tests=db.tests_of(results, acfg.get('decision_models', acfg['models']), region, months),
                    comparisons=db.comparisons_of(results, acfg.get('comparisons', []), region, months, db.external_methods(pcfg, cfg, months)),
                    external_models={k: dict(file=v.format(name=name), sha256=sha256(ROOT / v.format(name=name)),
                                             scoring_version=read(v.format(name=name)).get('scoring_version', 1)) for k, v in ext.items()},
                    cycle_position=i + 1)
        save_json(out_root / 'benchmark.json', data)
        if not args.no_figures:
            db.figure(out_root, data)
            db.reliability_figure(out_root, data)
        print('Saved:', out_root)


if __name__ == '__main__':
    main(ARGS)
