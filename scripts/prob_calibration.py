"""Tercile-probability calibration methods (docs/48), Phase 1 of "Probability and rainfall-distribution calibration".

Every method has the same interface on records — one per training year, over all grid cells:
    record = dict(s=(cell, 3) smoothed member-count probabilities (unblended), clim=(cell, 3) training-year category
                  frequencies, y=(cell,) observed category (-1 unavailable), zmean=(cell,) standardized ensemble mean,
                  lspread=(cell,) log spread ratio)
    model = CALIBRATORS[key].fit(records, area, **params)      # pooled over cells; equal weight per year, area within year
    p = CALIBRATORS[key].predict(record, model)                 # (cell, 3), non-negative, rows sum to one
A method that cannot be fitted (too few pairs, a missing category, optimizer failure) falls back to the incumbent climatology
blend, and says so (model['fallback']).

Pathway A of the plan: the amount correction is held fixed (MVS); every probability method starts from the same smoothed,
unblended probabilities, except the logistic models, which use their own declared ensemble predictors. Distinctions kept:
Dirichlet calibration uses only the log probabilities; multinomial logistic regression uses only the ensemble predictors
(standardized mean and log spread ratio), so the two are not the same model. Pseudocount smoothing is not Dirichlet
calibration.
"""
from dataclasses import dataclass, field
import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.special import expit, logsumexp, softmax

from calibration_core import fit_dirichlet, apply_dirichlet, log_inputs
from local_blend import fit_weights

EPS = 1e-12
VERSION = 1


# ---------------------------------------------------------------- pooled samples

def pack(records, area, need_predictors=False):
    """Valid (cell, year) pairs of all records, with weights: each year 1/Y, area-weighted within the year."""
    keys = ('s', 'clim', 'y', 'zmean', 'lspread')
    out = {k: [] for k in keys}
    weights = []
    for r in records:
        valid = (r['y'] >= 0) & np.isfinite(r['s']).all(-1) & np.isfinite(r['clim']).all(-1)
        if need_predictors:
            valid &= np.isfinite(r['zmean']) & np.isfinite(r['lspread'])
        if not valid.any():
            continue
        for k in keys:
            out[k].append(np.asarray(r[k])[valid])
        weights.append(area[valid] / area[valid].sum())
    if not weights:
        raise ValueError('No valid calibration pairs.')
    n = len(weights)
    a = {k: np.concatenate(v).astype(float) if k != 'y' else np.concatenate(v).astype(int) for k, v in out.items()}
    return a, np.concatenate(weights) / n


def predictors(a):
    return np.column_stack([np.ones(len(a['zmean'])), a['zmean'], a['lspread']])


def check_categories(y):
    if len(np.unique(y)) < 3:
        raise ValueError('All three observed categories are needed.')


# ---------------------------------------------------------------- methods

def fit_pseudocount(records, area, **_):
    return {}


def predict_pseudocount(r, m):
    return np.asarray(r['s'], float)


def fit_blend(records, area, **_):
    return dict(lam=float(fit_weights(records, area)['shared_lambda']))


def predict_blend(r, m):
    return (1 - m['lam']) * np.asarray(r['s'], float) + m['lam'] * np.asarray(r['clim'], float)


def fit_temperature(records, area, bounds=(0.25, 4.0), **_):
    """One temperature T > 0 (bounded): p = softmax(log p_s / T), fitted by weighted log loss."""
    a, w = pack(records, area)
    check_categories(a['y'])
    x = log_inputs(a['s'])
    idx = np.arange(len(x))
    loss = lambda lt: float(-w @ np.log(np.maximum(softmax(x / np.exp(lt), axis=1)[idx, a['y']], EPS)))
    res = minimize_scalar(loss, bounds=(np.log(bounds[0]), np.log(bounds[1])), method='bounded', options={'xatol': 1e-7})
    if not res.success:
        raise RuntimeError('Temperature fit failed.')
    best = min([(float(res.fun), float(res.x)), (loss(np.log(bounds[0])), float(np.log(bounds[0]))),
                (loss(np.log(bounds[1])), float(np.log(bounds[1])))])
    return dict(temperature=float(np.exp(best[1])), at_bound=bool(abs(best[1] - np.log(bounds[0])) < 1e-6
                                                                   or abs(best[1] - np.log(bounds[1])) < 1e-6))


def predict_temperature(r, m):
    p = np.full(np.shape(r['s']), np.nan)
    ok = np.isfinite(r['s']).all(-1)
    p[ok] = softmax(log_inputs(np.asarray(r['s'])[ok]) / m['temperature'], axis=1)
    return p


