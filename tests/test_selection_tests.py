import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import selection_tests as st          # noqa: E402


def test(p, train=-1.0, test=-0.5):
    return dict(training=dict(p_improvement=p, mean_difference=train), test=dict(mean_difference=test),
                decision=dict(holm_p=None, confirmed=False))


class Corrections(unittest.TestCase):
    def test_bh_matches_the_step_up_definition(self):
        adj = st.bh({'a': 0.01, 'b': 0.04, 'c': 0.03, 'd': 0.5})
        self.assertAlmostEqual(adj['a'], 0.04)
        self.assertAlmostEqual(adj['c'], 0.04 * 4 / 3)          # monotone: min(0.03*4/2, 0.04*4/3)
        self.assertAlmostEqual(adj['b'], 0.04 * 4 / 3)
        self.assertAlmostEqual(adj['d'], 0.5)

    def test_bh_confirms_at_least_what_holm_does(self):
        tests = {'m1': {'crps': {'Jun': test(0.010), 'Jul': test(0.020)}},
                 'm2': {'crps': {'Jun': test(0.030), 'Jul': test(0.040, test=0.1)}}}
        holm = st.decide(tests, ['m1', 'm2'], 'crps', 'holm')           # 0.04, 0.06, 0.06, 0.06
        bh = st.decide(tests, ['m1', 'm2'], 'crps', 'benjamini_hochberg')  # 0.04 for all four
        self.assertEqual([k for k, d in holm.items() if d['confirmed']], [('m1', 'Jun')])
        self.assertEqual(sorted(k for k, d in bh.items() if d['confirmed']), [('m1', 'Jul'), ('m1', 'Jun'), ('m2', 'Jun')])
        self.assertFalse(bh[('m2', 'Jul')]['confirmed'])        # worse over the test years

    def test_unknown_correction_is_refused(self):
        with self.assertRaises(ValueError):
            st.decide({'m': {'rps': {'Jun': test(0.01)}}}, ['m'], 'rps', 'bonferroni')


if __name__ == '__main__':
    unittest.main()
