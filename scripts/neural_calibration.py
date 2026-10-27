"""Distributional regression network (DRN) with a censored shifted gamma output: a neural extension of the EMOS model of
dist_calibration.py (docs/54). Benchmark only; nothing here changes the published forecast.

One small network is shared by every grid cell of a target (pooled over cells and training years, equal weight per year,
area within): it maps the ensemble summaries and the local context of a cell to the three parameters of a left-censored
shifted gamma in relative units (amount / training CHIRPS mean), as EMOS does with two linear predictors:
    mean mu = softplus(o1),  sd sigma = softplus(o2),  shift delta = -softplus(o3);  k = (mu / sigma)^2, theta = sigma^2 / mu.
Loss: the closed-form CRPS of the censored shifted gamma (Scheuerer & Hamill 2015) plus weight decay on the weights.
Gradient: the CRPS of each sample is differentiated with respect to (mu, sigma, delta) by forward differences (SciPy's
incomplete gamma, double precision) and back-propagated through the network by hand.
Training: full-batch Adam on every second cell in each direction (neighbouring 0.25-degree cells carry nearly the same
information; predictions cover every cell); early stopping on validation years held out of the training years (a different
random set for each of three seeds); the architecture (32, or 32-16 units) and the weight decay (1e-4 or 1e-3) are chosen by
the mean validation CRPS of the seeds, all inside the outer fold. The forecast is the equal mixture of the three seeds' distributions.

Variants (registered in dist_calibration.MODELS):
  drn_csg            the network on the ensemble summaries and the local context (INPUTS['full'])
  drn_linear_csg     control: the same inputs and CRPS loss, no hidden layer (a linear EMOS with more predictors)
  drn_climatology    ablation: the network without the forecast (climatology and location only)
  drn_forecast_only  ablation: the network on the ensemble summaries only (no climatology, no location)
  drn_sst            the DRN plus large-scale and regional inputs: SEAS5 Nino 3.4 and Indian Ocean Dipole indices of the
                     target months and the EMI rainfall regions (sst_indices.py)
  drn_pooled         one network for the four months of a cycle (scripts/pooled_benchmark.py): the DRN inputs plus the
                     month's position in the season (one-hot); four times the samples per network, from the same years
  drn_csg_tuned      the DRN with the configuration chosen on a separate tuning split (TUNING_FOLDS inner folds of years,
                     apart from the early-stopping years); diagnostic of the tuning procedure
  drn_emos_residual  a regularized neural correction of EMOS: EMOS (maximum likelihood, the training years of the seed) gives
                     the linear predictors of mu, sigma and delta; the network adds to them, starting from zero (its output
                     layer starts at zero, early stopping keeps EMOS if no step improves the held-out CRPS) with a penalty
                     OUT_PENALTY on the size of the correction
"""
import numpy as np
from scipy.special import betaln, expit, gammainc, gammaln

from dist_calibration import CSGamma, Distribution, FLOOR

INPUTS = {'full': ('m', 'q50', 's', 'md', 'q10', 'q90', 'logmu', 'cv', 'lat', 'lon'),
          'climatology': ('logmu', 'cv', 'lat', 'lon'),
          'forecast': ('m', 'q50', 's', 'md', 'q10', 'q90'),
          'full_sst': ('m', 'q50', 's', 'md', 'q10', 'q90', 'logmu', 'cv', 'lat', 'lon', 'nino34', 'dmi',
                       *(f'region_{i}' for i in range(1, 9)))}
INPUTS['full_regions'] = INPUTS['full'] + tuple(f'region_{i}' for i in range(1, 9))   # drn_regions: regions, no SST
INPUTS['pooled'] = INPUTS['full'] + tuple(f'target_{i}' for i in range(1, 5))   # drn_pooled: position of the month
NBHD = ('m_nb3', 's_nb3', 'q50_nb3', 'm_nb5')         # neighbourhood means of ensemble summaries (dist_benchmark.add_neighbourhood)
INPUTS['pooled_nbhd'] = INPUTS['pooled'] + NBHD       # drn_pooled_nbhd: the pooled DRN with neighbourhood inputs
INPUTS['pooled_all'] = INPUTS['pooled'] + tuple(f'cycle_{i}' for i in range(1, 5))   # drn_pooled_all: also the cycle
INPUTS['fmam_ondj'] = INPUTS['pooled'] + tuple(f'cycle_{i}' for i in range(1, 4))    # drn_fmam_ondj: the cycle, JJAS left out
OUT_PENALTY = 0.01                    # drn_emos_residual: penalty on the mean squared correction of EMOS's predictors
TUNING_FOLDS = 3                      # tuning='separate': inner folds of years that choose the configuration
SEEDS = (0, 1, 2)
VALID_SHARE = 0.2                     # share of the training years held out for early stopping
STEPS, CHECK, PATIENCE, LR = 2000, 10, 15, 0.003
DEFAULT_CONFIGS = ([32], 1e-4), ([32], 1e-3), ([32, 16], 1e-4), ([32, 16], 1e-3)   # architecture x weight decay
THIN = 2                              # training cells: every THIN-th cell in each direction


