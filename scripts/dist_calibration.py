"""Rainfall-distribution models (docs/48), Phase 2 of "Probability and rainfall-distribution calibration", Pathway B.

Each model predicts a full rainfall distribution for every grid cell from the raw ensemble; tercile probabilities, quantiles
and intervals are derived from it. Common interface:
    model = MODELS[key].fit(samples, **params)              # pooled over cells and years (equal weight per year, area within)
    dist  = MODELS[key].predict(features, model)            # a Distribution for one year's cells
    dist.cdf(x), dist.quantile(u), dist.terciles(q1, q2), dist.crps(y)

Pooling across cells with very different rainfall: amounts are expressed relative to the cell's climatology from the training
years — the observation y' = y / mu_obs, the ensemble mean m' = xbar / mu_model, the spread s' = sd / mu_model and the mean
absolute difference md' = MD / mu_model (mu_obs: CHIRPS mean, mu_model: raw-ensemble mean over the training years, equal-year
weights) — and the predicted distribution is scaled back by mu_obs. Cells with mu_obs or mu_model below 1 mm are not modelled.

Tercile convention (calibration_core): below y < q1, near q1 <= y <= q2, above y > q2, with q1, q2 the training CHIRPS terciles;
with q1 > 0 (probability-eligible cells) there is no atom at the boundaries, so p_below = F(q1), p_near = F(q2) - F(q1),
p_above = 1 - F(q2).
"""
from dataclasses import dataclass, field
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, gammainc, gammaincinv, gammaln

FLOOR = 1e-6


def softplus(x):
    return np.logaddexp(0, x)


# ---------------------------------------------------------------- distributions

class Distribution:
    """A predictive distribution per cell (vectorized over cells); subclasses give cdf and quantile."""

    def __init__(self, scale, valid):
        self.scale = np.asarray(scale, float)               # mu_obs per cell (mm)
        self.valid = np.asarray(valid, bool)

    def terciles(self, q1, q2):
        f1, f2 = self.cdf(q1), self.cdf(q2)
        p = np.column_stack([f1, f2 - f1, 1 - f2])
        p = np.clip(p, 0, 1)
        p /= p.sum(1, keepdims=True)
        p[~self.valid] = np.nan
        return p

    def crps(self, y, points=400):
        """CRPS (mm) by numerical integration of (F(x) - 1{x >= y})^2 on a grid from 0 beyond both y and the 99.9% quantile."""
        top = np.maximum(np.nan_to_num(self.quantile(np.full(len(y), .999)), nan=0.), np.nan_to_num(y)) * 1.05 + 1e-6
        u = np.linspace(0, 1, points)
        x = u[:, None] * top[None, :]
        F = np.stack([self.cdf(xi) for xi in x])
        H = (x >= y[None, :]).astype(float)
        out = np.trapz((F - H) ** 2, x, axis=0)
        return np.where(self.valid & np.isfinite(y), out, np.nan)


class CSGamma(Distribution):
    """Left-censored shifted gamma: Y = max(0, X + delta) * scale, X ~ Gamma(k, theta), delta <= 0."""

    def __init__(self, k, theta, delta, scale, valid):
        super().__init__(scale, valid)
        self.k, self.theta, self.delta = k, theta, delta

    def cdf(self, x):
        z = np.maximum(np.asarray(x, float) / np.where(self.scale > 0, self.scale, 1) - self.delta, 0)
        return np.where(x >= 0, gammainc(self.k, z / self.theta), 0.)

    def quantile(self, u):
        return self.scale * np.maximum(0, gammaincinv(self.k, np.clip(u, FLOOR, 1 - FLOOR)) * self.theta + self.delta)


class Logistic(Distribution):
    """Heteroscedastic extended-logistic distribution: P(Y <= q) = logistic((sqrt(q / scale) - mu) / sigma)."""

    def __init__(self, mu, sigma, scale, valid):
        super().__init__(scale, valid)
        self.mu, self.sigma = mu, sigma

    def cdf(self, x):
        x = np.maximum(np.asarray(x, float), 0)
        return expit((np.sqrt(x / np.where(self.scale > 0, self.scale, 1)) - self.mu) / self.sigma)

    def quantile(self, u):
        u = np.clip(u, FLOOR, 1 - FLOOR)
        return self.scale * np.maximum(0, self.mu + self.sigma * np.log(u / (1 - u))) ** 2


