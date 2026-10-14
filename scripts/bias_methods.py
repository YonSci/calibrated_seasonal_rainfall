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

Dry totals and ties (quantile-mapping methods EQM, GQM, DQM, QDM): a total at or below `wet_threshold` (1 mm
by default: a dry month or season, not a dry day) is "dry". The dry share of the model climatology, p0_model,
and of CHIRPS, p0_obs, are estimated with the equal-year weights. Dry members of a forecast are spread evenly
over the probability interval (0, p0_model) by their rank — deterministic stratified tie-breaking, with ties resolved
by member index — and a probability at or below p0_obs maps to 0 mm, also after any tail extrapolation. So the corrected dry share follows
CHIRPS instead of collapsing all tied zeros onto one probability.

Diagnostics: every fit returns `flags` (per-cell booleans, e.g. a ratio limit or a fallback that is active) and
every apply adds to `counts` ({name: [events, opportunities]}), so a benchmark can report how often each limit,
cap or fallback acts.

Methods that keep a "change signal" (DC, DQM, QDM, SDM, CDF-t) were built for climate change (reference vs
future period). Here the "future" is the forecast itself: the target year's ensemble against the model
climatology of the training years.
"""
from dataclasses import dataclass, field, replace
import numpy as np
from scipy.special import digamma, polygamma, gammainc, gammaincinv

EPS = 1e-9
SDM_CDF_MAX = 1 - 1e-7          # Switanek et al. (2017), step 2: upper threshold on CDF values


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
    them. Tied values share one position in the middle of their probability (dry totals are handled
    separately by `dry_positions`).
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


def count(s, name, events, opportunities):
    c = s.setdefault('counts', {}).setdefault(name, [0, 0])
    c[0] += int(events)
    c[1] += int(opportunities)


def dry_positions(x, u, p0, threshold):
    """Non-exceedance probabilities with the dry policy: dry values spread evenly over (0, p0) by rank."""
    u = np.array(u, float)
    dry = x <= threshold
    n = int(dry.sum())
    if p0 > 0:
        u[~dry] = np.maximum(u[~dry], p0)
        if n:
            rank = np.empty(n)
            rank[np.argsort(x[dry], kind='stable')] = np.arange(n)
            u[dry] = p0 * (rank + .5) / n
    return u


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


def forecast_ratio(members, mu_model, ratio_bounds, min_model_mean, s=None, name=None):
    """Forecast signal: ensemble-mean total over the model climatological mean, bounded."""
    a = np.divide(members.mean(0), mu_model, out=np.ones(members.shape[1]), where=mu_model >= min_model_mean)
    b = np.clip(a, *ratio_bounds)
    if s is not None:
        count(s, name, ((b != a) & s['ok']).sum(), s['ok'].sum())
    return b


def dry_shares(x, w, o, threshold):
    return (w[:, None] * (x <= threshold)).sum(0), (o <= threshold).mean(0)


def eqm_map(x, j, s, extrapolation, threshold):
    """Empirical quantile mapping of values x in cell j with the dry policy; constant-ratio extrapolation."""
    model, obs, p0m, p0o = s['model'], s['obs'], s['p0_model'][j], s['p0_obs'][j]
    u = dry_positions(x, model.cdf(x, j), p0m, threshold)
    dry = (p0o > 0) & (u <= p0o)
    out = obs.quantile(u, j)
    if extrapolation == 'constant_ratio':
        lo, hi, plo, phi = model.ends(j)
        top = x > hi
        if top.any() and hi > EPS:
            out[top] = x[top] * obs.quantile(phi, j) / hi
        bottom = (x < lo) & (x > threshold)
        if bottom.any() and lo > EPS:
            out[bottom] = x[bottom] * obs.quantile(plo, j) / lo
        count(s, 'extrapolated', (top & ~dry).sum() + (bottom & ~dry).sum(), len(x))
    return np.where(dry, 0., out)                  # the dry rule last: extrapolation never overrides it


# ---------------------------------------------------------------- methods

def fit_raw(models, obs, **_):
    return dict(ok=clean_obs(obs)[1], flags={})


def apply_raw(members, s, **_):
    return np.array(members, float)


def fit_ls(models, obs, min_model_mean=0.1, **_):
    x, w = pooled(models)
    o, ok = clean_obs(obs)
    mu_m, mu_o = wmean(x, w), o.mean(0)
    ratio = np.divide(mu_o, mu_m, out=np.ones_like(mu_o), where=mu_m >= min_model_mean)
    return dict(ok=ok, ratio=ratio, flags=dict(mean_fallback=mu_m < min_model_mean))


def apply_ls(members, s, **_):
    return members * s['ratio']


def fit_mvs(models, obs, ratio_bounds=(0.5, 2.0), min_model_sd=1.0, space='linear', zero_guard=False, **_):
    """Mean-variance scaling in linear or square-root space; ratio_bounds None means unbounded.

    zero_guard: corrected totals are 0 mm in cells where every training year has exactly 0 mm (a modelling choice:
    a finite history of zero rainfall does not make rain impossible).
    """
    f = np.sqrt if space == 'sqrt' else (lambda a: a)
    x, w = pooled([f(np.asarray(m, float)) for m in models])
    o, ok = clean_obs(obs)
    all_zero = (o == 0).all(0) & ok
    o = f(o)
    mu_m, sd_m, mu_o, sd_o = wmean(x, w), wstd(x, w), o.mean(0), o.std(0)
    r = np.ones_like(mu_m)
    np.divide(sd_o, sd_m, out=r, where=sd_m >= min_model_sd)
    flags = dict(sd_fallback=sd_m < min_model_sd)
    if ratio_bounds is not None:
        flags.update(ratio_lower_limit=r < ratio_bounds[0], ratio_upper_limit=r > ratio_bounds[1])
        r = np.clip(r, *ratio_bounds)
    if zero_guard:
        flags['zero_guard'] = all_zero
    return dict(ok=ok, mu_model=mu_m, mu_obs=mu_o, ratio=r, space=space, flags=flags, guard=all_zero if zero_guard else None)


def apply_mvs(members, s, **_):
    if s['space'] == 'sqrt':
        raw = s['mu_obs'] + s['ratio'] * (np.sqrt(members) - s['mu_model'])
    else:
        raw = s['mu_obs'] + s['ratio'] * (members - s['mu_model'])
    count(s, 'clipped_at_zero', ((raw < 0) & s['ok']).sum(), members.shape[0] * s['ok'].sum())
    out = np.maximum(raw, 0)
    out = out ** 2 if s['space'] == 'sqrt' else out
    if s.get('guard') is not None:
        out[:, s['guard']] = 0.
    return out


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
    span = b_bounds[1] - b_bounds[0]                 # a bound reached: the CV cannot be matched exactly
    at_bound = (b - b_bounds[0] < 1e-3 * span) | (b_bounds[1] - b < 1e-3 * span)
    return dict(ok=ok, a=a, b=b, flags=dict(b_at_bound=at_bound))


def apply_pt(members, s, **_):
    return s['a'] * members ** s['b']


def fit_dc(models, obs, min_model_mean=0.1, **_):
    x, w = pooled(models)
    o, ok = clean_obs(obs)
    mu_m = wmean(x, w)
    return dict(ok=ok, obs=o, mu_model=mu_m, flags=dict(mean_fallback=mu_m < min_model_mean))


def apply_dc(members, s, ratio_bounds=(0.2, 5.0), min_model_mean=0.1, **_):
    """Delta change: every training-year observation times the forecast's ensemble-mean ratio (not member-wise)."""
    return s['obs'] * forecast_ratio(members, s['mu_model'], ratio_bounds, min_model_mean, s, 'ratio_capped')


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
    return dict(ok=ok, thr_m=thr_m, s=np.where(good, s, 0.), dry=f_o == 0, wet_threshold=wet_threshold,
                flags=dict(always_wet=f_o >= 1, never_wet=f_o == 0, no_scaling=~good & (f_o > 0)))


