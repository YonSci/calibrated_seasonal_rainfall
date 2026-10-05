"""Isolated synthetic CLI smoke test. Never reads/writes project data or outputs.

Run from project root: python tests\smoke_github_regime_pipeline.py
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import numpy as np
import xarray as xr


def main():
    project=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='seasonal_regime_test_') as td:
        root=Path(td);(root/'scripts').mkdir();(root/'config').mkdir();(root/'data/masks').mkdir(parents=True)
        names=['common.py','output_runs.py','calibration_core.py','compare_calibration.py','run_calibration.py','verification_core.py','regime_core.py','prepare_regimes.py','run_regime_calibration.py','github_regime_core.py','evaluate_github_regimes.py']
        for name in names:shutil.copy2(project/'scripts'/name,root/'scripts'/name)
        lat=np.arange(5.,9.);lon=np.arange(35.,41.);coords=dict(lat=lat,lon=lon)
        dates=np.arange(np.datetime64('1993-01-01'),np.datetime64('2026-01-01'))
        rng=np.random.default_rng(431);rain=[]
        for day in dates:
            year=int(str(day)[:4]);d=int((day-np.datetime64(f'{year}-01-01')).astype(int))
            v=4+2.5*np.cos(2*np.pi*(d-210)/365)
            row=np.full((4,6),v);row[:,:3]=4+2.5*np.cos(4*np.pi*(d-100)/365)
            row*=1+.18*np.sin(year*.7);rain.append(row+rng.uniform(0,.1,(4,6)))
        rain=np.array(rain,dtype='float32');raw=root/'chirps.nc'
        ds=xr.Dataset(dict(precip=(('time','lat','lon'),rain)),coords=dict(time=dates,**coords));ds.precip.attrs['units']='mm/day';ds.to_netcdf(raw)
        xr.Dataset(dict(region_mask=(('lat','lon'),np.ones((4,6),dtype='int8'))),coords=coords).to_netcdf(root/'data/masks/ethiopia_common.nc')
        cfg=dict(chirps_file=str(raw),chirps_variable='precip',initialization_month=5,season=dict(name='JJAS',start='06-01',end='09-30'))
        (root/'config/project.json').write_text(json.dumps(cfg))
        folder=root/'data/processed/init05_JJAS';folder.mkdir(parents=True)
        for year in range(1993,2026):
            select=(dates>=np.datetime64(f'{year}-06-01'))&(dates<=np.datetime64(f'{year}-09-30'))
            obs=rain[select].sum(axis=0);members=25 if year<2017 else 51
            ensemble=np.maximum(0,obs[None,:,:]*1.2+rng.normal(0,100,(members,4,6)))
            attrs=dict(config_json=json.dumps(cfg),season_start=f'{year}-06-01')
            for kind,a,dims,c in [('ecmwf',ensemble,('member','lat','lon'),dict(member=np.arange(members),**coords)),('chirps',obs[None],('year','lat','lon'),dict(year=[year],**coords))]:
                ds=xr.Dataset(dict(precip_season=(dims,a)),coords=c,attrs=attrs);ds.precip_season.attrs['units']='mm';ds.to_netcdf(folder/f'{kind}_{year}_common.nc')
        commands=[['prepare_regimes.py'],['run_regime_calibration.py','--mode','training'],['run_regime_calibration.py','--mode','operational'],['evaluate_github_regimes.py','--mode','training'],['evaluate_github_regimes.py','--mode','operational'],['prepare_regimes.py','--regenerate']]
        for args in commands:
            subprocess.run([sys.executable,str(root/'scripts'/args[0]),*args[1:]],cwd=root,check=True)
        for mode,n in [('training',24),('operational',9)]:
            out=root/'outputs/regime_calibration/init05_JJAS'/mode
            report=json.loads((out/'regime_comparison_summary.json').read_text())
            assert len(report['years'])==n
            with xr.open_dataset(out/'regime_probabilities_and_weights.nc') as d:
                a=d.regularized_regime_blend_probability.values
                np.testing.assert_allclose(a.sum(axis=-1),1,atol=1e-12)
                for row in report['years']:
                    assert row['year'] not in row['training_years']
            assert (out/'annual_regime_rps.png').is_file()
            newroot=root/'outputs/regime_calibration_github/init05_JJAS'/mode
            newreport=json.loads((newroot/'regime_comparison_summary.json').read_text())
            assert newreport['baseline_reproduction']['passed']
            with xr.open_dataset(newroot/'regime_probabilities_and_weights.nc') as d:
                assert 'github_regime_raw' in d
                assert not (d.github_onset_eligibility_r2.values==1).any()
        assert len(list((root/'data/processed').glob('regime_climatology_backup_*')))==1
        print('PASS: both regime definitions, nested training, operational evaluation, identical shared baselines, separate outputs/masks, and regeneration backup.')


if __name__=='__main__':main()
