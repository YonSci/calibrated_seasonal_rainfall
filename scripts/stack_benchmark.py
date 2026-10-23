"""Stacking (docs/54, 3g): the equal-weight linear pool of three rainfall-distribution models, against the published pipeline.

For each target and fold the members' saved predictions (scripts/predictions.py) are combined into one distribution,
F = (F_EMOS + F_QR + F_DRN) / 3, and scored exactly as the members were (dist_benchmark.score_year, scoring version 2) with the
fold's own statistics. Months use the DRN pooled over the months of the cycle; the season, which is not pooled, the per-target
DRN. No fitting: the members were fitted in their own benchmarks on the same folds (the predictions must come from the
accepted runs). Equal weights: estimated weights would need a further inner split of very few years.

Tests: the pool against the published references (the per-year scores of the member benchmark, same folds), Holm across the
cycle's five targets (the method selection: Benjamini-Hochberg); comparisons: the pool against each member.

  python scripts/stack_benchmark.py --config config/probability_calibration/may_jjas_stacking.json
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


def parse():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--config', required=True)
    p.add_argument('--no-figures', action='store_true')
    return p.parse_args()


def read(p):
    return json.loads((ROOT / p).read_text(encoding='utf-8'))


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main(args):
    import accept_results as ar
    import bias_benchmark as bb
    import dist_benchmark as db
    import dist_calibration as dc
    import predictions as pr
    from common import load_config, save_json
    scfg = read(args.config)
    cfg = read(scfg['benchmark_config'])
    project = load_config(cfg['project_config'])
    cycle = Path(cfg['output_root']).name
    season = project['season']['name']
    region = cfg['primary_region']
    start = dict(commit=bb.git('rev-parse', 'HEAD'),
                 uncommitted_changes=bool(bb.git('status', '--porcelain', '--', 'scripts/stack_benchmark.py', 'scripts/predictions.py',
                                                 'scripts/dist_calibration.py', 'scripts/dist_benchmark.py', args.config)))
    results, used = {}, {}
    for t in cfg['targets']:
        members = scfg['members']['season' if t == season else 'months']
        saved = {(fam, m): pr.load(fam, cycle, t) for fam, m in members}
        ref_fam = members[0][0]
        ref_bench = ar.read_accepted(ref_fam, cycle)
        ctx = saved[tuple(members[0])]['context']
        for (fam, m), s in saved.items():                    # the members must share the folds and the observations
            for design in ('training', 'test'):
                if sorted(s['context'][design]) != sorted(ctx[design]):
                    raise ValueError(f'{fam}/{m} {t}: different {design} years')
                for y in ctx[design]:
                    if not np.allclose(s['context'][design][y]['y_obs'], ctx[design][y]['y_obs'], equal_nan=True):
                        raise ValueError(f'{fam}/{m} {t} {y}: different observations')
        area_e, regions = saved[tuple(members[0])]['area_e'], saved[tuple(members[0])]['regions']
        pool = {design: {y: dc.Pool([saved[(fam, m)]['predictions'][m][design][y] for fam, m in members]) for y in ctx[design]}
                for design in ('training', 'test')}
        store = {'stack': pr.score(pool, ctx, area_e, regions)}
        for fam, m in members:                               # the members, rescored the same way (comparisons)
            store[m] = pr.score(saved[(fam, m)]['predictions'][m], ctx, area_e, regions)
        methods = db.summarise(store)
        for k in ('incumbent', 'mvs_ensemble'):              # the published references of the member benchmark, same folds
            methods[k] = ref_bench['targets'][t]['methods'][k]
        results[t] = dict(methods=methods)
        used[t] = {f'{fam}/{m}': dict(file=s['file'], sha256=s['file_sha256']) for (fam, m), s in saved.items()}
        crpss = lambda k: methods[k]['training'][region].get('crpss', float('nan'))          # noqa: E731
        print(f"{t}: stack CRPSS {crpss('stack'):+.4f} (members " + ', '.join(f'{m} {crpss(m):+.4f}' for _, m in members) + ')', flush=True)
    names = sorted({m for t in cfg['targets'] for _, m in scfg['members']['season' if t == season else 'months']})
    pairs = [('stack', m) for m in names]
    out_root = ROOT / scfg['output_root']
    out_root.mkdir(parents=True, exist_ok=True)
    targets = cfg['targets']
    comparisons = {}
    for k, other in pairs:                                   # only the targets where the member is part of the pool
        ts = [t for t in targets if other in results[t]['methods']]
        for key, val in db.comparisons_of(results, [(k, other)], region, ts).items():
            comparisons[key] = val
    data = dict(created_utc=datetime.now(timezone.utc).isoformat(), config=args.config, config_contents=scfg, protocol=__doc__.strip(),
                provenance=dict(commit=start['commit'], uncommitted_changes=start['uncommitted_changes'], member_predictions=used,
                                code_sha256={f: sha256(ROOT / f) for f in ('scripts/stack_benchmark.py', 'scripts/predictions.py',
                                                                            'scripts/dist_calibration.py', 'scripts/dist_benchmark.py')}),
                scoring_version=dc.SCORING_VERSION, phase=scfg.get('phase', 4),
                pathway='B: rainfall-distribution models from the raw ensemble, combined (equal-weight linear pool)',
                models=['stack'] + names, decision_models=['stack'],
                registry=dict(stack=dict(name='Equal-weight pool of EMOS, quantile regression and the DRN',
                                         estimates='rainfall distribution (equal-weight linear pool)',
                                         predictors='those of the members', fitting='none: the members fitted in their own benchmarks',
                                         references=['Gneiting & Ranjan 2013'], outputs='CDF, quantiles, tercile probabilities'),
                              **{m: dict(name=dc.MODELS[m].name, estimates=dc.MODELS[m].estimates, predictors=dc.MODELS[m].predictors,
                                         fitting=dc.MODELS[m].fitting, references=dc.MODELS[m].references,
                                         outputs='CDF, quantiles, tercile probabilities') for m in names}),
                references=dict(incumbent='MVS -> smoothed counts -> climatology blend (published probabilities)',
                                mvs_ensemble='MVS-corrected ensemble (empirical distribution)'),
                regions={k: v['label'] for k, v in cfg['regions'].items()}, primary_region=region,
                training_years=cfg['training_years'], test_years=cfg['test_years'], targets=results,
                tests=db.tests_of(results, ['stack'], region, targets), comparisons=comparisons,
                config_members=scfg['members'])
    save_json(out_root / 'benchmark.json', data)
    if not args.no_figures:
        db.figure(out_root, data)
    print('Saved:', out_root)


if __name__ == '__main__':
    main(parse())
