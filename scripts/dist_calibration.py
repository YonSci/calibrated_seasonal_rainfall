"""Rainfall-distribution models (docs/48), Phases 2 and 3 of "Probability and rainfall-distribution calibration", Pathway B.

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

SCORING_VERSION = 2                  # CRPS rule: 1 = one uniform 400-point grid; 2 = split at the observation, closed form for CSG
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
        """CRPS (mm): integral of F(x)^2 from 0 to y plus (1 - F(x))^2 from y to beyond the 99.99% quantile, by the trapezoidal
        rule on points / 2 nodes on each side of the observation (SCORING_VERSION 2; scripts/crps_precision.py: within 0.15%
        of adaptive quadrature on dry, ordinary, wet and extreme cases, where a single uniform grid erred by up to 0.7%)."""
        y0 = np.nan_to_num(np.asarray(y, float))
        top = np.maximum(np.nan_to_num(self.quantile(np.full(len(y0), .9999)), nan=0.), y0) * 1.05 + 1e-6
        n = max(2, points // 2)
        u = np.linspace(0, 1, n)[:, None]
        a, b = u * y0[None, :], y0[None, :] + u * (top - y0)[None, :]
        Fa, Fb = np.stack([self.cdf(xi) for xi in a]), np.stack([self.cdf(xi) for xi in b])
        out = np.trapz(Fa ** 2, a, axis=0) + np.trapz((1 - Fb) ** 2, b, axis=0)
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

    def crps(self, y, points=400):
        """The closed form of Scheuerer & Hamill (2015) (neural_calibration.crps_csg), in mm."""
        from neural_calibration import crps_csg
        sc = np.where(self.scale > 0, self.scale, 1)
        out = sc * crps_csg(self.k, self.theta, self.delta, np.nan_to_num(np.asarray(y, float)) / sc)
        return np.where(self.valid & np.isfinite(y), out, np.nan)


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


# ---------------------------------------------------------------- Phase 3

def _logsinh(x, a, b):
    """Log-sinh transform z = log(sinh(a + b x)) / b (Wang et al. 2012), stable for large arguments; x >= 0, a, b > 0."""
    v = a + b * np.maximum(x, 0)
    return (v + np.log1p(-np.exp(-2 * v)) - np.log(2)) / b


def _logsinh_inv(z, a, b):
    w = b * z
    big = w > 20
    ash = np.where(big, w + np.log(2), np.arcsinh(np.exp(np.minimum(w, 20))))   # arcsinh(exp(w))
    return np.maximum((ash - a) / b, 0)


def _logsinh_logjac(x, a, b):
    """log dz/dx = log coth(a + b x)."""
    return -np.log(np.tanh(a + b * np.maximum(x, 0)))


class StudentT(Distribution):
    """BJP predictive: in log-sinh space Z ~ t_nu(mean, scale); amounts below the transform of zero are zero (censoring)."""

    def __init__(self, mean, sd, nu, a, b, scale, valid):
        super().__init__(scale, valid)
        self.mean, self.sd, self.nu, self.a, self.b = mean, sd, nu, a, b

    def cdf(self, x):
        from scipy.stats import t
        xr = np.maximum(np.asarray(x, float), 0) / np.where(self.scale > 0, self.scale, 1)
        return np.where(np.asarray(x) >= 0, t.cdf((_logsinh(xr, self.a, self.b) - self.mean) / self.sd, self.nu), 0.)

    def quantile(self, u):
        from scipy.stats import t
        z = self.mean + self.sd * t.ppf(np.clip(u, FLOOR, 1 - FLOOR), self.nu)
        return self.scale * _logsinh_inv(z, self.a, self.b)


def bjp_fit(S, **_):
    """Bayesian joint probability (Wang et al. 2009; Wang & Robertson 2011), pooled over cells in relative units.

    The ensemble mean m' and the observation y' are each log-sinh transformed; in transformed space they are bivariate
    normal, i.e. z_y = c0 + c1 (z_m - mean_m) / sd_m + e, e ~ N(0, s^2), with y' = 0 left-censored at the transform of zero.
    Transformation and normal parameters are fitted by weighted maximum likelihood (the posterior mode under flat priors);
    the uncertainty of the normal parameters is integrated analytically under the reference prior, with the number of
    training years as the effective sample size (cells of one year are not independent): a Student-t predictive with
    nu = years - 2 and scale s * sqrt(1 + 1/years + d^2/years), d the standardized predictor.
    """
    from scipy.stats import norm
    y, m, w, years = S['y'], S['m'], S['w'], int(S['n_years'])
    mpos = np.maximum(m, 1e-6)

    def nll_m(th):
        a, b = np.exp(th[0]), np.exp(th[1])
        z = _logsinh(mpos, a, b)
        mu, sd = th[2], np.exp(th[3])
        return float(-w @ (norm.logpdf(z, mu, sd) + _logsinh_logjac(mpos, a, b)))
    rm = minimize(nll_m, np.array([np.log(.1), 0., 1., np.log(.5)]), method='L-BFGS-B',
                  bounds=[(-9, 3), (-5, 3), (None, None), (-8, 8)], options={'maxiter': 500})
    am, bm, mum, sdm = np.exp(rm.x[0]), np.exp(rm.x[1]), rm.x[2], np.exp(rm.x[3])
    d = (_logsinh(mpos, am, bm) - mum) / sdm
    zero = y <= 1e-6

    def nll_y(th):
        a, b = np.exp(th[0]), np.exp(th[1])
        mean, sd = th[2] + th[3] * d, np.exp(th[4])
        z = _logsinh(y, a, b)
        lp = np.where(zero, norm.logcdf((_logsinh(0., a, b) - mean) / sd),
                      norm.logpdf(z, mean, sd) + _logsinh_logjac(y, a, b))
        return float(-w @ lp)
    ry = minimize(nll_y, np.array([np.log(.1), 0., 1., .3, np.log(.5)]), method='L-BFGS-B',
                  bounds=[(-9, 3), (-5, 3), (None, None), (None, None), (-8, 8)], options={'maxiter': 500})
    if not (np.isfinite(rm.x).all() and np.isfinite(ry.x).all()):
        raise RuntimeError('BJP fit failed')
    return dict(predictor=dict(a=float(am), b=float(bm), mean=float(mum), sd=float(sdm)),
                observation=dict(a=float(np.exp(ry.x[0])), b=float(np.exp(ry.x[1]))),
                regression=dict(c0=float(ry.x[2]), c1=float(ry.x[3]), sd=float(np.exp(ry.x[4]))),
                effective_sample_size=int(years), nu=int(years) - 2, converged=bool(rm.success and ry.success))


def bjp_predict(F, model):
    p, o, r = model['predictor'], model['observation'], model['regression']
    n = model['effective_sample_size']
    d = (_logsinh(np.maximum(np.nan_to_num(F['m']), 1e-6), p['a'], p['b']) - p['mean']) / p['sd']
    sd = r['sd'] * np.sqrt(1 + 1 / n + d ** 2 / n)
    return StudentT(r['c0'] + r['c1'] * d, sd, model['nu'], o['a'], o['b'], F['scale'], F['valid'])


class MemberMixture(Distribution):
    """BMA predictive: equal-weight mixture over members of a point mass at zero and a gamma for the cube root of the amount."""

    def __init__(self, p0, k, theta, scale, valid):
        super().__init__(scale, valid)
        self.p0, self.k, self.theta = p0, k, theta                 # (member, cell); NaN for absent members
        self.wt = np.isfinite(p0) / np.maximum(np.isfinite(p0).sum(0), 1)

    def _cdf_root(self, r):
        g = gammainc(np.nan_to_num(self.k, nan=1.), np.maximum(r, 0)[None, :] / np.nan_to_num(self.theta, nan=1.))
        return np.sum(self.wt * (np.nan_to_num(self.p0) + (1 - np.nan_to_num(self.p0)) * g), 0)

    def cdf(self, x):
        x = np.asarray(x, float)
        xr = np.maximum(x, 0) / np.where(self.scale > 0, self.scale, 1)
        return np.where(x >= 0, self._cdf_root(np.cbrt(xr)), 0.)

    def quantile(self, u, iterations=50):
        u = np.clip(np.asarray(u, float), FLOOR, 1 - FLOOR)
        lo = np.zeros(self.p0.shape[1])
        mean, sd = np.nan_to_num(self.k * self.theta), np.nan_to_num(np.sqrt(self.k) * self.theta)
        hi = np.max(mean + 12 * sd, 0) + 1e-6
        for _ in range(iterations):                                # bisection on the cube root
            mid = (lo + hi) / 2
            below = self._cdf_root(mid) < u
            lo, hi = np.where(below, mid, lo), np.where(below, hi, mid)
        return self.scale * ((lo + hi) / 2) ** 3


def _bma_parts(th, f):
    """Member-level PoP and gamma parameters; f: relative member amounts (sample/cell, member), NaN where absent."""
    fr = np.cbrt(np.maximum(f, 0))
    eta = th[0] + th[1] * fr + th[2] * (f <= 0)
    lin = th[3] + th[4] * fr
    mu = softplus(lin)
    v = softplus(th[5]) + softplus(th[6]) * np.maximum(f, 0) + 1e-6
    return fr, eta, lin, mu, v


def bma_fit(S, **_):
    """BMA for precipitation (Sloughter et al. 2007), exchangeable members with equal weights (Fraley et al. 2010).

    Each member kernel: P(Y' = 0) = logistic(a0 + a1 f^(1/3) + a2 1{f = 0}); given Y' > 0, Y'^(1/3) ~ Gamma with mean
    softplus(b0 + b1 f^(1/3)) and variance softplus(c0) + softplus(c1) f (relative units). All seven parameters are fitted
    jointly by weighted maximum likelihood of the mixture (analytic gradient).
    """
    from scipy.special import digamma
    y, w, f = S['y'], S['w'], S['members']
    ok = np.isfinite(f)
    f0 = np.where(ok, f, 0.)
    logpi = np.where(ok, -np.log(np.maximum(ok.sum(1, keepdims=True), 1)), -np.inf)
    zero = (y <= 1e-6)[:, None]
    z = np.cbrt(np.maximum(y, 1e-12))[:, None]

    def f_and_g(th):
        fr, eta, lin, mu, v = _bma_parts(th, f0)
        k, r = mu ** 2 / v, mu / v
        lg = k * np.log(r) - gammaln(k) + (k - 1) * np.log(z) - r * z
        l = np.where(zero, -softplus(-eta), -softplus(eta) + lg) + logpi
        mx = np.max(l, 1, keepdims=True)
        tot = mx[:, 0] + np.log(np.sum(np.exp(l - mx), 1))
        resp = np.exp(l - tot[:, None]) * w[:, None]              # weighted responsibilities
        p0 = expit(eta)
        de = np.where(zero, 1 - p0, -p0)
        dk = np.where(zero, 0., np.log(r) - digamma(k) + np.log(z))
        dr = np.where(zero, 0., k / r - z)
        dmu = dk * 2 * mu / v + dr / v
        dv = -dk * mu ** 2 / v ** 2 - dr * mu / v ** 2
        dlin = dmu * expit(lin)
        g = np.array([np.sum(resp * de), np.sum(resp * de * fr), np.sum(resp * de * (f0 <= 0)),
                      np.sum(resp * dlin), np.sum(resp * dlin * fr),
                      np.sum(resp * dv) * expit(th[5]), np.sum(resp * dv * np.maximum(f0, 0)) * expit(th[6])])
        return -float(w @ tot), -g
    res = minimize(f_and_g, np.array([-4., -1., 1., 0., 1., -3., -3.]), jac=True, method='L-BFGS-B', options={'maxiter': 500})
    if not np.isfinite(res.x).all():
        raise RuntimeError('BMA fit failed')
    return dict(theta=res.x.tolist(), converged=bool(res.success), weights='equal (exchangeable members)',
                form='logit P0 = a0 + a1 f^(1/3) + a2 1{f=0}; Y^(1/3)|Y>0 ~ Gamma(mean softplus(b0 + b1 f^(1/3)), '
                     'variance softplus(c0) + softplus(c1) f)')


def bma_predict(F, model):
    th = np.asarray(model['theta'])
    f = F['members']                                               # (member, cell), relative
    _, eta, _, mu, v = _bma_parts(th, np.nan_to_num(f))
    absent = ~np.isfinite(f)
    p0 = np.where(absent, np.nan, expit(eta))
    return MemberMixture(p0, np.where(absent, np.nan, mu ** 2 / v), np.where(absent, np.nan, v / mu), F['scale'], F['valid'])


QRF_LEVELS = tuple(np.round(np.arange(.025, .976, .025), 3))
QRF_PREDICTORS = ('m', 's', 'md', 'q10', 'q90', 'logmu', 'cv')


def qrf_fit(S, trees=200, min_leaf=40, max_features=.5, seed=0, **_):
    """Quantile regression forest (Meinshausen 2006): a random forest of the relative amount on ensemble and climatology
    predictors; the predictive distribution is the leaf-weighted empirical distribution of the training amounts."""
    from sklearn.ensemble import RandomForestRegressor
    X = np.column_stack([S[k] for k in QRF_PREDICTORS])
    forest = RandomForestRegressor(n_estimators=trees, min_samples_leaf=min_leaf, max_features=max_features, random_state=seed,
                                   n_jobs=1).fit(X, S['y'], sample_weight=S['w'] * len(S['y']))
    leaves = forest.apply(X)                                       # (sample, tree)
    return dict(_forest=forest, _leaves=leaves, _y=S['y'].copy(), _w=S['w'].copy(), trees=trees, min_leaf=min_leaf,
                max_features=max_features, seed=seed, predictors=list(QRF_PREDICTORS), levels=list(QRF_LEVELS),
                weights='all training samples of each leaf, by sample weight (Meinshausen 2006)')


def qrf_predict(F, model, chunk=150):
    from scipy import sparse
    forest, L, y, w = model['_forest'], model['_leaves'], model['_y'], model['_w']
    n, T = L.shape
    off = np.r_[0, np.cumsum(L.max(0) + 1)[:-1]]                    # leaf ids made unique across trees
    col = (L + off).ravel()
    leaf_sum = np.bincount(col, weights=np.repeat(w, T), minlength=off[-1] + L[:, -1].max() + 1)
    order = np.argsort(y)
    rank = np.empty(n, int)
    rank[order] = np.arange(n)
    A = sparse.csr_matrix((np.repeat(w, T) / leaf_sum[col] / T, (col, np.repeat(rank, T))), shape=(len(leaf_sum), n))
    X = np.column_stack([np.nan_to_num(F[k]) for k in QRF_PREDICTORS])
    lt = forest.apply(X) + off                                      # (cell, tree)
    lt = np.minimum(lt, len(leaf_sum) - 1)
    levels = np.asarray(model['levels'])
    q = np.zeros((len(levels), len(X)))
    ys = y[order]
    for s in range(0, len(X), chunk):
        rows = lt[s:s + chunk]
        Ind = sparse.csr_matrix((np.ones(rows.size), (np.repeat(np.arange(len(rows)), T), rows.ravel())), shape=(len(rows), len(leaf_sum)))
        C = np.cumsum((Ind @ A).toarray(), 1)                      # weighted CDF at the sorted training amounts
        C /= C[:, -1:]
        idx = np.minimum(np.array([np.searchsorted(c, levels) for c in C]), n - 1)      # first amount with CDF >= level
        q[:, s:s + chunk] = ys[idx].T
    return Quantiles(levels, q, F['scale'], F['valid'])


def _drn_fit(S, **params):
    import neural_calibration                           # JAX, only when a neural model is used (docs/54)
    return neural_calibration.fit(S, **params)


def _drn_predict(F, model):
    import neural_calibration
    return neural_calibration.predict(F, model)


class Pool(Distribution):
    """Equal-weight linear pool of predictive distributions (stacking, docs/54 3g): F = mean of the members' CDFs; quantiles by
    bisection; the CRPS by the split rule of Distribution.crps (scoring version 2)."""

    def __init__(self, members, weights=None):
        m0 = members[0]
        super().__init__(m0.scale, np.logical_and.reduce([m.valid for m in members]))
        self.members = list(members)
        self.weights = np.full(len(members), 1 / len(members)) if weights is None else np.asarray(weights, float) / np.sum(weights)

    def cdf(self, x):
        return np.sum([w * np.clip(m.cdf(x), 0, 1) for w, m in zip(self.weights, self.members)], axis=0)

    def quantile(self, u, iterations=60):
        u = np.clip(np.asarray(u, float), FLOOR, 1 - FLOOR)
        hi = np.max([np.nan_to_num(m.quantile(u), nan=0.) for m in self.members], axis=0) * 1.0001 + 1e-9
        lo = np.zeros_like(hi)
        for _ in range(iterations):
            mid = (lo + hi) / 2
            below = self.cdf(mid) < u
            lo, hi = np.where(below, mid, lo), np.where(below, hi, mid)
        return np.where(self.cdf(np.zeros_like(u)) >= u, 0., hi)


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
    Model('bjp', 'Bayesian joint probability', bjp_fit, bjp_predict,
          'rainfall distribution (log-sinh normal, censored at zero, Student-t predictive)', "ensemble mean m' (relative)",
          'censored maximum likelihood of the transforms and the joint normal; parameter uncertainty integrated with the '
          'number of training years as the effective sample', ('Wang et al. 2009', 'Wang & Robertson 2011', 'Wang et al. 2012')),
    Model('bma_precipitation', 'Bayesian model averaging for precipitation', bma_fit, bma_predict,
          'mixture over members: probability of zero and a gamma for the cube root of the amount',
          "each member's amount f' (relative), equal weights for exchangeable members",
          'maximum likelihood of the mixture, pooled', ('Sloughter et al. 2007', 'Fraley et al. 2010')),
    Model('quantile_regression_forest', 'Quantile regression forest', qrf_fit, qrf_predict,
          'conditional distribution as leaf-weighted training amounts; quantiles at 39 levels (2.5–97.5%)',
          "m', s', md', ensemble 10% and 90% quantiles (relative), log climatological mean, CHIRPS coefficient of variation",
          '200 trees, at least 40 samples per leaf, half the predictors per split, pooled', ('Meinshausen 2006',),
          defaults=dict(trees=200, min_leaf=40, max_features=.5, seed=0)),
    Model('drn_csg', 'Distributional regression network (DRN), censored shifted gamma', _drn_fit, _drn_predict,
          'rainfall distribution with a probability of zero (mixture of 3 seeds)',
          "m', ensemble median, s', md', ensemble 10% and 90% quantiles (relative), log climatological mean, CHIRPS coefficient "
          'of variation, latitude, longitude',
          'shared MLP (32 or 32-16 ELU units) -> CSG parameters; CRPS + weight decay; early stopping on held-out years; '
          'architecture and decay by validation CRPS, pooled', ('Rasp & Lerch 2018', 'Scheuerer & Hamill 2015',
                                                               'Uttarwar et al. 2025'), defaults=dict(inputs='full')),
    Model('drn_linear_csg', 'Linear CSG with the DRN inputs and CRPS (control)', _drn_fit, _drn_predict,
          'rainfall distribution with a probability of zero (mixture of 3 seeds)', 'the DRN inputs',
          'no hidden layer; CRPS; early stopping on held-out years, pooled', ('Scheuerer & Hamill 2015',),
          defaults=dict(inputs='full', configs=[([], 0.0)])),
    Model('drn_climatology', 'DRN without the forecast (climatology and location; ablation)', _drn_fit, _drn_predict,
          'rainfall distribution with a probability of zero (mixture of 3 seeds)',
          'log climatological mean, CHIRPS coefficient of variation, latitude, longitude (no SEAS5 input)',
          'as the DRN', ('Rasp & Lerch 2018',), defaults=dict(inputs='climatology')),
    Model('drn_forecast_only', 'DRN on the ensemble only (no climatology or location; ablation)', _drn_fit, _drn_predict,
          'rainfall distribution with a probability of zero (mixture of 3 seeds)',
          "m', ensemble median, s', md', ensemble 10% and 90% quantiles (relative); no local context",
          'as the DRN', ('Rasp & Lerch 2018',), defaults=dict(inputs='forecast')),
    Model('drn_sst', 'DRN with SST indices and rainfall regions', _drn_fit, _drn_predict,
          'rainfall distribution with a probability of zero (mixture of 3 seeds)',
          "the DRN inputs, SEAS5 Nino 3.4 and Indian Ocean Dipole indices of the target months, EMI rainfall regions "
          '(Korecha & Sorteberg 2013, one-hot)', 'as the DRN', ('Rasp & Lerch 2018', 'Korecha & Sorteberg 2013'),
          defaults=dict(inputs='full_sst')),
    Model('drn_regions', 'DRN with rainfall regions, no SST (control of drn_sst)', _drn_fit, _drn_predict,
          'rainfall distribution with a probability of zero (mixture of 3 seeds)', 'the DRN inputs and the EMI rainfall regions (one-hot), no SST',
          'as the DRN; separates the contribution of the SST indices from that of the regions', ('Rasp & Lerch 2018', 'Korecha & Sorteberg 2013'),
          defaults=dict(inputs='full_regions')),
    Model('drn_pooled', 'DRN pooled over the months of a cycle', _drn_fit, _drn_predict,
          'rainfall distribution with a probability of zero (mixture of 3 seeds)',
          "the DRN inputs and the month's position in the season (one-hot)",
          'one network for the four months (pooled_benchmark.py), otherwise as the DRN', ('Rasp & Lerch 2018',),
          defaults=dict(inputs='pooled')),
    Model('drn_pooled_residual', 'Neural correction of EMOS pooled over the months of a cycle', _drn_fit, _drn_predict,
          'rainfall distribution with a probability of zero (mixture of 3 seeds)',
          "the pooled DRN inputs; each month's own EMOS (mean and mean absolute difference) as the base",
          'one network for the four months (pooled_benchmark.py) added to the EMOS of each month, starting at zero, with a penalty on '
          'the correction', ('Scheuerer & Hamill 2015', 'Rasp & Lerch 2018'), defaults=dict(inputs='pooled', residual='emos')),
    Model('drn_pooled_nbhd', 'DRN pooled over the months, with neighbourhood inputs', _drn_fit, _drn_predict,
          'rainfall distribution with a probability of zero (mixture of 3 seeds)',
          "the pooled DRN inputs and 3x3 / 5x5 neighbourhood means of the ensemble summaries",
          'one network for the four months (pooled_benchmark.py), otherwise as the DRN', ('Rasp & Lerch 2018',),
          defaults=dict(inputs='pooled_nbhd')),
    Model('drn_pooled_all', 'DRN pooled over the months of all four cycles', _drn_fit, _drn_predict,
          'rainfall distribution with a probability of zero (mixture of 3 seeds)',
          "the pooled DRN inputs and the cycle (one-hot)",
          'one network for the 16 months of the four cycles (pooled_all_benchmark.py), otherwise as the DRN', ('Rasp & Lerch 2018',),
          defaults=dict(inputs='pooled_all')),
    Model('drn_fmam_ondj', 'DRN pooled over the months of the FMAM and ONDJ cycles', _drn_fit, _drn_predict,
          'rainfall distribution with a probability of zero (mixture of 3 seeds)',
          "the pooled DRN inputs and the cycle (one-hot)",
          'one network for the 12 months of the two FMAM cycles and ONDJ, without JJAS (pooled_all_benchmark.py), otherwise as '
          'the DRN', ('Rasp & Lerch 2018',), defaults=dict(inputs='fmam_ondj')),
    Model('drn_csg_tuned', 'DRN with a separate tuning split (diagnostic)', _drn_fit, _drn_predict,
          'rainfall distribution with a probability of zero (mixture of 3 seeds)', 'the DRN inputs',
          'configuration chosen by 3 inner folds of years, apart from the early-stopping years', ('Rasp & Lerch 2018',),
          defaults=dict(inputs='full', tuning='separate')),
    Model('drn_emos_residual', 'Neural correction of EMOS (censored shifted gamma)', _drn_fit, _drn_predict,
          'rainfall distribution with a probability of zero (mixture of 3 seeds)',
          'the DRN inputs; EMOS (mean and mean absolute difference) as the base',
          "EMOS by maximum likelihood, then a network added to its linear predictors, starting at zero, with a penalty on the "
          'correction; CRPS, early stopping on held-out years', ('Scheuerer & Hamill 2015', 'Rasp & Lerch 2018'),
          defaults=dict(inputs='full', residual='emos')),
]}


def features(members, mu_obs, mu_model, valid, cv=None, lat=None, lon=None):
    """Relative ensemble predictors of one year's members (member, cell); cv: the cell's training CHIRPS coefficient of
    variation (climatology predictor of the quantile regression forest); lat, lon: the cells' coordinates (DRN)."""
    xbar, sd = members.mean(0), members.std(0)
    md = np.abs(members[:, None, :] - members[None, :, :]).mean((0, 1))
    scale = np.where(mu_model > 0, mu_model, np.nan)
    q10, q50, q90 = np.quantile(members, [.1, .5, .9], axis=0)
    zero = np.zeros_like(xbar)
    return dict(m=xbar / scale, s=sd / scale, md=md / scale, q10=q10 / scale, q50=q50 / scale, q90=q90 / scale,
                members=members / scale, logmu=np.log(np.maximum(mu_obs, 1e-3)), cv=zero if cv is None else cv,
                lat=zero if lat is None else lat, lon=zero if lon is None else lon, scale=mu_obs, valid=valid)
