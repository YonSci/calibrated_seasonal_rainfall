"""Deterministic unit checks and an offline end-to-end synthetic June fixture.

No synthetic results are used as real 2026 verification evidence.
"""
from pathlib import Path
import json,sys,subprocess,tempfile,hashlib
import numpy as np
import pandas as pd
import xarray as xr
SCRIPTS=Path(__file__).resolve().parents[1]/'scripts';sys.path.insert(0,str(SCRIPTS))
from verify2026_common import daily_block,overlap_check,PERIODS,check_forecast,BASE
from verify2026_math import crps
from verify_frozen_2026 import calculate

def fixture(target):
    base=np.array([[0,10],[20,30.]])
    h=np.arange(30,96,2)[:,None,None]+base
    corrected=np.repeat((50+base)[None],51,axis=0)
    q1,q2=np.quantile(h,[1/3,2/3],axis=0)
    p=np.zeros((2,2,3));p[...,0]=1
    smooth=(51*p+.5)/52.5;clim=np.full_like(p,1/3)
    f=xr.Dataset(coords={'lat':[7.125,7.375],'lon':[37.125,37.375],'member':np.arange(51),'category':['below','near','above']},attrs={'initialization_month':5,'target_year':2026,'target_period':json.dumps({'name':target,'start':PERIODS[target][0],'end':PERIODS[target][1]}),'training_years':'1993-2025','method':'shared climatology blend','climatology_weight':.5})
    f['precip_corrected']=(('member','lat','lon'),corrected)
    for k,v in [('corrected_ensemble_mean',corrected.mean(0)),('observed_training_mean',h.mean(0)),('corrected_mean_anomaly',corrected.mean(0)-h.mean(0)),('q1',q1),('q2',q2)]:f[k]=(('lat','lon'),v)
    for k in ['precip_corrected','corrected_ensemble_mean','observed_training_mean','corrected_mean_anomaly','q1','q2']:f[k].attrs['units']='mm'
    for k,v in [('base_probability',p),('smoothed_probability',smooth),('climatology_probability',clim),('blend_probability',.5*smooth+.5*clim)]:f[k]=(('lat','lon','category'),v)
    for k in ['region_mask','amount_eligible','probability_eligible']:f[k]=(('lat','lon'),np.array([[1,1],[1,0]],'int8'))
    return f,h,corrected-5,50+base

def daily(year,amount):
    d=xr.Dataset({'precip':(('time','lat','lon'),np.repeat((amount/30)[None],30,axis=0))},coords={'time':pd.date_range(f'{year}-06-01',periods=30),'lat':[7.125,7.375],'lon':[37.125,37.375]},attrs={'title':'CHIRPS Version 2.0','version':'Version 2.0'})
    d.precip.attrs['units']='mm/day';return d

def main():
    f,h,raw,obs=fixture('Jun');check_forecast(f,'Jun')
    r,fields=calculate(f,raw,h,obs)
    assert r['amount']['corrected']['crps_mm']==0
    assert r['amount']['raw']['crps_mm']==5
    assert r['amount']['raw']['bias_mm']==-5
    assert r['probability']['raw_observed_thresholds']['rps']==0
    missing=obs.copy();missing[0,0]=np.nan
    r2,_=calculate(f,raw,h,missing);assert r2['amount_cells']==2
    extreme=obs.copy();extreme[0,0]=1000
    r3,_=calculate(f,raw,h,extreme);assert r3['probability']['raw_observed_thresholds']['zero_probability_observed_event_cells']==1
    ensemble=np.array([1.,2.,4.]);expected=np.abs(ensemble-2.5).mean()-.5*np.abs(ensemble[:,None]-ensemble).mean()
    assert np.isclose(crps(ensemble,2.5),expected)
    d=daily(2026,obs);assert daily_block(d,2026,6,f.lat,f.lon).shape==(30,2,2)
    for invalid in [d.isel(time=slice(0,-1)),d.assign_coords(lon=d.lon+.01)]:
        try:daily_block(invalid,2026,6,f.lat,f.lon)
        except ValueError:pass
        else:raise AssertionError('Incomplete/shifted input accepted')
    try:overlap_check(np.zeros(3),np.ones(3))
    except ValueError:pass
    else:raise AssertionError('Overlap mismatch accepted')
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp);inputs=p/'forecasts';cache=p/'cache';cache.mkdir();processed=p/'processed/init05_Jun';processed.mkdir(parents=True)
        for t in PERIODS:
            folder=inputs/f'init05_{t}/2026';folder.mkdir(parents=True);fixture(t)[0].to_netcdf(folder/'forecast_2026.nc')
        old=daily(2025,h[-1]);old.to_netcdf(p/'historical.nc');old.to_netcdf(cache/'chirps-v2.0.2025.06.days_p25.nc');d.to_netcdf(cache/'chirps-v2.0.2026.06.days_p25.nc')
        for cached in cache.glob('*.nc'):
            cached.with_suffix('.download.json').write_text(json.dumps({'url':BASE+cached.name,'sha256':hashlib.sha256(cached.read_bytes()).hexdigest()}))
        (p/'config.json').write_text(json.dumps({'chirps_file':str(p/'historical.nc'),'chirps_variable':'precip'}))
        for i,y in enumerate(range(1993,2026)):
            v=xr.Dataset({'precip_season':(('year','lat','lon'),h[i:i+1])},coords={'year':[y],'lat':f.lat,'lon':f.lon},attrs={'config_json':json.dumps({'season':{'name':'Jun','start':'06-01','end':'06-30'}})})
            v.precip_season.attrs['units']='mm';v.to_netcdf(processed/f'chirps_{y}_common.nc')
        rawd=xr.Dataset({'precip_season':(('member','lat','lon'),raw)},coords={'member':f.member,'lat':f.lat,'lon':f.lon},attrs={'season_start':'2026-06-01','season_end':'2026-06-30'})
        rawd.precip_season.attrs['units']='mm';rawd.to_netcdf(processed/'ecmwf_2026_common.nc')
        subprocess.run([sys.executable,str(SCRIPTS/'prepare_verification_2026.py'),'--config',str(p/'config.json'),'--months','Jun','--input-root',str(inputs),'--root',str(p/'assessment'),'--cache',str(cache)],check=True)
        subprocess.run([sys.executable,str(SCRIPTS/'verify_frozen_2026.py'),'--targets','Jun','--root',str(p/'assessment'),'--processed-root',str(p/'processed')],check=True)
        report=json.loads((p/'assessment/results/Jun/verification_report.json').read_text());assert report['amount']['corrected']['crps_mm']<1e-10
    print('PASS: scores, CRPS formula, zero-event probabilities, missing support, incomplete calendar, grid and overlap rejection; offline preparation-to-report integration')
if __name__=='__main__':main()