# ---------------------------------------------------------------- the CRPS of the censored shifted gamma
def _p_next(a, x, pa):
    """P(a + 1, x) from P(a, x): P(a + 1, x) = P(a, x) - x^a e^-x / Gamma(a + 1)."""
    with np.errstate(divide='ignore', invalid='ignore'):
        term = np.exp(a * np.log(np.where(x > 0, x, 1)) - x - gammaln(a + 1))
    return pa - np.where(x > 0, term, 0.)


def crps_csg(k, theta, delta, y):
    """Closed-form CRPS of Y = max(0, X + delta), X ~ Gamma(k, theta), delta <= 0 (Scheuerer & Hamill 2015, eq. 5)."""
    yt, ct = (y - delta) / theta, -delta / theta
    fk_y, fk_c = gammainc(k, yt), gammainc(k, ct)
    fk1_y, fk1_c = _p_next(k, yt, fk_y), _p_next(k, ct, fk_c)
    return (theta * yt * (2 * fk_y - 1) - theta * ct * fk_c ** 2 + theta * k * (1 + 2 * fk_c * fk1_c - fk_c ** 2 - 2 * fk1_y)
            - theta * k / np.pi * np.exp(betaln(.5, k + .5)) * (1 - gammainc(2 * k, 2 * ct)))


def _crps_msd(mu, sg, de, y):
    return crps_csg((mu / sg) ** 2, sg ** 2 / mu, de, y)


def _crps_and_grad(mu, sg, de, y):
    """CRPS per sample and its derivatives with respect to mu, sigma and delta (forward differences)."""
    c = _crps_msd(mu, sg, de, y)
    hm, hs, hd = 1e-6 * np.maximum(mu, 1e-3), 1e-6 * np.maximum(sg, 1e-3), 1e-6 * np.maximum(-de, 1e-3)
    return c, ((_crps_msd(mu + hm, sg, de, y) - c) / hm, (_crps_msd(mu, sg + hs, de, y) - c) / hs,
               (_crps_msd(mu, sg, de - hd, y) - c) / -hd)


# ---------------------------------------------------------------- the network
def _softplus(x):
    return np.logaddexp(0, x)


def _softplus_inv(x):
    return float(np.log(np.expm1(max(x, 1e-6))))


def _init(rng, sizes, out_bias, zero_out=False):
    params = []
    for i, (a, b) in enumerate(zip(sizes[:-1], sizes[1:])):
        last = i == len(sizes) - 2
        W = np.zeros((a, b)) if last and zero_out else rng.normal(0, 0.01 if last else np.sqrt(2 / (a + b)), (a, b))
        params.append([W, np.array(out_bias, float) if last else np.zeros(b)])
    return params


def _forward(params, X, keep=False, base=None):
    """CSG parameters (mu, sigma, delta) per row; with keep, the layer inputs and pre-activations for back-propagation.
    base: (rows, 3) linear predictors the network output is added to (drn_emos_residual), else none."""
    h, cache = X, []
    for W, b in params[:-1]:
        z = h @ W + b
        cache.append((h, z))
        h = np.where(z > 0, z, np.expm1(np.minimum(z, 0)))                     # ELU
    o = h @ params[-1][0] + params[-1][1]
    o = o if base is None else o + base
    cache.append((h, o))
    out = (_softplus(o[:, 0]) + (1e-3 if base is None else 0.), _softplus(o[:, 1]) + 1e-3, -_softplus(o[:, 2]))
    return (out, cache) if keep else out