def apply_loci(members, s, **_):
    out = np.where(members > s['thr_m'], np.maximum(s['wet_threshold'] + s['s'] * (members - s['thr_m']), 0), 0.)
    return np.where(s['dry'], 0., out)


def fit_eqm(models, obs, wet_threshold=1.0, **_):
    x, w = pooled(models)
    o, ok = clean_obs(obs)
    p0m, p0o = dry_shares(x, w, o, wet_threshold)
    return dict(ok=ok, model=Ecdf(x, w), obs=Ecdf(o), mu_model=wmean(x, w), p0_model=p0m, p0_obs=p0o,
                flags=dict(model_has_dry=p0m > 0, obs_has_dry=p0o > 0))


def apply_eqm(members, s, extrapolation='constant_ratio', wet_threshold=1.0, **_):
    out = np.full(members.shape, np.nan)
    for j in np.flatnonzero(s['ok']):
        out[:, j] = eqm_map(members[:, j], j, s, extrapolation, wet_threshold)
    return out


def fit_gqm(models, obs, wet_threshold=1.0, **_):
    """Parametric quantile mapping with a mixed (dry mass + gamma) distribution for model and observations."""
    x, w = pooled(models)
    o, ok = clean_obs(obs)
    wet_m, wet_o = x > wet_threshold, o > wet_threshold
    k_m, t_m, _ = gamma_mle(x, w, wet_m)
    k_o, t_o, _ = gamma_mle(o, np.full(len(o), 1. / len(o)), wet_o)
    p0_m, p0_o = dry_shares(x, w, o, wet_threshold)
    mu_m, mu_o = wmean(x, w), o.mean(0)
    all_dry_obs = p0_o >= 1
    fallback = ~(np.isfinite(k_m) & np.isfinite(k_o)) & ~all_dry_obs     # too few wet values: linear scaling
    ratio = np.divide(mu_o, mu_m, out=np.ones_like(mu_o), where=mu_m > 0.1)
    return dict(ok=ok, k_m=k_m, t_m=t_m, k_o=k_o, t_o=t_o, p0_m=p0_m, p0_o=p0_o, fallback=fallback,
                all_dry_obs=all_dry_obs, ratio=ratio, wet_threshold=wet_threshold,
                flags=dict(gamma_fallback=fallback, model_has_dry=p0_m > 0, obs_has_dry=p0_o > 0))


