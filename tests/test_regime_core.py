"""Run: python -m unittest discover -s tests -p test_regime_core.py -v"""
import sys
import unittest
from pathlib import Path
import tempfile
import numpy as np
import xarray as xr
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from regime_core import calendar_arrays,diagnose,fit_group_weights,apply_group_weights
from prepare_regimes import RegimeCache


class RegimeTests(unittest.TestCase):
    def test_leap_alignment_and_actual_totals(self):
        dates=np.arange(np.datetime64('2000-01-01'),np.datetime64('2001-01-01'))
        x=np.ones((366,1));x[59]=100;x[60]=7;x[-1]=9
        cycle,monthly=calendar_arrays(dates,x,2000)
        self.assertEqual(cycle.shape,(365,1));self.assertEqual(cycle[59,0],7)
        self.assertEqual(cycle[-1,0],9);self.assertEqual(monthly[1,0],128)
        self.assertEqual(monthly.sum()-cycle.sum(),100)
        with self.assertRaises(ValueError):calendar_arrays(dates[:-1],x[:-1],2000)

    def test_missing_is_not_a_regime(self):
        q=np.ones((365,3))*3;q[100,0]=np.nan
        f=diagnose(q,np.ones((12,3))*90,np.array([True,True,False]))
        self.assertEqual(f['regime'][0],-1);self.assertEqual(f['regime'][1],4)
        self.assertEqual(f['regime'][2],-2)
        self.assertFalse(f['JJAS_relevant'][0]);self.assertFalse(f['ratio_defined'][1])

    def test_harmonic_and_peak_diagnostics(self):
        t=np.arange(365);annual=4+3*np.cos(2*np.pi*(t-210)/365)
        semi=4+3*np.cos(4*np.pi*(t-100)/365)
        q=np.stack([annual,semi],axis=1)
        f=diagnose(q,np.ones((12,2))*100,np.ones(2,bool))
        np.testing.assert_allclose(f['C1_mm_day'],[3,0],atol=1e-10)
        np.testing.assert_allclose(f['C2_mm_day'],[0,3],atol=1e-10)
        self.assertEqual(f['raw_harmonic_class'].tolist(),[0,1])
        self.assertEqual(f['regime'].tolist(),[1,3])
        self.assertTrue(np.isnan(f['harmonic_ratio'][1]))
        self.assertGreaterEqual(f['peak_separation_days'][1],60)

    def test_blend_and_regularization(self):
        records=[dict(s=np.tile([.8,.1,.1],(20,1)),clim=np.ones((20,3))/3,y=np.zeros(20,dtype=int)) for _ in range(22)]
        groups=np.zeros((22,20),dtype=int);groups[:,10:]=1
        for r in records:r['y'][10:]=2
        fitted=fit_group_weights(records,groups,np.ones(20),np.ones(20,bool))
        for g in ['0','1']:
            fit=fitted['groups'][g]
            self.assertTrue(fit['supported'])
            self.assertLessEqual(abs(fit['regularized']-fitted['shared']),abs(fit['independent']-fitted['shared'])+1e-12)
        pred,weights=apply_group_weights(records[0],groups[0],fitted)
        for p in pred.values():np.testing.assert_allclose(p.sum(axis=1),1);self.assertTrue((p>=0).all())
        self.assertFalse(fitted['groups']['2']['supported'])
        self.assertEqual(fitted['groups']['2']['regularized'],fitted['shared'])
        # Shared fit exactly matches established full-domain local_blend baseline.
        from local_blend import fit_weights
        self.assertAlmostEqual(fitted['shared'],fit_weights(records,np.ones(20))['shared_lambda'],places=14)

    def test_fold_cache_excludes_target_and_missing(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'cache.nc';daily=np.ones((3,365,2,2))*2;monthly=np.ones((3,12,2,2))*60
            daily[2]=10000;daily[2,0,0,0]=np.nan
            ds=xr.Dataset(dict(daily_noleap=(('year','day','lat','lon'),daily),monthly_total=(('year','month','lat','lon'),monthly)),coords=dict(year=[1993,1994,1995],lat=[5.,6.],lon=[37.,38.]))
            ds.to_netcdf(path)
            cache=RegimeCache(path,np.ones(4,bool));q,m=cache.means([1993,1994])
            np.testing.assert_allclose(q,2);np.testing.assert_allclose(m,60)
            self.assertTrue(cache.fit([1993,1994])['observation_valid'].all())
            self.assertFalse(cache.fit([1993,1994,1995])['observation_valid'][0])


if __name__=='__main__':unittest.main()
