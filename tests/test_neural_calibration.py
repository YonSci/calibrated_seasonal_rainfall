import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import dist_calibration as dc          # noqa: E402
import neural_calibration as nc        # noqa: E402


def samples(n_years=10, cells=60, seed=0, signal=True):
    """Pooled training samples as dist_benchmark.fold makes them: rainfall (relative) driven by the ensemble mean."""
    rng = np.random.default_rng(seed)
    lat = np.repeat(np.arange(cells // 6) * .25, 6)[:cells]
    lon = np.tile(np.arange(6) * .25, cells // 6 + 1)[:cells]
    S = {k: [] for k in ('y', 'w') + nc.INPUTS['full']}
    for _ in range(n_years):
        a = rng.normal(size=cells)
        m = 1 + .3 * a
        y = np.maximum(0, (1 + (.25 * a if signal else 0) + .15 * rng.normal(size=cells)))
        S['y'].append(y)
        S['w'].append(np.full(cells, 1 / cells / n_years))
        for k, v in dict(m=m, q50=m, s=np.full(cells, .2), md=np.full(cells, .22), q10=m - .25, q90=m + .25,
                         logmu=np.full(cells, 4.), cv=np.full(cells, .3), lat=lat, lon=lon).items():
            S[k].append(v)
    S = {k: np.concatenate(v) for k, v in S.items()}
    S['n_years'] = n_years
    return S


class ClosedForm(unittest.TestCase):
    def test_crps_matches_numerical_integration(self):
        rng = np.random.default_rng(0)
        n = 300
        k, theta, delta = rng.uniform(.4, 8, n), rng.uniform(.05, 1, n), -rng.uniform(0, 1, n)
        y = np.where(rng.random(n) < .2, 0., rng.gamma(2, .6, n))
        num = dc.CSGamma(k, theta, delta, np.ones(n), np.ones(n, bool)).crps(y, points=16000)
        np.testing.assert_allclose(nc.crps_csg(k, theta, delta, y), num, atol=1e-3)

    def test_backpropagation_matches_finite_differences(self):
        rng = np.random.default_rng(1)
        X, y, w = rng.normal(size=(200, 4)), rng.gamma(3, .4, 200), np.full(200, 1 / 200)
        p = nc._init(rng, [4, 5, 3], [.5, -.5, -3.])
        for W, _ in p:
            W += rng.normal(0, .3, W.shape)
        _, g = nc._loss_grad(p, X, y, w, 1e-3)
        h = 1e-5
        p[0][0][1, 2] += h
        lp, _ = nc._loss_grad(p, X, y, w, 1e-3)
        p[0][0][1, 2] -= 2 * h
        lm, _ = nc._loss_grad(p, X, y, w, 1e-3)
        self.assertAlmostEqual(g[0][0][1, 2], (lp - lm) / (2 * h), delta=1e-4 * max(1, abs(g[0][0][1, 2])))


class Model(unittest.TestCase):
    def test_learns_the_forecast_signal_and_the_ablation_cannot(self):
        S, test = samples(seed=0), samples(n_years=4, seed=9)
        full = nc.fit(S, inputs='full', configs=[([8], 1e-4)])
        clim = nc.fit(S, inputs='climatology', configs=[([8], 1e-4)])
        F = dict(test, scale=np.ones(len(test['y'])), valid=np.ones(len(test['y']), bool))
        crps = lambda model: float(np.mean(nc.predict(F, model).crps(test['y'])))
        self.assertLess(crps(full), crps(clim))

    def test_mixture_quantiles_invert_the_cdf(self):
        parts = [(np.array([2., 5.]), np.array([.5, .2]), np.array([-.3, 0.])), (np.array([3., 4.]), np.array([.3, .3]), np.array([-.1, -.2]))]
        d = nc.CSGMixture(parts, np.array([10., 20.]), np.array([True, True]))
        for u in (.2, .5, .9):
            q = d.quantile(np.full(2, u))
            np.testing.assert_allclose(d.cdf(q)[q > 0], u, atol=1e-6)
        p = d.terciles(np.array([5., 10.]), np.array([12., 25.]))
        np.testing.assert_allclose(p.sum(1), 1)


if __name__ == '__main__':
    unittest.main()
