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
        d = dc.CSGamma(k, theta, delta, np.ones(n), np.ones(n, bool))
        num = dc.Distribution.crps(d, y, points=16000)                # the general numerical rule, not CSGamma's closed form
        np.testing.assert_allclose(nc.crps_csg(k, theta, delta, y), num, atol=1e-3)
        np.testing.assert_allclose(d.crps(y), nc.crps_csg(k, theta, delta, y))          # CSGamma scores by the closed form

    def test_mixture_crps_split_at_the_observation_is_accurate(self):
        from scipy import integrate
        parts = [(np.array([1.2]), np.array([.9]), np.array([-.1])), (np.array([4.]), np.array([.25]), np.array([-.02])),
                 (np.array([2.5]), np.array([.5]), np.array([-.05]))]
        d = nc.CSGMixture(parts, np.array([700.]), np.array([True]))
        for y in (0., 150., 420., 900., 2500.):
            F = lambda x: float(d.cdf(np.array([x]))[0])                  # noqa: E731
            ref = (integrate.quad(lambda x: F(x) ** 2, 0, y, limit=400)[0] if y > 0 else 0.) +                 integrate.quad(lambda x: (1 - F(x)) ** 2, y, max(y, float(d.quantile(np.array([1 - 1e-10]))[0])), limit=400)[0]
            self.assertLess(abs(float(d.crps(np.array([y]))[0]) - ref), 2e-3 * ref + 1e-6, y)

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

    def test_emos_residual_starts_at_emos_and_its_gradient_is_exact(self):
        S = samples(seed=3)
        theta = dc.emos_fit({k: S[k] for k in ('y', 'm', 'md', 'w')})['theta']
        base = nc.emos_base(theta, S['m'], S['md'])
        rng = np.random.default_rng(0)
        X, _ = nc._design(S, nc.INPUTS['full'])
        p = nc._init(rng, [X.shape[1], 6, 3], [0., 0., 0.], zero_out=True)
        mu, sg, de = nc._forward(p, X, base=base)                                # zero output layer: exactly EMOS
        e = dc.emos_predict(dict(m=S['m'], md=S['md'], scale=np.ones(len(S['y'])), valid=np.ones(len(S['y']), bool)), dict(theta=theta))
        np.testing.assert_allclose((mu / sg) ** 2, e.k, rtol=1e-10)                  # mean, spread and shift exactly
        np.testing.assert_allclose(sg ** 2 / mu, e.theta, rtol=1e-10)
        np.testing.assert_allclose(de, e.delta)
        p[-1][0] += rng.normal(0, .1, p[-1][0].shape)
        _, g = nc._loss_grad(p, X, S['y'], S['w'], 1e-3, base, .01)
        h = 1e-6
        p[-1][0][2, 1] += h
        lp, _ = nc._loss_grad(p, X, S['y'], S['w'], 1e-3, base, .01)
        p[-1][0][2, 1] -= 2 * h
        lm, _ = nc._loss_grad(p, X, S['y'], S['w'], 1e-3, base, .01)
        self.assertAlmostEqual(g[-1][0][2, 1], (lp - lm) / (2 * h), delta=1e-4 * max(1, abs(g[-1][0][2, 1])))

    def test_variants_fit_and_predict(self):
        S, test = samples(seed=4), samples(n_years=3, seed=8)
        for extra in (S, test):
            n = len(extra['y'])
            extra.update(nino34=np.repeat(np.arange(len(extra['y']) // 60), 60)[:n].astype(float), dmi=np.zeros(n),
                         **{f'region_{i}': np.zeros(n) for i in range(1, 9)})
        F = dict(test, scale=np.ones(len(test['y'])), valid=np.ones(len(test['y']), bool))
        for kw in (dict(inputs='forecast'), dict(inputs='full_sst'), dict(inputs='full', residual='emos')):
            model = nc.fit(S, configs=[([4], 1e-4)], **kw)
            d = nc.predict(F, model)
            self.assertTrue(np.isfinite(d.crps(test['y'])).all(), kw)
        self.assertEqual(len(model['members'][0]['emos']), 5)

    def test_training_reports_why_it_stopped(self):
        model = nc.fit(samples(seed=2), configs=[([4], 1e-4)])
        self.assertEqual(len(model['training']), 3)
        for r in model['training']:
            self.assertEqual(set(r), {'best_step', 'steps_run', 'stop', 'nonfinite', 'fallback'})
            self.assertIn(r['stop'], ('early_stopping', 'max_steps', 'nonfinite'))
            self.assertLessEqual(r['best_step'], r['steps_run'])
        self.assertEqual(model['converged'], all(r['stop'] == 'early_stopping' and not r['nonfinite'] for r in model['training']))

    def test_regions_only_control_fits(self):
        S, test = samples(seed=4), samples(n_years=3, seed=8)
        for extra in (S, test):
            extra.update({f'region_{i}': (np.arange(len(extra['y'])) % 8 == i - 1).astype(float) for i in range(1, 9)})
        model = nc.fit(S, inputs='full_regions', configs=[([4], 1e-4)])
        self.assertEqual(model['inputs'][-8:], [f'region_{i}' for i in range(1, 9)])
        self.assertNotIn('nino34', model['inputs'])
        d = nc.predict(dict(test, scale=np.ones(len(test['y'])), valid=np.ones(len(test['y']), bool)), model)
        self.assertTrue(np.isfinite(d.crps(test['y'])).all())

    def test_separate_tuning_reports_every_configuration(self):
        S = samples(seed=5)
        model = nc.fit(S, configs=[([4], 1e-4), ([4, 3], 1e-3)], tuning='separate')
        self.assertEqual(model['tuning'], 'separate')
        self.assertEqual(len(model['validation_crps']), 2)
        best = min(model['validation_crps'], key=model['validation_crps'].get)
        self.assertEqual(best, f"{model['hidden']}|{model['decay']}")
        self.assertEqual(len(model['members']), 3)

    def test_pooled_rows_hold_out_whole_years(self):
        a, b = samples(n_years=6, cells=60, seed=6), samples(n_years=6, cells=30, seed=7)    # two months, different cell counts
        S = {k: np.concatenate([a[k], b[k]]) for k in a if k != 'n_years'}
        S['year_index'] = np.concatenate([np.repeat(np.arange(6), 60), np.repeat(np.arange(6), 30)])
        S['n_years'] = 6
        for i in range(1, 5):
            S[f'target_{i}'] = np.concatenate([np.full(360, float(i == 1)), np.full(180, float(i == 2))])
        model = nc.fit(S, inputs='pooled', configs=[([4], 1e-4)])
        self.assertEqual(model['inputs'][-4:], ['target_1', 'target_2', 'target_3', 'target_4'])
        self.assertTrue(all(m['steps'] >= 0 for m in model['members']))

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
