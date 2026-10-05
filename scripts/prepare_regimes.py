"""Build daily CHIRPS cache, corrected climatology, and independent mask layers."""
import argparse
import hashlib
import json
import numpy as np
import xarray as xr
from common import ROOT,load_config,source_path,save_netcdf,save_json
from output_runs import staged_output,check_destination
from regime_core import calendar_arrays,diagnose,REGIMES,SETTINGS,TARGETS

CACHE=ROOT/'data/processed/regime_climatology'


def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def load_region(path,lat=None,lon=None):
    with xr.open_dataset(source_path(path)) as d:
        a=d.region_mask.transpose('lat','lon').load()
    if not np.isin(a.values,[0,1]).all() or not (a.values==1).any():raise ValueError('Expected nonempty binary country mask.')
    if lat is not None and (not np.array_equal(a.lat,lat) or not np.array_equal(a.lon,lon)):raise ValueError('Country mask grid mismatch.')
    return a


class RegimeCache:
    def __init__(self,path,region):
        with xr.open_dataset(path) as d:
            self.years=d.year.values.astype(int).tolist();self.lat=d.lat.values.copy();self.lon=d.lon.values.copy()
            self.daily=d.daily_noleap.values.reshape(len(self.years),365,-1).astype(float)
            self.monthly=d.monthly_total.values.reshape(len(self.years),12,-1).astype(float)
            self.attrs=dict(d.attrs)
        self.region=np.asarray(region,bool).reshape(-1);self.memo={}
        # Sufficient sums allow subset means without allocating another daily cube.
        self.daily_finite=np.isfinite(self.daily);self.monthly_finite=np.isfinite(self.monthly)
        self.daily=np.nan_to_num(self.daily);self.monthly=np.nan_to_num(self.monthly)
        self.total_daily=self.daily.sum(axis=0);self.total_monthly=self.monthly.sum(axis=0)
        self.count_daily=self.daily_finite.sum(axis=0);self.count_monthly=self.monthly_finite.sum(axis=0)
    def means(self,years):
        years=tuple(sorted(years))
        if len(set(years))!=len(years) or not years or not set(years)<=set(self.years):raise ValueError('Invalid climatology training years.')
        omitted=[i for i,y in enumerate(self.years) if y not in years]
        q=self.total_daily-self.daily[omitted].sum(axis=0); m=self.total_monthly-self.monthly[omitted].sum(axis=0)
        nq=self.count_daily-self.daily_finite[omitted].sum(axis=0);nm=self.count_monthly-self.monthly_finite[omitted].sum(axis=0)
        q/=len(years);m/=len(years);q[nq!=len(years)]=np.nan;m[nm!=len(years)]=np.nan
        return q,m
    def fit(self,years):
        key=tuple(sorted(years))
        if key not in self.memo:self.memo[key]=diagnose(*self.means(key),self.region)
        return self.memo[key]


def diagnostic_dataset(fields,lat,lon,attrs):
    out=xr.Dataset(coords=dict(lat=lat,lon=lon),attrs=attrs)
    for k,v in fields.items():out[k]=( ('lat','lon'),np.asarray(v).reshape(len(lat),len(lon)).astype('int8') if np.asarray(v).dtype==bool else np.asarray(v).reshape(len(lat),len(lon)))
    out.regime.attrs['codes']=json.dumps(REGIMES)
    out.refinement_reason.attrs['codes']=json.dumps(REGIMES)+'; reason 4=other timing/unresolved peaks, 5=weak cycle'
    out.raw_harmonic_class.attrs['codes']='-1 missing/weak; 0 annual-dominant; 1 semiannual-dominant; 2 nearly equal'
    return out


