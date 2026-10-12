"""Selection-aware confirmation of rainfall-amount bias-correction methods through the full probability pipeline (docs/47).

Read-only experiment. Configured by the "confirmation" block of config/bias_correction/<name>.json; any cycle, any
method of the registry (scripts/bias_methods.py).

Pipeline for one amount method (the operational one, with the amount correction swapped):
    corrected members -> tercile counts against the training CHIRPS terciles -> alpha smoothing
    -> blend with climatology, p = (1 - lambda) p_s + lambda p_clim, one lambda per target fitted by
       leave-one-year-out within the training years (local_blend.fit_weights, over the full rectangle as operationally)
Design:
    outer leave-one-year-out over the training years. For outer year y every fit (amount correction, terciles,
    climatology, lambda) uses only the other training years; lambda comes from inner leave-one-year-out within them.
    Selection-aware procedures choose a method for year y with the inner (training-only) scores:
        SEL-P: lowest inner blended RPS (probability product); SEL-A: lowest inner CRPS (amount product).
    Their outer scores therefore include the effect of choosing among the declared candidate family.
    Test years: all fits and the selection on the training years, scored on the test years (exploratory).
Scores per year (area-weighted over a region, equal years): blended RPS and RPSS, category Brier scores and skill
(below and above normal), reliability tables; ensemble CRPS of the amounts (and the fair CRPS).
Tests against the operational method: paired whole-year sign-flip, Holm across the declared family
(every method and target for the method comparisons; the targets for SEL-P, SEL-A and each sensitivity variant).
Variants (e.g. the MVS all-zero guard) run through the same pipeline but are never chosen by SEL-P / SEL-A.
Checkpoints (one per target and method) are reused only when the complete dependency fingerprint of the target
(configuration contents, masks, input files, calculation code; bias_benchmark.dependencies) is unchanged.
"""
import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def parse():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--config', default='config/bias_correction/sep_ondj.json')
    p.add_argument('--methods', nargs='+', help='subset of the declared family (default: all of it)')
    p.add_argument('--targets', nargs='+')
    p.add_argument('--workers', type=int, default=3, help='parallel targets (memory: about 1 GB each)')
    p.add_argument('--no-figures', action='store_true')
    p.add_argument('--no-resume', action='store_true', help='ignore and overwrite the checkpoints')
    return p.parse_args()


ARGS = parse() if __name__ == '__main__' else None
ROOT_DIR = Path(__file__).resolve().parents[1]
if ARGS is not None:
    os.environ.setdefault('CALIBRATION_CYCLE', json.loads((ROOT_DIR / ARGS.config).read_text(encoding='utf-8'))['cycle'])

from common import ROOT, load_config, save_json                              # noqa: E402
from bias_methods import resolve                                     # noqa: E402
from calibration_core import fit_amount, categories, labels                 # noqa: E402
from compare_calibration import smooth                                      # noqa: E402
from local_blend import fit_weights                                         # noqa: E402
from run_calibration import cell_area                                       # noqa: E402
from significance import paired_summary, holm, ALPHA                        # noqa: E402
import bias_benchmark as bb                                                 # noqa: E402


class Pipeline:
    """One amount method through the probability pipeline, with every fit cached by its excluded years."""

    def __init__(self, method, params, models, obs, train, alpha, regions=None, area=None):
        self.m, self.p = resolve(method, params)
        self.models, self.obs, self.train, self.alpha = models, obs, train, alpha
        self.regions, self.area = regions or {}, area
        self.cache = {}

    def fit_apply(self, exclude, years):
        """Fit on the training years minus `exclude`, return records for `years` (cached per (exclude, year))."""
        need = [y for y in years if (exclude, y) not in self.cache]
        if need:
            T = [z for z in self.train if z not in exclude]
            O = np.stack([self.obs[z] for z in T])
            pars = fit_amount([self.models[z] for z in T], O, np.ones(O.shape[1], bool))
            state = self.m.fit([self.models[z] for z in T], O, **self.p)
            lab = np.stack([labels(self.obs[z], pars) for z in T])
            clim = np.stack([(lab == k).mean(0) for k in range(3)], -1)
            clim[~pars['probability_eligible']] = np.nan
            for y in need:
                ens = np.asarray(self.m.apply(self.models[y], state, **self.p), float)
                ok = state['ok']
                c = categories(np.where(ok, ens, 0.), pars['q1'], pars['q2'])
                prob = np.stack([(c == k).mean(0) for k in range(3)], -1)
                prob[~(ok & pars['probability_eligible'])] = np.nan
                y_obs = self.obs[y]
                a = ok & np.isfinite(y_obs)
                e, yo, to = np.where(a, ens, 0.), np.where(a, y_obs, 0.), np.where(a, O, 0.)
                cells = dict(crps=bb.ensemble_crps(e, yo), crps_clim=bb.ensemble_crps(to, yo),
                             crps_fair=bb.fair_crps(e, yo), crps_fair_clim=bb.fair_crps(to, yo))
                amount = {}                                  # region scores only: the cache stays small
                for name, mask in self.regions.items():
                    sel = mask & a
                    w = self.area[sel] / self.area[sel].sum()
                    amount[name] = {k: float(w @ v[sel]) for k, v in cells.items()}
                self.cache[exclude, y] = dict(s=smooth(prob, len(ens), alpha=self.alpha).astype('float32'), clim=clim.astype('float32'),
                                              y=labels(y_obs, pars).astype('int8'), amount=amount)
        return [self.cache[exclude, y] for y in years]


