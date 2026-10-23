"""Pathway B (Phases 2 and 3): rainfall-distribution models against the published pipeline (docs/48).

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
import traceback
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

CODE = ['scripts/dist_benchmark.py', 'scripts/dist_calibration.py', 'scripts/neural_calibration.py', 'scripts/sst_indices.py', 'scripts/prob_calibration.py', 'scripts/prob_benchmark.py']
LEVELS = (.1, .5, .9)
BINS = np.linspace(0, 1, 11)                         # reliability: forecast-probability bins of 0.1
MIN_SHARE = .01                                      # reliability bins with fewer forecasts are not drawn


def read(p):
    return json.loads((ROOT / p).read_text(encoding='utf-8'))


def pinball(q, y, tau):
    r = y - q
    return np.where(r >= 0, tau * r, (tau - 1) * r)


# Neighbourhood inputs (drn_pooled_nbhd): means of ensemble summaries over the national cells around each cell, from the
# fold's own relative features (so no information from outside the fold); 3x3 and 5x5 windows on the 0.25-degree grid.
NBHD = {'m_nb3': ('m', 1), 's_nb3': ('s', 1), 'q50_nb3': ('q50', 1), 'm_nb5': ('m', 2)}


def neighbourhood_matrices(idx, nlon):
    """{radius: sparse (n x n) matrix} with 1 where cell j (national) is within the radius of cell i, itself included."""
    from scipy.sparse import csr_matrix
    pos = {int(c): i for i, c in enumerate(idx)}
    r, c = np.divmod(np.asarray(idx), nlon)
    out = {}
    for R in sorted({v[1] for v in NBHD.values()}):
        rows, cols = [], []
        for i, (ri, ci) in enumerate(zip(r, c)):
            for dr in range(-R, R + 1):
                for dc_ in range(-R, R + 1):
                    j = pos.get(int((ri + dr) * nlon + ci + dc_)) if 0 <= ci + dc_ < nlon else None
                    if j is not None:
                        rows.append(i)
                        cols.append(j)
        out[R] = csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(idx), len(idx)))
    return out


def add_neighbourhood(F, mats):
    """The neighbourhood inputs of one year's features F (valid cells only; a cell without valid neighbours keeps its own value)."""
    valid = np.asarray(F['valid'], bool).astype(float)
    out = {}
    for name, (src, R) in NBHD.items():
        v = np.nan_to_num(np.asarray(F[src], float)) * valid
        num, den = mats[R] @ v, mats[R] @ valid
        out[name] = np.where(den > 0, num / np.where(den > 0, den, 1), np.asarray(F[src], float))
    return out


def fold(models, obs, T, idx, area_e, valid_min=1.0, coords=None, extra=None, nbhd=None):
    """Training samples (relative units) and per-cell statistics from the training years T, on the national cells idx;
    coords: (latitude, longitude) of those cells (location predictors of the DRN, docs/54); extra: {input: {year: per-cell
    array}} of further inputs (sst_indices.extra_inputs)."""
    lat_c, lon_c = coords if coords is not None else (None, None)
    O = np.stack([obs[z][idx] for z in T])
    mu_o = O.mean(0)
    mu_m = np.mean([models[z][:, idx].mean(0) for z in T], axis=0)          # equal-year weights
    q1, q2 = np.quantile(O, [1 / 3, 2 / 3], axis=0, method='linear')
    prob_ok = (O.std(0) >= 1.0) & (q1 > 0) & ((q2 - q1) > 1e-6)
    valid = np.isfinite(O).all(0) & (mu_o >= valid_min) & (mu_m >= valid_min)
    thr = np.quantile(O, dc.THRESHOLD_LEVELS, axis=0).T / np.where(valid, mu_o, 1)[:, None]
    cv = np.where(valid, O.std(0) / np.where(valid, mu_o, 1), 0.)
    M = max(models[z].shape[0] for z in T)
    keys = ('m', 's', 'md', 'q10', 'q50', 'q90', 'logmu', 'cv', 'lat', 'lon') + tuple(extra or {}) + (tuple(NBHD) if nbhd else ())
    S = {k: [] for k in ('y', 'w', 'thresholds', 'members') + keys}
    for z in T:
        F = dc.features(models[z][:, idx], mu_o, mu_m, valid, cv, lat_c, lon_c)
        F.update({k: v[z] for k, v in (extra or {}).items()})
        if nbhd:
            F.update(add_neighbourhood(F, nbhd))
        w = np.where(valid, area_e, 0.)
        S['y'].append(np.where(valid, obs[z][idx] / np.where(valid, mu_o, 1), 0)[valid])
        for k in keys:
            S[k].append(F[k][valid])
        mem = np.full((int(valid.sum()), M), np.nan)              # (sample, member), NaN beyond the year's members
        mem[:, :F['members'].shape[0]] = F['members'][:, valid].T
        S['members'].append(mem)
        S['w'].append((w / w.sum())[valid] / len(T))
        S['thresholds'].append(thr[valid])
    S = {k: np.concatenate(v) for k, v in S.items()}
    S['n_years'] = len(T)
    clim_cat = categories(O, q1, q2)
    p_clim = np.stack([(clim_cat == k).mean(0) for k in range(3)], -1)
    return S, dict(mu_o=mu_o, mu_m=mu_m, q1=q1, q2=q2, prob_ok=prob_ok, valid=valid, O=O, p_clim=p_clim, cv=cv)


