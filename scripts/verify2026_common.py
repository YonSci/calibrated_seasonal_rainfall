"""Paths, calendar and grid guards for frozen-forecast verification."""
import calendar,hashlib,json
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
import pandas as pd
import xarray as xr
from cycle import CYCLE, YEAR, REF, REF_DASH, REF_YEARS, MEMBERS, REGIME, REGIME_YEARS, OVERLAP_YEAR, EVALUATION_STUDY
ROOT=Path(__file__).resolve().parents[1]
from common import season_months
# Months and periods of the cycle's season (Jun-Sep + JJAS for the May cycle).
_SEASON=CYCLE.project['season']
MONTHS={calendar.month_abbr[m]:m for m in season_months(CYCLE.project)}
PERIODS={k:(f'{m:02d}-01',f'{m:02d}-{calendar.monthrange(2000,m)[1]:02d}') for k,m in MONTHS.items()}  # same convention as monthly_config
PERIODS[_SEASON['name']]=(_SEASON['start'],_SEASON['end'])
BASE='https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/netcdf/p25/by_month/'
from cycle import SEASON, TARGET_ORDER, DOMAIN_VIEW, target_window
TAG=CYCLE.tag                                    # e.g. init05, init09
TARGETS=[SEASON,*MONTHS]                         # freeze/verification order: season, then months

def window_iso(target):
    s,e=target_window(target);return s.isoformat(),e.isoformat()

def window_days(target):
    s,e=target_window(target);return (e-s).days+1

def month_year(name):
    # Calendar year of a month target (January of an ONDJ season falls in the next year).
    return target_window(name)[0].year

def path(p):
    p=Path(p);return p if p.is_absolute() else ROOT/p

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(p,d):Path(p).write_text(json.dumps(d,indent=2,allow_nan=False),encoding='utf-8')
def now():return datetime.now(timezone.utc).isoformat()
def dates(year,start,end):
    m,d=map(int,end.split('-'));end=f'{m:02d}-{min(d,calendar.monthrange(year,m)[1]):02d}'
    return pd.date_range(f'{year}-{start}',f'{year}-{end}',freq='D')

def check_forecast(d,target):
    if int(d.attrs.get('target_year',-1))!=YEAR or int(d.attrs.get('initialization_month',-1))!=CYCLE.init_month:raise ValueError(f'Expected {CYCLE.init_month_name}-initialized {YEAR} forecast')
    if json.loads(d.attrs['target_period'])!={'name':target,'start':PERIODS[target][0],'end':PERIODS[target][1]}:raise ValueError('Forecast target period mismatch')
    if d.attrs.get('training_years')!=f'{REF}' or 'shared climatology blend' not in d.attrs.get('method',''):raise ValueError(f'Expected final shared blend trained only on {REF}')
    if list(map(str,d.category.values))!=['below','near','above']:raise ValueError('Unexpected categories/order')
    if d.sizes['member']!=MEMBERS or len(np.unique(d.member))!=MEMBERS:raise ValueError(f'Expected {MEMBERS} unique members')
    for c in ['lat','lon']:
        if not np.allclose(np.diff(d[c]),.25,atol=1e-6,rtol=0):raise ValueError('Expected ascending 0.25 degree common grid')
    for name in ['region_mask','amount_eligible','probability_eligible']:
        if not np.isin(d[name],[0,1]).all():raise ValueError('Invalid '+name)
    for name in ['precip_corrected','corrected_ensemble_mean','observed_training_mean','corrected_mean_anomaly','q1','q2']:
        if d[name].attrs.get('units')!='mm':raise ValueError('Expected mm for '+name)
    av=d.amount_eligible.values==1;pv=d.probability_eligible.values==1
    if (pv&~av).any():raise ValueError('Probability eligibility outside amount support')
    x=d.precip_corrected.transpose('member','lat','lon').values
    if not np.isfinite(x[:,av]).all() or (x[:,av]<0).any():raise ValueError('Invalid corrected member values')
    if not np.allclose(x[:,av].mean(0),d.corrected_ensemble_mean.values[av],atol=.001,rtol=1e-6):raise ValueError('Stored ensemble mean mismatch')
    if not np.allclose((d.corrected_ensemble_mean-d.observed_training_mean).values[av],d.corrected_mean_anomaly.values[av],atol=.001,rtol=1e-6):raise ValueError('Stored anomaly mismatch')
    q1=d.q1.values;q2=d.q2.values
    if not np.isfinite(q1[pv]).all() or not np.isfinite(q2[pv]).all() or (q2[pv]<=q1[pv]).any():raise ValueError('Invalid saved thresholds')
    lam=float(d.attrs['climatology_weight'])
    if not np.isfinite(lam) or not 0<=lam<=1:raise ValueError('Invalid blend weight')
    p={}
    for k in ['base_probability','smoothed_probability','climatology_probability','blend_probability']:
        v=d[k].transpose('lat','lon','category').values;p[k]=v
        if not np.isfinite(v[pv]).all() or (v[pv]<0).any() or (v[pv]>1).any() or not np.allclose(v[pv].sum(-1),1,atol=1e-6,rtol=0):raise ValueError('Invalid '+k)
    counts=np.stack([(x<q1).mean(0),((x>=q1)&(x<=q2)).mean(0),(x>q2).mean(0)],-1)
    if not np.allclose(p['base_probability'][pv],counts[pv],atol=1e-6,rtol=0):raise ValueError('Base member counts mismatch')
    if not np.allclose(p['smoothed_probability'][pv],(MEMBERS*p['base_probability'][pv]+.5)/(MEMBERS+1.5),atol=1e-6,rtol=0):raise ValueError('Smoothing formula mismatch')
    if not np.allclose(p['blend_probability'][pv],((1-lam)*p['smoothed_probability']+lam*p['climatology_probability'])[pv],atol=1e-6,rtol=0):raise ValueError('Blend formula mismatch')

