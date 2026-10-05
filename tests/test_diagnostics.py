"""Controlled probabilities test metric direction, missing support and bin endpoints."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import numpy as np
import xarray as xr
from diagnose_august import calculate

def test_metrics():
    y=np.array([[[0,1],[2,-1]],[[2,0],[1,-1]]])
    good=np.eye(3)[np.maximum(y,0)]
    flat=np.full(good.shape,1/3)
    d=xr.Dataset(coords={'year':[2000,2001],'lat':[5,10],'lon':[35,36],'category':['below','near','above']})
    for name,p in [('shared_blend',flat),('regularized_regime_blend',good)]:d[name+'_probability']=(('year','lat','lon','category'),p)
    d['observed_category']=(('year','lat','lon'),y)
    d['probability_common_support']=(('year','lat','lon'),(y>=0).astype('int8'))
    d['region_mask']=(('lat','lon'),np.ones((2,2),'int8'))
    r,f=calculate(d)
    assert r['regularized_regime_blend']['annual_rps']==[0.,0.]
    assert np.nanmax(f.rps_difference)<0
    assert np.isnan(f.rps_difference.values[1,1])
    for method in r:
        for bins in r[method]['reliability'].values():assert np.isclose(sum(b['weight_fraction'] for b in bins),1)
    for bins in r['regularized_regime_blend']['reliability'].values():
        assert bins[0]['observed_frequency']==0 and bins[-1]['observed_frequency']==1
    d['shared_blend_probability'].values[0,0,0]=[1,1,1]
    try:calculate(d)
    except ValueError:pass
    else:raise AssertionError('Invalid probabilities were accepted')
    print('PASS: metrics, bin endpoints, support, weights and invalid probabilities')
if __name__=='__main__':test_metrics()