def score_year(name, p, crps, quant, stats, y_obs, area_e, regions, store):
    """Region scores of one method for one year (p: terciles; crps: per cell; quant: {tau: per-cell quantile})."""
    y_cat = categories(y_obs, stats['q1'], stats['q2'])
    t = np.eye(3)[y_cat]
    rps = lambda q, mask: np.sum((np.cumsum(q[mask], -1)[:, :2] - np.cumsum(t[mask], -1)[:, :2]) ** 2, -1)
    crps_clim = bb.ensemble_crps(np.where(stats['valid'], stats['O'], 0), np.where(stats['valid'], y_obs, 0))
    clim_q10, clim_q90 = np.quantile(stats['O'], [.1, .9], axis=0)        # climatology's 10-90% range (training years)
    brier = lambda q, mask, c: (q[mask, c] - t[mask, c]) ** 2
    for reg, mask in regions.items():
        pv = mask & stats['prob_ok'] & stats['valid'] & np.isfinite(y_obs) & (np.isfinite(p).all(-1) if p is not None else True)
        av = mask & stats['valid'] & np.isfinite(y_obs) & (np.isfinite(crps) if crps is not None else True)
        d = store.setdefault(reg, dict(years=[], per_year={}))
        rec = {}
        if p is not None and pv.any():
            w = area_e[pv] / area_e[pv].sum()
            rec.update(rps=float(w @ rps(p, pv)), rps_clim=float(w @ rps(stats['p_clim'], pv)))
            for c, cat in ((0, 'below'), (2, 'above')):                     # Brier scores of the outer categories
                rec[f'brier_{cat}'] = float(w @ brier(p, pv, c))
                rec[f'brier_{cat}_clim'] = float(w @ brier(stats['p_clim'], pv, c))
        if crps is not None and av.any():
            w = area_e[av] / area_e[av].sum()
            rec.update(crps=float(w @ crps[av]), crps_clim=float(w @ crps_clim[av]))
            for tau in LEVELS:
                rec[f'pinball_{int(tau * 100)}'] = float(w @ pinball(quant[tau][av], y_obs[av], tau))
            rec['coverage_80'] = float(w @ ((y_obs[av] >= quant[.1][av]) & (y_obs[av] <= quant[.9][av])))
            rec['width_80'] = float(w @ (quant[.9][av] - quant[.1][av]))          # sharpness: mean 10-90% width (mm)
            rec['width_80_clim'] = float(w @ (clim_q90[av] - clim_q10[av]))
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
    if pcfg.get('members'):                                  # the same ensemble size in every year (docs/52, docs/54)
        models = {z: m[:pcfg['members']] for z, m in models.items()}
    area_all = cell_area(lat, lon)
    idx = np.flatnonzero(bb.load_mask(cfg['cells'], lat, lon))
    glat, glon = np.meshgrid(lat, lon, indexing='ij')
    coords = (glat.ravel()[idx], glon.ravel()[idx])
    extra = None
    if pcfg.get('extra_inputs'):                             # SST indices and rainfall regions (docs/54)
        import sst_indices
        extra = sst_indices.extra_inputs(pcfg['extra_inputs'], bb.target_config(project, target), sorted(set(train + test)),
                                         lat, lon, idx)
    area_e = area_all[idx]
    nbhd = neighbourhood_matrices(idx, len(lon)) if pcfg.get('neighbourhood') else None
    regions = {k: bb.load_mask(v, lat, lon)[idx] for k, v in cfg['regions'].items()}
    save = bool(pcfg.get('save_predictions'))                 # every fold's predicted distributions, for rescoring and stacking
    preds = {k: {'training': {}, 'test': {}} for k in pcfg['models']} if save else None
    context = {'training': {}, 'test': {}} if save else None
    rec = Records(pcfg['reference_amount_method'], cfg['methods'].get(pcfg['reference_amount_method'], {}), models, obs, train,
                  cfg['smoothing_alpha'])
    keys = pcfg['models']
    store = {k: {'training': {}, 'test': {}} for k in keys + ['incumbent', 'mvs_ensemble']}
    diag = {k: dict(crossings=[], converged=[]) for k in keys}
    rel = {k: {'training': {}, 'test': {}} for k in keys + ['incumbent']} if pcfg.get('reliability') else None
    primary = regions[cfg['primary_region']]

    def evaluate(design, y, T, inner_records, outer_record, fitted=None):
        S, st = fold(models, obs, T, idx, area_e, coords=coords, extra=extra, nbhd=nbhd)
        y_obs = obs[y][idx]
        if save:
            context[design][y] = stats_record(st, y_obs)
        lam_fit = pc.fit(pc.INCUMBENT, inner_records, area_all)               # incumbent: blend weight from inner years
        p_inc = pc.predict(lam_fit, outer_record)[idx]
        score_year(y, p_inc, None, None, st, y_obs, area_e, regions, store['incumbent'][design])
        rmask = primary & st['prob_ok'] & st['valid'] & np.isfinite(y_obs)
        if rel is not None:
            reliability_add(rel['incumbent'][design], p_inc, categories(y_obs, st['q1'], st['q2']), rmask, area_e)
        ens = correct(pcfg['reference_amount_method'], [models[z][:, idx] for z in T], np.stack([obs[z][idx] for z in T]),
                      models[y][:, idx], {k: v for k, v in cfg['methods'].get(pcfg['reference_amount_method'], {}).items()})
        ens_ok = np.isfinite(ens).all(0)
        e0 = np.where(ens_ok, ens, 0.)
        crps_ens = np.where(ens_ok, bb.ensemble_crps(e0, np.nan_to_num(y_obs)), np.nan)
        quant = {tau: np.quantile(e0, tau, axis=0) for tau in LEVELS}
        score_year(y, None, crps_ens, quant, st, y_obs, area_e, regions, store['mvs_ensemble'][design])
        F = dc.features(models[y][:, idx], st['mu_o'], st['mu_m'], st['valid'], st['cv'], *coords)
        F.update({k: v[y] for k, v in (extra or {}).items()})
        if nbhd:
            F.update(add_neighbourhood(F, nbhd))
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
            if save:
                preds[k][design][y] = d
            if rel is not None:
                reliability_add(rel[k][design], p, categories(y_obs, st['q1'], st['q2']), rmask, area_e)
    for y in train:                                         # outer leave-one-year-out
        T = [z for z in train if z != y]
        inner = [rec.get(frozenset((y, z)), [y, z])[1] for z in T]
        evaluate('training', y, T, inner, rec.get(frozenset((y,)), [y])[0])
        print(f'{target} {y}', flush=True)
    oof = [rec.get(frozenset((z,)), [z])[0] for z in train]
    fitted = {}
    for y, r in zip(test, rec.get(frozenset(), test)):      # test years: fitted once on all training years
        evaluate('test', y, train, oof, r, fitted)
    summary = summarise(store)
    fitted = {k: {kk: vv for kk, vv in v.items() if not kk.startswith('_')} for k, v in fitted.items()}   # no forests
    rel = None if rel is None else {k: {d: {c: {q: v.tolist() for q, v in a.items()} for c, a in r.items()} for d, r in dd.items()}
                                    for k, dd in rel.items()}
    saved = dict(predictions=preds, context=context, area_e=area_e.astype(np.float32), regions=regions,
                 scoring_version=dc.SCORING_VERSION) if save else None
    return target, dict(tag=tag, methods=summary, fitted=fitted, **({'reliability': rel} if rel is not None else {}),
                        **({'_saved': saved} if saved is not None else {}),
                        diagnostics={k: dict(mean_crossing_share=float(np.mean(v['crossings'])) if v['crossings'] else None,
                                             all_converged=bool(all(v['converged']))) for k, v in diag.items()})


