"""Statistical downscaling by model output statistics (MOS), as in CPT / PyCPT used by ICPAC and IRI (docs/53), against the
published pipeline, one cycle.

Methods, each fitted inside the folds:
  cca   canonical correlation analysis: EOF pre-filtering of the predictor and of the predictand (CHIRPS at every
        0.25-degree cell), canonical modes between the leading PCs
  pcr   principal component regression: each CHIRPS cell regressed on the leading predictor PCs
Predictor fields (settings.fields): SEAS5 square-root rainfall over the model box (1-degree cells), SEAS5 sea-surface
temperature over the tropical Indian and Pacific Oceans (2-degree cells), or both with equal weight; ensemble means of the
first 25 members in every year. Rainfall is square-root, every field standardized per cell with the training years. The
field and the numbers of modes (predictor EOFs up to 6, predictand EOFs up to 6, canonical modes up to 3) are chosen by
inner leave-one-year-out cross-validation (smallest mean normalized squared error over the cells). The predictive
distribution is Gaussian in square-root space; its variance is the cross-validated error variance scaled by (1 + leverage)
of the forecast, so it is wider for unusual forecasts. Tercile probabilities from it, blended with climatology with a weight
chosen by the same inner folds; amounts and ranges from 51 quantile members of it.
References in the same folds: the published probabilities (RPS) and the MVS-corrected ensemble (CRPS). Design and tests as
the other benchmarks: outer leave-one-year-out over the training years, test years fitted on all training years; paired
whole-year sign-flip, Holm across the two methods and the targets; not worse over the test years. Also the forecast year,
scored against CHIRPS once observed (never published).

  python scripts/mos_benchmark.py --config config/mos/sep_ondj.json
"""
import argparse
import hashlib
import json
import os
import pickle
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.stats import norm


def parse():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--config', default='config/mos/sep_ondj.json')
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
from calibration_core import categories                                 # noqa: E402
import bias_benchmark as bb                                             # noqa: E402
import prob_calibration as pc                                           # noqa: E402
import dist_benchmark as db                                             # noqa: E402
from prob_benchmark import Records                                      # noqa: E402
import leung_dirichlet_benchmark as ldb                                 # noqa: E402

CODE = ['scripts/mos_benchmark.py', 'scripts/download_seas5_sst.py', 'scripts/leung_dirichlet_benchmark.py', 'scripts/dist_benchmark.py', 'scripts/bias_methods.py',
        'scripts/prob_calibration.py', 'scripts/prob_benchmark.py']
METHODS = ['cca', 'pcr']
LABELS = dict(cca='Canonical correlation analysis (CCA)', pcr='Principal component regression (PCR)')
LEVELS = (.1, .5, .9)
K = 51                                                                   # quantile members of the predictive distribution
EPS = 1e-6


def read(p):
    return json.loads((ROOT / p).read_text(encoding='utf-8'))


