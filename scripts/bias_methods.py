"""Rainfall-amount bias-correction methods for seasonal ensemble totals (one target, every grid cell).

Interface, the same for every method (docs/47):
    state = METHODS[name].fit(models, obs, **params)
        models : list over training years of (member, cell) arrays of model totals (mm)
        obs    : (year, cell) CHIRPS totals for the same years (mm)
    out = METHODS[name].apply(members, state, **params)
        members: (member, cell) model totals of one forecast (the target year); out has one row per member,
                 except Delta Change (one row per training year).

Equal-year weighting: a training year has total weight 1/Y however many members it has (25 members to 2016,
51 from 2017), so each member of year y weighs 1/(Y M_y). Each observed year weighs 1/Y. Every member is
corrected individually. Cells with missing observations in any training year are returned as NaN.

Methods that keep a "change signal" (DC, DQM, QDM, SDM, CDF-t) were built for climate change (reference vs
future period). Here the "future" is the forecast itself: the target year's ensemble against the model
climatology of the training years.
"""
from dataclasses import dataclass, field
import numpy as np
from scipy.special import digamma, polygamma, gammainc, gammaincinv

EPS = 1e-9


# ---------------------------------------------------------------- weighted helpers (equal-year weighting)

def pooled(models):
    """All training members stacked, with weights 1/(Y*M_y) that sum to 1."""
    x = np.concatenate([np.asarray(m, float) for m in models])
    w = np.concatenate([np.full(len(m), 1. / (len(models) * len(m))) for m in models])
    return x, w


def wmean(x, w):
    return w @ x


def wstd(x, w):
    mu = w @ x
    return np.sqrt(np.maximum(w @ (x * x) - mu * mu, 0))


class Ecdf:
    """Weighted empirical CDF for every cell (column).

    Distinct values with mid-point (Hazen) plotting positions, linear between them and constant beyond
    them. Tied values, such as a mass of zeros, share one position in the middle of their probability.
    """

    def __init__(self, x, w=None):
        x = np.asarray(x, float)
        n = len(x)
        w = np.full(n, 1. / n) if w is None else np.asarray(w, float) / np.sum(w)
        self.v, self.p = [], []
        for j in range(x.shape[1]):
            v, inv = np.unique(x[:, j], return_inverse=True)
            wj = np.bincount(inv.ravel(), weights=w, minlength=len(v))
            self.v.append(v)
            self.p.append(np.cumsum(wj) - wj / 2)

    def cdf(self, x, j):
        return np.interp(x, self.v[j], self.p[j])

    def quantile(self, u, j):
        return np.interp(u, self.p[j], self.v[j])

    def ends(self, j):
        return self.v[j][0], self.v[j][-1], self.p[j][0], self.p[j][-1]


def clean_obs(obs):
    """Observations with ineligible cells (any missing training year) set to 0, and the eligibility mask."""
    obs = np.asarray(obs, float)
    ok = np.isfinite(obs).all(axis=0)
    return np.where(ok[None, :], obs, 0.), ok


def gamma_mle(x, w, wet):
    """Weighted maximum-likelihood gamma (shape k, scale theta) of the wet values of every column.

    Thom/Greenwood starting value, then Newton steps on log k - digamma(k) = log(mean) - mean(log).
    Returns k, theta and the number of wet values; columns with fewer than 3 wet values get NaN.
    """
    W = np.where(wet, w if w.ndim == 2 else w[:, None], 0.)
    sw = W.sum(0)
    n = wet.sum(0)
    xs = np.where(wet, x, 1.)
    with np.errstate(divide='ignore', invalid='ignore'):
        m = (W * xs).sum(0) / sw
        L = (W * np.log(xs)).sum(0) / sw
        s = np.maximum(np.log(m) - L, 1e-8)
        k = (3 - s + np.sqrt((s - 3) ** 2 + 24 * s)) / (12 * s)
        for _ in range(8):
            k = np.maximum(k - (np.log(k) - digamma(k) - s) / (1 / k - polygamma(1, k)), 1e-3)
        k = np.minimum(k, 1e4)
        theta = m / k
    bad = n < 3
    return np.where(bad, np.nan, k), np.where(bad, np.nan, theta), n