def stats_record(st, y_obs):
    """What score_year needs from a fold besides the prediction (float32), and the observation of the scored year."""
    f32 = lambda a: np.asarray(a, np.float32)
    return dict(q1=f32(st['q1']), q2=f32(st['q2']), valid=np.asarray(st['valid'], bool), prob_ok=np.asarray(st['prob_ok'], bool),
                O=f32(st['O']), p_clim=f32(st['p_clim']), y_obs=f32(y_obs))


def save_predictions(out_root, target, saved):
    """<output_root>/predictions/<target>.pkl: {predictions: {model: {design: {year: Distribution}}}, context: {design: {year:
    stats}}, area_e, regions, scoring_version}. Rescoring (scripts/rescore.py) and stacking (scripts/stack_benchmark.py) read it."""
    import pickle
    f = out_root / 'predictions' / f'{target}.pkl'
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(pickle.dumps(saved, protocol=pickle.HIGHEST_PROTOCOL))
    return f


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


def summarise(store):
    """Per method, design and region: the per-year scores and their means and skill scores."""
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
                    if 'brier_below' in d['per_year']:                   # Brier skill of the outer categories
                        s.update({f'bss_{c}': 1 - m(f'brier_{c}') / m(f'brier_{c}_clim') for c in ('below', 'above')},
                                 brier_below=m('brier_below'), brier_above=m('brier_above'))
                if 'crps' in d['per_year']:
                    s.update(crps=m('crps'), crpss=1 - m('crps') / m('crps_clim'), coverage_80=m('coverage_80'),
                             **{f'pinball_{int(t * 100)}': m(f'pinball_{int(t * 100)}') for t in LEVELS})
                    if 'width_80' in d['per_year']:                      # sharpness of the 10-90% range
                        s.update(width_80=m('width_80'), width_80_clim=m('width_80_clim'))
                summary[k][design][reg] = s
    return summary


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