# ---------------------------------------------------------------- predictors
def blocks(a, block):
    """Mean over `block` x `block` cells of a 2-D field, ignoring missing cells."""
    ny, nx = a.shape
    b = a[:ny - ny % block, :nx - nx % block].reshape(ny // block, block, nx // block, block)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)                  # all-missing blocks (land) stay missing
        return np.nanmean(b, axis=(1, 3)).ravel()


def predictor(models, years, shape, block, members=None):
    """SEAS5 ensemble-mean square-root rainfall averaged over the model's 1-degree cells (blocks of `block` x `block` cells),
    from the first `members` members of every year (the same ensemble size in hindcasts and forecasts)."""
    return np.array([blocks(np.sqrt(np.maximum(np.asarray(models[z][:members], float).mean(0), 0)).reshape(shape), block)
                     for z in years])


def target_months(tc):
    """Calendar months of a target (its season's start and end months; seasons may cross the year)."""
    a, b = int(tc['season']['start'][:2]), int(tc['season']['end'][:2])
    return [(a - 1 + i) % 12 + 1 for i in range((b - a) % 12 + 1)]


def sst_files(init, years):
    return [ROOT / f'data/raw/ecmwf_sst/init{init:02d}/sst_{y}.nc' for y in years]


def sst_predictor(init, months, years, block):
    """SEAS5 sea-surface temperature (first 25 members; scripts/download_seas5_sst.py) averaged over the target months,
    in blocks of `block` x `block` 1-degree cells over the tropical Indian and Pacific Oceans; cells missing in any year
    (land) are dropped. None if a year's file is missing."""
    import xarray as xr
    files = sst_files(init, years)
    if not all(f.is_file() for f in files):
        return None
    leads = [(m - init) % 12 + 1 for m in months]
    rows = []
    for f in files:
        with xr.open_dataset(f) as d:
            rows.append(blocks(d.sst.sel(lead_month=leads).mean('lead_month').values.astype(float), block))
    rows = np.array(rows)
    keep = np.isfinite(rows).all(0)
    return dict(zip(years, rows[:, keep]))


# ---------------------------------------------------------------- the MOS model
class MOS:
    """CCA or PCR on standardized fields; the predictor field (rainfall, SST or both) and the modes chosen by inner
    leave-one-year-out; Gaussian predictive distribution whose spread grows with the forecast's leverage; tercile
    probabilities blended with climatology, the weight chosen by the same inner leave-one-year-out."""

    BLEND = np.round(np.arange(0, 1.0001, 0.05), 2)

    def __init__(self, kind, max_x=6, max_y=6, max_cca=3, fields=None):
        self.kind, self.max_x, self.max_y, self.max_cca, self.fields = kind, max_x, max_y, max_cca, fields

    def combos(self, n):
        mx = min(self.max_x, n - 2)
        if self.kind == 'pcr':
            return [(i, 0, 0) for i in range(1, mx + 1)]
        my = min(self.max_y, n - 2)
        return [(i, j, k) for i in range(1, mx + 1) for j in range(1, my + 1) for k in range(1, min(i, j, self.max_cca) + 1)]

    @staticmethod
    def _standardize(A):
        mu, sd = A.mean(0), A.std(0)
        sd = np.where(sd > EPS, sd, 1.0)
        return mu, sd

    @staticmethod
    def column_weights(widths):
        """Equal total weight for each field of a combined predictor (1/sqrt(columns) per column after standardization)."""
        return np.concatenate([np.full(w, 1 / np.sqrt(w)) for w in widths])

    def _fit_core(self, X, Y, w=None):
        """SVDs of the standardized training fields (shared by every combination of modes)."""
        n = len(X)
        mx, sx = self._standardize(X)
        my, sy = self._standardize(Y)
        w = np.ones(X.shape[1]) if w is None else w
        Xz, Yz = (X - mx) / sx * w, (Y - my) / sy
        Ux, Sx, Vx = np.linalg.svd(Xz, full_matrices=False)
        core = dict(n=n, mx=mx, sx=sx, w=w, my=my, sy=sy, Sx=Sx, Vx=Vx, Xpc=Ux * np.sqrt(n), Yz=Yz)
        if self.kind == 'cca':
            Uy, Sy, Vy = np.linalg.svd(Yz, full_matrices=False)
            core.update(Ypc=Uy * np.sqrt(n), Yload=(Sy[:, None] * Vy) / np.sqrt(n))
        return core

    @staticmethod
    def _predict_core(core, x, combo):
        """The prediction in square-root space and the forecast's regressors (unit variance over the training years):
        the predictor PCs (PCR) or the predictor canonical variates (CCA)."""
        nxm, nym, ncm = combo
        n = core['n']
        xz = (x - core['mx']) / core['sx'] * core['w']
        xpc = (xz @ core['Vx'][:nxm].T) / core['Sx'][:nxm] * np.sqrt(n)
        if nym == 0:                                                     # PCR
            B = core['Xpc'][:, :nxm].T @ core['Yz'] / n
            yz, v = xpc @ B, xpc
        else:                                                            # CCA
            C = core['Xpc'][:, :nxm].T @ core['Ypc'][:, :nym] / n
            A, s, Bt = np.linalg.svd(C, full_matrices=False)
            v = xpc @ A[:, :ncm]
            ypc = v @ np.diag(s[:ncm]) @ Bt[:ncm]
            yz = ypc @ core['Yload'][:nym]
        return core['my'] + core['sy'] * yz, v

    @staticmethod
    def leverage(v, n):
        """Leverage of a forecast with regressors v (unit variance, uncorrelated over n training years), with the intercept."""
        return (1 + float(v @ v)) / n

    def fit(self, X, Y, cells=None, area=None, widths=None):
        """Choose the predictor field and the modes by inner leave-one-year-out (normalized squared error); keep the error
        variance per cell, scaled for leverage; choose the climatology blend weight of the probabilities by the same folds.
        X: (n, p) array, or {field: (n, p) array} of candidate predictor fields; Y: (n, q) square-root rainfall.
        cells, area: the cells (and their areas) scored for probabilities, for the blend weight.
        widths: {field: [columns of each part]} for combined fields, which give each part equal weight."""
        Xs = X if isinstance(X, dict) else {'rain': X}
        fields = [f for f in (self.fields or list(Xs)) if f in Xs]
        n = len(Y)
        combos = self.combos(n - 1)
        err, resid, lev = {}, {}, {}
        for f in fields:
            wcol = self.column_weights(widths[f]) if widths and f in widths else None
            for j in range(n):
                keep = np.arange(n) != j
                core = self._fit_core(Xs[f][keep], Y[keep], wcol)
                for c in combos:
                    mu, v = self._predict_core(core, Xs[f][j], c)
                    e = Y[j] - mu
                    err[f, c] = err.get((f, c), 0) + e ** 2
                    resid.setdefault((f, c), []).append(e)
                    lev.setdefault((f, c), []).append(self.leverage(v, n - 1))
        var = Y.var(0)
        live = var > 0.01 if (var > 0.01).any() else var > 0        # cells with year-to-year variation (dry cells would dominate)
        score = {k: float(np.mean(err[k][live] / (n * var[live]))) for k in err}
        self.field, self.combo = min(score, key=score.get)
        self.score = score[self.field, self.combo]
        E = np.square(resid[self.field, self.combo])                 # (n, q)
        h = np.array(lev[self.field, self.combo])                    # (n,)
        S = E / (1 + h)[:, None]
        self.s2 = np.maximum(S.mean(0), EPS)                         # error variance per cell, net of leverage
        self.inner_leverage = h
        self.w = self._blend(Y, Y - np.array(resid[self.field, self.combo]), S, h, cells, area)
        wcol = self.column_weights(widths[self.field]) if widths and self.field in widths else None
        self.core = self._fit_core(Xs[self.field], Y, wcol)
        return self

    def _blend(self, Y, mu, S, h, cells, area):
        """Climatology blend weight of the tercile probabilities: smallest inner leave-one-year-out RPS (area-weighted over
        the probability cells), each left-out year with the terciles and error variance of the other years."""
        n, q = Y.shape
        cells = np.ones(q, bool) if cells is None else cells
        area = np.ones(q) if area is None else area
        total = np.zeros(len(self.BLEND))
        weight = 0.0
        for j in range(n):
            keep = np.arange(n) != j
            O = Y[keep] ** 2
            q1, q2 = np.quantile(O, [1 / 3, 2 / 3], axis=0, method='linear')
            ok = cells & (O.std(0) >= 1.0) & (q1 > 0) & ((q2 - q1) > 1e-6)
            if not ok.any():
                continue
            s2 = np.maximum(S[keep].mean(0), EPS)                    # the error variance without year j
            p = gaussian_terciles(mu[j], np.sqrt(s2 * (1 + h[j])), q1, q2)[ok]
            o = np.eye(3)[categories(Y[j] ** 2, q1, q2)][ok]
            a = area[ok] / area[ok].sum()
            for i, wb in enumerate(self.BLEND):
                pb = wb * p + (1 - wb) / 3
                total[i] += a @ ((pb[:, 0] - o[:, 0]) ** 2 + (pb[:, :2].sum(1) - o[:, :2].sum(1)) ** 2)
            weight += 1
        return float(self.BLEND[np.argmin(total)]) if weight else 1.0

    def predict(self, x):
        """Mean and standard deviation (square-root space) for a forecast: x an array, or {field: array}."""
        xf = x[self.field] if isinstance(x, dict) else x
        mu, v = self._predict_core(self.core, xf, self.combo)
        return mu, np.sqrt(self.s2 * (1 + self.leverage(v, self.core['n'])))


def gaussian_terciles(mean, sigma, q1, q2):
    """Tercile probabilities of a Gaussian in square-root space, with the tercile limits q1, q2 in mm."""
    s1, s2 = np.sqrt(np.maximum(q1, 0)), np.sqrt(np.maximum(q2, 0))
    below = norm.cdf((s1 - mean) / sigma)
    above = 1 - norm.cdf((s2 - mean) / sigma)
    p = np.stack([below, np.clip(1 - below - above, 0, 1), above], -1)
    return p / p.sum(-1, keepdims=True)


def products(mean, sigma, q1, q2, blend=1.0):
    """Tercile probabilities (blended with climatology: blend x MOS + (1 - blend) / 3), 51 quantile members (mm) and the
    quantiles of the Gaussian in square-root space."""
    p = blend * gaussian_terciles(mean, sigma, q1, q2) + (1 - blend) / 3
    z = norm.ppf((np.arange(K) + .5) / K)
    ens = np.maximum(mean[None] + sigma[None] * z[:, None], 0) ** 2
    quant = {t: np.maximum(mean + sigma * norm.ppf(t), 0) ** 2 for t in LEVELS}
    return p, ens, quant


# ---------------------------------------------------------------- one target
def run_target(config_path, target):
    mcfg = read(config_path)
    cfg = read(mcfg['benchmark_config'])
    project = load_config(cfg['project_config'])
    rng = lambda a, b: list(range(a, b + 1))
    train, test = rng(*cfg['training_years']), rng(*cfg['test_years'])
    tag, models, obs, lat, lon = bb.load_target(cfg, project, target)
    shape = (len(lat), len(lon))
    area_all = cell_area(lat, lon)
    idx = np.flatnonzero(bb.load_mask(cfg['cells'], lat, lon))
    area_e = area_all[idx]
    regions = {k: bb.load_mask(v, lat, lon)[idx] for k, v in cfg['regions'].items()}
    primary = regions[cfg['primary_region']]
    mvs_params = dict(cfg['methods'].get('mvs', {}))
    rec_mvs = Records('mvs', mvs_params, models, obs, train, cfg['smoothing_alpha'])
    s = mcfg['settings']
    years_all = sorted(set(train + test + [read(cfg['cycle'])['forecast_year']]) & set(models))
    Xall, widths = predictors(s, bb.target_config(project, target), models, years_all, shape)
    keys = METHODS + ['incumbent', 'mvs_ensemble']
    store = {k: {'training': {}, 'test': {}} for k in keys}
    rel = {k: {'training': {}, 'test': {}} for k in METHODS + ['incumbent']}
    chosen = {k: {'training': [], 'test': []} for k in METHODS}
    choices = {k: {'training': [], 'test': []} for k in METHODS}

    def evaluate(design, y, T, inner_mvs, outer_mvs):
        _, st = db.fold(models, obs, T, idx, area_e)
        y_obs = obs[y][idx]
        q1, q2 = st['q1'], st['q2']
        O = np.stack([obs[z][idx] for z in T])
        score = lambda k, p=None, crps=None, quant=None: db.score_year(y, p, crps, quant, st, y_obs, area_e, regions, store[k][design])

        def prob(k, p):
            score(k, p=p)
            ldb.reliability_add(rel[k][design], p, categories(y_obs, q1, q2), primary & st['prob_ok'] & st['valid'] & np.isfinite(y_obs), area_e)
        prob('incumbent', pc.predict(pc.fit(pc.INCUMBENT, inner_mvs, area_all), outer_mvs)[idx])
        ens_mvs, _, _, _ = ldb.corrected('mvs', mvs_params, [models[z][:, idx] for z in T], O, models[y][:, idx])
        ok = np.isfinite(ens_mvs).all(0)
        e0 = np.where(ok, ens_mvs, 0.)
        score('mvs_ensemble', crps=np.where(ok, bb.ensemble_crps(e0, np.nan_to_num(y_obs)), np.nan),
              quant={t: np.where(ok, np.quantile(e0, t, axis=0), np.nan) for t in LEVELS})
        X = {f: np.array([Xall[f][z] for z in T]) for f in Xall}
        Ys = np.sqrt(np.maximum(O, 0))
        for k in METHODS:
            m = MOS(k, s['max_x_modes'], s['max_y_modes'], s['max_cca_modes'], s.get('fields')).fit(
                X, Ys, cells=primary & st['prob_ok'] & st['valid'], area=area_e, widths=widths)
            mean, sig = m.predict({f: Xall[f][y] for f in Xall})
            p, ens, quant = products(mean, sig, q1, q2, m.w)
            score(k, p=p, crps=bb.ensemble_crps(ens, np.nan_to_num(y_obs)), quant=quant)      # one record per year, both products
            ldb.reliability_add(rel[k][design], p, categories(y_obs, q1, q2), primary & st['prob_ok'] & st['valid'] & np.isfinite(y_obs), area_e)
            chosen[k][design].append(list(m.combo))
            choices[k][design].append(dict(field=m.field, blend=m.w))

    for y in train:                                          # outer leave-one-year-out
        T = [z for z in train if z != y]
        evaluate('training', y, T, [rec_mvs.get(frozenset((y, z)), [y, z])[1] for z in T], rec_mvs.get(frozenset((y,)), [y])[0])
        print(f'{target} {y}', flush=True)
    oof = [rec_mvs.get(frozenset((z,)), [z])[0] for z in train]
    for y, rm in zip(test, rec_mvs.get(frozenset(), test)):
        evaluate('test', y, train, oof, rm)
    summary = {}
    for k, dd in store.items():
        summary[k] = {}
        for design, regs in dd.items():
            summary[k][design] = {}
            for reg, d in regs.items():
                mean = lambda key: float(np.mean(d['per_year'][key]))
                out = dict(years=d['years'], per_year=d['per_year'])
                if 'rps' in d['per_year']:
                    out.update(rps=mean('rps'), rpss=1 - mean('rps') / mean('rps_clim'))
                if 'crps' in d['per_year']:
                    out.update(crps=mean('crps'), crpss=1 - mean('crps') / mean('crps_clim'), coverage_80=mean('coverage_80'),
                               **{f'pinball_{int(t * 100)}': mean(f'pinball_{int(t * 100)}') for t in LEVELS})
                summary[k][design][reg] = out
    rel = {k: {d: {c: {q: v.tolist() for q, v in a.items()} for c, a in r.items()} for d, r in dd.items()} for k, dd in rel.items()}
    return target, dict(tag=tag, methods=summary, reliability=rel, modes=chosen, choices=choices, fields=list(Xall),
                        validation=forecast_validation(mcfg, cfg, models, obs, lat, lon, idx, Xall, widths, mvs_params, area_all, primary))


def predictors(s, tc, models, years, shape):
    """Candidate predictor fields {field: {year: vector}} and the part widths of combined fields: SEAS5 rainfall over the
    model box; with settings.fields including SST, SEAS5 sea-surface temperature and the two combined."""
    rain = dict(zip(years, predictor(models, years, shape, s['block'], s.get('members'))))
    X, widths = {'rain': rain}, {}
    wanted = s.get('fields', ['rain'])
    if any('sst' in f for f in wanted):
        sst = sst_predictor(tc['initialization_month'], target_months(tc), years, s.get('sst_block', 2))
        if sst is None:
            raise FileNotFoundError(f"SEAS5 SST missing for init {tc['initialization_month']:02d}: run scripts/download_seas5_sst.py")
        X['sst'] = sst
        X['rain+sst'] = {z: np.concatenate([rain[z], sst[z]]) for z in years}
        widths['rain+sst'] = [len(rain[years[0]]), len(sst[years[0]])]
    return {f: X[f] for f in wanted}, widths


def forecast_validation(mcfg, cfg, models, obs, lat, lon, idx, Xall, widths, mvs_params, area_all, primary):
    """The forecast year, every method fitted on the cycle's reference years, scored once its CHIRPS exists (never published)."""
    cycle = read(cfg['cycle'])
    year = cycle['forecast_year']
    ref = [z for z in range(cycle['reference_years'][0], cycle['reference_years'][1] + 1) if z in obs]
    if year not in models or any(year not in v for v in Xall.values()) or not ref:
        return None
    O = np.stack([obs[z][idx] for z in ref])
    q1, q2 = np.quantile(O, [1 / 3, 2 / 3], axis=0, method='linear')
    s = mcfg['settings']
    X = {f: np.array([Xall[f][z] for z in ref]) for f in Xall}
    cells = primary & (O.std(0) >= 1.0) & (q1 > 0) & ((q2 - q1) > 1e-6)
    probs, ens = {}, {}
    for k in METHODS:
        m = MOS(k, s['max_x_modes'], s['max_y_modes'], s['max_cca_modes'], s.get('fields')).fit(
            X, np.sqrt(np.maximum(O, 0)), cells=cells, area=area_all[idx], widths=widths)
        probs[k], ens[k], _ = products(*m.predict({f: Xall[f][year] for f in Xall}), q1, q2, m.w)
    rec = Records('mvs', mvs_params, models, obs, ref, cfg['smoothing_alpha'])
    fit = pc.fit(pc.INCUMBENT, [rec.get(frozenset((z,)), [z])[0] for z in ref], area_all)
    probs['incumbent_recomputed'] = pc.predict(fit, ldb.forecast_record('mvs', mvs_params, models, obs, ref, year, cfg['smoothing_alpha']))[idx]
    ens['mvs_ensemble'], _, _, _ = ldb.corrected('mvs', mvs_params, [models[z][:, idx] for z in ref], O, models[year][:, idx])
    return dict(probs=probs, ens=ens, O=O, q1=q1, q2=q2, primary=primary, area=area_all[idx], year=year)


def validate_target(cycle, target, v, lat, lon, idx):
    """Score a forecast-year result against its observation (forecast year, once CHIRPS exists)."""
    if not v:
        return None
    return ldb.validate(cycle, target, v['year'], lat, lon, idx, v['O'], v['q1'], v['q2'], v['probs'], v['ens'], v['primary'], v['area'])


def tests_of(results, region, targets):
    out = {}
    for score, ref in (('rps', 'incumbent'), ('crps', 'mvs_ensemble')):
        stats = {(k, t): {d: paired_summary(results[t]['methods'][k][d][region]['per_year'][score],
                                            results[t]['methods'][ref][d][region]['per_year'][score]) for d in ('training', 'test')}
                 for k in METHODS for t in targets}
        adj = holm({f'{k}|{t}': x['training']['p_improvement'] for (k, t), x in stats.items()})
        for (k, t), x in stats.items():
            x['decision'] = dict(reference=ref, holm_p_family=float(adj[f'{k}|{t}']), no_harm=x['test']['mean_difference'] <= 0,
                                 confirmed=bool(x['training']['mean_difference'] < 0 and adj[f'{k}|{t}'] < ALPHA and x['test']['mean_difference'] <= 0))
            out.setdefault(k, {}).setdefault(score, {})[t] = x
    return out


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(args):
    mcfg = read(args.config)
    cfg = read(mcfg['benchmark_config'])
    project = load_config(cfg['project_config'])
    targets = args.targets or cfg['targets']
    out_root = ROOT / mcfg['output_root']
    parts = out_root / 'parts'
    parts.mkdir(parents=True, exist_ok=True)
    dep = bb.dependencies(cfg, project, targets, mcfg['benchmark_config'])
    sst = sorted((ROOT / f"data/raw/ecmwf_sst/init{bb.target_config(project, targets[0])['initialization_month']:02d}").glob('sst_*.nc'))         if any('sst' in f for f in mcfg['settings'].get('fields', [])) else []
    extra = hashlib.sha256(''.join(sha256(ROOT / f) for f in CODE + [args.config]).encode() +
                           ''.join(f.name + sha256(f) for f in sst).encode()).hexdigest()
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
    cycle = read(cfg['cycle'])
    validation = {}
    for t in targets:                                       # the forecast year, scored once observed
        v = results[t].pop('validation', None)
        if v:
            _, _, _, lat, lon = bb.load_target(cfg, project, t)
            idx = np.flatnonzero(bb.load_mask(cfg['cells'], lat, lon))
            r = validate_target(cycle, t, v, lat, lon, idx)
            if r:
                validation[t] = r
    data = dict(created_utc=datetime.now(timezone.utc).isoformat(), config=args.config, config_contents=mcfg, protocol=__doc__.strip(),
                provenance=bb.provenance(cfg, project, targets, mcfg['benchmark_config'], dep, extra=CODE + [args.config]),
                version=2, methods=METHODS, labels=LABELS,
                sst_files=dict(count=len(sst), sha256=hashlib.sha256(''.join(f.name + sha256(f) for f in sst).encode()).hexdigest()),
                references=dict(incumbent='Published probabilities: MVS -> smoothed counts -> climatology blend',
                                mvs_ensemble='MVS-corrected ensemble (published amount correction)'),
                regions={k: v['label'] for k, v in cfg['regions'].items()}, primary_region=cfg['primary_region'],
                training_years=cfg['training_years'], test_years=cfg['test_years'], targets=results,
                tests=tests_of(results, cfg['primary_region'], targets), validation=validation)
    save_json(out_root / 'benchmark.json', data)
    figure(out_root, data)
    print('Saved:', out_root)


def figure(out, data):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    reg = data['primary_region']
    T = list(data['targets'])
    rows = [('incumbent', 'rpss', 'Published probabilities (RPSS)'), ('cca', 'rpss', 'CCA (RPSS)'), ('pcr', 'rpss', 'PCR (RPSS)'),
            ('mvs_ensemble', 'crpss', 'MVS ensemble (CRPSS)'), ('cca', 'crpss', 'CCA (CRPSS)'), ('pcr', 'crpss', 'PCR (CRPSS)')]
    fig, axes = plt.subplots(1, 2, figsize=(13, 0.55 * len(rows) + 2.2), sharey=True, layout='constrained')
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
    fig.suptitle(f'Statistical downscaling (MOS) against the published pipeline ({data["regions"][reg]}); * confirmed better than the reference',
                 fontsize=10)
    (out / 'figures').mkdir(parents=True, exist_ok=True)
    fig.savefig(out / 'figures/mos_summary.png', dpi=140)
    plt.close(fig)


if __name__ == '__main__':
    main(ARGS)
