import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import bias_methods as bm                                               # noqa: E402
from grazfeeding import IADDirichlet, member_probabilities, observed_category   # noqa: E402


class IAD(unittest.TestCase):
    def test_calibrated_input_stays_near_identity(self):
        rng = np.random.default_rng(1)
        P = rng.dirichlet([2, 2, 2], 4000)
        y = np.array([rng.choice(3, p=p) for p in P])                  # outcomes drawn from P: already calibrated
        c = IADDirichlet().fit(P, y)
        self.assertTrue(c.converged)
        self.assertLess(np.abs(c.predict(P) - P).mean(), 0.02)

    def test_overconfident_input_is_softened(self):
        rng = np.random.default_rng(2)
        y = rng.integers(0, 3, 3000)
        P = np.full((3000, 3), .05)
        hit = rng.random(3000) < .5
        guess = np.where(hit, y, rng.integers(0, 3, 3000))
        P[np.arange(3000), guess] = .9
        q = IADDirichlet().fit(P, y).predict(P)
        self.assertLess(q.max(1).mean(), .8)
        np.testing.assert_allclose(q.sum(1), 1, atol=1e-9)


class Leung(unittest.TestCase):
    def test_member_climatology_and_pooled_extra_members(self):
        rng = np.random.default_rng(3)
        obs = rng.gamma(4, 50, (20, 10))
        models = [np.stack([o * .5 + 10 + rng.normal(0, 5, 10) for _ in range(25)]) for o in obs]
        m, p = bm.resolve('leung_affine', {})
        s = m.fit(models, obs, **p)
        out = np.stack([m.apply(x, s, **p) for x in models])
        np.testing.assert_allclose(out.mean((0, 1)), obs.mean(0), rtol=1e-6)    # each member's climatology -> observed mean
        self.assertTrue((s['ratio_member'] <= 2).all() and (s['ratio_member'] >= .5).all())
        extra = m.apply(np.vstack([models[0], models[0][:5]]), s, **p)       # 30 members: 5 use the pooled climatology
        self.assertEqual(extra.shape, (30, 10))
        self.assertEqual(s['counts']['pooled_climatology_members'][0], 5 * 10)
        self.assertTrue((extra >= 0).all())


class Categories(unittest.TestCase):
    def test_counts_and_categories(self):
        q1, q2 = np.array([10., 10.]), np.array([20., 20.])
        p = member_probabilities(np.array([[5., 25.], [15., 25.], [25., np.nan]]), q1, q2)
        np.testing.assert_allclose(p[0], [1 / 3, 1 / 3, 1 / 3])
        self.assertTrue(np.isnan(p[1]).all())
        np.testing.assert_array_equal(observed_category(np.array([5., 10., 20., 21., np.nan]), *(np.full(5, v) for v in (10., 20.))), [0, 1, 1, 2, -1])


if __name__ == '__main__':
    unittest.main()
