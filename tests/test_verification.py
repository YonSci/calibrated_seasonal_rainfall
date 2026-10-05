"""Run from project root: python -m unittest discover -s tests -p test_verification.py -v"""
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
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from verification_core import crps,roc_curve,temporal_correlation,probability_losses


class VerificationTests(unittest.TestCase):
    def test_crps_matches_pairwise_formula(self):
        x=np.array([[0.,1.],[2.,3.],[4.,5.]])
        o=np.array([1.,3.])
        pair=np.abs(x[:,None,:]-x[None,:,:]).sum(axis=(0,1))
        np.testing.assert_allclose(crps(x,o),np.mean(abs(x-o),axis=0)-pair/(2*3*3))
        np.testing.assert_allclose(crps(x,o,True),np.mean(abs(x-o),axis=0)-pair/(2*3*2))
        np.testing.assert_array_equal(crps(np.tile(o,(25,1)),o),0)

    def test_roc_ties_and_weighting(self):
        self.assertAlmostEqual(roc_curve(np.array([.1,.9]),np.array([0,1]),np.ones(2))[2],1)
        self.assertAlmostEqual(roc_curve(np.ones(4),np.array([0,1,0,1]),np.array([1,2,3,4]))[2],.5)
        self.assertIsNone(roc_curve(np.ones(4),np.ones(4),np.ones(4)))

    def test_correlation_and_missing_labels(self):
        a=np.arange(9.)[:,None];np.testing.assert_allclose(temporal_correlation(a,2*a+3),1)
        bs,rps,ll=probability_losses(np.array([[0,0,1.],[.2,.4,.4]]),np.array([2,-1]))
        self.assertEqual(rps[0],0);self.assertTrue(np.isnan(rps[1]));self.assertTrue(np.isnan(bs[1]).all())

    def test_cli_and_regional_verification(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);(folder/'scripts').mkdir();(folder/'config').mkdir()
            for name in ('common.py','calibration_core.py','run_calibration.py','verification_core.py','verify_calibration.py'):
                shutil.copy(root/'scripts'/name,folder/'scripts'/name)
            cfg=dict(initialization_month=5,season=dict(name='JJAS',start='06-01',end='09-30'),archive_years=[1993,2026],observation_years=[1993,2025])
            (folder/'config/project.json').write_text(json.dumps(cfg))
            data=folder/'data/processed/init05_JJAS';data.mkdir(parents=True)
            lat=np.array([5.,6.]);lon=np.array([35.,36.,37.]);rng=np.random.default_rng(7)
            for year in range(1993,2026):
                n=25 if year<2017 else 51;signal=100+40*np.sin((year-1993)*1.7)
                a=np.maximum(0,rng.normal(signal+40,35,(n,2,3)))
                attrs=dict(config_json=json.dumps(cfg),season_start=f'{year}-06-01')
                d=xr.Dataset({'precip_season':(('member','lat','lon'),a)},coords={'member':np.arange(n),'lat':lat,'lon':lon},attrs=attrs)
                d.precip_season.attrs['units']='mm';d.to_netcdf(data/f'ecmwf_{year}_common.nc')
                o=np.maximum(0,rng.normal(signal,15,(1,2,3)));o[0,0,0]=np.nan
                d=xr.Dataset({'precip_season':(('year','lat','lon'),o)},coords={'year':[year],'lat':lat,'lon':lon},attrs=attrs)
                d.precip_season.attrs['units']='mm';d.to_netcdf(data/f'chirps_{year}_common.nc')
            def run(name,*args):
                r=subprocess.run([sys.executable,str(folder/'scripts'/name),*args],capture_output=True,text=True)
                self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            run('run_calibration.py','--mode','development')
            region=np.ones((2,3),np.int8);region[1,2]=0
            xr.Dataset({'region_mask':(('lat','lon'),region)},coords={'lat':lat,'lon':lon}).to_netcdf(folder/'region.nc')
            run('verify_calibration.py','--bootstrap','100','--subsamples','2','--region-mask',str(folder/'region.nc'),'--region-name','test_region')
            dest=folder/'outputs/verification/init05_JJAS/test_region'
            s=json.loads((dest/'verification_summary.json').read_text())
            self.assertEqual(s['evaluation_years'],list(range(2017,2026)))
            self.assertTrue(s['region']['applied'])
            self.assertTrue(np.isfinite(s['summary']['corrected_crps_skill']))
            with xr.open_dataset(dest/'spatial_verification.nc') as d:
                self.assertTrue(np.isnan(d.corrected_crps_mm.sel(lat=6,lon=37)))
            self.assertEqual(len(list((dest/'figures').glob('*.png'))),5)
            if os.environ.get('VERIFICATION_PREVIEW_DIR'):
                shutil.copytree(dest/'figures',os.environ['VERIFICATION_PREVIEW_DIR'],dirs_exist_ok=True)
            m=json.loads((dest/'member_count_sensitivity.json').read_text())
            self.assertEqual(m['subset_size'],25)
            self.assertAlmostEqual(m['comparison']['base_rps']['full_51'],s['summary']['base_rps'])


if __name__=='__main__':unittest.main()
