"""Run: python -m unittest discover -s tests -p test_calibration.py -v"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import numpy as np
import xarray as xr
from scipy.optimize import check_grad
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from calibration_core import (fit_amount,correct_amount,probabilities,labels,objective,
                              fit_dirichlet,apply_dirichlet,log_inputs)


class CalibrationTests(unittest.TestCase):
    def test_equal_year_weights_with_unequal_members(self):
        ms=[np.full((25 if y<10 else 51,2),float(y)) for y in range(20)]
        obs=np.tile(np.arange(20.)[:,None],(1,2))
        p=fit_amount(ms,obs,np.ones(2,bool))
        np.testing.assert_allclose(p['mu_model'],9.5)
        np.testing.assert_allclose(p['sd_model'],np.std(np.arange(20.)))

    def test_affine_correction_and_missing_mask(self):
        obs=np.tile((100+np.arange(24.)*10)[:,None],(1,3));obs[:,2]=np.nan
        ms=[np.full((25,3),2*(100+y*10)+20) for y in range(24)]
        p=fit_amount(ms,obs,np.array([1,0,1],bool))
        self.assertEqual(p['amount_eligible'].tolist(),[True,False,False])
        self.assertAlmostEqual(p['scale'][0],0.5)
        np.testing.assert_allclose(correct_amount(ms[3],p)[:,0],130)
        self.assertTrue(np.isnan(correct_amount(ms[3],p)[:,1:]).all())

    def test_ties_and_probability_sum(self):
        obs=np.tile(np.arange(24.)[:,None],(1,2));obs[:,1]=0
        ms=[np.full((25,2),y+2.) for y in range(24)]
        p=fit_amount(ms,obs,np.ones(2,bool))
        self.assertFalse(p['probability_eligible'][1])
        m=np.array([[p['q1'][0]-1,0],[p['q1'][0],0],[p['q2'][0],0],[p['q2'][0]+1,0]])
        q=probabilities(m,p)
        np.testing.assert_allclose(q[0],[.25,.5,.25]);self.assertTrue(np.isnan(q[1]).all())
        self.assertEqual(labels(np.array([np.nan,0]),p).tolist(),[-1,-1])

    def test_dirichlet_gradient_and_simplex(self):
        rng=np.random.default_rng(8);p=rng.dirichlet(np.ones(3),80);y=np.arange(80)%3
        x=log_inputs(p);w=np.full(80,1/80);theta=np.r_[np.eye(3).ravel(),np.zeros(3)]+rng.normal(0,.1,12)
        err=check_grad(lambda t:objective(t,x,y,w)[0],lambda t:objective(t,x,y,w)[1],theta)
        self.assertLess(err,1e-5)
        model=fit_dirichlet([p,p],[y,y],np.ones(80))
        q=apply_dirichlet(np.vstack([p,[0,0,1],[np.nan]*3]),model)
        np.testing.assert_allclose(q[:-1].sum(axis=1),1);self.assertTrue((q[:-1]>=0).all());self.assertTrue(np.isnan(q[-1]).all())

    def test_cli_development_final_and_holdout_isolation(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);(folder/'scripts').mkdir();(folder/'config').mkdir()
            for name in ('calibration_core.py','run_calibration.py','common.py'):
                shutil.copy(root/'scripts'/name,folder/'scripts'/name)
            cfg=dict(initialization_month=5,season=dict(name='JJAS',start='06-01',end='09-30'),archive_years=[1993,2026],observation_years=[1993,2025])
            (folder/'config/project.json').write_text(json.dumps(cfg))
            data=folder/'data/processed/init05_JJAS';data.mkdir(parents=True)
            lat=np.array([5.,6.]);lon=np.array([35.,36.,37.]);rng=np.random.default_rng(7)
            attrs={'config_json':json.dumps(cfg)}
            for year in range(1993,2027):
                n=25 if year<2017 else 51
                signal=100+50*np.sin((year-1993)*1.7)
                m=np.maximum(0,rng.normal(signal+40,35,(n,2,3)))
                d=xr.Dataset({'precip_season':(('member','lat','lon'),m)},coords={'member':np.arange(n),'lat':lat,'lon':lon},attrs=dict(attrs,season_start=f'{year}-06-01'))
                d.precip_season.attrs['units']='mm';d.to_netcdf(data/f'ecmwf_{year}_common.nc')
                if year<=2025:
                    o=np.maximum(0,rng.normal(signal,15,(1,2,3)));o[0,0,0]=np.nan
                    d=xr.Dataset({'precip_season':(('year','lat','lon'),o)},coords={'year':[year],'lat':lat,'lon':lon},attrs=attrs)
                    d.precip_season.attrs['units']='mm';d.to_netcdf(data/f'chirps_{year}_common.nc')
            mask=np.ones((2,3),np.int8);mask[1,2]=0
            xr.Dataset({'land_mask':(('lat','lon'),mask)},coords={'lat':lat,'lon':lon}).to_netcdf(folder/'mask.nc')
            def run(mode):
                c=subprocess.run([sys.executable,str(folder/'scripts/run_calibration.py'),'--mode',mode,'--land-mask',str(folder/'mask.nc')],capture_output=True,text=True)
                self.assertEqual(c.returncode,0,c.stdout+c.stderr)
            run('development')
            fitted=folder/'models/init05_JJAS/development/dirichlet_parameters.json'
            first=json.loads(fitted.read_text())
            with xr.open_dataset(folder/'outputs/calibration/init05_JJAS/development/probabilities.nc') as d:
                self.assertEqual(d.sizes['year'],9)
                self.assertTrue(np.isnan(d.dirichlet_probability.sel(lat=6,lon=37)).all())
                self.assertTrue(np.isnan(d.dirichlet_probability.sel(lat=5,lon=35)).all())
            # Alter ONLY heldout observations; fitted Dirichlet parameters must not change.
            path=data/'chirps_2020_common.nc'
            d=xr.load_dataset(path);d['precip_season']=d.precip_season*2;d.precip_season.attrs['units']='mm';d.to_netcdf(path)
            run('development');self.assertEqual(first,json.loads(fitted.read_text()))
            run('final')
            with xr.open_dataset(folder/'outputs/calibration/init05_JJAS/final/corrected_2026.nc') as d:
                self.assertEqual(d.sizes['member'],51)
                self.assertTrue(np.isnan(d.precip_corrected.sel(lat=6,lon=37)).all())


if __name__=='__main__':unittest.main()