def _loss_grad(params, X, y, w, decay, base=None, out_penalty=0.):
    (mu, sg, de), cache = _forward(params, X, keep=True, base=base)
    c, (gm, gs, gd) = _crps_and_grad(mu, sg, de, y)
    o = cache[-1][1]
    d = np.column_stack([gm * expit(o[:, 0]), gs * expit(o[:, 1]), -gd * expit(o[:, 2])]) * w[:, None]
    corr = o if base is None else o - base                                   # the network's own output
    if out_penalty:
        d = d + 2 * out_penalty * w[:, None] * corr
    grads = [None] * len(params)
    h = cache[-1][0]
    grads[-1] = [h.T @ d + 2 * decay * params[-1][0], d.sum(0)]
    delta = d @ params[-1][0].T
    for i in range(len(params) - 2, -1, -1):
        hin, z = cache[i]
        delta = delta * np.where(z > 0, 1., np.exp(np.minimum(z, 0)))       # ELU derivative
        grads[i] = [hin.T @ delta + 2 * decay * params[i][0], delta.sum(0)]
        delta = delta @ params[i][0].T
    loss = float(w @ c) + decay * sum(float(np.sum(W ** 2)) for W, _ in params) + out_penalty * float(w @ np.sum(corr ** 2, 1))
    return loss, grads


def _score(params, X, y, w, base=None):
    mu, sg, de = _forward(params, X, base=base)
    return float(w @ _crps_msd(mu, sg, de, y))


def _train(X, y, w, train_rows, valid_rows, hidden, decay, seed, base=None, out_penalty=0., report=None):
    """Adam on the training rows, early stopping on the validation rows (weighted CRPS); returns (params, best validation
    CRPS, best step). With base (drn_emos_residual) the output layer starts at zero: the starting point is the base model.
    report (a dict) receives the diagnostics: best_step, steps_run, stop ('early_stopping', 'max_steps' or 'nonfinite'),
    nonfinite (a non-finite loss, gradient or validation score occurred) and fallback (the starting point was returned)."""
    rng = np.random.default_rng(seed)
    Xt, yt, wt = X[train_rows], y[train_rows], w[train_rows] / w[train_rows].sum()
    Xv, yv, wv = X[valid_rows], y[valid_rows], w[valid_rows] / w[valid_rows].sum()
    bt, bv = (None, None) if base is None else (base[train_rows], base[valid_rows])
    mean = float(wt @ yt)
    sd = float(np.sqrt(wt @ (yt - mean) ** 2))
    if base is None:
        params = _init(rng, [X.shape[1]] + list(hidden) + [3], [_softplus_inv(mean), _softplus_inv(sd), -3.])
    else:
        params = _init(rng, [X.shape[1]] + list(hidden) + [3], [0., 0., 0.], zero_out=True)
    m = [[np.zeros_like(W), np.zeros_like(b)] for W, b in params]
    v = [[np.zeros_like(W), np.zeros_like(b)] for W, b in params]
    b1, b2, eps = .9, .999, 1e-8
    best, best_p, best_step, bad = _score(params, Xv, yv, wv, bv), [[W.copy(), b.copy()] for W, b in params], 0, 0
    stop, nonfinite, step = 'max_steps', False, 0
    for step in range(1, STEPS + 1):
        loss, g = _loss_grad(params, Xt, yt, wt, decay, bt, out_penalty)
        if not (np.isfinite(loss) and all(np.isfinite(a).all() for gi in g for a in gi)):
            stop, nonfinite = 'nonfinite', True
            break
        for i in range(len(params)):
            for j in range(2):
                m[i][j] = b1 * m[i][j] + (1 - b1) * g[i][j]
                v[i][j] = b2 * v[i][j] + (1 - b2) * g[i][j] ** 2
                params[i][j] = params[i][j] - LR * (m[i][j] / (1 - b1 ** step)) / (np.sqrt(v[i][j] / (1 - b2 ** step)) + eps)
        if step % CHECK == 0:
            s = _score(params, Xv, yv, wv, bv)
            if not np.isfinite(s):
                stop, nonfinite = 'nonfinite', True
                break
            if s < best - 1e-7:
                best, best_p, best_step, bad = s, [[W.copy(), b.copy()] for W, b in params], step, 0
            else:
                bad += 1
                if bad >= PATIENCE:
                    stop = 'early_stopping'
                    break
    if report is not None:
        report.update(best_step=best_step, steps_run=step, stop=stop, nonfinite=nonfinite, fallback=best_step == 0)
    return best_p, best, best_step


# ---------------------------------------------------------------- the model interface (dist_calibration.Model)
def _design(D, inputs, norm=None):
    X = np.column_stack([np.asarray(D[k], float) for k in inputs])
    if norm is None:
        mu, sd = X.mean(0), X.std(0)
        norm = dict(mean=mu.tolist(), sd=np.where(sd > 1e-9, sd, 1.).tolist())
    return (X - np.asarray(norm['mean'])) / np.asarray(norm['sd']), norm