def apply_gqm(members, s, **_):
    thr = s['wet_threshold']
    out = np.full(members.shape, np.nan)
    for j in np.flatnonzero(s['ok']):
        x = members[:, j]
        if s['all_dry_obs'][j]:
            out[:, j] = 0.
            continue
        if s['fallback'][j]:
            out[:, j] = x * s['ratio'][j]
            continue
        p0m, p0o = s['p0_m'][j], s['p0_o'][j]
        g = gammainc(s['k_m'][j], np.maximum(x, 0) / s['t_m'][j])
        u = np.clip(dry_positions(x, p0m + (1 - p0m) * g, p0m, thr), 1e-9, 1 - 1e-9)
        q = np.clip((u - p0o) / max(1 - p0o, EPS), 0, 1 - 1e-9)
        out[:, j] = np.where(u <= p0o, 0., gammaincinv(s['k_o'][j], q) * s['t_o'][j])
    return out


def apply_dqm(members, s, extrapolation='constant_ratio', ratio_bounds=(0.2, 5.0), min_model_mean=0.1, wet_threshold=1.0, **_):
    """Detrended QM: divide by the bounded forecast ensemble-mean ratio a, quantile-map, multiply by a.

    The ratio is removed and put back, but the mapping in between changes the normalized mean, so the
    corrected forecast's mean anomaly is not, in general, the raw forecast's.
    """
    a = forecast_ratio(members, s['mu_model'], ratio_bounds, min_model_mean, s, 'ratio_capped')
    out = np.full(members.shape, np.nan)
    for j in np.flatnonzero(s['ok']):
        out[:, j] = eqm_map(members[:, j] / a[j], j, s, extrapolation, wet_threshold) * a[j]
    return out