def fit_dirichlet_cal(records, area, **_):
    """Regularized Dirichlet calibration of the log smoothed probabilities (calibration_core: identity-regularized)."""
    return fit_dirichlet([r['s'] for r in records], [r['y'] for r in records], area)


def predict_dirichlet_cal(r, m):
    return apply_dirichlet(np.asarray(r['s'], float), m)


def fit_multinomial(records, area, l2=1e-3, **_):
    """Regularized multinomial logistic regression on [1, standardized ensemble mean, log spread ratio].

    Near normal is the reference class (its coefficients are 0); L2 on the slopes only. Weighted log loss.
    """
    a, w = pack(records, area, need_predictors=True)
    check_categories(a['y'])
    X = predictors(a)
    Y = np.eye(3)[a['y']]

    def loss(theta):
        W = np.zeros((3, 3))
        W[[0, 2]] = theta.reshape(2, 3)
        z = X @ W.T
        lse = logsumexp(z, axis=1)
        f = float(w @ (lse - z[np.arange(len(z)), a['y']])) + l2 * float(np.sum(W[:, 1:] ** 2))
        g = (softmax(z, axis=1) - Y) * w[:, None]
        G = g.T @ X
        G[:, 1:] += 2 * l2 * W[:, 1:]
        return f, G[[0, 2]].ravel()
    res = minimize(loss, np.zeros(6), jac=True, method='L-BFGS-B', options={'maxiter': 500})
    if not res.success or not np.isfinite(res.x).all():
        raise RuntimeError('Multinomial logistic fit failed: ' + str(res.message))
    W = np.zeros((3, 3))
    W[[0, 2]] = res.x.reshape(2, 3)
    return dict(coefficients=W.tolist(), features=['intercept', 'standardized_mean', 'log_spread_ratio'], l2=l2,
                reference_class='near')


def predict_multinomial(r, m):
    X = np.column_stack([np.ones(len(r['zmean'])), r['zmean'], r['lspread']])
    p = softmax(X @ np.asarray(m['coefficients']).T, axis=1)
    p[~np.isfinite(X).all(1) | ~np.isfinite(r['s']).all(-1)] = np.nan
    return p


def ordinal_probabilities(theta, X):
    t1, d, beta = theta[0], theta[1], theta[2:]
    t2 = t1 + np.exp(d)                                   # ordered cutpoints
    eta = X @ beta
    f1, f2 = expit(t1 - eta), expit(t2 - eta)
    return np.column_stack([f1, f2 - f1, 1 - f2])


def fit_ordinal(records, area, l2=1e-3, **_):
    """Ordinal (cumulative-logit) model: P(Y <= k) = logistic(theta_k - x·beta), theta_1 < theta_2; x = [mean, log spread]."""
    a, w = pack(records, area, need_predictors=True)
    check_categories(a['y'])
    X = predictors(a)[:, 1:]
    idx = np.arange(len(X))

    def loss(theta):
        p = ordinal_probabilities(theta, X)
        return float(-w @ np.log(np.maximum(p[idx, a['y']], EPS))) + l2 * float(np.sum(theta[2:] ** 2))
    res = minimize(loss, np.array([-.7, np.log(1.4), 0., 0.]), method='L-BFGS-B', options={'maxiter': 500})
    if not np.isfinite(res.x).all():
        raise RuntimeError('Ordinal logistic fit failed: ' + str(res.message))
    t1, d = res.x[:2]
    return dict(theta=res.x.tolist(), cutpoints=[float(t1), float(t1 + np.exp(d))], beta=res.x[2:].tolist(),
                features=['standardized_mean', 'log_spread_ratio'], l2=l2, converged=bool(res.success))


def predict_ordinal(r, m):
    X = np.column_stack([r['zmean'], r['lspread']])
    p = ordinal_probabilities(np.asarray(m['theta']), X)
    p[~np.isfinite(X).all(1) | ~np.isfinite(r['s']).all(-1)] = np.nan
    return p


# ---------------------------------------------------------------- Phase 2: one-vs-rest binary calibrators (Pathway A)
# Each category k gets its own binary calibration of p_k (event "category k" against the rest); the three calibrated values are
# then divided by their sum. The normalized vector is the forecast that is fitted, checked and scored.

FLOOR = 1e-4                                              # protects logs and the normalization against exact 0 / 1


def logit(p):
    p = np.clip(p, FLOOR, 1 - FLOOR)
    return np.log(p / (1 - p))


