"""Third-stage neural models and their tools (docs/54, 3g): the linear pool, neighbourhood inputs, the pooled neural correction
of EMOS (an EMOS per month), saved predictions and the configurations of the new runs."""
import json
import pickle
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))
import accept_results as ar             # noqa: E402
import dist_benchmark as db             # noqa: E402
import dist_calibration as dc           # noqa: E402
import neural_calibration as nc         # noqa: E402
import predictions as pr                # noqa: E402
from test_neural_calibration import samples   # noqa: E402

CYCLES = ('jan_fmam', 'feb_fmam', 'may_jjas', 'sep_ondj')


def read(p):
    return json.loads((ROOT / p).read_text(encoding='utf-8'))


def csg(k, theta, delta, n=5):
    return dc.CSGamma(np.full(n, k), np.full(n, theta), np.full(n, delta), np.full(n, 50.), np.ones(n, bool))


class LinearPool(unittest.TestCase):
    def test_the_pool_of_one_distribution_is_that_distribution(self):
        d = csg(2., .5, -.1)
        p = dc.Pool([d, d, d])
        x = np.linspace(0, 200, 5)
        np.testing.assert_allclose(p.cdf(x), d.cdf(x), atol=1e-12)
        np.testing.assert_allclose(p.quantile(np.full(5, .5)), d.quantile(np.full(5, .5)), rtol=1e-6)

    def test_the_cdf_is_the_mean_and_the_quantile_inverts_it(self):
        a, b, c = csg(2., .5, -.1), csg(4., .3, -.2), csg(1.5, 1., 0.)
        p = dc.Pool([a, b, c])
        x = np.array([0., 10., 40., 80., 150.])
        np.testing.assert_allclose(p.cdf(x), (a.cdf(x) + b.cdf(x) + c.cdf(x)) / 3, atol=1e-12)
        for u in (.1, .5, .9):
            q = p.quantile(np.full(5, u))
            np.testing.assert_allclose(p.cdf(q)[q > 0], u, atol=1e-6)

    def test_the_pool_is_no_worse_than_its_members_on_average(self):
        """CRPS is convex in F: the pool's CRPS never exceeds the mean of the members' (and its split rule is accurate)."""
        a, b, c = csg(2., .5, -.1), csg(4., .3, -.2), csg(1.5, 1., 0.)
        p = dc.Pool([a, b, c])
        for y in (0., 20., 60., 140.):
            yy = np.full(5, y)
            self.assertLessEqual(p.crps(yy)[0], np.mean([m.crps(yy)[0] for m in (a, b, c)]) + 1e-3)

    def test_a_cell_invalid_in_any_member_is_invalid(self):
        a, b = csg(2., .5, -.1), csg(4., .3, -.2)
        b.valid[2] = False
        self.assertFalse(dc.Pool([a, b]).valid[2])
        self.assertTrue(np.isnan(dc.Pool([a, b]).terciles(np.full(5, 20.), np.full(5, 60.))[2]).all())


class Neighbourhood(unittest.TestCase):
    def test_windows_on_the_grid(self):
        nlon = 4                                                 # a 3 x 4 grid; the national cells skip (0, 0)
        idx = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11])
        mats = db.neighbourhood_matrices(idx, nlon)
        counts = np.asarray(mats[1].sum(1)).ravel()
        self.assertEqual(counts[list(idx).index(5)], 8)          # (1, 1): its 3 x 3 window without (0, 0)
        self.assertEqual(counts[list(idx).index(3)], 4)          # corner (0, 3): no wrap-around to the next row
        self.assertEqual(counts[list(idx).index(4)], 5)          # (1, 0): five, without (0, 0)
        self.assertEqual(mats[1][list(idx).index(4), list(idx).index(3)], 0)   # no wrap-around to the previous row's end
        self.assertTrue((np.asarray(mats[2].sum(1)).ravel() >= counts).all())

    def test_means_over_valid_neighbours(self):
        idx = np.arange(9)                                       # 3 x 3, the centre cell is 4
        mats = db.neighbourhood_matrices(idx, 3)
        F = dict(m=np.arange(9.), s=np.ones(9), q50=np.arange(9.), valid=np.ones(9, bool))
        F['valid'][0] = False
        F['m'][0] = 1e6                                          # an invalid cell must not enter its neighbours' means
        out = db.add_neighbourhood(F, mats)
        self.assertEqual(set(out), set(db.NBHD))
        self.assertAlmostEqual(out['m_nb3'][4], np.mean(np.arange(1, 9.)))
        self.assertAlmostEqual(out['s_nb3'][4], 1.)
        self.assertEqual(tuple(db.NBHD), nc.NBHD)
        self.assertEqual(nc.INPUTS['pooled_nbhd'][-4:], nc.NBHD)


