"""Phase 1 probability-calibration benchmark (docs/48): which tercile-probability method gives the best published probabilities?

Pathway A: the amount correction is fixed (the operational MVS, configurable); the probability-calibration stage is replaced.
For each target, nested year-based validation over the training years:
  outer leave-one-year-out: for the left-out year y every fit uses only the other training years — the amount correction and
  terciles (each inner year z from a fit without y and z), and every calibrator's parameters, fitted on the inner out-of-fold
  records of the other years; the calibrated probabilities of year y are then scored.
  test years: fits on all training years (calibrators on their leave-one-year-out records), scored on the test years
  (exploratory).
  SEL: a calibrator is chosen for each outer year by inner cross-validation of the calibrators (blocks of consecutive
  years, 'selection_folds') on the inner records only (lowest inner RPS), so its score includes the choice among the methods.
Scores (per year, area-weighted over a region; equal years): RPS/RPSS (primary), category Brier scores and skill, log loss
and its skill against climatology, reliability tables. Tests: each method against the incumbent climatology blend, paired
whole-year sign-flip, Holm across every method and target; SEL against the incumbent, Holm across the targets; no harm over
the test years.

  python scripts/prob_benchmark.py --config config/probability_calibration/sep_ondj.json
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
    p.add_argument('--config', default='config/probability_calibration/sep_ondj.json')
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
from calibration_core import fit_amount, categories, labels             # noqa: E402
from compare_calibration import smooth                                  # noqa: E402
from run_calibration import cell_area                                   # noqa: E402
from significance import paired_summary, holm, ALPHA                    # noqa: E402
from bias_methods import resolve                                        # noqa: E402
import bias_benchmark as bb                                             # noqa: E402
import prob_calibration as pc                                           # noqa: E402

CODE = ['scripts/prob_benchmark.py', 'scripts/prob_calibration.py']


def read(p):
    return json.loads((ROOT / p).read_text(encoding='utf-8'))


class Records:
    """Records of the fixed amount correction, cached by the years excluded from its fit."""

    def __init__(self, method, params, models, obs, train, alpha):
        self.m, self.p = resolve(method, params)
        self.models, self.obs, self.train, self.alpha = models, obs, train, alpha
        self.cache = {}

    def get(self, exclude, years):
        need = [y for y in years if (exclude, y) not in self.cache]
        if need:
            T = [z for z in self.train if z not in exclude]
            O = np.stack([self.obs[z] for z in T])
            pars = fit_amount([self.models[z] for z in T], O, np.ones(O.shape[1], bool))
            state = self.m.fit([self.models[z] for z in T], O, **self.p)
            lab = np.stack([labels(self.obs[z], pars) for z in T])
            clim = np.stack([(lab == k).mean(0) for k in range(3)], -1)
            elig = state['ok'] & pars['probability_eligible']
            clim[~elig] = np.nan
            mu, sd = O.mean(0), O.std(0)
            for y in need:
                ens = np.asarray(self.m.apply(self.models[y], state, **self.p), float)
                c = categories(np.where(state['ok'], ens, 0.), pars['q1'], pars['q2'])
                prob = np.stack([(c == k).mean(0) for k in range(3)], -1)
                prob[~elig] = np.nan
                with np.errstate(divide='ignore', invalid='ignore'):
                    zmean = np.where(elig & (sd > 0), (ens.mean(0) - mu) / sd, np.nan)
                    lspread = np.where(elig & (sd > 0) & (ens.std(0) > 0), np.log(ens.std(0) / sd), np.nan)
                self.cache[exclude, y] = dict(s=smooth(prob, len(ens), alpha=self.alpha).astype('float32'),
                                              clim=clim.astype('float32'), y=labels(self.obs[y], pars).astype('int8'),
                                              zmean=zmean.astype('float32'), lspread=lspread.astype('float32'))
        return [self.cache[exclude, y] for y in years]


def scores(p, r, area, mask, bins=10):
    from bias_confirmation import prob_scores
    s, rel = prob_scores(p, r, area, mask, bins)
    valid = mask & (r['y'] >= 0) & np.isfinite(p).all(-1) & np.isfinite(r['clim']).all(-1)
    w = area[valid] / area[valid].sum()
    idx = np.arange(valid.sum())
    yv = r['y'][valid]
    s['log_loss'] = float(-w @ np.log(np.maximum(p[valid][idx, yv], 1e-12)))
    s['log_loss_clim'] = float(-w @ np.log(np.maximum(np.asarray(r['clim'], float)[valid][idx, yv], 1e-12)))
    return s, rel


def inner_cv_rps(key, recs, area, mask, params, folds=6):
    """Cross-validated RPS of a calibrator on the given records only (blocks of consecutive years), for the selection."""
    vals = []
    for block in np.array_split(np.arange(len(recs)), min(folds, len(recs))):
        f = pc.fit(key, [r for i, r in enumerate(recs) if i not in set(block)], area, params)
        vals += [scores(pc.predict(f, recs[i]), recs[i], area, mask)[0]['rps'] for i in block]
    return float(np.mean(vals))


def accumulate(store, y, p, r, area, regions):
    for name, mask in regions.items():
        s, rel = scores(p, r, area, mask)
        d = store.setdefault(name, dict(years=[], per_year={}, reliability={}))
        d['years'].append(y)
        for k, v in s.items():
            d['per_year'].setdefault(k, []).append(v)
        for k, v in rel.items():
            d['reliability'][k] = d['reliability'].get(k, 0) + v


def summarise(d):
    m = lambda k: float(np.mean(d['per_year'][k]))
    n = len(d['years'])
    out = dict(years=d['years'], per_year=d['per_year'], rps=m('rps'), rpss=1 - m('rps') / m('rps_clim'),
               bss_below=1 - m('brier_below') / m('brier_below_clim'), bss_above=1 - m('brier_above') / m('brier_above_clim'),
               log_loss=m('log_loss'), log_loss_skill=1 - m('log_loss') / m('log_loss_clim'))
    out['reliability'] = {k: dict(weight=(v[0] / n).round(6).tolist(),
                                  mean_forecast=np.divide(v[1], v[0], out=np.full(len(v[0]), np.nan), where=v[0] > 0).round(4).tolist(),
                                  observed_frequency=np.divide(v[2], v[0], out=np.full(len(v[0]), np.nan), where=v[0] > 0).round(4).tolist())
                          for k, v in d['reliability'].items()}
    return out


def run_target(config_path, target):
    pcfg = read(config_path)
    cfg = read(pcfg['benchmark_config'])
    project = load_config(cfg['project_config'])
    rng = lambda a, b: list(range(a, b + 1))
    train, test = rng(*cfg['training_years']), rng(*cfg['test_years'])
    tag, models, obs, lat, lon = bb.load_target(cfg, project, target)
    area = cell_area(lat, lon)
    regions = {k: bb.load_mask(v, lat, lon) for k, v in cfg['regions'].items()}
    sel_mask = regions[pcfg.get('selection_region', cfg['primary_region'])]
    methods = pcfg['methods']
    params = pcfg.get('parameters', {})
    rec = Records(pcfg['amount_method'], cfg['methods'].get(pcfg['amount_method'], {}), models, obs, train, cfg['smoothing_alpha'])
    store = {m: {'training': {}, 'test': {}} for m in methods + (['SEL'] if pcfg.get('selection') else [])}
    fitted_info = {m: dict(fallbacks=0) for m in methods}
    chosen = {}
    for y in train:                                          # outer leave-one-year-out
        inner = [rec.get(frozenset((y, z)), [y, z])[1] for z in train if z != y]
        outer = rec.get(frozenset((y,)), [y])[0]
        preds = {}
        for m in methods:
            f = pc.fit(m, inner, area, params.get(m))
            fitted_info[m]['fallbacks'] += f['fallback'] is not None
            preds[m] = pc.predict(f, outer)
            accumulate(store[m]['training'], y, preds[m], outer, area, regions)
        if pcfg.get('selection'):
            cv = {m: inner_cv_rps(m, inner, area, sel_mask, params.get(m), pcfg.get('selection_folds', 6)) for m in methods}
            chosen[y] = min(cv, key=cv.get)
            accumulate(store['SEL']['training'], y, preds[chosen[y]], outer, area, regions)
        print(f'{target} {y}' + (f' SEL {chosen[y]}' if chosen else ''), flush=True)
    oof = [rec.get(frozenset((z,)), [z])[0] for z in train]  # test years: calibrators fitted on all training years
    tests = rec.get(frozenset(), test)
    test_fits = {m: pc.fit(m, oof, area, params.get(m)) for m in methods}
    chosen_test = None
    if pcfg.get('selection'):
        cv = {m: inner_cv_rps(m, oof, area, sel_mask, params.get(m), pcfg.get('selection_folds', 6)) for m in methods}
        chosen_test = min(cv, key=cv.get)
    for y, r in zip(test, tests):
        for m in methods:
            p = pc.predict(test_fits[m], r)
            accumulate(store[m]['test'], y, p, r, area, regions)
            if m == chosen_test:
                accumulate(store['SEL']['test'], y, p, r, area, regions)
    result = dict(tag=tag, methods={}, fitted={})
    for m, d in store.items():
        result['methods'][m] = {design: {reg: summarise(v) for reg, v in dd.items()} for design, dd in d.items()}
    for m in methods:
        info = fitted_info[m]
        result['fitted'][m] = dict(fallbacks=info['fallbacks'], folds=len(train), test_fit=test_fits[m]['model'],
                                   test_fallback=test_fits[m]['fallback'])
    if pcfg.get('selection'):
        result['selection'] = dict(criterion='inner leave-one-year-out RPS of the calibrators (training years only)',
                                   chosen_training={str(k): v for k, v in chosen.items()}, chosen_test=chosen_test,
                                   frequency={m: sum(v == m for v in chosen.values()) for m in methods})
    return target, result


def tests_of(results, methods, incumbent, region, targets, selection):
    out = {}
    for score in ('rps', 'brier_below', 'brier_above', 'log_loss'):
        stats = {(m, t): {d: paired_summary(results[t]['methods'][m][d][region]['per_year'][score],
                                            results[t]['methods'][incumbent][d][region]['per_year'][score]) for d in ('training', 'test')}
                 for m in methods if m != incumbent for t in targets}
        adj = holm({f'{m}|{t}': s['training']['p_improvement'] for (m, t), s in stats.items()})
        for (m, t), s in stats.items():
            s['decision'] = dict(holm_p_family=float(adj[f'{m}|{t}']), no_harm=s['test']['mean_difference'] <= 0,
                                 confirmed=bool(s['training']['mean_difference'] < 0 and adj[f'{m}|{t}'] < ALPHA and s['test']['mean_difference'] <= 0))
            out.setdefault(m, {}).setdefault(score, {})[t] = s
    if selection:
        stats = {t: {d: paired_summary(results[t]['methods']['SEL'][d][region]['per_year']['rps'],
                                       results[t]['methods'][incumbent][d][region]['per_year']['rps']) for d in ('training', 'test')}
                 for t in targets}
        adj = holm({t: s['training']['p_improvement'] for t, s in stats.items()})
        for t, s in stats.items():
            s['decision'] = dict(holm_p=float(adj[t]), no_harm=s['test']['mean_difference'] <= 0,
                                 confirmed=bool(s['training']['mean_difference'] < 0 and adj[t] < ALPHA and s['test']['mean_difference'] <= 0))
        out['SEL'] = {'rps': stats}
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
    methods = pcfg['methods']
    tests = tests_of(results, methods, pc.INCUMBENT, cfg['primary_region'], targets, pcfg.get('selection'))
    prov = bb.provenance(cfg, project, targets, pcfg['benchmark_config'], dep, extra=CODE + [args.config])
    data = dict(created_utc=datetime.now(timezone.utc).isoformat(), config=args.config, config_contents=pcfg, protocol=__doc__.strip(),
                provenance=prov, phase=1, pathway='A: fixed amount correction, replaced probability calibration',
                amount_method=pcfg['amount_method'], incumbent=pc.INCUMBENT, methods=methods, version=pc.VERSION,
                registry={k: dict(name=c.name, inputs=c.inputs, multiclass=c.multiclass, parameters=c.parameters,
                                  references=c.references, incumbent=c.incumbent, outputs='tercile probabilities only (no CDF)')
                          for k, c in pc.CALIBRATORS.items() if k in methods},
                regions={k: v['label'] for k, v in cfg['regions'].items()}, primary_region=cfg['primary_region'],
                training_years=cfg['training_years'], test_years=cfg['test_years'], targets=results, tests=tests)
    save_json(out_root / 'benchmark.json', data)
    if not args.no_figures:
        figures(out_root, data)
    print('Saved:', out_root)


def figures(out, data):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    reg = data['primary_region']
    targets = list(data['targets'])
    rows = data['methods'] + (['SEL'] if 'SEL' in next(iter(data['targets'].values()))['methods'] else [])
    name = lambda m: 'SEL (chosen per year)' if m == 'SEL' else data['registry'][m]['name']
    tr, te = data['training_years'], data['test_years']
    fig, axes = plt.subplots(1, 3, figsize=(17, 0.45 * len(rows) + 2.6), sharey=True)
    for ax, (design, key, title) in zip(axes, [('training', 'rpss', f'RPSS, outer leave-one-year-out {tr[0]}-{tr[1]}'),
                                               ('test', 'rpss', f'RPSS, fit {tr[0]}-{tr[1]}, scored {te[0]}-{te[1]}'),
                                               ('training', 'log_loss_skill', f'Log-loss skill, {tr[0]}-{tr[1]}')]):
        v = np.array([[data['targets'][t]['methods'][m][design][reg][key] for t in targets] for m in rows])
        lim = max(np.nanmax(np.abs(v)), .02)
        ax.imshow(v, cmap='RdBu', vmin=-lim, vmax=lim, aspect='auto')
        for i, m in enumerate(rows):
            for j, t in enumerate(targets):
                mark = ''
                if design == 'training' and key == 'rpss' and m != data['incumbent']:
                    tt = data['tests'].get(m, {}).get('rps', {}).get(t)
                    mark = ' *' if tt and tt['decision']['confirmed'] else ''
                ax.text(j, i, f'{v[i, j]:+.3f}{mark}', ha='center', va='center', fontsize=8,
                        fontweight='bold' if m == data['incumbent'] else 'normal')
        ax.set_xticks(range(len(targets)), targets)
        ax.set_title(title, fontsize=10)
    axes[0].set_yticks(range(len(rows)), [name(m) for m in rows])
    fig.suptitle(f"Probability calibration, Phase 1 (amount correction fixed: {data['amount_method'].upper()}; {data['regions'][reg]})", fontsize=12)
    fig.text(.5, .005, '* better than the incumbent climatology blend (Holm across every method and target; SEL across the targets) '
             'and not worse over the test years. Skill against the training climatology.', ha='center', fontsize=8)
    fig.tight_layout(rect=(0, .03, 1, .95))
    (out / 'figures').mkdir(parents=True, exist_ok=True)
    fig.savefig(out / 'figures/probability_summary.png', dpi=150)
    plt.close(fig)
    season = targets[-1]
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.2))
    for ax, cat in zip(axes, ['below', 'above']):
        ax.plot([0, 1], [0, 1], color='k', lw=.8)
        for m in data['methods']:
            r = data['targets'][season]['methods'][m]['training'][reg]['reliability'][cat]
            f, o, w = (np.array(r[k], float) for k in ('mean_forecast', 'observed_frequency', 'weight'))
            keep = w > .002
            ax.plot(f[keep], o[keep], marker='o', ms=3.5, label=name(m))
        ax.set(xlim=(0, 1), ylim=(0, 1), xlabel='Forecast probability', ylabel='Observed frequency', title=f'{season}: {cat} normal')
        ax.grid(alpha=.3)
    axes[1].legend(fontsize=7)
    fig.suptitle(f'Reliability of each method, outer leave-one-year-out {tr[0]}-{tr[1]} ({data["regions"][reg]})', fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, .93))
    fig.savefig(out / 'figures/probability_reliability.png', dpi=150)
    plt.close(fig)


if __name__ == '__main__':
    main(ARGS)