def provenance(cfg, project, targets, pcfg, dep, start, keys, config):
    """The benchmark provenance (bias_benchmark.provenance) with the complete dependency set the checkpoints are keyed on:
    the commit and code hashes at the start of the run (the code actually imported), the hash of every code and
    configuration file, the resume keys, the SST files when used, and whether HEAD moved during the run."""
    p = bb.provenance(cfg, project, targets, pcfg['benchmark_config'], dep, extra=CODE + [config])
    end_commit = p['commit']
    p.update(commit=start['commit'], commit_at_end=end_commit, commit_changed_during_run=end_commit != start['commit'],
             uncommitted_changes=start['uncommitted_changes'] or p['uncommitted_changes'], started_utc=start['utc'],
             code_sha256={**p.get('code_sha256', {}), **start['code_sha256']},
             resume_keys_sha256=hashlib.sha256('|'.join(keys[t] for t in targets).encode()).hexdigest(),
             experiment=dict(models=pcfg['models'], decision_models=pcfg.get('decision_models'), members=pcfg.get('members'),
                             configs=pcfg.get('parameters'), extra_inputs=pcfg.get('extra_inputs'),
                             training_years=cfg['training_years'], test_years=cfg['test_years']))
    if pcfg.get('extra_inputs'):
        import sst_indices
        files = {}
        for t in targets:
            tc = bb.target_config(project, t)
            yrs = list(range(cfg['training_years'][0], cfg['test_years'][1] + 1))
            files.update({f.relative_to(ROOT).as_posix(): sha256(f) for f in sst_indices.sst_files(tc['initialization_month'], yrs) if f.is_file()})
        files[sst_indices.REGION_FILE] = sha256(ROOT / sst_indices.REGION_FILE)
        p['extra_input_files_sha256'] = files
    return p


def external_methods(pcfg, cfg, targets):
    """Per-year scores of models from another benchmark run on the same folds (pcfg external_models: {model: benchmark.json
    path, '{name}' the cycle}), for the diagnostic comparisons only; the years must match."""
    out = {}
    for k, path in (pcfg.get('external_models') or {}).items():
        f = ROOT / path.format(name=Path(cfg['output_root']).name)
        if not f.is_file():
            raise FileNotFoundError(f'{f}: run that benchmark first (external model {k})')
        other = json.loads(f.read_text(encoding='utf-8'))
        if other.get('scoring_version', 1) != dc.SCORING_VERSION:
            raise ValueError(f'{f}: scored with scoring version {other.get("scoring_version", 1)}, this run with {dc.SCORING_VERSION}; '
                             'comparisons need the same CRPS rule')
        for t in targets:
            out.setdefault(t, {})[k] = other['targets'][t]['methods'][k]
    return out


