import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import mos_benchmark as mb          # noqa: E402


def synthetic(n=25, p=30, q=80, seed=0):
    """A shared signal f drives both fields; the last year is held out."""
    rng = np.random.default_rng(seed)
    f = rng.normal(size=n)
    X = np.outer(f, rng.normal(size=p)) + 0.3 * rng.normal(size=(n, p))
    Y = 5 + np.outer(f, rng.normal(size=q)) + 0.3 * rng.normal(size=(n, q))
    return X, Y


class MOSModel(unittest.TestCase):
    def test_recovers_a_shared_signal(self):
        X, Y = synthetic()
        for kind in ('cca', 'pcr'):
            m = mb.MOS(kind).fit(X[:-1], Y[:-1])
            mean, sigma = m.predict(X[-1])
            self.assertGreater(np.corrcoef(mean - Y[:-1].mean(0), Y[-1] - Y[:-1].mean(0))[0, 1], 0.8, kind)
            self.assertTrue((sigma > 0).all())
            self.assertLessEqual(m.combo[0], 6)

    def test_spread_grows_with_leverage(self):
        X, Y = synthetic()
        m = mb.MOS('pcr').fit(X[:-1], Y[:-1])
        typical = X[:-1].mean(0)
        _, s_typical = m.predict(typical)
        _, s_unusual = m.predict(typical + 4 * (X[:-1] - typical).std(0))
        self.assertTrue((s_unusual > s_typical).all())

    def test_blend_weight_follows_the_signal(self):
        rng = np.random.default_rng(1)
        X, Y = synthetic(n=30, seed=1)
        Y = Y ** 2 / 4 + 5                                             # rainfall-like amounts whose square root carries the signal
        Ys = np.sqrt(Y)
        strong = mb.MOS('pcr').fit(X, Ys)
        noise = mb.MOS('pcr').fit(rng.normal(size=X.shape), Ys)
        self.assertGreater(strong.w, noise.w)
        self.assertLessEqual(noise.w, 0.5)

    def test_field_choice_and_combined_weights(self):
        X, Y = synthetic()
        rng = np.random.default_rng(2)
        fields = {'rain': rng.normal(size=X.shape), 'sst': X, 'rain+sst': np.hstack([rng.normal(size=X.shape), X])}
        m = mb.MOS('pcr', fields=['rain', 'sst', 'rain+sst']).fit(fields, Y, widths={'rain+sst': [X.shape[1], X.shape[1]]})
        self.assertIn(m.field, ('sst', 'rain+sst'))                    # the informative field is used
        w = mb.MOS.column_weights([4, 16])
        self.assertAlmostEqual(float(np.sum(w[:4] ** 2)), float(np.sum(w[4:] ** 2)))

    def test_target_months_cross_the_year(self):
        self.assertEqual(mb.target_months({'season': {'start': '10-01', 'end': '01-31'}}), [10, 11, 12, 1])
        self.assertEqual(mb.target_months({'season': {'start': '06-01', 'end': '06-30'}}), [6])

    def test_products_are_coherent(self):
        mean, sigma = np.array([2.0, 5.0, 8.0]), np.array([1.0, 1.0, 1.0])
        q1, q2 = np.array([16.0, 16.0, 16.0]), np.array([36.0, 36.0, 36.0])       # square roots 4 and 6
        p, ens, quant = mb.products(mean, sigma, q1, q2)
        np.testing.assert_allclose(p.sum(-1), 1, atol=1e-9)
        self.assertGreater(p[0, 0], 0.9)                       # far below the lower tercile
        self.assertGreater(p[2, 2], 0.9)
        self.assertEqual(ens.shape, (mb.K, 3))
        self.assertTrue((ens >= 0).all())
        self.assertAlmostEqual(quant[.5][1], 25.0, places=6)   # median of sqrt-space N(5, 1), squared


if __name__ == '__main__':
    unittest.main()