def apply_qdm(members, s, max_ratio=5.0, wet_threshold=1.0, **_):
    """Quantile delta mapping: observed quantile at the member's rank times the member's relative change.

    The relative change is kept only where the model quantile is above the dry threshold and the change is
    below `max_ratio`; elsewhere the observed quantile is used, or the change is capped (both counted).
    """
    fc = Ecdf(members)
    out = np.full(members.shape, np.nan)
    p0f_all = (members <= wet_threshold).mean(0)
    for j in np.flatnonzero(s['ok']):
        x = members[:, j]
        tau = dry_positions(x, fc.cdf(x, j), p0f_all[j], wet_threshold)
        qm, qo = s['model'].quantile(tau, j), s['obs'].quantile(tau, j)
        low = qm <= wet_threshold
        delta = np.divide(x, qm, out=np.ones_like(x), where=~low)
        capped = delta > max_ratio
        y = np.where(low, qo, qo * np.minimum(delta, max_ratio))
        p0o = s['p0_obs'][j]
        out[:, j] = np.where((p0o > 0) & (tau <= p0o), 0., y)
        count(s, 'low_denominator', low.sum(), len(x))
        count(s, 'ratio_capped', (capped & ~low).sum(), len(x))
    return out


def fit_cdft(models, obs, min_model_mean=0.1, **_):
    """CDF-t with the model first scaled to the observed mean (multiplicative form of the CDFt convention)."""
    x, w = pooled(models)
    o, ok = clean_obs(obs)
    mu_m, mu_o = wmean(x, w), o.mean(0)
    c = np.divide(mu_o, mu_m, out=np.ones_like(mu_o), where=mu_m >= min_model_mean)
    return dict(ok=ok, c=c, model=Ecdf(x * c, w), obs=Ecdf(o), flags=dict(mean_fallback=mu_m < min_model_mean))


def apply_cdft(members, s, **_):
    """x' = F_Of^-1(F_Mf(x)) with F_Of = F_Oh(F_Mh^-1(F_Mf)), i.e. x' = Q_Mf(F_Mh(Q_Oh(F_Mf(x)))).

    Implementation choices: the model and forecast are first scaled to the CHIRPS mean, and the result stays
    within the scaled forecast ensemble's range (counted when a member lands on its minimum or maximum).
    """
    z = members * s['c']
    fc = Ecdf(z)
    out = np.full(members.shape, np.nan)
    for j in np.flatnonzero(s['ok']):
        u = fc.cdf(z[:, j], j)
        y = fc.quantile(s['model'].cdf(s['obs'].quantile(u, j), j), j)
        out[:, j] = y
        count(s, 'at_forecast_range_edge', ((y <= fc.v[j][0]) | (y >= fc.v[j][-1])).sum(), len(y))
    return out