def normalize(q):
    q = np.clip(q, FLOOR, 1 - FLOOR)
    return q / q.sum(-1, keepdims=True)


def binary_fit(features, t, w, init, bounds=None, l2=0., penalised=()):
    """Weighted logistic fit of the event t on features (with intercept as features[:, 0])."""
    def loss(th):
        z = features @ th
        p = expit(z)
        f = float(-w @ (t * np.log(np.maximum(p, EPS)) + (1 - t) * np.log(np.maximum(1 - p, EPS))))
        g = features.T @ (w * (p - t))
        for i in penalised:
            f += l2 * th[i] ** 2
            g[i] += 2 * l2 * th[i]
        return f, g
    res = minimize(loss, np.asarray(init, float), jac=True, method='L-BFGS-B', bounds=bounds, options={'maxiter': 500})
    if not np.isfinite(res.x).all():
        raise RuntimeError('Binary calibration fit failed: ' + str(res.message))
    return res.x


def fit_platt(records, area, l2=1e-4, **_):
    """Platt scaling per category: q_k = logistic(c + a·logit(p_k)), then normalized."""
    a, w = pack(records, area)
    check_categories(a['y'])
    coef = []
    for k in range(3):
        X = np.column_stack([np.ones(len(w)), logit(a['s'][:, k])])
        coef.append(binary_fit(X, (a['y'] == k).astype(float), w, [0., 1.], l2=l2, penalised=(1,)).tolist())
    return dict(coefficients=coef, features=['intercept', 'logit(p_k)'], normalization='divide by the sum')


def predict_platt(r, m):
    s = np.asarray(r['s'], float)
    q = np.column_stack([expit(c[0] + c[1] * logit(s[:, k])) for k, c in enumerate(m['coefficients'])])
    p = normalize(q)
    p[~np.isfinite(s).all(-1)] = np.nan
    return p


def fit_beta(records, area, **_):
    """Beta calibration per category: logit q_k = c + a·ln p_k − b·ln(1 − p_k), a, b ≥ 0; then normalized."""
    a, w = pack(records, area)
    check_categories(a['y'])
    coef = []
    for k in range(3):
        p = np.clip(a['s'][:, k], FLOOR, 1 - FLOOR)
        X = np.column_stack([np.ones(len(w)), np.log(p), -np.log(1 - p)])
        coef.append(binary_fit(X, (a['y'] == k).astype(float), w, [0., 1., 1.],
                               bounds=[(None, None), (0, None), (0, None)]).tolist())
    return dict(coefficients=coef, features=['intercept', 'ln p_k', '-ln(1 - p_k)'], constraints='a, b >= 0',
                normalization='divide by the sum')


def predict_beta(r, m):
    s = np.clip(np.asarray(r['s'], float), FLOOR, 1 - FLOOR)
    q = np.column_stack([expit(c[0] + c[1] * np.log(s[:, k]) - c[2] * np.log(1 - s[:, k])) for k, c in enumerate(m['coefficients'])])
    p = normalize(q)
    p[~np.isfinite(np.asarray(r['s'], float)).all(-1)] = np.nan
    return p


def weighted_pav(x, t, w):
    """Weighted isotonic (non-decreasing) regression of t on x: block x-means and fitted values (pool adjacent violators)."""
    order = np.argsort(x, kind='stable')
    xs, ts, ws = x[order], t[order], w[order]
    vals, wts, xsum = [], [], []
    for xi, ti, wi in zip(xs, ts, ws):
        vals.append(ti)
        wts.append(wi)
        xsum.append(xi * wi)
        while len(vals) > 1 and vals[-2] > vals[-1]:
            v2, w2, x2 = vals.pop(), wts.pop(), xsum.pop()
            v1, w1, x1 = vals.pop(), wts.pop(), xsum.pop()
            vals.append((v1 * w1 + v2 * w2) / (w1 + w2))
            wts.append(w1 + w2)
            xsum.append(x1 + x2)
    centres = np.array(xsum) / np.array(wts)
    return centres, np.array(vals)


def fit_isotonic(records, area, **_):
    """Isotonic regression per category (pooled over cells and years), then normalized; constant beyond the data."""
    a, w = pack(records, area)
    check_categories(a['y'])
    maps = []
    for k in range(3):
        cx, cv = weighted_pav(a['s'][:, k], (a['y'] == k).astype(float), w)
        maps.append(dict(x=cx.tolist(), y=cv.tolist()))
    return dict(maps=maps, blocks=[len(m['x']) for m in maps], normalization='divide by the sum', floor=FLOOR)