def mixed_gamma_cdf(x, p0, k, theta, threshold):
    """Mixed distribution: dry mass p0 at or below the threshold, gamma above it. Dry values get p0/2."""
    g = gammainc(k, np.maximum(x, 0) / theta)
    return np.where(x > threshold, p0 + (1 - p0) * g, p0 / 2)


def mixed_gamma_ppf(u, p0, k, theta):
    q = np.clip((u - p0) / np.maximum(1 - p0, EPS), 0, 1 - 1e-9)
    return np.where(u <= p0, 0., gammaincinv(k, q) * theta)


def forecast_ratio(members, mu_model, ratio_bounds, min_model_mean):
    """Forecast signal: ensemble-mean total over the model climatological mean, bounded."""
    a = np.divide(members.mean(0), mu_model, out=np.ones(members.shape[1]), where=mu_model >= min_model_mean)
    return np.clip(a, *ratio_bounds)


def eqm_map(x, j, model, obs, extrapolation):
    """Empirical quantile mapping of values x in cell j; constant-ratio extrapolation beyond the training range."""
    out = obs.quantile(model.cdf(x, j), j)
    if extrapolation == 'constant_ratio':
        lo, hi, plo, phi = model.ends(j)
        top = x > hi
        if top.any() and hi > EPS:
            out[top] = x[top] * obs.quantile(phi, j) / hi
        bottom = x < lo
        if bottom.any() and lo > EPS:
            out[bottom] = x[bottom] * obs.quantile(plo, j) / lo
    return out


# ---------------------------------------------------------------- methods

def fit_raw(models, obs, **_):
    return dict(ok=clean_obs(obs)[1])


def apply_raw(members, s, **_):
    return np.array(members, float)


def fit_ls(models, obs, min_model_mean=0.1, **_):
    x, w = pooled(models)
    o, ok = clean_obs(obs)
    mu_m, mu_o = wmean(x, w), o.mean(0)
    ratio = np.divide(mu_o, mu_m, out=np.ones_like(mu_o), where=mu_m >= min_model_mean)
    return dict(ok=ok, ratio=ratio)


def apply_ls(members, s, **_):
    return members * s['ratio']


def fit_mvs(models, obs, ratio_bounds=(0.5, 2.0), min_model_sd=1.0, space='linear', **_):
    """Mean-variance scaling in linear or square-root space; ratio_bounds None means unbounded."""
    f = np.sqrt if space == 'sqrt' else (lambda a: a)
    x, w = pooled([f(np.asarray(m, float)) for m in models])
    o, ok = clean_obs(obs)
    o = f(o)
    mu_m, sd_m, mu_o, sd_o = wmean(x, w), wstd(x, w), o.mean(0), o.std(0)
    r = np.ones_like(mu_m)
    np.divide(sd_o, sd_m, out=r, where=sd_m >= min_model_sd)
    if ratio_bounds is not None:
        r = np.clip(r, *ratio_bounds)
    return dict(ok=ok, mu_model=mu_m, mu_obs=mu_o, ratio=r, space=space)


def apply_mvs(members, s, **_):
    if s['space'] == 'sqrt':
        return np.maximum(s['mu_obs'] + s['ratio'] * (np.sqrt(members) - s['mu_model']), 0) ** 2
    return np.maximum(s['mu_obs'] + s['ratio'] * (members - s['mu_model']), 0)


