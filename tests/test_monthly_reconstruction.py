import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_monthly import compare_totals

class ReconstructionTests(unittest.TestCase):
    def test_reported_roundoff_passes(self):
        result=compare_totals([1000.00048828125,np.nan],[1000.,np.nan])
        self.assertTrue(result['passed'])
        self.assertAlmostEqual(result['maximum_absolute_difference_mm'],.00048828125)
    def test_material_difference_fails(self):
        self.assertFalse(compare_totals([1000.01],[1000.])['passed'])
    def test_missingness_still_fails(self):
        with self.assertRaises(ValueError):compare_totals([np.nan],[1.])
    def test_float32_grouped_sums(self):
        rng=np.random.default_rng(5)
        daily=rng.uniform(0,60,(122,100)).astype('float32')
        seasonal=daily.sum(axis=0)
        monthly=[v.sum(axis=0).astype('float64') for v in np.split(daily,[30,61,92])]
        # Simulates previous float32 accumulation within each stored target.
        result=compare_totals(sum(monthly),seasonal)
        self.assertTrue(result['passed'])

if __name__=='__main__':unittest.main()