class PooledResidual(unittest.TestCase):
    def pooled(self, seed=6):
        a, b = samples(n_years=6, cells=60, seed=seed), samples(n_years=6, cells=60, seed=seed + 1)
        b['y'] = b['y'] * 2.                                     # a second month with another relation to the forecast
        S = {k: np.concatenate([a[k], b[k]]) for k in a if k != 'n_years'}
        S['year_index'] = np.tile(np.repeat(np.arange(6), 60), 2)
        S['n_years'] = 6
        for i in range(1, 5):
            S[f'target_{i}'] = np.concatenate([np.full(360, float(i == 1)), np.full(360, float(i == 2))])
        return S

    def test_month_groups(self):
        S = self.pooled()
        g = nc.groups_of(S)
        self.assertEqual(list(np.unique(g)), [0, 1])
        self.assertIsNone(nc.groups_of(samples()))

    def test_an_emos_per_month_and_predictions_after_a_json_round_trip(self):
        S = self.pooled()
        model = nc.fit(S, inputs='pooled', residual='emos', configs=[([4], 1e-4)])
        emos = model['members'][0]['emos']
        self.assertEqual(sorted(emos), [0, 1])
        self.assertNotEqual(emos[0], emos[1])                    # each month its own EMOS
        model = json.loads(json.dumps(model))                    # as stored: string keys
        F = dict({k: v[:120] for k, v in S.items() if k != 'n_years'}, scale=np.ones(120), valid=np.ones(120, bool))
        F2 = dict({k: v[360:480] for k, v in S.items() if k != 'n_years'}, scale=np.ones(120), valid=np.ones(120, bool))
        d1, d2 = nc.predict(F, model), nc.predict(F2, model)
        self.assertTrue(np.isfinite(d1.crps(F['y'])).all())
        self.assertGreater(np.median(d2.quantile(np.full(120, .5))), np.median(d1.quantile(np.full(120, .5))))

    def test_emos_base_by_group(self):
        th = {0: [0., 1., .1, 1., -.1], 1: [1., 0., .2, 0., 0.]}
        out = nc.emos_base(th, np.array([1., 2.]), np.array([.5, .5]), np.array([0, 1]))
        np.testing.assert_allclose(out[0], nc.emos_base(th[0], [1.], [.5])[0])
        np.testing.assert_allclose(out[1], nc.emos_base(th[1], [2.], [.5])[0])


class SavedPredictions(unittest.TestCase):
    def test_round_trip_and_the_accepted_run_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'may_jjas' / 'neural'
            out.mkdir(parents=True)
            saved = dict(predictions={'drn_csg': {'training': {1993: csg(2., .5, -.1)}, 'test': {}}},
                         context={'training': {1993: db.stats_record(dict(q1=np.full(5, 20.), q2=np.full(5, 60.), valid=np.ones(5, bool),
                                                                              prob_ok=np.ones(5, bool), O=np.ones((3, 5)), p_clim=np.full((5, 3), 1 / 3)),
                                                                         np.full(5, 30.))}, 'test': {}},
                         area_e=np.ones(5, np.float32), regions={'ethiopia': np.ones(5, bool)}, scoring_version=dc.SCORING_VERSION)
            f = db.save_predictions(out, 'JJAS', saved)
            back = pickle.loads(f.read_bytes())
            np.testing.assert_allclose(back['predictions']['drn_csg']['training'][1993].cdf(np.full(5, 30.)),
                                       saved['predictions']['drn_csg']['training'][1993].cdf(np.full(5, 30.)))
            self.assertEqual(back['context']['training'][1993]['y_obs'].dtype, np.float32)
            (out / 'benchmark.json').write_text('{}', encoding='utf-8')
            reg = dict(accepted={'neural/may_jjas': dict(sha256=pr.sha256(out / 'benchmark.json'))}, gated=['neural'])
            with mock.patch.object(pr, 'OUT', Path(tmp)), mock.patch.object(ar, 'load', return_value=reg):
                self.assertIn('file_sha256', pr.load('neural', 'may_jjas', 'JJAS'))
                (out / 'benchmark.json').write_text('{"newer": 1}', encoding='utf-8')     # a newer, unaccepted run
                with self.assertRaises(ValueError):
                    pr.load('neural', 'may_jjas', 'JJAS')
                self.assertIn('predictions', pr.load('neural', 'may_jjas', 'JJAS', accepted_only=False))