def comparisons_of(results, pairs, region, targets, external=None):
    """Diagnostic paired comparisons between models (no adjustment, no decision): {'model|other': {score: {target: summary}}}.
    external: {target: {model: summary}} of models from another benchmark on the same folds (external_methods)."""
    out = {}
    for k, other in pairs:
        for score in ('rps', 'crps'):
            for t in targets:
                pool = {**(external or {}).get(t, {}), **results[t]['methods']}
                a, b = pool[k], pool[other]
                if a['training'][region]['years'] != b['training'][region]['years'] or a['test'][region]['years'] != b['test'][region]['years']:
                    raise ValueError(f'{k} and {other} were scored on different years for {t}')
                if score not in a['training'][region]['per_year'] or score not in b['training'][region]['per_year']:
                    continue
                out.setdefault(f'{k}|{other}', {}).setdefault(score, {})[t] = {
                    d: paired_summary(a[d][region]['per_year'][score], b[d][region]['per_year'][score]) for d in ('training', 'test')}
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
    # the code the workers import is the code at the start of the run: its commit, and whether those files were clean then
    start = dict(commit=bb.git('rev-parse', 'HEAD'), uncommitted_changes=bool(bb.git('status', '--porcelain', '--', *CODE, args.config)),
                 code_sha256={f: sha256(ROOT / f) for f in CODE + [args.config]}, utc=datetime.now(timezone.utc).isoformat())
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
                    print(f'{t} FAILED:\n' + ''.join(traceback.format_exception(exc)), flush=True)   # with the worker's traceback
                    continue
                (parts / f'{t}.pkl').write_bytes(pickle.dumps(dict(key=keys[t], value=value)))
                results[t] = value
            if failed:
                raise RuntimeError('Targets failed (completed targets are checkpointed): ' + '; '.join(failed))
    results = {t: results[t] for t in targets}
    for t in targets:                                        # saved predictions go to their own files, not into the JSON
        saved = results[t].pop('_saved', None)
        if saved is not None:
            save_predictions(out_root, t, saved)
    model_keys = pcfg['models']
    data = dict(created_utc=datetime.now(timezone.utc).isoformat(), config=args.config, config_contents=pcfg, protocol=__doc__.strip(),
                provenance=provenance(cfg, project, targets, pcfg, dep, start, keys, args.config),
                scoring_version=dc.SCORING_VERSION,
                phase=pcfg.get('phase', 2), pathway='B: rainfall-distribution models from the raw ensemble', models=model_keys,
                registry={k: dict(name=dc.MODELS[k].name, estimates=dc.MODELS[k].estimates, predictors=dc.MODELS[k].predictors,
                                  fitting=dc.MODELS[k].fitting, references=dc.MODELS[k].references,
                                  outputs='CDF, quantiles, tercile probabilities') for k in model_keys},
                references=dict(incumbent='MVS -> smoothed counts -> climatology blend (published probabilities)',
                                mvs_ensemble='MVS-corrected ensemble (empirical distribution)'),
                regions={k: v['label'] for k, v in cfg['regions'].items()}, primary_region=cfg['primary_region'],
                training_years=cfg['training_years'], test_years=cfg['test_years'], targets=results,
                decision_models=pcfg.get('decision_models', model_keys),
                tests=tests_of(results, pcfg.get('decision_models', model_keys), cfg['primary_region'], targets),
                comparisons=comparisons_of(results, pcfg.get('comparisons', []), cfg['primary_region'], targets,
                                           external_methods(pcfg, cfg, targets)),
                external_models={k: dict(file=v.format(name=Path(cfg['output_root']).name),
                                         sha256=sha256(ROOT / v.format(name=Path(cfg['output_root']).name)),
                                         commit=json.loads((ROOT / v.format(name=Path(cfg['output_root']).name)).read_text(encoding='utf-8'))['provenance']['commit'],
                                         scoring_version=json.loads((ROOT / v.format(name=Path(cfg['output_root']).name)).read_text(encoding='utf-8')).get('scoring_version', 1))
                                 for k, v in (pcfg.get('external_models') or {}).items()})
    save_json(out_root / 'benchmark.json', data)
    if not args.no_figures:
        figure(out_root, data)
        if any('reliability' in r for r in results.values()):
            reliability_figure(out_root, data)
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
                if design == 'training' and k in data['tests']:
                    tt = data['tests'][k]['rps' if key == 'rpss' else 'crps'][t]['decision']
                    mark = ' *' if tt['confirmed'] else ''
                ax.text(j, i, f'{v[i, j]:+.3f}{mark}', ha='center', va='center', fontsize=8, fontweight='bold' if k == 'incumbent' else 'normal')
        ax.set_xticks(range(len(T)), T)
        ax.set_title(title, fontsize=10)
    axes[0].set_yticks(range(len(rows)), [n for _, n in rows])
    fig.suptitle(f'Rainfall-distribution models (Phase {data.get("phase", 2)}, Pathway B) against the published pipeline '
                 f'({data["regions"][reg]})', fontsize=12)
    fig.text(.5, .005, '* better than the reference (RPS: the published probabilities; CRPS: the MVS-corrected ensemble), Holm across the '
             'models and targets, and not worse over the test years.', ha='center', fontsize=8)
    fig.tight_layout(rect=(0, .03, 1, .95))
    (out / 'figures').mkdir(parents=True, exist_ok=True)
    fig.savefig(out / 'figures/distribution_summary.png', dpi=150)
    plt.close(fig)