def _thinned(S):
    """Rows of the training cells: every THIN-th latitude and longitude of the 0.25-degree grid."""
    lat, lon = np.asarray(S['lat'], float), np.asarray(S['lon'], float)
    if not (np.ptp(lat) > 0 and np.ptp(lon) > 0):
        return np.ones(len(lat), bool)
    return (np.round((lat - lat.min()) / 0.25) % THIN == 0) & (np.round((lon - lon.min()) / 0.25) % THIN == 0)


def emos_base(theta, m, md, group=None):
    """EMOS's linear predictors of mu, sigma and delta (dist_calibration.emos_fit) per row. theta: one parameter vector, or
    {group: vector} with each row's group (pooled samples: the month), so each month has its own EMOS."""
    m, md = np.nan_to_num(np.asarray(m, float)), np.nan_to_num(np.asarray(md, float))
    if isinstance(theta, dict):
        out = np.zeros((len(m), 3))
        for g, th in theta.items():
            r = np.asarray(group) == int(g)
            out[r] = emos_base(th, m[r], md[r])
        return out
    th = np.asarray(theta, float)
    return np.column_stack([th[0] + th[1] * m, th[2] + th[3] * md, np.full(len(m), th[4])])


def groups_of(D):
    """The month group of each row of pooled samples or features (target_1..4 one-hot), or None."""
    cols = [f'target_{i}' for i in range(1, 5)]
    if not all(c in D for c in cols):
        return None
    return np.argmax(np.column_stack([np.asarray(D[c], float) for c in cols]), 1)