def blend(r, lam):
    return (1 - lam) * r['s'].astype(float) + lam * r['clim'].astype(float)


def prob_scores(p, r, area, region, bins):
    """Region-weighted RPS, climatology RPS, category Brier scores and reliability accumulations of one year."""
    y = r['y']
    valid = region & (y >= 0) & np.isfinite(p).all(-1) & np.isfinite(r['clim']).all(-1)
    w = area[valid] / area[valid].sum()
    t = np.eye(3)[y[valid]]
    pv, cv = p[valid], r['clim'][valid].astype(float)
    rps = lambda q: np.sum((np.cumsum(q, -1)[:, :2] - np.cumsum(t, -1)[:, :2]) ** 2, -1)
    out = dict(rps=float(w @ rps(pv)), rps_clim=float(w @ rps(cv)))
    rel = {}
    for k, name in [(0, 'below'), (2, 'above')]:
        out[f'brier_{name}'] = float(w @ (pv[:, k] - t[:, k]) ** 2)
        out[f'brier_{name}_clim'] = float(w @ (cv[:, k] - t[:, k]) ** 2)
        b = np.minimum((pv[:, k] * bins).astype(int), bins - 1)
        rel[name] = np.stack([np.bincount(b, w, bins), np.bincount(b, w * pv[:, k], bins), np.bincount(b, w * t[:, k], bins)])
    return out, rel