def reliability_figure(out, data):
    """Reliability diagrams (below and above normal) of the published probabilities and every model, per target and design."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    T = list(data['targets'])
    keys = ['incumbent'] + list(data['models'])
    names = dict(incumbent='Published (MVS + blend)', **{k: data['registry'][k]['name'] for k in data['models']})
    colours = ['#000000', '#1b9e77', '#d95f02', '#7570b3', '#e7298a', '#66a61e', '#e6ab02']
    for design in ('training', 'test'):
        fig, axes = plt.subplots(2, len(T), figsize=(3.3 * len(T), 6.9), sharex=True, sharey=True, squeeze=False, layout='constrained')
        for j, t in enumerate(T):
            for i, cat in enumerate(('below', 'above')):
                ax = axes[i, j]
                ax.plot([0, 1], [0, 1], color='#999', lw=.8, ls='--')
                ax.axhline(1 / 3, color='#ccc', lw=.6)
                ax.axvline(1 / 3, color='#ccc', lw=.6)
                for n, k in enumerate(keys):
                    a = data['targets'][t].get('reliability', {}).get(k, {}).get(design, {}).get(cat)
                    if not a:
                        continue
                    w, fs, ob = (np.asarray(a[q]) for q in ('w', 'f', 'o'))
                    ok = w >= MIN_SHARE * w.sum()
                    share = w[ok] / w.sum()
                    ax.plot(fs[ok] / w[ok], ob[ok] / w[ok], '-', color=colours[n % len(colours)], lw=1.2, label=names[k], zorder=2)
                    ax.scatter(fs[ok] / w[ok], ob[ok] / w[ok], s=6 + 400 * share, color=colours[n % len(colours)], alpha=.75, zorder=3)
                ax.set_xlim(0, 1)
                ax.set_ylim(0, 1)
                ax.set_aspect('equal')
                ax.set_title(f'{t}: {cat} normal', fontsize=9)
                if i == 1:
                    ax.set_xlabel('Forecast probability')
                if j == 0:
                    ax.set_ylabel('Observed frequency')
        axes[0, 0].legend(fontsize=6, loc='upper left')
        yrs = data['training_years' if design == 'training' else 'test_years']
        how = 'leave-one-year-out ' if design == 'training' else 'fitted on the training years, scored '
        fig.suptitle(f'Reliability of the tercile probabilities, {data["regions"][data["primary_region"]]}, {how}{yrs[0]}-{yrs[1]}. '
                     f'Marker area: share of forecasts in the bin (bins under {MIN_SHARE:.0%} not shown); on the diagonal = reliable', fontsize=10)
        (out / 'figures').mkdir(parents=True, exist_ok=True)
        fig.savefig(out / f'figures/reliability_{design}.png', dpi=120)
        plt.close(fig)


if __name__ == '__main__':
    main(ARGS)
