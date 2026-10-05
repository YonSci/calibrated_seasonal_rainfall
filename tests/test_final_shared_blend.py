import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
import xarray as xr
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import final_shared_blend as m
from calibration_core import fit_amount

class FinalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng=np.random.default_rng(721)
        cls.models={y:rng.gamma(8,30,(25 if y<2017 else 51,4)) for y in m.TRAIN+[2026]}
        cls.obs={y:rng.gamma(6,30,4) for y in m.TRAIN}
        cls.land=np.ones(4,bool);cls.area=np.ones(4)
    def test_target_cannot_change_fit(self):
        pars,clim,lam=m.fit_final(self.models,self.obs,self.land,self.area,lambda _:None)
        changed=dict(self.models);changed[2026]=changed[2026]*10
        pars2,clim2,lam2=m.fit_final(changed,self.obs,self.land,self.area,lambda _:None)
        self.assertEqual(lam,lam2);np.testing.assert_equal(clim,clim2)
        for k in pars:np.testing.assert_equal(pars[k],pars2[k])
    def test_equal_year_amount_weighting(self):
        data=[self.models[y] for y in m.TRAIN];obs=np.stack([self.obs[y] for y in m.TRAIN])
        a=fit_amount(data,obs,self.land)
        changed=list(data);changed[0]=np.repeat(changed[0],3,axis=0)
        b=fit_amount(changed,obs,self.land)
        for k in a:np.testing.assert_allclose(a[k],b[k],atol=1e-10)
    def test_final_files_and_51_members(self):
        pars,clim,lam=m.fit_final(self.models,self.obs,self.land,self.area,lambda _:None)
        cfg=dict(initialization_month=5,season=dict(name='JJAS',start='06-01',end='09-30'))
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)
            report=m.write_result(out,cfg,self.models,{y:np.arange(len(a)) for y,a in self.models.items()},
                np.array([3.,4.]),np.array([33.,34.]),pars,clim,lam,np.array([1,1,1,0],bool),self.area,{}, {})
            self.assertEqual(report['target_members'],51)
            with xr.open_dataset(out/'forecast_2026.nc') as d:
                self.assertEqual(d.sizes['member'],51)
                np.testing.assert_allclose(d.blend_probability.sum('category'),1.)
                np.testing.assert_allclose(d.smoothed_probability,(51*d.base_probability+.5)/52.5)
                np.testing.assert_allclose(d.blend_probability,(1-lam)*d.smoothed_probability+lam*d.climatology_probability)
            self.assertEqual(len(list(out.glob('*.png'))),2)

if __name__=='__main__':unittest.main()
