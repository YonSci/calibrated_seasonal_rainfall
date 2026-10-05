r"""Run with an existing final JJAS file; exercises the gates that protect delivery.

python tests\test_delivery_checks.py --forecast outputs\final_shared_blend\init05_JJAS\2026\forecast_2026.nc
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import xarray as xr
from finalize_forecast_delivery import forecast_check,evidence_check,read_json,ROOT

def main():
    p=argparse.ArgumentParser();p.add_argument('--forecast',required=True);a=p.parse_args()
    source=Path(a.forecast)
    stats,d=forecast_check(source,'JJAS');assert stats['members']==51
    evidence_check(read_json(ROOT/'evidence/all_regime_experiments.json'),['JJAS','Jun','Jul','Aug','Sep'])
    with tempfile.TemporaryDirectory() as tmp:
        q=Path(tmp)/'changed.nc'
        wrong=d.copy(deep=True);wrong.attrs['climatology_weight']=1-float(wrong.attrs['climatology_weight']);wrong.to_netcdf(q)
        try:forecast_check(q,'JJAS')
        except ValueError as e:assert 'blend formula' in str(e)
        else:raise AssertionError('Changed blend weight was accepted')
        try:forecast_check(source,'Aug')
        except ValueError as e:assert 'target period' in str(e)
        else:raise AssertionError('Wrong target was accepted')
    evidence=read_json(ROOT/'evidence/all_regime_experiments.json')
    evidence['experiments'].append(evidence['experiments'][0])
    try:evidence_check(evidence,['JJAS','Jun','Jul','Aug','Sep'])
    except ValueError:pass
    else:raise AssertionError('Duplicate experiment record was accepted')
    print('PASS: source consistency; all-five-target evidence; modified blend, wrong target and duplicate evidence rejection')
if __name__=='__main__':main()
