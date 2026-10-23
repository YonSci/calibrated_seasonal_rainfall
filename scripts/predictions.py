"""Saved per-fold predictions of the distribution benchmarks (docs/54, 3g): load them, check they belong to the accepted run,
and score them with the current scoring rule — so a scoring change needs no refit, and models can be combined (stacking).

dist_benchmark.py and pooled_benchmark.py write <output_root>/predictions/<target>.pkl when their configuration has
"save_predictions": true: {predictions: {model: {design: {year: Distribution}}}, context: {design: {year: fold statistics and
the observation}}, area_e, regions, scoring_version}.

  python scripts/predictions.py rescore --family neural --cycle may_jjas      # CRPS etc. of every saved model, current rule
"""
import argparse
import hashlib
import json
import pickle
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
OUT = ROOT / 'outputs/probability_calibration'


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def folder(family, cycle):
    return OUT / cycle / family


def load(family, cycle, target, accepted_only=True):
    """The saved predictions of a family, cycle and target. With accepted_only, the benchmark next to them must be the accepted
    one (scripts/accept_results.py), so the predictions and the published scores come from the same run."""
    import accept_results as ar
    f = folder(family, cycle) / 'predictions' / f'{target}.pkl'
    if not f.is_file():
        raise FileNotFoundError(f'{f}: no saved predictions (the benchmark must run with "save_predictions": true)')
    if accepted_only and family in ar.gated(ar.load()):
        e = ar.load()['accepted'].get(f'{family}/{cycle}')
        bench = folder(family, cycle) / 'benchmark.json'
        if not e or not bench.is_file() or sha256(bench) != e['sha256']:
            raise ValueError(f'{family}/{cycle}: the predictions next to {bench} are not those of the accepted run')
    saved = pickle.loads(f.read_bytes())
    saved['file'] = (f.relative_to(ROOT) if f.is_relative_to(ROOT) else f).as_posix()
    saved['file_sha256'] = sha256(f)
    return saved


def score(dists, context, area_e, regions, years=None):
    """Score records (dist_benchmark.score_year format) of one model's saved distributions: {design: {region: {years, per_year}}}."""
    import dist_benchmark as db
    store = {'training': {}, 'test': {}}
    for design in ('training', 'test'):
        for y in sorted(dists.get(design, {})):
            if years is not None and y not in years:
                continue
            d, st = dists[design][y], context[design][y]
            y_obs = np.asarray(st['y_obs'], float)
            stats = {k: np.asarray(v, float) if k not in ('valid', 'prob_ok') else v for k, v in st.items()}
            p = d.terciles(stats['q1'], stats['q2'])
            q = {tau: d.quantile(np.full(len(y_obs), tau)) for tau in db.LEVELS}
            db.score_year(y, p, d.crps(np.nan_to_num(y_obs)), q, stats, y_obs, np.asarray(area_e, float), regions, store[design])
    return store


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('rescore')
    r.add_argument('--family', required=True)
    r.add_argument('--cycle', required=True)
    r.add_argument('--targets', nargs='+')
    a = ap.parse_args()
    import dist_benchmark as db
    import dist_calibration as dc
    bench = json.loads((folder(a.family, a.cycle) / 'benchmark.json').read_text(encoding='utf-8'))
    out = dict(family=a.family, cycle=a.cycle, scoring_version=dc.SCORING_VERSION, of_scoring_version=bench.get('scoring_version', 1),
               targets={})
    for t in a.targets or list(bench['targets']):
        saved = load(a.family, a.cycle, t)
        store = {k: score(v, saved['context'], saved['area_e'], saved['regions']) for k, v in saved['predictions'].items()}
        out['targets'][t] = db.summarise(store)
        prim = bench['primary_region']
        for k in store:
            s = out['targets'][t][k]['training'][prim]
            print(f"{t} {k}: CRPSS {s.get('crpss', float('nan')):+.4f} (was {bench['targets'][t]['methods'][k]['training'][prim].get('crpss', float('nan')):+.4f})")
    f = folder(a.family, a.cycle) / f'rescored_v{dc.SCORING_VERSION}.json'
    f.write_text(json.dumps(out, indent=1) + '\n', encoding='utf-8')
    print('Saved:', f)


if __name__ == '__main__':
    main()