def fit_pt(models, obs, b_bounds=(0.1, 3.0), iterations=40, **_):
    """Power transformation a*x^b: b matches the coefficient of variation, then a matches the mean."""
    x, w = pooled(models)
    o, ok = clean_obs(obs)
    mu_o = o.mean(0)
    cv_o = np.divide(o.std(0), mu_o, out=np.zeros_like(mu_o), where=mu_o > EPS)

    def cv_model(b):
        y = x ** b
        mu = wmean(y, w)
        return np.divide(wstd(y, w), mu, out=np.zeros_like(mu), where=mu > EPS)

    lo, hi = np.full_like(mu_o, b_bounds[0]), np.full_like(mu_o, b_bounds[1])
    for _ in range(iterations):                    # CV of x^b increases with b: bisection, all cells at once
        mid = (lo + hi) / 2
        low = cv_model(mid) < cv_o
        lo, hi = np.where(low, mid, lo), np.where(low, hi, mid)
    b = (lo + hi) / 2
    mb = wmean(x ** b, w)
    a = np.divide(mu_o, mb, out=np.ones_like(mu_o), where=mb > EPS)
    return dict(ok=ok, a=a, b=b)


def apply_pt(members, s, **_):
    return s['a'] * members ** s['b']


def fit_dc(models, obs, min_model_mean=0.1, **_):
    x, w = pooled(models)
    o, ok = clean_obs(obs)
    return dict(ok=ok, obs=o, mu_model=wmean(x, w))


def apply_dc(members, s, ratio_bounds=(0.2, 5.0), min_model_mean=0.1, **_):
    """Delta change: every training-year observation times the forecast's ensemble-mean ratio (not member-wise)."""
    return s['obs'] * forecast_ratio(members, s['mu_model'], ratio_bounds, min_model_mean)


def fit_loci(models, obs, wet_threshold=1.0, **_):
    """Local intensity scaling: model threshold with the observed wet frequency, then intensity scaling."""
    x, w = pooled(models)
    o, ok = clean_obs(obs)
    wet_o = o > wet_threshold
    f_o = wet_o.mean(0)
    model = Ecdf(x, w)
    thr_m = np.array([0. if f >= 1 else model.quantile(1 - f, j) for j, f in enumerate(f_o)])
    wet_m = x > thr_m
    W = np.where(wet_m, w[:, None], 0.)
    with np.errstate(divide='ignore', invalid='ignore'):
        int_m = (W * x).sum(0) / W.sum(0)
        int_o = np.where(wet_o, o, 0).sum(0) / wet_o.sum(0)
        s = (int_o - wet_threshold) / (int_m - thr_m)
    good = np.isfinite(s) & (s > 0) & (f_o > 0)
    return dict(ok=ok, thr_m=thr_m, s=np.where(good, s, 0.), dry=f_o == 0, wet_threshold=wet_threshold)


def apply_loci(members, s, **_):
    out = np.where(members > s['thr_m'], np.maximum(s['wet_threshold'] + s['s'] * (members - s['thr_m']), 0), 0.)
    return np.where(s['dry'], 0., out)


def fit_eqm(models, obs, **_):
    x, w = pooled(models)
    o, ok = clean_obs(obs)
    return dict(ok=ok, model=Ecdf(x, w), obs=Ecdf(o), mu_model=wmean(x, w))


def apply_eqm(members, s, extrapolation='constant_ratio', **_):
    out = np.full(members.shape, np.nan)
    for j in np.flatnonzero(s['ok']):
        out[:, j] = eqm_map(members[:, j], j, s['model'], s['obs'], extrapolation)
    return out


def fit_gqm(models, obs, wet_threshold=1.0, **_):
    """Parametric quantile mapping with a mixed (dry mass + gamma) distribution for model and observations."""
    x, w = pooled(models)
    o, ok = clean_obs(obs)
    wet_m, wet_o = x > wet_threshold, o > wet_threshold
    k_m, t_m, _ = gamma_mle(x, w, wet_m)
    k_o, t_o, _ = gamma_mle(o, np.full(len(o), 1. / len(o)), wet_o)
    p0_m = (w[:, None] * ~wet_m).sum(0)
    p0_o = (~wet_o).mean(0)
    mu_m, mu_o = wmean(x, w), o.mean(0)
    fallback = ~(np.isfinite(k_m) & np.isfinite(k_o))   # too few wet values: linear scaling
    ratio = np.divide(mu_o, mu_m, out=np.ones_like(mu_o), where=mu_m > 0.1)
    return dict(ok=ok, k_m=k_m, t_m=t_m, k_o=k_o, t_o=t_o, p0_m=p0_m, p0_o=p0_o, fallback=fallback,
                ratio=ratio, wet_threshold=wet_threshold)