def run_target(config_path, target, methods, family, key, resume=True):
    cfg = json.loads((ROOT / config_path).read_text(encoding='utf-8'))
    conf = cfg['confirmation']
    project = load_config(cfg['project_config'])
    rng = lambda a, b: list(range(a, b + 1))
    train, test = rng(*cfg['training_years']), rng(*cfg['test_years'])
    alpha, bins = cfg['smoothing_alpha'], conf.get('reliability_bins', 10)
    tag, models, obs, lat, lon = bb.load_target(cfg, project, target)
    area = cell_area(lat, lon)
    regions = {k: bb.load_mask(v, lat, lon) for k, v in cfg['regions'].items()}
    sel_name = conf.get('selection_region', cfg['primary_region'])
    sel_region = regions[sel_name]
    out = dict(tag=tag, methods={}, selection={})
    inner = {}
    parts = ROOT / conf['output_root'] / 'parts'
    parts.mkdir(parents=True, exist_ok=True)
    for method in methods:
        part = parts / f'{target}__{method}.json'
        if resume and part.is_file():                        # checkpoint of a completed (target, method), same dependencies
            saved = json.loads(part.read_text(encoding='utf-8'))
            if saved.get('key') == key:
                out['methods'][method] = saved['result']
                inner[method] = dict(training={int(y): v for y, v in saved['inner']['training'].items()}, test=saved['inner']['test'])
                print(f'{target:4s} {method:9s} loaded from checkpoint', flush=True)
                continue
        pipe = Pipeline(method, cfg['methods'].get(method, {}), models, obs, train, alpha, regions, area)
        res = {d: {r: dict(per_year={}, reliability={}) for r in regions} for d in ('training', 'test')}
        inner[method] = dict(training={}, test={})
        lambdas = []
        for y in train:                                      # outer leave-one-year-out
            others = [z for z in train if z != y]
            recs = [pipe.fit_apply(frozenset((y, z)), [y, z])[1] for z in others]   # one fit per pair, applied to both years
            lam = fit_weights(recs, area)['shared_lambda']
            lambdas.append(lam)
            inner[method]['training'][y] = dict(
                rps=float(np.mean([prob_scores(blend(r, lam), r, area, sel_region, bins)[0]['rps'] for r in recs])),
                crps=float(np.mean([r['amount'][sel_name]['crps'] for r in recs])))
            r = pipe.fit_apply(frozenset((y,)), [y])[0]
            score_into(res['training'], y, blend(r, lam), r, area, regions, bins)
        oof = [pipe.fit_apply(frozenset((z,)), [z])[0] for z in train]      # test years: everything fitted on the training years
        lam_test = fit_weights(oof, area)['shared_lambda']
        inner[method]['test'] = dict(
            rps=float(np.mean([prob_scores(blend(r, lam_test), r, area, sel_region, bins)[0]['rps'] for r in oof])),
            crps=float(np.mean([r['amount'][sel_name]['crps'] for r in oof])))
        for y, r in zip(test, pipe.fit_apply(frozenset(), test)):
            score_into(res['test'], y, blend(r, lam_test), r, area, regions, bins)
        out['methods'][method] = finish(res, regions, dict(training_mean=float(np.mean(lambdas)), training=lambdas, test=lam_test))
        pipe.cache.clear()
        save_json(part, dict(key=key, result=out['methods'][method], inner=inner[method]))
        tr = out['methods'][method]['training'][cfg['primary_region']]
        print(f"{target:4s} {method:9s} blended RPSS {tr['rpss']:+.4f}  BSS below {tr['bss_below']:+.4f} above {tr['bss_above']:+.4f}  "
              f"CRPSS {tr['crpss']:+.4f}  lambda {np.mean(lambdas):.2f}", flush=True)
    # Selection-aware procedures: the method is chosen for each outer year from training-only scores
    for name, key in [('SEL-P', 'rps'), ('SEL-A', 'crps')]:
        chosen = {y: min(family, key=lambda m: inner[m]['training'][y][key]) for y in train}      # declared family only
        chosen_test = min(family, key=lambda m: inner[m]['test'][key])
        sel = {}
        for design, years, pick in [('training', train, chosen), ('test', test, {y: chosen_test for y in test})]:
            sel[design] = {}
            for r in regions:
                src = lambda y: out['methods'][pick[y]][design][r]['per_year']
                per_year = {k: [src(y)[k][list(out['methods'][pick[y]][design][r]['years']).index(y)] for y in years]
                            for k in out['methods'][methods[0]][design][r]['per_year']}
                sel[design][r] = summary_from(per_year, years)
        out['selection'][name] = dict(criterion=f'inner {key.upper()} (training years only)', chosen_training=chosen,
                                      chosen_test=chosen_test, frequency={m: sum(v == m for v in chosen.values()) for m in family},
                                      **sel)
    return target, out


def score_into(res, y, p, r, area, regions, bins):
    for name, mask in regions.items():
        s, rel = prob_scores(p, r, area, mask, bins)
        s.update(r['amount'][name])
        d = res[name]
        d.setdefault('years', []).append(y)
        for k, v in s.items():
            d['per_year'].setdefault(k, []).append(v)
        for k, v in rel.items():
            d['reliability'][k] = d['reliability'].get(k, 0) + v


def summary_from(per_year, years):
    m = lambda k: float(np.mean(per_year[k]))
    return dict(years=list(years), per_year=per_year, rps=m('rps'), rpss=1 - m('rps') / m('rps_clim'),
                brier_below=m('brier_below'), bss_below=1 - m('brier_below') / m('brier_below_clim'),
                brier_above=m('brier_above'), bss_above=1 - m('brier_above') / m('brier_above_clim'),
                crps=m('crps'), crpss=1 - m('crps') / m('crps_clim'),
                crps_fair=m('crps_fair'), crpss_fair=1 - m('crps_fair') / m('crps_fair_clim'))