def fit_sdm(models, obs, wet_threshold=1.0, **_):
    """Scaled distribution mapping, precipitation (Switanek et al. 2017, Sect. 4.1.1), steps 1-2 for the training data.

    Wet totals are those above the threshold (step 1). Gamma distributions are fitted by maximum likelihood to the
    wet CHIRPS totals and, with the equal-year weights, to the wet model totals (step 2). The recurrence intervals
    of the sorted wet values are kept with their positions, for the interpolation of step 4.
    """
    x, w = pooled(models)
    o, ok = clean_obs(obs)
    wet_m, wet_o = x > wet_threshold, o > wet_threshold
    k_m, t_m, _ = gamma_mle(x, w, wet_m)
    k_o, t_o, _ = gamma_mle(o, np.full(len(o), 1. / len(o)), wet_o)
    fr_m = (w[:, None] * wet_m).sum(0)                       # RD_MODH / TD_MODH (equal-year weights)
    fr_o = wet_o.mean(0)                                     # RD_OBS / TD_OBS
    ri_obs, ri_mod = [], []
    with np.errstate(invalid='ignore', divide='ignore'):
        for j in range(o.shape[1]):
            v = np.sort(o[wet_o[:, j], j])
            cdf = np.minimum(gammainc(k_o[j], v / t_o[j]), SDM_CDF_MAX)
            ri_obs.append(1 / (1 - cdf))                     # step 4, observations; positions 0..1 (equal weights)
            keep = wet_m[:, j]
            vm, inv = np.unique(x[keep, j], return_inverse=True)
            ww = np.bincount(inv.ravel(), weights=w[keep], minlength=len(vm))
            c = np.cumsum(ww) - ww / 2                         # weighted positions, rescaled to keep the range 0..1
            pos = (c - c[0]) / (c[-1] - c[0]) if len(c) > 1 else np.zeros(len(c))
            cdfm = np.minimum(gammainc(k_m[j], vm / t_m[j]), SDM_CDF_MAX)
            ri_mod.append((pos, 1 / (1 - cdfm)))
    mu_m, mu_o = wmean(x, w), o.mean(0)
    ratio = np.divide(mu_o, mu_m, out=np.ones_like(mu_o), where=mu_m > 0.1)
    fallback = ~(np.isfinite(k_m) & np.isfinite(k_o)) | (fr_m <= 0)
    return dict(ok=ok, k_m=k_m, t_m=t_m, k_o=k_o, t_o=t_o, fr_m=fr_m, fr_o=fr_o, ri_obs=ri_obs, ri_mod=ri_mod,
                ratio=ratio, fallback=fallback, wet_threshold=wet_threshold, flags=dict(gamma_fallback=fallback))


def sdm_cell(x, k_o, t_o, k_m, t_m, fr_o, fr_m, ri_obs, ri_mod, threshold):
    """Steps 1-7 for one cell's forecast members x; returns the corrected members (None: fewer than 3 wet)."""
    wet = x > threshold
    order = np.argsort(np.where(wet, x, -np.inf), kind='stable')
    xr = np.sort(x[wet])
    n_f = len(xr)
    if n_f < 3:
        return None
    k_f, t_f, _ = gamma_mle(xr[:, None], np.full(n_f, 1. / n_f), np.ones((n_f, 1), bool))
    k_f, t_f = k_f[0], t_f[0]
    rd_bc = int(min(round(n_f * fr_o / fr_m), n_f))         # step 1, Eq. (1); never more rain members (step 7)
    cdf_f = np.minimum(gammainc(k_f, xr / t_f), SDM_CDF_MAX)  # step 2
    sfr = gammaincinv(k_f, cdf_f) * t_f / np.maximum(gammaincinv(k_m, cdf_f) * t_m, EPS)   # step 3, Eq. (3)
    ri_f = 1 / (1 - cdf_f)                                   # step 4, Eq. (4)
    grid = np.linspace(0, 1, n_f)                            # step 4: interpolate the RI arrays, keeping their range
    ri_io = np.interp(grid, np.linspace(0, 1, len(ri_obs)), ri_obs) if len(ri_obs) > 1 else np.full(n_f, ri_obs[0])
    pos_m, ri_m = ri_mod
    ri_im = np.interp(grid, pos_m, ri_m) if len(ri_m) > 1 else np.full(n_f, ri_m[0])
    ri_s = np.maximum(1, ri_io * ri_f / ri_im)               # step 5, Eq. (5)
    cdf_s = np.sort(1 - 1 / ri_s)                            # Eq. (6), ordered like the sorted forecast values
    bc = gammaincinv(k_o, np.minimum(cdf_s, SDM_CDF_MAX)) * t_o * sfr   # step 6, Eq. (7)
    y = np.zeros(len(x))
    if rd_bc > 0:
        if rd_bc < n_f:                                      # step 6: interpolate to the corrected number of rain members
            bc = np.interp(np.linspace(0, 1, rd_bc), grid, bc) if rd_bc > 1 else bc[-1:]
        y[order[-rd_bc:]] = np.sort(bc)                      # step 7: largest corrected value to the largest raw member
    return y


