import sys
import unittest
from pathlib import Path
import numpy as np
import xarray as xr
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from plot_forecast_products import classify, derive

class MapTests(unittest.TestCase):
    def test_ties_and_weak_signal_are_not_below(self):
        p=np.array([[.5,.25,.25],[.35,.33,.32],[.5,.5,0],[np.nan]*3])
        raw,shown,peak,ties=classify(p,np.array([1,1,1,0],bool))
        np.testing.assert_array_equal(raw,[0,0,-1,-2])
        np.testing.assert_array_equal(shown,[0,-1,-1,-2])
        np.testing.assert_array_equal(ties,[0,0,1,0])
        self.assertTrue(np.isnan(peak[-1]))
    def test_bad_eligible_probabilities_rejected(self):
        for p in [[.7,.4,.1],[-.1,.5,.6],[np.nan,.5,.5]]:
            with self.assertRaises(ValueError):classify(np.array([p]),np.array([True]))
    def test_category_order_masks_and_percent_anomaly(self):
        d=xr.Dataset(coords={'lat':[4.,5.],'lon':[35.,36.],'category':['above','below','near']},
                     attrs={'initialization_month':5,'target_year':2026})
        d['blend_probability']=(('lat','lon','category'),np.broadcast_to([.2,.6,.2],(2,2,3)))
        for name in ['region_mask','probability_eligible','amount_eligible']:
            d[name]=(('lat','lon'),np.ones((2,2),dtype='int8'))
        d['region_mask'].values[1,1]=0
        for name,v in [('observed_training_mean',[[100.,5.],[0.,100.]]),('corrected_ensemble_mean',[[80.,10.],[3.,100.]]),('corrected_mean_anomaly',[[-20.,5.],[3.,0.]])]:
            d[name]=(('lat','lon'),v);d[name].attrs['units']='mm'
        g=derive(d)
        self.assertEqual(g.display_tercile.values[0,0],0)
        self.assertEqual(g.rainfall_anomaly_percent.values[0,0],-20.)
        self.assertTrue(np.isnan(g.rainfall_anomaly_percent.values[0,1]))
        self.assertTrue(np.isnan(g.rainfall_anomaly_percent.values[1,0]))
        self.assertTrue(np.isnan(g.rainfall_anomaly_mm.values[1,1]))
        self.assertEqual(g.display_tercile.values[1,1],-2)
        np.testing.assert_allclose(g.blend_probability.values[0,0],[.6,.2,.2])

if __name__=='__main__':unittest.main()
