import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from significance import sign_flip_p, holm, gate, paired_summary


class SignificanceTests(unittest.TestCase):
    def test_sign_flip_exact(self):
        # All 5 differences negative: only the all-negative pattern is as extreme -> 1/32
        self.assertAlmostEqual(sign_flip_p([-1, -2, -3, -4, -5]), 1 / 32)
        self.assertEqual(sign_flip_p([1, 2, 3]), 1.0)
        self.assertAlmostEqual(sign_flip_p([0, 0, 0, 0]), 1.0)

    def test_holm_monotone_and_capped(self):
        adj = holm({'a': .01, 'b': .04, 'c': .03})
        self.assertAlmostEqual(adj['a'], .03)
        self.assertAlmostEqual(adj['c'], .06)
        self.assertAlmostEqual(adj['b'], .06)  # monotone: never below a smaller p's adjustment
        self.assertEqual(holm({'x': .9, 'y': .8})['x'], 1.0)

    def test_gate_requires_clean_and_no_harm(self):
        good = dict(mean_difference=-.01)
        self.assertTrue(gate(good, dict(mean_difference=-.001), .01)['adopt'])
        self.assertFalse(gate(good, dict(mean_difference=+.001), .01)['adopt'])   # harms 2017-2025
        self.assertFalse(gate(good, dict(mean_difference=-.01), .2)['adopt'])     # not significant
        self.assertFalse(gate(dict(mean_difference=+.01), dict(mean_difference=-.1), .01)['adopt'])

    def test_paired_summary(self):
        s = paired_summary([1., 1., 1.], [2., 2., 2.])
        self.assertEqual(s['mean_difference'], -1.)
        self.assertEqual(s['years_better'], 3)
        self.assertEqual(s['bootstrap_95'], [-1., -1.])


if __name__ == '__main__':
    unittest.main()