def apply_sdm(members, s, **_):
    out = np.full(members.shape, np.nan)
    for j in np.flatnonzero(s['ok']):
        x = members[:, j]
        y = None if s['fallback'][j] else sdm_cell(x, s['k_o'][j], s['t_o'][j], s['k_m'][j], s['t_m'][j], s['fr_o'][j],
                                                    s['fr_m'][j], s['ri_obs'][j], s['ri_mod'][j], s['wet_threshold'])
        count(s, 'linear_scaling_fallback', y is None, 1)
        out[:, j] = x * s['ratio'][j] if y is None else y
    return out


def fit_leung(models, obs, beta=0.3, ratio_bounds=(0.5, 2.0), sigma_min=1.0, **_):
    """Modified-Leung member-wise affine calibration (GrazFeediNG, Munoz & Demissie; docs/51), as in process_calib.py.

    Every member index m has its own climatology over the training years: mean mu_m and standard deviation sd_m (ddof 0).
    sd_eff_m = (1 - beta) sd_m + beta sd_pool, sd_pool = sqrt(mean_m sd_m^2); r_m = clip((sd_obs + 1e-6) / (sd_eff_m + 1e-6),
    0.5, 2), r_m = 1 where sd_obs and sd_eff_m are both below sigma_min (1 mm). Members without their own climatology
    (index beyond the training years' member count, e.g. members 26-51 from 2017) use the pooled climatology
    (mean over members of mu_m, sd_pool): an implementation choice, since the original assumes equal member counts.
    """
    o, ok = clean_obs(obs)
    M = min(len(m) for m in models)
    X = np.stack([np.asarray(m, float)[:M] for m in models])                  # (year, member, cell)
    mu_m, sd_m = X.mean(0), X.std(0)                                            # per member, over the years
    sd_pool = np.sqrt((sd_m ** 2).mean(0))
    mu_o, sd_o = o.mean(0), o.std(0)

    def ratio(sd_eff):
        tiny = (sd_o < sigma_min) & (sd_eff < sigma_min)
        raw = (sd_o + 1e-6) / (sd_eff + 1e-6)
        return np.where(tiny, 1.0, np.clip(raw, *ratio_bounds)), tiny, raw
    r_m, tiny_m, raw_m = ratio((1 - beta) * sd_m + beta * sd_pool)
    r_p, _, _ = ratio(sd_pool)
    flags = dict(both_tiny=tiny_m.mean(0) > 0.5, ratio_lower_limit=((raw_m < ratio_bounds[0]) & ~tiny_m).mean(0) > 0.5,
                 ratio_upper_limit=((raw_m > ratio_bounds[1]) & ~tiny_m).mean(0) > 0.5)
    return dict(ok=ok, mu_obs=mu_o, mu_member=mu_m, ratio_member=r_m, mu_pool=mu_m.mean(0), ratio_pool=r_p, members=M, flags=flags)