def apply_gqm(members, s, **_):
    with np.errstate(invalid='ignore'):
        u = np.clip(mixed_gamma_cdf(members, s['p0_m'], s['k_m'], s['t_m'], s['wet_threshold']), 1e-6, 1 - 1e-6)
        out = mixed_gamma_ppf(u, s['p0_o'], s['k_o'], s['t_o'])
    return np.where(s['fallback'], members * s['ratio'], out)


def apply_dqm(members, s, extrapolation='constant_ratio', ratio_bounds=(0.2, 5.0), min_model_mean=0.1, **_):
    """Detrended QM: remove the forecast's ensemble-mean ratio, quantile-map, put the ratio back."""
    a = forecast_ratio(members, s['mu_model'], ratio_bounds, min_model_mean)
    out = np.full(members.shape, np.nan)
    for j in np.flatnonzero(s['ok']):
        out[:, j] = eqm_map(members[:, j] / a[j], j, s['model'], s['obs'], extrapolation) * a[j]
    return out


def apply_qdm(members, s, max_ratio=5.0, wet_threshold=1.0, **_):
    """Quantile delta mapping: observed quantile at the member's rank times the member's relative change."""
    fc = Ecdf(members)
    out = np.full(members.shape, np.nan)
    for j in np.flatnonzero(s['ok']):
        x = members[:, j]
        tau = fc.cdf(x, j)
        qm, qo = s['model'].quantile(tau, j), s['obs'].quantile(tau, j)
        delta = np.minimum(np.divide(x, qm, out=np.ones_like(x), where=qm > wet_threshold), max_ratio)
        out[:, j] = np.where(qm > wet_threshold, qo * delta, qo)
    return out


def fit_cdft(models, obs, min_model_mean=0.1, **_):
    """CDF-t with the model first scaled to the observed mean (multiplicative form of the CDFt convention)."""
    x, w = pooled(models)
    o, ok = clean_obs(obs)
    mu_m, mu_o = wmean(x, w), o.mean(0)
    c = np.divide(mu_o, mu_m, out=np.ones_like(mu_o), where=mu_m >= min_model_mean)
    return dict(ok=ok, c=c, model=Ecdf(x * c, w), obs=Ecdf(o))


def apply_cdft(members, s, **_):
    """x' = F_Of^-1(F_Mf(x)) with F_Of = F_Oh(F_Mh^-1(F_Mf)), i.e. x' = Q_Mf(F_Mh(Q_Oh(F_Mf(x))))."""
    z = members * s['c']
    fc = Ecdf(z)
    out = np.full(members.shape, np.nan)
    for j in np.flatnonzero(s['ok']):
        u = fc.cdf(z[:, j], j)
        out[:, j] = fc.quantile(s['model'].cdf(s['obs'].quantile(u, j), j), j)
    return out


def fit_sdm(models, obs, wet_threshold=1.0, **_):
    x, w = pooled(models)
    o, ok = clean_obs(obs)
    wet_m, wet_o = x > wet_threshold, o > wet_threshold
    k_m, t_m, _ = gamma_mle(x, w, wet_m)
    k_o, t_o, _ = gamma_mle(o, np.full(len(o), 1. / len(o)), wet_o)
    fr_m = (w[:, None] * wet_m).sum(0)
    fr_o = wet_o.mean(0)
    obs_wet =[np.sort(o[wet_o[:, j], j]) for j in range(o.shape[1])]
    mod_wet = []                                          # weighted wet-value quantile function of every cell
    for j in range(x.shape[1]):
        keep = wet_m[:, j]
        v, inv = np.unique(x[keep, j], return_inverse=True)
        ww = np.bincount(inv.ravel(), weights=w[keep], minlength=len(v))
        mod_wet.append((v, (np.cumsum(ww) - ww / 2) / max(ww.sum(), EPS)))
    mu_m, mu_o = wmean(x, w), o.mean(0)
    ratio = np.divide(mu_o, mu_m, out=np.ones_like(mu_o), where=mu_m > 0.1)
    return dict(ok=ok, k_m=k_m, t_m=t_m, k_o=k_o, t_o=t_o, fr_m=fr_m, fr_o=fr_o, obs_wet=obs_wet,
                mod_wet=mod_wet, ratio=ratio, wet_threshold=wet_threshold)