def plot_diagnostics(d,out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap,BoundaryNorm
    cmap=ListedColormap(['#bdbdbd','#e5c494','#1b9e77','#7570b3','#d95f02','#f1da49'])
    fig,ax=plt.subplots(figsize=(8,7))
    v=d.regime.where(d.region_mask==1)
    im=ax.pcolormesh(d.lon,d.lat,v,cmap=cmap,norm=BoundaryNorm(np.arange(-1.5,5),6),shading='auto')
    cb=fig.colorbar(im,ax=ax,ticks=range(-1,5),shrink=.7);cb.ax.set_yticklabels([REGIMES[g] for g in range(-1,5)])
    ax.set(title='Observed rainfall regimes | diagnostic grid, no cosmetic reassignment',xlabel='Longitude',ylabel='Latitude',aspect='equal')
    fig.tight_layout();fig.savefig(out/'regime_diagnostics.png',dpi=160);plt.close(fig)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',default='config/project.json');p.add_argument('--region-mask',default='data/masks/ethiopia_common.nc');p.add_argument('--regenerate',action='store_true')
    args=p.parse_args();cfg=load_config(args.config);mask=load_region(args.region_mask);path=source_path(cfg['chirps_file'])
    years=list(range(1993,2026));check_destination(CACHE,args.regenerate)
    cycles=[];months=[]
    with xr.open_dataset(path) as ds:
        var=ds[cfg.get('chirps_variable','precip')]
        rename={k:v for k,v in [('latitude','lat'),('longitude','lon')] if k in var.dims}
        var=var.rename(rename).transpose('time','lat','lon').sortby('lat').sortby('lon')
        if not np.array_equal(var.lat,mask.lat) or not np.array_equal(var.lon,mask.lon):raise ValueError('Raw CHIRPS must match the existing 0.25 degree country/common grid exactly. No implicit regridding.')
        unit=var.attrs.get('units','').lower().replace(' ','').replace('**','^')
        if unit not in ['mm','mm/day','mm/d','mmd-1','mmday-1','mmd^-1','mmday^-1']:raise ValueError(f'Expected daily CHIRPS in mm/day (or mm daily amounts), got {unit!r}. Verify metadata; do not relabel other units.')
        for y in years:
            a=var.sel(time=slice(f'{y}-01-01',f'{y}-12-31')).load()
            q,m=calendar_arrays(a.time.values,a.values,y);cycles.append(q.astype('float32'));months.append(m)
            print(f'Cached calendar {y}: {len(a.time)} days; leap day retained in monthly totals.',flush=True)
    attrs=dict(source_path=str(path),source_sha256=sha256(path),config_json=json.dumps(cfg),
               calendar_policy='365-day cycle excludes Feb29 by month-day; actual monthly totals retain Feb29; complete calendar required',
               missing_policy='Strict completeness within each training subset; no imputation',settings_json=json.dumps(SETTINGS))
    cache=xr.Dataset(dict(daily_noleap=(('year','day','lat','lon'),np.stack(cycles)),
                          monthly_total=(('year','month','lat','lon'),np.stack(months))),
                     coords=dict(year=years,day=np.arange(1,366),month=np.arange(1,13),lat=mask.lat,lon=mask.lon),attrs=attrs)
    cache.daily_noleap.attrs['units']='mm/day';cache.monthly_total.attrs['units']='mm'
    with staged_output(CACHE,args.regenerate) as out:
        save_netcdf(cache,out/'chirps_calendar_cache.nc')
        fitted=RegimeCache(out/'chirps_calendar_cache.nc',mask.values==1)
        for name,train in [('training_1993_2016',list(range(1993,2017))),('descriptive_1993_2025',years)]:
            fields=fitted.fit(train);q,m=fitted.means(train)
            d=diagnostic_dataset(fields,mask.lat.values,mask.lon.values,dict(**attrs,training_years=json.dumps(train),
                    onset_detection_status='Not computed; absent evidence is not a pass. Not required for rainfall totals.',
                    physical_land_mask_status='Not inferred from country mask or CHIRPS validity.',
                    refinement_policy='Fixed experimental peak rules; not an official EMI classification; no morphological cleanup'))
            d['region_mask']=mask.astype('int8');d['daily_climatology']=(('day','lat','lon'),q.reshape(365,len(mask.lat),len(mask.lon)))
            d['monthly_climatology']=(('month','lat','lon'),m.reshape(12,len(mask.lat),len(mask.lon)))
            save_netcdf(d,out/f'{name}.nc')
        plot_diagnostics(d,out)
        save_json(out/'preparation_report.json',dict(**attrs,years=years,regime_codes=REGIMES,seasonal_relevance_candidates=TARGETS,
            note='Full-baseline map is descriptive only. Evaluation recomputes regimes inside each fold. No forecast files changed.',
            descriptive_cells_by_regime={str(g):int((d.regime.values==g).sum()) for g in REGIMES},
            monthly_annual_identity='annual_mean_mm is sum of actual-calendar monthly climatologies; noleap annual diagnostic deliberately differs by mean Feb29 rain'))
    print('Ready:',CACHE)


if __name__=='__main__':main()