def same_grid(d,f):
    if not np.array_equal(d.lat,f.lat) or not np.array_equal(d.lon,f.lon):raise ValueError('Grid differs from frozen forecast; no implicit interpolation allowed')

def daily_block(ds,year,month,lat,lon,variable='precip'):
    """Subset native p25 cells by coordinate matching, never interpolation."""
    label=' '.join(str(ds.attrs.get(k,'')) for k in ['title','version']).lower()
    if 'chirps' not in label or '2.0' not in label:raise ValueError('Expected explicit CHIRPS Version 2.0 metadata')
    a=ds[variable]
    rename={c:v for c,v in [('latitude','lat'),('longitude','lon')] if c in a.dims}
    a=a.rename(rename)
    if set(a.dims)!={'time','lat','lon'}:raise ValueError('Expected time, lat, lon')
    if str(a.attrs.get('units','')).lower().strip() not in {'mm/day','mm/d','mm day-1','mm day^-1','mm d-1','mm'}:raise ValueError('Unexpected CHIRPS units')
    idx=pd.DatetimeIndex(a.time.values)
    if not idx.is_unique or not idx.is_monotonic_increasing or not (idx==idx.normalize()).all():raise ValueError('Invalid daily time labels')
    want=dates(year,f'{month:02d}-01',f'{month:02d}-{calendar.monthrange(year,month)[1]:02d}')
    missing=want.difference(idx)
    if len(missing):raise ValueError(f'Incomplete {year}-{month:02d}: missing {len(missing)} daily labels')
    a=a.sel(time=want).sortby('lat').sortby('lon')
    for name,coords in [('lat',lat),('lon',lon)]:
        axis=pd.Index(a[name].values)
        if not axis.is_unique:raise ValueError('Duplicate '+name)
        selected=axis.get_indexer(np.asarray(coords),method='nearest',tolerance=1e-6)
        if np.any(selected<0):raise ValueError('Historical/common grid does not match official p25 '+name+'; recover original remapping procedure')
        a=a.isel({name:selected}).assign_coords({name:np.asarray(coords)})
    a=a.transpose('time','lat','lon').astype('float64').load()
    if np.isinf(a.values).any() or (a.values<0).any():raise ValueError('Invalid negative/infinite daily rainfall')
    return a

def overlap_check(downloaded,historical,tolerance=1e-4):
    x,y=np.asarray(downloaded),np.asarray(historical)
    if x.shape!=y.shape or not np.array_equal(np.isfinite(x),np.isfinite(y)):raise ValueError('Overlap shape/missing-data support differs')
    v=np.isfinite(x)
    if not v.any():raise ValueError('Overlap contains no valid observations')
    error=float(np.max(np.abs(x[v]-y[v])))
    if error>tolerance:raise ValueError(f'Historical overlap differs by {error:g} mm/day (limit {tolerance:g}); do not mix products or loosen tolerance without investigating')
    return {'maximum_absolute_difference_mm_day':error,'comparison_values':int(v.sum()),'tolerance_mm_day':tolerance,'passed':True}

def total(a):
    count=np.isfinite(a.values).sum(0)
    z=np.sum(a.values,axis=0,dtype=np.float64)
    return z,count

def area(d):return np.broadcast_to(np.cos(np.deg2rad(d.lat.values.astype(float)))[:,None],(d.sizes['lat'],d.sizes['lon']))