def predict_isotonic(r, m):
    s = np.asarray(r['s'], float)
    q = np.column_stack([np.interp(s[:, k], mp['x'], mp['y']) for k, mp in enumerate(m['maps'])])
    p = normalize(q)
    p[~np.isfinite(s).all(-1)] = np.nan
    return p


# ---------------------------------------------------------------- registry

@dataclass(frozen=True)
class Calibrator:
    key: str
    name: str
    fit: object
    predict: object
    inputs: str
    multiclass: str
    parameters: str
    references: tuple
    incumbent: bool = False
    defaults: dict = field(default_factory=dict)


CALIBRATORS = {c.key: c for c in [
    Calibrator('pseudocount', 'Pseudocount smoothing (no blend)', fit_pseudocount, predict_pseudocount,
               'member counts: p_k = (n_k + alpha) / (M + 3 alpha)', 'joint (counts)', 'alpha fixed (0.5)', ('Wilks 2019',)),
    Calibrator('climatology_blend', 'Climatology blend (incumbent)', fit_blend, predict_blend,
               'smoothed probabilities and training climatology', 'joint', 'lambda: one per target, minimum RPS', ('Rajagopalan et al. 2002',),
               incumbent=True),
    Calibrator('temperature', 'Temperature scaling', fit_temperature, predict_temperature,
               'log smoothed probabilities', 'joint (softmax)', 'one temperature T in 0.25-4, log loss', ('Guo et al. 2017',)),
    Calibrator('dirichlet', 'Regularized Dirichlet calibration', fit_dirichlet_cal, predict_dirichlet_cal,
               'log smoothed probabilities only', 'joint (softmax of a linear map)', '3x3 map + bias, identity-regularized, log loss',
               ('Kull et al. 2019',)),
    Calibrator('multinomial_logistic', 'Regularized multinomial logistic regression', fit_multinomial, predict_multinomial,
               'standardized ensemble mean, log spread ratio (no probabilities)', 'joint (softmax; near = reference)',
               '6 coefficients, L2 on slopes, log loss', ('Wilks 2019',), defaults=dict(l2=1e-3)),
    Calibrator('ordinal_logistic', 'Ordinal (cumulative-logit) logistic regression', fit_ordinal, predict_ordinal,
               'standardized ensemble mean, log spread ratio', 'ordinal (ordered cutpoints)',
               '2 ordered cutpoints + 2 slopes, L2 on slopes, log loss', ('McCullagh 1980',), defaults=dict(l2=1e-3)),
    Calibrator('platt_ovr', 'Platt (sigmoid) calibration, one-vs-rest + normalization', fit_platt, predict_platt,
               'logit of each smoothed category probability', 'one-vs-rest, then divided by the sum',
               '2 per category (intercept, slope), L2 1e-4 on the slope, binary log loss', ('Platt 1999',), defaults=dict(l2=1e-4)),
    Calibrator('beta_ovr', 'Beta calibration, one-vs-rest + normalization', fit_beta, predict_beta,
               'ln p_k and ln(1 - p_k) of each smoothed category probability', 'one-vs-rest, then divided by the sum',
               '3 per category (c, a >= 0, b >= 0), binary log loss', ('Kull et al. 2017',)),
    Calibrator('isotonic_ovr', 'Isotonic regression, one-vs-rest + normalization', fit_isotonic, predict_isotonic,
               'each smoothed category probability', 'one-vs-rest, then divided by the sum',
               'monotone step map per category, pooled over cells and years (weighted pool-adjacent-violators)',
               ('Zadrozny & Elkan 2002',)),
]}
INCUMBENT = 'climatology_blend'


def fit(key, records, area, params=None):
    """Fit a calibrator; on failure fall back to the incumbent and record why."""
    c = CALIBRATORS[key]
    p = {**c.defaults, **(params or {})}
    try:
        return dict(key=key, model=c.fit(records, area, **p), fallback=None)
    except (ValueError, RuntimeError, FloatingPointError, np.linalg.LinAlgError) as exc:
        return dict(key=key, model=CALIBRATORS[INCUMBENT].fit(records, area), fallback=f'{type(exc).__name__}: {exc}')


def predict(fitted, record):
    c = CALIBRATORS[INCUMBENT if fitted['fallback'] else fitted['key']]
    p = np.asarray(c.predict(record, fitted['model']), float)
    ok = np.isfinite(p).all(-1)
    if ok.any() and ((p[ok] < -1e-12).any() or not np.allclose(p[ok].sum(-1), 1, atol=1e-8)):
        raise ValueError(f'Invalid probabilities from {fitted["key"]}')
    return p