def apply_sdm(members, s, **_):
    """Scaled distribution mapping (relative form, Switanek et al. 2017) for every cell."""
    thr = s['wet_threshold']
    lim = lambda p: np.clip(p, 1e-5, 1 - 1e-5)
    out = np.full(members.shape, np.nan)
    n = len(members)
    for j in np.flatnonzero(s['ok']):
        x = members[:, j]
        wet = x > thr
        xr = np.sort(x[wet])
        k_o, t_o, k_m, t_m = s['k_o'][j], s['t_o'][j], s['k_m'][j], s['t_m'][j]
        if len(xr) < 3 or not np.isfinite([k_o, t_o, k_m, t_m]).all() or s['fr_m'][j] <= 0:
            out[:, j] = x * s['ratio'][j]                       # too few wet values: linear scaling
            continue
        k_f, t_f, _ = gamma_mle(xr[:, None], np.full(len(xr), 1. / len(xr)), np.ones((len(xr), 1), bool))
        k_f, t_f = k_f[0], t_f[0]
        fr_f = wet.mean()
        expected = int(min(round(n * s['fr_o'][j] * fr_f / s['fr_m'][j]), n))
        pp = (np.arange(len(xr)) + .5) / len(xr)
        ow = s['obs_wet'][j]
        oq = np.interp(pp, (np.arange(len(ow)) + .5) / len(ow), ow) if len(ow) else np.zeros_like(pp)
        mv, mp = s['mod_wet'][j]
        mq = np.interp(pp, mp, mv)
        obs_cdf, mod_cdf = lim(gammainc(k_o, oq / t_o)), lim(gammainc(k_m, mq / t_m))
        sce_cdf = lim(gammainc(k_f, xr / t_f))
        adapted = lim(1 - 1 / ((1 / (1 - obs_cdf)) * (1 / (1 - sce_cdf)) / (1 / (1 - mod_cdf))))
        xv = (gammaincinv(k_o, np.sort(adapted)) * t_o
              * (gammaincinv(k_f, sce_cdf) * t_f) / np.maximum(gammaincinv(k_m, sce_cdf) * t_m, EPS))
        if len(xr) > expected:
            xv = np.interp(np.linspace(1, len(xr), expected), np.linspace(1, len(xr), len(xr)), xv) if expected else xv[:0]
        else:
            xv = np.r_[np.zeros(expected - len(xr)), xv]
        y = np.zeros(n)
        if expected:
            y[np.argsort(x, kind='stable')[-expected:]] = xv
        out[:, j] = y
    return out


@dataclass(frozen=True)
class Method:
    key: str
    label: str
    fit: object
    apply: object
    family: str
    definition: str
    references: tuple
    member_wise: bool = True
    uses_forecast_distribution: bool = False
    defaults: dict = field(default_factory=dict)


BASELINE = Method('raw', 'Raw ECMWF (no correction)', fit_raw, apply_raw, 'baseline',
                  "x' = x (the uncorrected model; baseline, not a candidate)", ('Johnson et al. 2019',))