def finish(res, regions, lam):
    out = dict(lambda_=lam)
    for design in res:
        out[design] = {}
        for r in regions:
            d = res[design][r]
            s = summary_from(d['per_year'], d['years'])
            n = len(d['years'])
            s['reliability'] = {k: dict(weight=(v[0] / n).round(6).tolist(),
                                        mean_forecast=np.divide(v[1], v[0], out=np.full(len(v[0]), np.nan), where=v[0] > 0).round(4).tolist(),
                                        observed_frequency=np.divide(v[2], v[0], out=np.full(len(v[0]), np.nan), where=v[0] > 0).round(4).tolist())
                                for k, v in d['reliability'].items()}
            out[design][r] = s
    return out


def comparisons(results, methods, family, ref, region, targets):
    """Methods vs reference (Holm across every declared method and target), each variant vs reference (Holm across the
    targets), and SEL-P / SEL-A vs reference (Holm across the targets; the search is inside the procedure)."""
    out = {}
    for score in ('rps', 'brier_below', 'brier_above', 'crps'):
        stats = {}
        for m in methods:
            if m == ref:
                continue
            for t in targets:
                a, b = results[t]['methods'][m], results[t]['methods'][ref]
                stats[m, t] = {d: paired_summary(a[d][region]['per_year'][score], b[d][region]['per_year'][score]) for d in ('training', 'test')}
        adj = holm({f'{m}|{t}': s['training']['p_improvement'] for (m, t), s in stats.items() if m in family})
        for m in {m for m, _ in stats if m not in family}:
            adj.update({f'{m}|{t}': v for t, v in holm({t: stats[m, t]['training']['p_improvement'] for t in targets}).items()})
        for (m, t), s in stats.items():
            p_adj = adj[f'{m}|{t}']
            s['decision'] = dict(holm_p_family=float(p_adj), family='declared methods x targets' if m in family else 'targets (variant)',
                                 no_harm=s['test']['mean_difference'] <= 0,
                                 confirmed=bool(s['training']['mean_difference'] < 0 and p_adj < ALPHA and s['test']['mean_difference'] <= 0))
            out.setdefault(m, {}).setdefault(score, {})[t] = s
    for name, score in [('SEL-P', 'rps'), ('SEL-A', 'crps')]:
        stats = {}
        for t in targets:
            a, b = results[t]['selection'][name], results[t]['methods'][ref]
            stats[t] = {d: paired_summary(a[d][region]['per_year'][score], b[d][region]['per_year'][score]) for d in ('training', 'test')}
        adj = holm({t: s['training']['p_improvement'] for t, s in stats.items()})
        for t, s in stats.items():
            s['decision'] = dict(holm_p=float(adj[t]), no_harm=s['test']['mean_difference'] <= 0,
                                 confirmed=bool(s['training']['mean_difference'] < 0 and adj[t] < ALPHA and s['test']['mean_difference'] <= 0))
        out[name] = {score: stats}
    return out


def main(args):
    cfg = json.loads((ROOT / args.config).read_text(encoding='utf-8'))
    conf = cfg['confirmation']
    project = load_config(cfg['project_config'])
    family = args.methods or conf['methods']
    ref = cfg['reference_method']
    if ref not in family:
        family = [ref] + family
    variants = [v for v in conf.get('variants', []) if not args.methods]
    methods = family + variants
    targets = args.targets or cfg['targets']
    dep = bb.dependencies(cfg, project, targets, args.config)          # one fingerprint: checkpoints and provenance
    keys = {t: bb.dependency_key(dep, t) for t in targets}
    results = {}
    workers = args.workers or min(len(targets), max(1, (os.cpu_count() or 2) - 1))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for job in [pool.submit(run_target, args.config, t, methods, family, keys[t], not args.no_resume) for t in targets]:
            t, res = job.result()
            results[t] = res
    tests = comparisons(results, methods, family, ref, cfg['primary_region'], targets)
    out_root = ROOT / conf['output_root']
    data = dict(created_utc=datetime.now(timezone.utc).isoformat(), config=args.config, protocol=__doc__.strip(),
                provenance=bb.provenance(cfg, project, targets, args.config, dep) | dict(checkpoint_keys=keys),
                methods=methods, family=family, variants=variants, reference=ref, targets=results, tests=tests)
    save_json(out_root / 'confirmation.json', data)
    if not args.no_figures:
        import bias_benchmark_figures as figs
        figs.confirmation_figures(out_root, data, cfg)
    print('Saved:', out_root)


if __name__ == '__main__':
    main(ARGS)
