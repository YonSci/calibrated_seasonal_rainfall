import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import xarray as xr
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import local_blend as m
import run_monthly as monthly
from compare_calibration import make_record


class LocalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng=np.random.default_rng(908)
        cls.models={y:rng.gamma(6,30,(25 if y<2017 else 51,4)) for y in range(1993,2026)}
        cls.obs={y:rng.gamma(5,30,4) for y in cls.models}
        cls.land=np.ones(4,bool);cls.area=np.ones(4);cls.region=np.array([1,1,1,0],bool)

    def test_analytic_local_optimum_and_shrinkage(self):
        records=[make_record([z for z in m.TRAIN if z!=y],y,self.models,self.obs,self.land) for y in m.TRAIN]
        fit=m.fit_weights(records,self.area)
        for cell in range(4):
            def loss(lam):
                vals=[]
                for r in records:
                    pred=(1-lam)*r['s'][cell]+lam*r['clim'][cell]
                    vals.append(np.sum(np.cumsum(pred-np.eye(3)[r['y'][cell]])[:2]**2))
                return np.mean(vals)
            lam=fit['local_lambda'][cell]
            self.assertLessEqual(loss(lam),min(loss(v) for v in np.linspace(0,1,101))+1e-12)
            reg=fit['regularized_lambda'][cell];shared=fit['shared_lambda']
            self.assertLessEqual(abs(reg-shared),abs(lam-shared)+1e-12)
            self.assertLessEqual(loss(reg)+m.GAMMA*(reg-shared)**2,min(loss(v)+m.GAMMA*(v-shared)**2 for v in np.linspace(0,1,101))+1e-12)

    def test_outer_year_exclusion(self):
        target=2010;train=[z for z in m.TRAIN if z!=target]
        def one(obs):
            inner=[make_record([z for z in train if z!=y],y,self.models,obs,self.land) for y in train]
            w=m.fit_weights(inner,self.area)
            return w,m.apply_weights(make_record(train,target,self.models,obs,self.land),w)
        changed=dict(self.obs);changed[target]=changed[target]+10000
        a,p=one(self.obs);b,q=one(changed)
        for k in a:np.testing.assert_equal(a[k],b[k])
        for k in p:np.testing.assert_equal(p[k],q[k])

    def test_both_modes_and_files(self):
        cfg=dict(initialization_month=5,season=dict(name='Jun',start='06-01',end='06-30'))
        for mode in ['training','operational']:
            targets,rows,records,weights=m.run(self.models,self.obs,self.land,self.area,self.region,mode,lambda _:None)
            with tempfile.TemporaryDirectory() as tmp:
                out=Path(tmp)
                m.save_outputs(out,cfg,mode,targets,rows,records,weights,self.area,self.region,np.array([3.,4.]),np.array([33.,34.]),{})
                with xr.open_dataset(out/'local_probabilities_and_weights.nc') as d:
                    np.testing.assert_allclose(d.regularized_local_blend_probability.sum('category'),1.)
                    self.assertEqual(d.sizes['year'],24 if mode=='training' else 9)
                self.assertEqual(len(list(out.glob('*.png'))),3)

    def test_monthly_configs_and_reconstruction(self):
        cfg=dict(initialization_month=5,season=dict(name='JJAS',start='06-01',end='09-30'))
        self.assertEqual(monthly.monthly_config(cfg,7)['season']['end'],'07-31')
        self.assertEqual(cfg['season']['name'],'JJAS')
        with tempfile.TemporaryDirectory() as tmp,patch.object(monthly,'ROOT',Path(tmp)):
            root=Path(tmp)
            for year in range(1993,2027):
                for kind in (['ecmwf','chirps'] if year<2026 else ['ecmwf']):
                    for name,value in [('JJAS',10.),('Jun',1.),('Jul',2.),('Aug',3.),('Sep',4.)]:
                        path=root/f'data/processed/init05_{name}/{kind}_{year}_common.nc';path.parent.mkdir(parents=True,exist_ok=True)
                        xr.Dataset({'precip_season':(('lat','lon'),[[value,np.nan],[value,value]])},coords=dict(lat=[3.,4.],lon=[33.,34.])).to_netcdf(path)
            monthly.reconstruction_check()
            self.assertTrue((root/'outputs/qc/monthly_reconstruction.json').exists())

    def test_monthly_accumulation_intervals(self):
        import pandas as pd
        from prepare_seasonal import model_season,chirps_season
        cfg=dict(initialization_month=5,season=dict(name='JJAS',start='06-01',end='09-30'),
                 ecmwf_variable='tp',chirps_variable='precip',negative_increment_tolerance_mm=.2)
        dates=pd.date_range('1993-05-01','1993-10-30')
        daily=np.arange(1,len(dates)+1,dtype=float)
        model=xr.Dataset({'tp':(('forecast_period','number','latitude','longitude'),
                             np.cumsum(daily)[:,None,None,None]/1000)},
                         coords=dict(forecast_period=np.arange(len(dates)),number=[0],latitude=[5.],longitude=[35.],
                                     forecast_reference_time=np.datetime64('1993-05-01'),
                                     valid_time=('forecast_period',dates+pd.Timedelta(days=1))))
        model.tp.attrs['units']='m'
        obs=xr.Dataset({'precip':(('time','lat','lon'),daily[:,None,None])},coords=dict(time=dates,lat=[5.],lon=[35.]))
        obs.precip.attrs['units']='mm/day'
        monthly_model=[];monthly_obs=[]
        for month in [6,7,8,9]:
            mc=monthly.monthly_config(cfg,month)
            a,qc=model_season(model,mc,1993);b=chirps_season(obs,mc,1993)
            expected=daily[dates.month==month].sum()
            self.assertAlmostEqual(float(a.precip_season.values.item()),expected)
            self.assertAlmostEqual(float(b.precip_season.values.item()),expected)
            monthly_model.append(a.precip_season.values.item());monthly_obs.append(b.precip_season.values.item())
        self.assertAlmostEqual(sum(monthly_model),model_season(model,cfg,1993)[0].precip_season.values.item())
        self.assertAlmostEqual(sum(monthly_obs),chirps_season(obs,cfg,1993).precip_season.values.item())


if __name__=='__main__':unittest.main()