METHODS = {m.key: m for m in [
    Method('ls', 'Linear Scaling', fit_ls, apply_ls, 'scaling',
           "x' = x * mu_obs / mu_model (multiplicative mean correction)", ('Lenderink et al. 2007', 'Teutschbein & Seibert 2012')),
    Method('mvs', 'Mean-Variance Scaling (operational)', fit_mvs, apply_mvs, 'scaling',
           "x' = max(0, mu_obs + r (x - mu_model)), r = clip(sd_obs/sd_model, 0.5, 2); r = 1 if sd_model < 1 mm",
           ('Torralba et al. 2017', 'Manzanas et al. 2019'), defaults=dict(ratio_bounds=(0.5, 2.0), min_model_sd=1.0)),
    Method('vs', 'Variance Scaling (unbounded)', fit_mvs, apply_mvs, 'scaling',
           "Same algebra as MVS without the project's ratio limits: r = sd_obs/sd_model", ('Teutschbein & Seibert 2012',),
           defaults=dict(ratio_bounds=None, min_model_sd=0.1)),
    Method('sqrt_mvs', 'Square-root-space Mean-Variance Scaling', fit_mvs, apply_mvs, 'scaling',
           "MVS applied to sqrt(x), clipped at 0 and squared back (docs/36)", ('Manzanas et al. 2019',),
           defaults=dict(ratio_bounds=(0.5, 2.0), min_model_sd=0.1, space='sqrt')),
    Method('pt', 'Power Transformation', fit_pt, apply_pt, 'scaling',
           "x' = a x^b, b matches the coefficient of variation, a the mean", ('Leander & Buishand 2007', 'Teutschbein & Seibert 2012')),
    Method('dc', 'Delta Change', fit_dc, apply_dc, 'change-preserving',
           "Training-year CHIRPS totals times (forecast ensemble mean / model climatological mean)",
           ('Hay et al. 2000', 'Teutschbein & Seibert 2012'), member_wise=False, uses_forecast_distribution=True),
    Method('loci', 'Local Intensity Scaling', fit_loci, apply_loci, 'scaling',
           "Model wet threshold with the observed wet frequency, then intensity scaling above it",
           ('Schmidli et al. 2006',)),
    Method('eqm', 'Empirical Quantile Mapping', fit_eqm, apply_eqm, 'quantile mapping',
           "x' = Q_obs(F_model(x)), constant-ratio extrapolation", ('Boe et al. 2007', 'Themessl et al. 2011', 'Gudmundsson et al. 2012')),
    Method('gqm', 'Gamma Quantile Mapping', fit_gqm, apply_gqm, 'quantile mapping',
           "x' = G_obs^-1(G_model(x)), mixed dry mass + gamma, weighted maximum likelihood", ('Piani et al. 2010',)),
    Method('dqm', 'Detrended Quantile Mapping', fit_eqm, apply_dqm, 'change-preserving',
           "EQM of x / a, times a, with a = forecast ensemble mean / model mean", ('Cannon et al. 2015',),
           uses_forecast_distribution=True),
    Method('qdm', 'Quantile Delta Mapping', fit_eqm, apply_qdm, 'change-preserving',
           "x' = Q_obs(tau) * x / Q_model(tau), tau = rank of x in the forecast ensemble", ('Cannon et al. 2015',),
           uses_forecast_distribution=True),
    Method('sdm', 'Scaled Distribution Mapping', fit_sdm, apply_sdm, 'change-preserving',
           "Gamma fits to observations, model climatology and forecast ensemble; scaled relative change and rain frequency",
           ('Switanek et al. 2017',), uses_forecast_distribution=True),
    Method('cdft', 'CDF-transform', fit_cdft, apply_cdft, 'change-preserving',
           "F_obs,f = F_obs(F_model^-1(F_forecast)); x' = F_obs,f^-1(F_forecast(x)); model first scaled to the observed mean",
           ('Michelangeli et al. 2009', 'Vrac et al. 2012'), uses_forecast_distribution=True),
]}
ALL = {'raw': BASELINE, **METHODS}       # benchmark rows: the baseline and the 13 methods


def correct(key, models, obs, members, params=None):
    """Fit on the training years and correct one forecast. Ineligible cells are NaN."""
    m = ALL[key]
    p = {**m.defaults, **(params or {})}
    state = m.fit(models, obs, **p)
    out = np.asarray(m.apply(np.asarray(members, float), state, **p), float)
    out[:, ~state['ok']] = np.nan
    return out
