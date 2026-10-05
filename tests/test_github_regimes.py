"""Run: python -m unittest discover -s tests -p test_github_regimes.py -v"""
import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from github_regime_core import classify,onset_layers,remove_small,MONTH_EDGES


def cycle(rates):
    return np.concatenate([np.full(b-a,r) for a,b,r in zip(MONTH_EDGES[:-1],MONTH_EDGES[1:],rates)])


class GithubTests(unittest.TestCase):
    def test_geographic_refinement(self):
        # Same rainfall cycle west/east of geographic threshold gives R1/R2.
        q=cycle([.5,1,4,5,2,4,8,8,4,.5,.5,.5])
        f=classify(np.tile(q[:,None],(1,8)),[8,9],[36,37,39,40],np.ones(8,bool))
        np.testing.assert_array_equal(f['regime_raw'].reshape(2,4),[[1,1,2,2],[1,1,2,2]])
        self.assertTrue((f['monthly_peak2']==4).all())

    def test_autumn_lowland_and_arid_priority(self):
        q=cycle([.2,.3,5,6,3,.1,.1,.1,.2,5,6,2])
        f=classify(np.tile(q[:,None],(1,4)),[6,7],[42,43],np.ones(4,bool))
        np.testing.assert_array_equal(f['regime_cleaned'],3)
        f=classify(np.tile((q*.05)[:,None],(1,4)),[6,7],[42,43],np.ones(4,bool))
        np.testing.assert_array_equal(f['regime_cleaned'],0)

    def test_missing_and_cleanup_ledger(self):
        q=np.ones((365,9))*2;q[:,4]=.1;q[0,0]=np.nan
        f=classify(q,[5,6,7],[35,36,37],np.ones(9,bool))
        self.assertEqual(f['regime_raw'][0],-1);self.assertEqual(f['regime_cleaned'][0],-1)
        self.assertEqual(f['regime_raw'][4],0);self.assertEqual(f['regime_cleaned'][4],1)
        self.assertTrue(f['cleanup_changed'][4]);self.assertEqual(f['cleanup_changed'].sum(),1)

    def test_four_connected_cleanup(self):
        a=np.eye(3,dtype=bool)
        self.assertFalse(remove_small(a,2).any())
        a[0,1]=True;self.assertEqual(remove_small(a,2).sum(),3)

    def test_onset_unknown_separate_from_rainfall(self):
        fields={'onset_candidate_r2':np.array([True,True,False,True]),'observation_valid':np.array([True,True,True,False])}
        region=np.ones(4,bool)
        status=onset_layers(fields,region)['onset_eligibility_r2']
        np.testing.assert_array_equal(status,[-1,-1,0,-1])
        fields['onset_candidate_r2'][3]=False
        status=onset_layers(fields,region,[.6,.59,np.nan,np.nan])['onset_eligibility_r2']
        np.testing.assert_array_equal(status,[1,0,0,-1])
        with self.assertRaises(ValueError):onset_layers(fields,region,[60,59,0,0])

    def test_volume_contributions_close(self):
        from compare_regime_definitions import contributions
        m=np.ones((12,4))*10;a=np.array([1.,2.,3.,4.]);g=np.array([0,1,2,3]);r=np.ones(4,bool)
        out=contributions(g,r,m,a)
        self.assertAlmostEqual(sum(x['JJAS_volume_percent'] for x in out['rows']),100)
        self.assertAlmostEqual(out['total_observed_JJAS_km3'],.0004)
        self.assertAlmostEqual(out['rows'][2]['mean_JJAS_mm'],40)


if __name__=='__main__':unittest.main()