def apply_leung(members, s, **_):
    members = np.asarray(members, float)
    M = s['members']
    mu = np.vstack([s['mu_member'][:min(M, len(members))]] + ([np.repeat(s['mu_pool'][None], len(members) - M, 0)] if len(members) > M else []))
    r = np.vstack([s['ratio_member'][:min(M, len(members))]] + ([np.repeat(s['ratio_pool'][None], len(members) - M, 0)] if len(members) > M else []))
    count(s, 'pooled_climatology_members', max(len(members) - M, 0) * s['ok'].sum(), len(members) * s['ok'].sum())
    raw = s['mu_obs'] + r * (members - mu)
    count(s, 'clipped_at_zero', ((raw < 0) & s['ok']).sum(), members.shape[0] * s['ok'].sum())
    return np.maximum(raw, 0)


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
           "x' = x * mu_obs / mu_model (multiplicative mean correction; ratio 1 where mu_model < 0.1 mm)",
           ('Lenderink et al. 2007', 'Teutschbein & Seibert 2012')),
    Method('mvs', 'Mean-Variance Scaling (operational)', fit_mvs, apply_mvs, 'scaling',
           "x' = max(0, mu_obs + r (x - mu_model)), r = clip(sd_obs/sd_model, 0.5, 2); r = 1 if sd_model < 1 mm",
           ('Torralba et al. 2017', 'Manzanas et al. 2019'), defaults=dict(ratio_bounds=(0.5, 2.0), min_model_sd=1.0)),
    Method('vs', 'Variance Scaling (unbounded)', fit_mvs, apply_mvs, 'scaling',
           "Same algebra and the same r = 1 fallback (sd_model < 1 mm) as MVS, without the 0.5-2 ratio limits",
           ('Teutschbein & Seibert 2012',), defaults=dict(ratio_bounds=None, min_model_sd=1.0)),
    Method('sqrt_mvs', 'Square-root-space Mean-Variance Scaling', fit_mvs, apply_mvs, 'scaling',
           "MVS applied to sqrt(x) (r limits 0.5-2; r = 1 if the sqrt-space sd < 0.1), clipped at 0 and squared back (docs/36)",
           ('Manzanas et al. 2019',), defaults=dict(ratio_bounds=(0.5, 2.0), min_model_sd=0.1, space='sqrt')),
    Method('pt', 'Power Transformation', fit_pt, apply_pt, 'scaling',
           "x' = a x^b: b (0.1-3) matches the coefficient of variation where reachable (bound hits reported), a the mean",
           ('Leander & Buishand 2007', 'Teutschbein & Seibert 2012')),
    Method('dc', 'Delta Change', fit_dc, apply_dc, 'change-preserving',
           "Training-year CHIRPS totals times a = forecast ensemble mean / model mean (a in 0.2-5): historical scenarios, "
           "not corrected members",
           ('Hay et al. 2000', 'Teutschbein & Seibert 2012'), member_wise=False, uses_forecast_distribution=True),
    Method('loci', 'Local Intensity Scaling', fit_loci, apply_loci, 'scaling',
           "Model threshold with the observed frequency of totals above 1 mm, then intensity scaling above it "
           "(designed for daily rainfall; here monthly or seasonal totals)",
           ('Schmidli et al. 2006',)),
    Method('eqm', 'Empirical Quantile Mapping', fit_eqm, apply_eqm, 'quantile mapping',
           "x' = Q_obs(F_model(x)) with the dry policy; constant-ratio extrapolation outside the training range",
           ('Boe et al. 2007', 'Themessl et al. 2011', 'Gudmundsson et al. 2012')),
    Method('gqm', 'Gamma Quantile Mapping', fit_gqm, apply_gqm, 'quantile mapping',
           "x' = G_obs^-1(G_model(x)), G = dry mass (<= 1 mm) + gamma by weighted maximum likelihood, with the dry "
           "policy; linear scaling where fewer than 3 wet values",
           ('Piani et al. 2010',)),
    Method('dqm', 'Detrended Quantile Mapping', fit_eqm, apply_dqm, 'change-preserving',
           "a * EQM(x / a), a = forecast ensemble mean / model mean (0.2-5): removes and reapplies the bounded ratio; "
           "exact preservation of the final mean anomaly is not guaranteed",
           ('Cannon et al. 2015',), uses_forecast_distribution=True),
    Method('qdm', 'Quantile Delta Mapping', fit_eqm, apply_qdm, 'change-preserving',
           "x' = Q_obs(tau) * x / Q_model(tau), tau = rank of x in the forecast ensemble; change capped at 5 and replaced "
           "by Q_obs(tau) where Q_model(tau) <= 1 mm (both reported), so preservation is partial there",
           ('Cannon et al. 2015',), uses_forecast_distribution=True),
    Method('sdm', 'Scaled Distribution Mapping', fit_sdm, apply_sdm, 'change-preserving',
           "Switanek et al. (2017) precipitation steps 1-7: gamma fits, recurrence intervals interpolated to the "
           "forecast's length, scaled CDF, rain-member count; model climatology with equal-year weights",
           ('Switanek et al. 2017',), uses_forecast_distribution=True),
    Method('cdft', 'CDF-transform', fit_cdft, apply_cdft, 'change-preserving',
           "F_obs,f = F_obs(F_model^-1(F_forecast)); x' = F_obs,f^-1(F_forecast(x)); implementation choices: model and "
           "forecast first scaled to the CHIRPS mean, values stay within the scaled forecast range",
           ('Michelangeli et al. 2009', 'Vrac et al. 2012'), uses_forecast_distribution=True),
]}
# Sensitivity variants: scored and screened against the reference, but outside the declared family of 13 methods
# (not in the family-wide multiplicity correction and never chosen by the selection-aware procedures).
VARIANTS = {m.key: m for m in [
    Method('mvs_zero_guard', 'MVS with all-zero guard (variant)', fit_mvs, apply_mvs, 'variant',
           "Operational MVS, but corrected totals are 0 mm where every training year has exactly 0 mm (a documented modelling "
           "choice, not a physical rule)", ('Torralba et al. 2017', 'Manzanas et al. 2019'),
           defaults=dict(ratio_bounds=(0.5, 2.0), min_model_sd=1.0, zero_guard=True)),
]}
# External methods: implemented from other systems and evaluated in their own benchmarks (not in the declared family).
EXTERNAL = {m.key: m for m in [
    Method('leung_affine', 'Modified-Leung member-wise affine (GrazFeediNG)', fit_leung, apply_leung, 'external',
           "x'_m = max(0, mu_obs + r_m (x_m - mu_m)) with each member's own climatology; r_m = clip(sd_obs / sd_eff_m, 0.5, 2), "
           "sd_eff_m = 0.7 sd_m + 0.3 sd_pool; r = 1 where both spreads < 1 mm; members without their own climatology use the "
           "pooled one (process_calib.py, docs/51)", ('Munoz & Demissie, GrazFeediNG',),
           defaults=dict(beta=0.3, ratio_bounds=(0.5, 2.0), sigma_min=1.0)),
]}
ALL = {'raw': BASELINE, **METHODS, **VARIANTS, **EXTERNAL}   # benchmark rows: baseline, the 13 methods, variants, external


META_KEYS = ('base', 'label', 'family', 'definition')


def resolve(key, entry=None):
    """The method of a configuration entry and its parameters.

    An entry is either parameters of a registry method, or a configured variant of one:
    {"base": "mvs", "label": "...", "family": "...", <parameters>} (e.g. MVS with other ratio limits).
    """
    entry = dict(entry or {})
    params = {k: v for k, v in entry.items() if k not in META_KEYS}
    if 'base' not in entry:
        m = ALL[key]
        return m, {**m.defaults, **params}
    base = ALL[entry['base']]
    m = replace(base, key=key, label=entry.get('label', f'{base.label} ({key})'), family=entry.get('family', base.family),
                definition=entry.get('definition', f'{base.definition}; parameters {params}'), defaults={**base.defaults, **params})
    return m, dict(m.defaults)


def correct(key, models, obs, members, params=None):
    """Fit on the training years and correct one forecast. Ineligible cells are NaN."""
    m = ALL[key]
    p = {**m.defaults, **(params or {})}
    state = m.fit(models, obs, **p)
    out = np.asarray(m.apply(np.asarray(members, float), state, **p), float)
    out[:, ~state['ok']] = np.nan
    return out
