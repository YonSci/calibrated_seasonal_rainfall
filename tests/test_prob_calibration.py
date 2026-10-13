import sys
import unittest
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import prob_calibration as pc            # noqa: E402
import dist_calibration as dc            # noqa: E402


def records(years=20, cells=300, seed=0, sharp=2.5):
    """Synthetic over-confident forecasts: true probabilities from a latent signal, forecasts sharper than the truth."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(years):
        z = rng.normal(size=cells)
        logits = np.column_stack([-z, np.zeros(cells), z])
        true = np.exp(logits) / np.exp(logits).sum(1, keepdims=True)
        y = np.array([rng.choice(3, p=p) for p in true])
        s = np.exp(sharp * logits) / np.exp(sharp * logits).sum(1, keepdims=True)
        s = (s * 51 + .5) / 52.5
        out.append(dict(s=s, clim=np.full((cells, 3), 1 / 3), y=y.astype('int8'), zmean=z.astype('float32'),
                        lspread=np.zeros(cells, 'float32')))
    return out, np.ones(cells)


def rps(p, y):
    t = np.eye(3)[y]
    return np.mean(np.sum((np.cumsum(p, 1)[:, :2] - np.cumsum(t, 1)[:, :2]) ** 2, 1))


class Probability(unittest.TestCase):
    def test_every_method_gives_valid_probabilities_and_beats_raw_counts(self):
        train, area = records()
        test, _ = records(years=5, seed=9)
        raw = np.mean([rps(r['s'], r['y']) for r in test])
        for key in pc.CALIBRATORS:
            f = pc.fit(key, train, area)
            self.assertIsNone(f['fallback'], key)
            ps = [pc.predict(f, r) for r in test]
            for p in ps:
                self.assertTrue((p >= 0).all() and np.allclose(p.sum(1), 1), key)
            if key != 'pseudocount':
                self.assertLess(np.mean([rps(p, r['y']) for p, r in zip(ps, test)]), raw, key)

    def test_pool_adjacent_violators(self):
        x, v = pc.weighted_pav(np.array([1., 2., 3., 4.]), np.array([0., 1., 0., 1.]), np.ones(4))
        self.assertTrue((np.diff(v) >= 0).all())
        np.testing.assert_allclose(v, [0., .5, 1.])

    def test_temperature_flattens_over_confident_counts(self):
        train, area = records(sharp=3.)
        self.assertGreater(pc.fit('temperature', train, area)['model']['temperature'], 1.5)

    def test_missing_category_falls_back_to_the_incumbent(self):
        train, area = records(years=3)
        for r in train:
            r['y'] = np.where(r['y'] == 2, 1, r['y']).astype('int8')
        f = pc.fit('multinomial_logistic', train, area)
        self.assertIsNotNone(f['fallback'])
        self.assertIn('lam', f['model'])


class Distributions(unittest.TestCase):
    def check(self, d, n):
        u = np.linspace(.05, .95, 7)
        qs = np.array([d.quantile(np.full(n, ui)) for ui in u])
        self.assertTrue((np.diff(qs, axis=0) >= -1e-9).all() and (qs >= 0).all())           # non-crossing, non-negative
        for ui, q in zip(u, qs):
            pos = q > 1e-6
            np.testing.assert_allclose(d.cdf(q)[pos], ui, atol=2e-3)                       # quantile inverts the CDF
        p = d.terciles(np.full(n, 5.), np.full(n, 12.))
        self.assertTrue(np.allclose(p.sum(1), 1) and (p >= 0).all())

    def test_distributions_are_coherent(self):
        n = 6
        valid = np.ones(n, bool)
        scale = np.linspace(5, 50, n)
        self.check(dc.CSGamma(np.full(n, 2.), np.full(n, .5), -.1, scale, valid), n)
        self.check(dc.Logistic(np.full(n, 1.), np.full(n, .3), scale, valid), n)
        levels = dc.QR_LEVELS
        q = np.array([np.full(n, .2 + 1.6 * t) for t in levels])
        q[3] -= .5                                                                           # a crossing to be rearranged
        self.check(dc.Quantiles(levels, q, scale, valid), n)

    def test_numerical_crps_matches_a_sample_estimate(self):
        rng = np.random.default_rng(1)
        d = dc.CSGamma(np.array([3.]), np.array([.4]), -.2, np.array([20.]), np.array([True]))
        sample = 20 * np.maximum(0, rng.gamma(3., .4, 200000) - .2)
        y = np.array([25.])
        mc = np.mean(np.abs(sample - y[0])) - .5 * np.mean(np.abs(sample[:100000] - sample[100000:]))
        self.assertAlmostEqual(float(d.crps(y)[0]), mc, delta=.02 * mc)

    def test_models_recover_a_known_relationship(self):
        rng = np.random.default_rng(3)
        n = 6000
        m = rng.gamma(4., .25, n)
        y = np.maximum(0, rng.gamma(4., .25 * m / 1., n) - .05)                    # mean grows with m
        thr = np.tile(np.quantile(y, dc.THRESHOLD_LEVELS), (n, 1))
        S = dict(y=y, m=m, s=np.full(n, .3), md=np.full(n, .35), w=np.full(n, 1 / n), thresholds=thr)
        F = dict(m=np.array([.5, 1., 2.]), s=np.full(3, .3), md=np.full(3, .35), scale=np.ones(3), valid=np.ones(3, bool))
        for key, mdl in dc.MODELS.items():
            d = mdl.predict(F, mdl.fit(S))
            med = d.quantile(np.full(3, .5))
            self.assertTrue(med[0] < med[1] < med[2], key)                         # wetter ensemble, wetter forecast


if __name__ == '__main__':
    unittest.main()
