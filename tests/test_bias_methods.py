import sys
import unittest
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from bias_methods import METHODS, VARIANTS, ALL, correct, pooled, Ecdf          # noqa: E402
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
        self.assertEqual(set(ALL) - set(METHODS), {'raw'} | set(VARIANTS))

    def test_configured_variants_resolve_to_their_base(self):
        from bias_methods import resolve
        m, p = resolve('mvs_r3', {'base': 'mvs', 'ratio_bounds': [1 / 3, 3.0], 'label': 'MVS, ratio limits 1/3-3', 'family': 'scaling'})
        self.assertEqual((m.key, m.label, m.family, p['ratio_bounds'], p['min_model_sd']), ('mvs_r3', 'MVS, ratio limits 1/3-3', 'scaling', [1 / 3, 3.0], 1.0))
        models, obs, rng = synthetic()
        target = rng.gamma(3., 60., (51, obs.shape[1]))
        np.testing.assert_allclose(m.apply(target, m.fit(models, obs, **p), **p),
                                   correct('mvs', models, obs, target, dict(ratio_bounds=(1 / 3, 3.0))))
        self.assertEqual(resolve('mvs', {'ratio_bounds': [0.5, 2.0]})[0].key, 'mvs')

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

    def test_sdm_follows_the_published_steps(self):
        """Independent implementation of Switanek et al. (2017) Sect. 4.1.1, steps 1-7 (equal member counts)."""
        from scipy import stats
        rng = np.random.default_rng(11)
        thr, years, n = 1.0, 30, 25
        obs = np.where(rng.random((years, 2)) < .2, 0., rng.gamma(2., 40., (years, 2)))
        models = [np.where(rng.random((n, 2)) < .1, 0., rng.gamma(2.5, 60., (n, 2))) for _ in range(years)]
        target = np.where(rng.random((n, 2)) < .1, 0., rng.gamma(2.5, 75., (n, 2)))
        got = correct('sdm', models, obs, target, dict(wet_threshold=thr))
        hist = np.concatenate(models)
        for j in range(2):
            o, h, f = obs[:, j], hist[:, j], target[:, j]
            ow, hw, fw = np.sort(o[o > thr]), np.sort(h[h > thr]), np.sort(f[f > thr])
            rd_bc = min(int(round(len(fw) * (len(ow) / len(o)) / (len(hw) / len(h)))), len(fw))          # Eq. (1)
            go, gh, gf = (stats.gamma(*stats.gamma.fit(v, floc=0)) for v in (ow, hw, fw))                    # step 2
            cdf = lambda g, v: np.minimum(g.cdf(v), 1 - 1e-7)
            sfr = gf.ppf(cdf(gf, fw)) / gh.ppf(cdf(gf, fw))                                                  # Eq. (3)
            ri = lambda g, v: 1 / (1 - cdf(g, v))                                                          # Eq. (4)
            stretch = lambda a: np.interp(np.linspace(1, len(a), len(fw)), np.arange(1, len(a) + 1), a)
            ri_s = np.maximum(1, stretch(ri(go, ow)) * ri(gf, fw) / stretch(ri(gh, hw)))                    # Eq. (5)
            bc = go.ppf(np.sort(1 - 1 / ri_s)) * sfr                                                         # Eqs. (6)-(7)
            bc = np.interp(np.linspace(1, len(fw), rd_bc), np.arange(1, len(fw) + 1), bc)                   # step 6
            ref = np.zeros(n)
            ref[np.argsort(np.where(f > thr, f, -np.inf), kind='stable')[-rd_bc:]] = np.sort(bc)            # step 7: by rank
            np.testing.assert_allclose(got[:, j], ref, rtol=2e-3, atol=.05, err_msg=f'cell {j}')

    def test_dry_share_follows_observations(self):
        """Review case: 25% of CHIRPS totals and 50% of model totals are 0 mm; the corrected dry share is about 25%."""
        rng = np.random.default_rng(7)
        years, n, cells = 40, 51, 3
        obs = np.where(rng.random((years, cells)) < .25, 0., rng.gamma(2., 30., (years, cells)))
        models = [np.where(rng.random((n, cells)) < .5, 0., rng.gamma(2., 50., (n, cells))) for _ in range(years)]
        shares = {k: [] for k in ('eqm', 'gqm', 'dqm', 'qdm')}
        for _ in range(20):
            target = np.where(rng.random((n, cells)) < .5, 0., rng.gamma(2., 50., (n, cells)))
            for key in shares:
                shares[key].append((correct(key, models, obs, target) <= 1.0).mean())
        for key, v in shares.items():
            self.assertAlmostEqual(np.mean(v), .25, delta=.06, msg=key)

    def test_sdm_keeps_the_rank_order_of_the_members(self):
        """Step 7: the largest corrected value goes to the largest raw member, and so on."""
        for seed in range(20):
            rng = np.random.default_rng(seed)
            obs = rng.gamma(2., 40., (30, 1))
            models = [rng.gamma(1.2, 90., (25, 1)) for _ in range(30)]
            f = rng.gamma(3., 50., (25, 1))
            y = correct('sdm', models, obs, f)[:, 0]
            self.assertTrue((np.diff(y[np.argsort(f[:, 0], kind='stable')]) >= -1e-9).all(), seed)

    def test_dry_rule_survives_extrapolation(self):
        """Review case: every CHIRPS year 0.5 mm (dry), model 2-5 mm, a 100 mm forecast member: still 0 mm."""
        obs = np.full((24, 1), .5)
        models = [np.array([[2.], [3.], [4.], [5.]]) for _ in range(24)]
        fc = np.array([[2.], [3.], [4.], [5.], [100.]])
        for key in ('eqm', 'dqm', 'gqm'):
            np.testing.assert_array_equal(correct(key, models, obs, fc).ravel(), 0., err_msg=key)

    def test_zero_guard_variant(self):
        """Review case: CHIRPS always 0 mm, model members 0, 0, 20, 40 mm: MVS gives 0, 0, 2.5, 12.5; the guard gives 0."""
        obs = np.zeros((24, 1))
        models = [np.array([[0.], [0.], [20.], [40.]]) for _ in range(24)]
        fc = np.array([[0.], [0.], [20.], [40.]])
        np.testing.assert_allclose(correct('mvs', models, obs, fc).ravel(), [0, 0, 2.5, 12.5])
        np.testing.assert_array_equal(correct('mvs_zero_guard', models, obs, fc).ravel(), 0.)
        wet_models, wet_obs, rng = synthetic()
        target = rng.gamma(3., 60., (51, wet_obs.shape[1]))
        np.testing.assert_array_equal(correct('mvs_zero_guard', wet_models, wet_obs, target), correct('mvs', wet_models, wet_obs, target))

    def test_all_dry_and_few_wet_samples(self):
        rng = np.random.default_rng(3)
        models = [rng.gamma(2., 20., (25, 2)) for _ in range(24)]
        target = rng.gamma(2., 20., (25, 2))
        dry_obs = np.zeros((24, 2))
        for key in ('eqm', 'gqm', 'dqm', 'qdm', 'sdm', 'ls'):        # MVS keeps r >= 0.5, so it does not (as operational)
            out = correct(key, models, dry_obs, target)
            self.assertTrue(np.allclose(out, 0), key)                     # never-wet CHIRPS: corrected totals 0 mm
        dry_models = [np.zeros((25, 2)) for _ in range(24)]
        obs = rng.gamma(2., 20., (24, 2))
        for key in METHODS:
            out = correct(key, dry_models, obs, np.zeros((25, 2)))
            self.assertTrue(np.isfinite(out).all() and (out >= 0).all(), key)
        few = np.zeros((24, 2))
        few[:2] = 50.                                                    # two wet years only: parametric methods fall back
        for key in ('gqm', 'sdm'):
            out = correct(key, models, few, target)
            self.assertTrue(np.isfinite(out).all(), key)

    def test_diagnostics_are_reported(self):
        models, obs, rng = synthetic()
        target = rng.gamma(3., 60., (51, obs.shape[1]))
        m = METHODS['mvs']
        s = m.fit(models, obs, **m.defaults)
        self.assertEqual(set(s['flags']), {'sd_fallback', 'ratio_lower_limit', 'ratio_upper_limit'})
        m.apply(target, s, **m.defaults)
        self.assertEqual(s['counts']['clipped_at_zero'][1], 51 * obs.shape[1])
        self.assertEqual(METHODS['vs'].defaults['min_model_sd'], METHODS['mvs'].defaults['min_model_sd'])

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
