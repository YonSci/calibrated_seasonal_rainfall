import sys
import unittest
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from bias_methods import METHODS, ALL, correct, pooled, Ecdf          # noqa: E402
from calibration_core import fit_amount, correct_amount          # noqa: E402


def synthetic(years=24, cells=6, seed=1, scale=2.0, shape=3.0):
    """Model = a too-wet gamma world; 25 members to 2016-like years, 51 after."""
    rng = np.random.default_rng(seed)
    obs = rng.gamma(shape, 30., (years, cells))
    models = [rng.gamma(shape, 30. * scale, (25 if y < years - 8 else 51, cells)) for y in range(years)]
    return models, obs, rng


class BiasMethods(unittest.TestCase):
    def test_registry_has_thirteen_distinct_methods(self):
        self.assertEqual(len(METHODS), 13)
        self.assertEqual(len({m.label for m in METHODS.values()}), 13)
        self.assertEqual([k for k, m in METHODS.items() if not m.member_wise], ['dc'])

    def test_raw_baseline_is_identity_and_not_a_method(self):
        models, obs, rng = synthetic()
        target = rng.gamma(3., 60., (51, obs.shape[1]))
        self.assertNotIn('raw', METHODS)
        np.testing.assert_array_equal(correct('raw', models, obs, target), target)
        self.assertEqual(set(ALL) - set(METHODS), {'raw'})

    def test_operational_mvs_matches_calibration_core(self):
        models, obs, rng = synthetic()
        target = rng.gamma(3., 60., (51, obs.shape[1]))
        expected = correct_amount(target, fit_amount(models, obs, np.ones(obs.shape[1], bool)))
        np.testing.assert_allclose(correct('mvs', models, obs, target), expected, rtol=1e-12)

    def test_equal_year_weighting(self):
        """Repeating every member of one year must not change any fit (the year keeps weight 1/Y)."""
        models, obs, rng = synthetic(cells=3)
        target = rng.gamma(3., 60., (51, 3))
        doubled = [np.r_[m, m] if i == 0 else m for i, m in enumerate(models)]
        for key in ALL:
            np.testing.assert_allclose(correct(key, doubled, obs, target), correct(key, models, obs, target),
                                       rtol=1e-6, atol=1e-6, err_msg=key)
        x, w = pooled(models)
        self.assertAlmostEqual(w.sum(), 1.)
        self.assertAlmostEqual(w[:25].sum(), 1 / len(models))
        self.assertAlmostEqual(w[-51:].sum(), 1 / len(models))

    def test_shapes_nonnegative_and_missing_cells(self):
        models, obs, rng = synthetic()
        obs[3, 2] = np.nan
        target = rng.gamma(3., 60., (51, obs.shape[1]))
        for key, m in METHODS.items():
            out = correct(key, models, obs, target)
            self.assertEqual(out.shape, (len(obs) if key == 'dc' else 51, obs.shape[1]), key)
            self.assertTrue(np.isnan(out[:, 2]).all(), key)
            self.assertTrue((out[:, [0, 1, 3, 4, 5]] >= 0).all(), key)

    def test_moment_methods_match_training_moments(self):
        models, obs, _ = synthetic()
        x, w = pooled(models)
        for key, tol in (('ls', 1e-6), ('pt', 1e-6), ('vs', 1e-2)):        # VS clips negative values at 0
            y = correct(key, models, obs, x)
            np.testing.assert_allclose(w @ y, obs.mean(0), rtol=tol, err_msg=key)
        for key, tol in (('pt', 1e-3), ('vs', 2e-2)):
            y = correct(key, models, obs, x)
            cv = np.sqrt(w @ (y * y) - (w @ y) ** 2) / (w @ y)
            np.testing.assert_allclose(cv, obs.std(0) / obs.mean(0), rtol=tol, err_msg=key)

    def test_quantile_mapping_removes_a_multiplicative_bias(self):
        """Model = 2 x observations: quantile mappings bring the forecast back near x/2."""
        models, obs, rng = synthetic(years=30, cells=4, seed=3)
        target = rng.gamma(3., 60., (51, 4))
        for key in ('eqm', 'gqm', 'dqm', 'qdm', 'cdft', 'sdm'):
            y = correct(key, models, obs, target)
            ratio = np.median(y.mean(0) / (target.mean(0) / 2))
            self.assertAlmostEqual(ratio, 1., delta=.2, msg=key)

    def test_forecast_signal_methods_keep_a_wet_forecast_wet(self):
        """A forecast 50% wetter than the model climatology stays clearly wetter after correction."""
        models, obs, rng = synthetic(years=30, cells=4, seed=5)
        target = rng.gamma(3., 90., (51, 4))
        for key in ('dc', 'dqm', 'qdm', 'cdft', 'sdm'):
            y = correct(key, models, obs, target)
            self.assertGreater(np.median(y.mean(0) / obs.mean(0)), 1.25, key)

    def test_rank_histogram_is_flat_for_a_reliable_ensemble(self):
        """25 members give 26 rank positions; they must not alias onto the 10 histogram bins."""
        import bias_benchmark as bb
        rng = np.random.default_rng(0)
        n = 40000
        h = bb.pit_histogram(bb.pit(rng.normal(size=(25, n)), rng.normal(size=n)), np.full(n, 1 / n), 10)
        self.assertAlmostEqual(h.sum(), 1.)
        self.assertLess(np.abs(h * 10 - 1).max(), .06)

    def test_figure_module_imports(self):
        import bias_benchmark_figures                                    # noqa: F401  (catches syntax errors)

    def test_ecdf_ties_and_tails(self):
        e = Ecdf(np.array([[0.], [0.], [10.], [20.]]))
        self.assertAlmostEqual(e.cdf(np.array([0.]), 0)[0], .25)
        self.assertAlmostEqual(e.quantile(np.array([.99]), 0)[0], 20.)


if __name__ == '__main__':
    unittest.main()
