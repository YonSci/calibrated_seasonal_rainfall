import sys
import unittest
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import bias_confirmation as bc                     # noqa: E402
from compare_calibration import make_record        # noqa: E402


def synthetic(years=range(1993, 2017), cells=40, seed=2):
    rng = np.random.default_rng(seed)
    obs = {y: rng.gamma(3., 30., cells) for y in years}
    models = {y: rng.gamma(3., 55., (25 if y < 2005 else 51, cells)) for y in years}
    return models, obs


class Confirmation(unittest.TestCase):
    def test_mvs_pipeline_equals_the_operational_records(self):
        """The confirmation pipeline with MVS reproduces compare_calibration.make_record (the operational path)."""
        models, obs = synthetic()
        train = sorted(obs)
        pipe = bc.Pipeline('mvs', {}, models, obs, train, .5)
        for y in (1993, 2004, 2016):
            got = pipe.fit_apply(frozenset((y,)), [y])[0]
            ref = make_record([z for z in train if z != y], y, models, obs, np.ones(40, bool))
            np.testing.assert_allclose(got['s'], ref['s'], rtol=1e-6, atol=1e-7)
            np.testing.assert_allclose(got['clim'], ref['clim'], rtol=1e-6, atol=1e-7)
            np.testing.assert_array_equal(got['y'], ref['y'])

    def test_pair_fits_are_reused(self):
        models, obs = synthetic()
        pipe = bc.Pipeline('ls', {}, models, obs, sorted(obs), .5)
        a = pipe.fit_apply(frozenset((1993, 1994)), [1993, 1994])
        self.assertIs(pipe.fit_apply(frozenset((1994, 1993)), [1994])[0], a[1])

    def test_configured_smoothing_is_used(self):
        """A nondefault alpha follows the explicit formula (count + alpha) / (members + 3 alpha)."""
        from calibration_core import fit_amount, categories
        models, obs = synthetic()
        train = sorted(obs)
        y, alpha = 2016, 2.0
        rec = bc.Pipeline('raw', {}, models, obs, train, alpha).fit_apply(frozenset((y,)), [y])[0]
        T = [z for z in train if z != y]
        pars = fit_amount([models[z] for z in T], np.stack([obs[z] for z in T]), np.ones(40, bool))
        c = categories(models[y], pars['q1'], pars['q2'])
        n = len(models[y])
        expected = np.stack([((c == k).sum(0) + alpha) / (n + 3 * alpha) for k in range(3)], -1)
        ok = pars['probability_eligible']
        np.testing.assert_allclose(rec['s'][ok], expected[ok], rtol=1e-6)
        default = bc.Pipeline('raw', {}, models, obs, train, .5).fit_apply(frozenset((y,)), [y])[0]
        self.assertGreater(np.nanmax(np.abs(rec['s'] - default['s'])), .01)

    def test_checkpoint_fingerprint_covers_the_calculation(self):
        """Inputs, masks, configurations and every calculation file (CRPS, smoothing, blend) enter the key."""
        import bias_benchmark as bb
        for f in ('scripts/bias_benchmark.py', 'scripts/compare_calibration.py', 'scripts/local_blend.py',
                  'scripts/bias_methods.py', 'scripts/bias_confirmation.py', 'scripts/calibration_core.py'):
            self.assertIn(f, bb.CODE_FILES)
        dep = dict(code_sha256={'a': '1'}, config={}, project_config={}, cycle_config={}, masks={}, scoring_version=3,
                   inputs={'Oct': {'sha256': 'x'}, 'Nov': {'sha256': 'y'}})
        k = bb.dependency_key(dep, 'Oct')
        self.assertEqual(k, bb.dependency_key(dict(dep, inputs={'Oct': {'sha256': 'x'}, 'Nov': {'sha256': 'changed'}}), 'Oct'))
        self.assertNotEqual(k, bb.dependency_key(dict(dep, inputs={'Oct': {'sha256': 'changed'}, 'Nov': {'sha256': 'y'}}), 'Oct'))
        self.assertNotEqual(k, bb.dependency_key(dict(dep, code_sha256={'a': '2'}), 'Oct'))

    def test_scores_of_a_perfect_forecast(self):
        cells = 30
        y = np.array([0, 1, 2] * 10)
        r = dict(y=y, clim=np.full((cells, 3), 1 / 3, 'float32'))
        p = np.eye(3)[y]
        s, rel = bc.prob_scores(p, r, np.ones(cells), np.ones(cells, bool), 10)
        self.assertEqual(s['rps'], 0.)
        self.assertEqual(s['brier_below'], 0.)
        self.assertGreater(s['rps_clim'], 0.)
        self.assertAlmostEqual(rel['below'][0].sum(), 1.)


if __name__ == '__main__':
    unittest.main()