class Quantiles(Distribution):
    """Piecewise-linear CDF through predicted quantiles q_tau (relative units), non-crossing by rearrangement.

    Tail policy: F rises linearly from 0 at 0 to tau_min at q_tau_min; above q_tau_max it rises linearly to 1 at
    q_tau_max + (q_tau_max - q_0.5).
    """

    def __init__(self, levels, q_rel, scale, valid):
        super().__init__(scale, valid)
        self.levels = np.asarray(levels, float)
        q = np.sort(np.maximum(q_rel, 0), axis=0)            # rearrangement (non-crossing) and non-negative support
        top = q[-1] + np.maximum(q[-1] - q[len(levels) // 2], 1e-3)
        self.knots = np.vstack([np.zeros(q.shape[1]), q, top])      # relative units
        self.probs = np.r_[0., self.levels, 1.]

    def cdf(self, x):
        """Piecewise-linear interpolation through each cell's knots (vectorized over cells)."""
        xr = np.asarray(x, float) / np.where(self.scale > 0, self.scale, 1)
        K = self.knots
        i = np.clip((K <= xr[None, :]).sum(0) - 1, 0, len(K) - 2)
        cols = np.arange(K.shape[1])
        x0, x1 = K[i, cols], K[i + 1, cols]
        frac = np.where(x1 > x0, (xr - x0) / np.where(x1 > x0, x1 - x0, 1), 1.)
        out = self.probs[i] + np.clip(frac, 0, 1) * (self.probs[i + 1] - self.probs[i])
        return np.where(xr >= K[-1], 1., out)

    def quantile(self, u):
        u = np.clip(np.asarray(u, float), 0, 1)
        i = np.clip(np.searchsorted(self.probs, u, side='right') - 1, 0, len(self.probs) - 2)
        cols = np.arange(self.knots.shape[1])
        frac = (u - self.probs[i]) / (self.probs[i + 1] - self.probs[i])
        return (self.knots[i, cols] + frac * (self.knots[i + 1, cols] - self.knots[i, cols])) * self.scale


# ---------------------------------------------------------------- models

def emos_fit(S, **_):
    """EMOS with a censored shifted gamma (Scheuerer & Hamill 2015 form), fitted by weighted maximum likelihood.

    mean mu = softplus(a0 + a1 m'), sd sigma = softplus(b0 + b1 md'), shift delta = -softplus(d) (all relative units).
    """
    y, m, md, w = S['y'], S['m'], S['md'], S['w']
    zero = y <= 0

    def nll(th):
        mu, sg, de = softplus(th[0] + th[1] * m), softplus(th[2] + th[3] * md) + 1e-3, -softplus(th[4])
        k, theta = (mu / sg) ** 2, sg ** 2 / mu
        z = np.maximum(y - de, 1e-9)
        lp = np.where(zero, np.log(np.maximum(gammainc(k, -de / theta), 1e-300)),
                      (k - 1) * np.log(z) - z / theta - gammaln(k) - k * np.log(theta))
        return float(-w @ lp)
    best = None
    for start in ([0., 1., -1., 1., -3.], [.5, .5, -.5, .5, -2.]):
        res = minimize(nll, np.array(start), method='L-BFGS-B', options={'maxiter': 400})
        if np.isfinite(res.fun) and (best is None or res.fun < best.fun):
            best = res
    if best is None or not np.isfinite(best.x).all():
        raise RuntimeError('EMOS fit failed')
    return dict(theta=best.x.tolist(), converged=bool(best.success),
                form='mu = softplus(a0 + a1 m), sigma = softplus(b0 + b1 md), delta = -softplus(d)')


def emos_predict(F, model):
    th = np.asarray(model['theta'])
    mu, sg, de = softplus(th[0] + th[1] * F['m']), softplus(th[2] + th[3] * F['md']) + 1e-3, -softplus(th[4])
    return CSGamma((mu / sg) ** 2, sg ** 2 / mu, de, F['scale'], F['valid'])


THRESHOLD_LEVELS = (.1, .2, .3, .4, .5, .6, .7, .8, .9)


def helr_fit(S, **_):
    """Heteroscedastic extended logistic regression (Messner et al. 2014 form) on climatological thresholds.

    P(Y' <= q') = logistic((sqrt(q') - (b0 + b1 sqrt(m'))) / exp(g0 + g1 log s')); thresholds: each cell's training CHIRPS
    deciles (relative units). Weighted log loss over all thresholds (each threshold set weighs like one sample).
    """
    y, m, s, w, thr = S['y'], S['m'], S['s'], S['w'], S['thresholds']        # thr: (n, J)
    sq = np.sqrt(np.maximum(thr, 0))
    t = (y[:, None] <= thr).astype(float)
    xm, xs = np.sqrt(np.maximum(m, 0)), np.log(np.maximum(s, 1e-3))
    ww = w[:, None] / thr.shape[1]

    def loss(th):
        mu, sg = th[0] + th[1] * xm, np.exp(th[2] + th[3] * xs)
        z = (sq - mu[:, None]) / sg[:, None]
        p = np.clip(expit(z), 1e-12, 1 - 1e-12)
        return float(-(ww * (t * np.log(p) + (1 - t) * np.log(1 - p))).sum())
    res = minimize(loss, np.array([0., 1., -1., 0.]), method='L-BFGS-B', options={'maxiter': 400})
    if not np.isfinite(res.x).all():
        raise RuntimeError('HELR fit failed')
    return dict(theta=res.x.tolist(), converged=bool(res.success), thresholds='training CHIRPS deciles of each cell')


def helr_predict(F, model):
    th = np.asarray(model['theta'])
    mu = th[0] + th[1] * np.sqrt(np.maximum(F['m'], 0))
    sg = np.exp(th[2] + th[3] * np.log(np.maximum(F['s'], 1e-3)))
    return Logistic(mu, sg, F['scale'], F['valid'])


QR_LEVELS = tuple(np.round(np.arange(.05, .951, .05), 2))


def qr_fit(S, l2=1e-4, smooth=1e-3, **_):
    """Regularized linear quantile regression per level (pinball loss, Huber-smoothed for the optimizer), q'_tau = b0 + b1 m' + b2 s'."""
    X = np.column_stack([np.ones(len(S['y'])), S['m'], S['s']])
    y, w = S['y'], S['w']
    coefs = []
    for tau in QR_LEVELS:
        def loss(b):
            r = y - X @ b
            a = np.abs(r)
            huber = np.where(a <= smooth, r * r / (2 * smooth), a - smooth / 2)
            dh = np.where(a <= smooth, r / smooth, np.sign(r))
            wt = np.where(r >= 0, tau, 1 - tau)
            f = float(w @ (wt * huber)) + l2 * float(b[1:] @ b[1:])
            g = -X.T @ (w * wt * dh)
            g[1:] += 2 * l2 * b[1:]
            return f, g
        res = minimize(loss, np.array([np.quantile(y, tau), 0., 0.]), jac=True, method='L-BFGS-B', options={'maxiter': 500})
        if not np.isfinite(res.x).all():
            raise RuntimeError(f'Quantile regression failed at tau={tau}')
        coefs.append(res.x.tolist())
    return dict(levels=list(QR_LEVELS), coefficients=coefs, l2=l2, tails='linear to 0 below the lowest level; linear to 1 at '
                'q_max + (q_max - q_0.5) above the highest', noncrossing='rearrangement (sorting) of the predicted quantiles')


def qr_predict(F, model):
    X = np.column_stack([np.ones(len(F['m'])), F['m'], F['s']])
    q = np.array([X @ np.asarray(b) for b in model['coefficients']])
    d = Quantiles(model['levels'], np.nan_to_num(q), F['scale'], F['valid'])
    d.crossings = float(np.mean(np.any(np.diff(q, axis=0) < 0, axis=0)[F['valid']])) if F['valid'].any() else 0.
    return d


@dataclass(frozen=True)
class Model:
    key: str
    name: str
    fit: object
    predict: object
    estimates: str
    predictors: str
    fitting: str
    references: tuple
    defaults: dict = field(default_factory=dict)


MODELS = {m.key: m for m in [
    Model('emos_csg', 'EMOS, censored shifted gamma', emos_fit, emos_predict,
          'rainfall distribution with a probability of zero', "ensemble mean m' and mean absolute difference md' (relative)",
          'maximum likelihood, pooled over cells', ('Scheuerer & Hamill 2015',)),
    Model('extended_logistic', 'Heteroscedastic extended logistic regression', helr_fit, helr_predict,
          'coherent CDF across all thresholds', "sqrt of the ensemble mean m', log spread s' (relative)",
          'log loss over each cell’s CHIRPS deciles, pooled', ('Wilks 2009', 'Messner et al. 2014')),
    Model('quantile_regression', 'Regularized quantile regression', qr_fit, qr_predict,
          'conditional quantiles at 19 levels (5–95%), CDF by interpolation', "ensemble mean m' and spread s' (relative)",
          'pinball loss per level (Huber-smoothed), L2 1e-4, pooled', ('Koenker & Bassett 1978',), defaults=dict(l2=1e-4)),
]}


def features(members, mu_obs, mu_model, valid):
    """Relative ensemble predictors of one year's members (member, cell)."""
    xbar, sd = members.mean(0), members.std(0)
    md = np.abs(members[:, None, :] - members[None, :, :]).mean((0, 1))
    scale = np.where(mu_model > 0, mu_model, np.nan)
    return dict(m=xbar / scale, s=sd / scale, md=md / scale, scale=mu_obs, valid=valid)