def fit(S, inputs='full', configs=None, seeds=SEEDS, residual=None, out_penalty=OUT_PENALTY, tuning='early_stopping', **_):
    """Fit the DRN on the pooled training samples S (dist_benchmark.fold): choose the configuration by the seeds' validation
    CRPS, keep the three seeds of the chosen configuration. residual='emos': the network corrects EMOS fitted, for each
    seed, on that seed's training years. tuning='separate': the configuration is chosen by TUNING_FOLDS inner folds of
    years (each fold's years scored by a network trained on the other years, early-stopped on a further share of them),
    then the three seeds of the chosen configuration are trained as usual. S['year_index'] (pooled samples) gives each row's
    training year; otherwise rows are taken to come year by year in equal numbers."""
    kw_configs = configs
    configs = [(list(h), float(d)) for h, d in (configs or DEFAULT_CONFIGS)]
    names = INPUTS[inputs] if isinstance(inputs, str) else tuple(inputs)
    X, norm = _design(S, names)
    y, w = np.asarray(S['y'], float), np.asarray(S['w'], float)
    n_years = int(S['n_years'])
    year = np.asarray(S['year_index']) if 'year_index' in S else np.repeat(np.arange(n_years), len(y) // n_years)
    rows = _thinned(S)
    runs = {}
    tuned = None
    if tuning == 'separate':
        if residual:
            raise ValueError('tuning="separate" is not implemented for the residual model')
        tuned = {}
        folds = np.array_split(np.random.default_rng(2000).permutation(n_years), TUNING_FOLDS)
        for c, (hidden, decay) in enumerate(configs):
            total = 0.
            for k, fy in enumerate(folds):
                tune = np.isin(year, fy)
                rest = np.setdiff1d(np.arange(n_years), fy)
                held = np.random.default_rng(3000 + k).choice(rest, max(1, round(VALID_SHARE * len(rest))), replace=False)
                vrows = np.isin(year, held)
                fit_rows = ~tune & ~vrows
                # standardization fitted on this inner fitting subset only, then applied to its early-stopping and tuning years
                _, norm_k = _design({kk: np.asarray(S[kk])[fit_rows] for kk in names}, names)
                Xk, _ = _design(S, names, norm_k)
                p, _, _ = _train(Xk, y, w, rows & fit_rows, rows & vrows, hidden, decay, k)
                tr = rows & tune
                total += _score(p, Xk[tr], y[tr], w[tr] / w[tr].sum()) * len(fy)
            tuned[c] = total / n_years
        configs = [configs[min(tuned, key=tuned.get)]]           # only the chosen configuration is trained with the seeds
    for c, (hidden, decay) in enumerate(configs):
        for seed in seeds:
            held = np.random.default_rng(1000 + seed).choice(n_years, max(1, round(VALID_SHARE * n_years)), replace=False)
            vrows = np.isin(year, held)
            base, theta = None, None
            if residual == 'emos':
                from dist_calibration import emos_fit
                tr = ~np.isin(year, held)
                grp = groups_of(S)
                if grp is None:
                    theta = emos_fit({k: np.asarray(S[k])[tr] for k in ('y', 'm', 'md', 'w')})['theta']
                else:                                            # pooled samples: an EMOS per month (each month's own base)
                    theta = {}
                    for g in np.unique(grp):
                        r = tr & (grp == g)
                        theta[int(g)] = list(emos_fit({k: np.asarray(S[k])[r] for k in ('y', 'm', 'md', 'w')})['theta'])
                base = emos_base(theta, S['m'], S['md'], grp)
            rep = {}
            p, s, steps = _train(X, y, w, rows & ~vrows, rows & vrows, hidden, decay, seed, base,
                                 out_penalty if residual else 0., report=rep)
            runs.setdefault(c, []).append(dict(params=p, valid_crps=s, steps=steps, seed=seed, emos=theta, report=rep))
    score = {c: float(np.mean([r['valid_crps'] for r in rs])) for c, rs in runs.items()}
    best = min(score, key=score.get)
    hidden, decay = configs[best]
    if tuned is not None:                                           # report the tuning-split scores of every configuration
        all_configs = [(list(h), float(d)) for h, d in ((kw_configs or DEFAULT_CONFIGS))]
        score = {i: v for i, v in tuned.items()}
        configs = all_configs
    return dict(inputs=list(names), norm=norm, hidden=hidden, decay=decay, tuning=tuning,
                members=[dict(params=[[W.tolist(), b.tolist()] for W, b in r['params']], steps=r['steps'], seed=r['seed'],
                              **({'emos': (r['emos'] if isinstance(r['emos'], dict) else list(r['emos']))}
                                 if r['emos'] is not None else {})) for r in runs[best]],
                residual=residual,
                validation_crps={f'{configs[c][0]}|{configs[c][1]}': v for c, v in score.items()},
                steps=[r['steps'] for r in runs[best]],
                training=[r['report'] for r in runs[best]],          # best step, steps run, stop reason, non-finite, fallback
                converged=all(r['report'].get('stop') == 'early_stopping' and not r['report'].get('nonfinite') for r in runs[best]),
                form='DRN: shared MLP (ELU) -> censored shifted gamma (mu, sigma, delta); CRPS + weight decay; '
                     'early stopping on held-out years; mixture of 3 seeds')


class CSGMixture(Distribution):
    """Equal mixture of censored shifted gammas (the seeds of a DRN); quantiles by bisection on the mixture CDF."""

    def __init__(self, parts, scale, valid):
        super().__init__(scale, valid)
        self.parts = parts                                  # [(k, theta, delta)] in relative units

    def _rel_cdf(self, z):
        z = np.asarray(z, float)
        return np.mean([np.where(z >= 0, gammainc(k, np.maximum(z - d, 0) / t), 0.) for k, t, d in self.parts], axis=0)

    def cdf(self, x):
        return self._rel_cdf(np.asarray(x, float) / np.where(self.scale > 0, self.scale, 1))

    def quantile(self, u, iterations=60):
        u = np.clip(np.asarray(u, float), FLOOR, 1 - FLOOR)
        ones = np.ones_like(self.scale, dtype=float)
        hi = np.max([CSGamma(k, t, d, ones, self.valid).quantile(u) for k, t, d in self.parts], axis=0) + 1e-9
        lo = np.zeros_like(hi)
        for _ in range(iterations):
            mid = (lo + hi) / 2
            below = self._rel_cdf(mid) < u
            lo, hi = np.where(below, mid, lo), np.where(below, hi, mid)
        return self.scale * np.where(self._rel_cdf(np.zeros_like(u)) >= u, 0., hi)


def predict(F, model):
    """The mixture of the seeds' distributions for one year's cells (features F from dist_calibration.features)."""
    X, _ = _design(F, model['inputs'], model['norm'])
    X = np.nan_to_num(X)
    parts = []
    for m in model['members']:
        emos = m.get('emos')
        if isinstance(emos, dict):                               # JSON keys are strings
            emos = {int(g): th for g, th in emos.items()}
        base = emos_base(emos, F['m'], F['md'], groups_of(F)) if emos is not None else None
        mu, sg, de = _forward([[np.asarray(W), np.asarray(b)] for W, b in m['params']], X, base=base)
        parts.append(((mu / sg) ** 2, sg ** 2 / mu, de))
    return CSGMixture(parts, F['scale'], F['valid'])
