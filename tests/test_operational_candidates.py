"""Synthetic tests; do not interpret these scores as real forecast skill."""
import sys
import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import xarray as xr
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import evaluate_candidates as m


class OperationalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng=np.random.default_rng(867)
        cls.models={y:rng.gamma(8,30,(25 if y<2017 else 51,4)) for y in m.TRAIN+m.TARGET}
        cls.obs={y:rng.gamma(6,30,4) for y in cls.models}
        cls.land=np.ones(4,bool);cls.area=np.ones(4);cls.region=np.array([1,1,1,0],bool)

    def test_target_observations_do_not_affect_fit_or_probabilities(self):
        pars, maps, clim=m.fit_training(self.models,self.obs,self.land,self.area,lambda _:None)
        changed=dict(self.obs)
        for y in m.TARGET:changed[y]=changed[y]+10000
        pars2,maps2,clim2=m.fit_training(self.models,changed,self.land,self.area,lambda _:None)
        self.assertEqual(maps,maps2)
        np.testing.assert_equal(clim,clim2)
        for k in pars:np.testing.assert_equal(pars[k],pars2[k])
        rows,rec=m.evaluate(self.models,self.obs,pars,maps,clim,self.area,self.region)
        rows2,rec2=m.evaluate(self.models,changed,pars2,maps2,clim2,self.area,self.region)
        for a,b in zip(rec,rec2):
            for name in m.NAMES:np.testing.assert_allclose(a['pred'][name],b['pred'][name])
        self.assertNotEqual(rows,rows2)
        # Smoothing uses the actual 51-member count.
        np.testing.assert_allclose(rec[0]['pred']['smooth'],(51*rec[0]['pred']['base']+.5)/52.5)

    def test_cli_outputs_and_mask(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);lat=np.array([3.,4.]);lon=np.array([33.,34.])
            mask=root/'region.nc'
            xr.Dataset({'region_mask':(('lat','lon'),self.region.reshape(2,2).astype('int8'))},coords=dict(lat=lat,lon=lon)).to_netcdf(mask)
            loaded=('init05_JJAS',self.models,self.obs,{y:np.arange(len(v)) for y,v in self.models.items()},lat,lon)
            with patch.object(m,'ROOT',root),patch.object(m,'load_config',return_value={}),patch.object(m,'load_inputs',return_value=loaded),patch.object(sys,'argv',['evaluate','--region-mask',str(mask)]):
                m.main()
            out=root/'outputs/model_comparison/init05_JJAS/operational_period'
            summary=json.loads((out/'operational_comparison_summary.json').read_text())
            self.assertEqual(summary['primary_candidate'],'blend')
            self.assertEqual(summary['members']['2017'],51)
            with xr.open_dataset(out/'operational_probabilities.nc') as d:
                self.assertEqual(d.blend_probability.shape,(9,2,2,3))
                np.testing.assert_allclose(d.blend_probability.sum('category'),1)
            with xr.open_dataset(out/'spatial_scores.nc') as d:
                self.assertTrue(np.isnan(d.blend_rps.values[1,1]))
                self.assertEqual(d.valid_year_count.values[1,1],0)
            bins=json.loads((out/'reliability_bins.json').read_text())
            for name in m.NAMES:
                for category in bins[name]:self.assertAlmostEqual(sum(b['weight'] for b in category),1.)
            self.assertEqual(len(list(out.glob('*.png'))),4)


if __name__=='__main__':unittest.main()