class NewRunConfigurations(unittest.TestCase):
    def test_models_exist_and_the_reruns_save_predictions(self):
        for cy in CYCLES:
            for fam in ('distribution', 'phase3'):
                c = read(f'config/probability_calibration/{cy}_{fam}.json')
                self.assertEqual(c.get('members'), 25, (cy, fam))
                self.assertTrue(c.get('save_predictions'), (cy, fam))
            self.assertTrue(read(f'config/probability_calibration/{cy}_neural.json').get('save_predictions'), cy)
            p2 = read(f'config/probability_calibration/{cy}_neural_pooled2.json')
            self.assertTrue(set(p2['models']) <= set(dc.MODELS))
            self.assertTrue(set(p2['decision_models']) <= set(p2['models']))
            self.assertTrue(p2['neighbourhood'] and p2['save_predictions'])
            self.assertEqual(p2['members'], 25)

    def test_stacking_members_come_from_runs_that_save_them(self):
        for cy in CYCLES:
            st = read(f'config/probability_calibration/{cy}_stacking.json')
            self.assertIn('stacking', ar.GATED)
            for part in ('months', 'season'):
                self.assertEqual(len(st['members'][part]), 3)
                for fam, m in st['members'][part]:
                    self.assertIn(fam, ar.GATED)
                    self.assertIn(m, dc.MODELS)
                    c = read(f'config/probability_calibration/{cy}_{fam}.json')
                    self.assertIn(m, c['models'], (cy, fam, m))
                    self.assertTrue(c.get('save_predictions'), (cy, fam))

    def test_all_cycles_network(self):
        a = read('config/probability_calibration/all_neural_pooled_all.json')
        self.assertEqual(len(a['cycles']), 4)
        self.assertEqual(a['models'], ['drn_pooled_all'])
        self.assertIn('{name}', a['cycle_output'])
        self.assertEqual(nc.INPUTS['pooled_all'][-4:], tuple(f'cycle_{i}' for i in range(1, 5)))
        for fam in ('neural_pooled2', 'neural_all', 'neural_fmam_ondj'):
            self.assertEqual(ar.TARGETS_OF[fam], 4)

    def test_fmam_ondj_network(self):
        import pooled_all_benchmark as pa
        a = read('config/probability_calibration/all_neural_fmam_ondj.json')
        self.assertEqual([Path(p).name.split('_neural')[0] for p in a['cycles']], ['jan_fmam', 'feb_fmam', 'sep_ondj'])   # no JJAS
        self.assertEqual(a['models'], ['drn_fmam_ondj'])
        self.assertIn('neural_fmam_ondj', ar.GATED)
        self.assertEqual(nc.INPUTS['fmam_ondj'], nc.INPUTS['pooled'] + ('cycle_1', 'cycle_2', 'cycle_3'))
        self.assertEqual(dc.MODELS['drn_fmam_ondj'].defaults['inputs'], 'fmam_ondj')
        self.assertEqual(pa.cycle_onehot(2, 3), dict(cycle_1=0., cycle_2=0., cycle_3=1.))
        self.assertEqual(pa.cycle_onehot(1), pa.cycle_onehot(1, 4))     # the four-cycle network keeps its inputs


if __name__ == '__main__':
    unittest.main()
