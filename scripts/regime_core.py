"""Observed-cycle diagnostics and fixed, auditable regime-blend experiment."""
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks

REGIMES = {-2:'outside_country', -1:'missing_observations', 0:'arid',
           1:'annual_summer', 2:'spring_and_summer', 3:'spring_and_autumn',
           4:'other_or_uncertain'}
SETTINGS = dict(arid_annual_mm=200., amplitude_floor_mm_day=1e-4,
                minimum_relative_amplitude=.05, peak_sigma_days=10.,
                peak_prominence_fraction=.15, secondary_peak_fraction=.30,
                minimum_peak_separation_days=60, gamma=.05,
                minimum_group_years=20, minimum_group_cells=10)
TARGETS = {'JJAS':([6,7,8,9],120.,.20), 'Jun':([6],30.,.05),
           'Jul':([7],30.,.05), 'Aug':([8],30.,.05), 'Sep':([9],30.,.05)}


def calendar_arrays(dates, values, year):
    """Require complete daily calendar; return 365-day cycle and actual month sums.

    February 29 is excluded ONLY from the harmonic cycle, not from totals.
    Missing grid values stay missing: no NaN-to-zero precipitation conversion.
    """
    dates = np.asarray(dates).astype('datetime64[D]')
    expected = np.arange(np.datetime64(f'{year}-01-01'), np.datetime64(f'{year+1}-01-01'))
    if not np.array_equal(dates,expected):
        raise ValueError(f'{year}: timestamps must contain exactly one entry per calendar day, in order.')
    values=np.asarray(values,dtype=float)
    if len(values)!=len(dates) or np.isinf(values).any() or (values[np.isfinite(values)]<0).any():
        raise ValueError(f'{year}: invalid daily rainfall.')
    md=np.array([str(d)[5:] for d in dates]); months=np.array([int(s[:2]) for s in md])
    cycle=values[md!='02-29']
    monthly=np.stack([values[months==m].sum(axis=0) for m in range(1,13)])
    return cycle,monthly


def diagnose(cycle, monthly, region):
    """Input training means (365,pixel) and (12,pixel); output flattened fields."""
    q=np.asarray(cycle,float); monthly=np.asarray(monthly,float); region=np.asarray(region,bool)
    valid=np.isfinite(q).all(axis=0)&np.isfinite(monthly).all(axis=0)
    annual=monthly.sum(axis=0); angle=2*np.pi*np.arange(365)/365
    cs=[];phase=[]
    for k in [1,2]:
        a=2/365*np.cos(k*angle)@q;b=2/365*np.sin(k*angle)@q
        cs.append(np.hypot(a,b));phase.append(1+np.mod(np.arctan2(b,a),2*np.pi)*365/(2*np.pi*k))
    c1,c2=cs; floor=SETTINGS['amplitude_floor_mm_day']
    ratio=np.divide(c2,c1,out=np.full_like(c1,np.nan),where=c1>floor)
    strong=valid&(np.maximum(c1,c2)>np.maximum(floor,SETTINGS['minimum_relative_amplitude']*q.mean(axis=0)))
    # Raw: -1 unavailable/weak, 0 annual-dominant, 1 semiannual-dominant, 2 equal.
    raw=np.full(len(region),-1,dtype='int8'); raw[strong&(c1>c2)]=0;raw[strong&(c2>c1)]=1
    raw[strong&np.isclose(c1,c2,rtol=1e-6,atol=floor)]=2
    sm=gaussian_filter1d(q,SETTINGS['peak_sigma_days'],axis=0,mode='wrap')
    p1=np.full(len(region),np.nan);p2=p1.copy();prom1=p1.copy();prom2=p1.copy();sep=p1.copy()
    group=np.full(len(region),-1,dtype='int8'); group[valid]=4
    for i in np.flatnonzero(valid&region):
        v=sm[:,i]; amplitude=np.ptp(v)
        if amplitude<=floor:continue
        peaks,props=find_peaks(np.tile(v,3),prominence=max(floor,SETTINGS['peak_prominence_fraction']*amplitude))
        keep=(peaks>=365)&(peaks<730);peaks=peaks[keep]-365;prom=props['prominences'][keep]
        if not len(peaks):continue
        order=np.argsort(-v[peaks],kind='stable');peaks=peaks[order];prom=prom[order]
        p1[i]=peaks[0]+1;prom1[i]=prom[0]
        for j in range(1,len(peaks)):
            distance=min(abs(int(peaks[j]-peaks[0])),365-abs(int(peaks[j]-peaks[0])))
            if distance>=SETTINGS['minimum_peak_separation_days'] and v[peaks[j]]>=SETTINGS['secondary_peak_fraction']*v[peaks[0]]:
                p2[i]=peaks[j]+1;prom2[i]=prom[j];sep[i]=distance;break
        spring=any(60<=p<=151 for p in [p1[i],p2[i]])
        summer=any(152<=p<=273 for p in [p1[i],p2[i]])
        autumn=any(274<=p<=334 for p in [p1[i],p2[i]])
        if strong[i] and spring and summer:group[i]=2
        elif raw[i]==1 and spring and autumn:group[i]=3
        elif raw[i]==0 and 152<=p1[i]<=273:group[i]=1
    group[valid&(annual<SETTINGS['arid_annual_mm'])]=0
    group[~region]=-2
    # Per-cell reason preserves the distinction between a weak cycle and other timing.
    reason=group.copy();reason[(group==4)&~strong]=5
    out=dict(refinement_reason=reason,observation_valid=valid,regime=group,raw_harmonic_class=raw,
             annual_mean_mm=annual,annual_noleap_mean_mm=q.sum(axis=0),
             C1_mm_day=c1,C2_mm_day=c2,harmonic_ratio=ratio,
             ratio_defined=valid&(c1>floor),cycle_strong=strong,
             annual_harmonic_peak_day=np.where(c1>floor,phase[0],np.nan),
             semiannual_first_peak_day=np.where(c2>floor,phase[1],np.nan),
             primary_peak_day=p1,secondary_peak_day=p2,
             primary_prominence_mm_day=prom1,secondary_prominence_mm_day=prom2,
             peak_separation_days=sep)
    for name,(months,minimum,share) in TARGETS.items():
        total=monthly[np.array(months)-1].sum(axis=0)
        fraction=np.divide(total,annual,out=np.full_like(annual,np.nan),where=annual>0)
        out[name+'_mean_mm']=total;out[name+'_annual_share']=fraction
        out[name+'_relevant']=valid&region&(total>=minimum)&(fraction>=share)
    return out


def fit_group_weights(records, groups, area, region, gamma=SETTINGS['gamma'],
                      min_years=SETTINGS['minimum_group_years'], min_cells=SETTINGS['minimum_group_cells']):
    """Equal-year, area-weighted RPS fit. Shared weight uses original full domain.

    Group labels must be cross-fitted for each record. Uncertain/missing cells
    fall back to the shared fit. Cell counts are support gates, not iid samples.
    """
    p=np.stack([r['s'] for r in records]);c=np.stack([r['clim'] for r in records]);y=np.stack([r['y'] for r in records])
    valid=(y>=0)&np.isfinite(p).all(axis=-1)&np.isfinite(c).all(axis=-1)
    truth=np.eye(3)[np.maximum(y,0)];res=np.cumsum(p-truth,axis=-1)[...,:2];direction=np.cumsum(c-p,axis=-1)[...,:2]
    a=np.where(valid,(direction**2).sum(axis=-1),0.);b=np.where(valid,-(res*direction).sum(axis=-1),0.)
    def moments(mask):
        w=np.where(mask,area[None,:],0.);den=w.sum(axis=1);ok=den>0
        if not ok.any():return 0.,0.,0
        w=w[ok]/den[ok,None]/ok.sum()
        return float(np.sum(w*a[ok])),float(np.sum(w*b[ok])),int(ok.sum())
    aa,bb,n=moments(valid)
    if n!=len(records):raise ValueError('Inner year without valid probability pairs.')
    shared=float(np.clip(bb/aa,0,1)) if aa>1e-15 else 1.
    fits={}
    for g in range(4):
        mask=valid&(np.asarray(groups)==g)&region[None,:]
        supported_year=mask.sum(axis=1)>=min_cells;mask &= supported_year[:,None]
        aa,bb,n=moments(mask);supported=n>=min_years and aa>1e-15
        fits[str(g)]=dict(independent=float(np.clip(bb/aa,0,1)) if supported else shared,
                         regularized=float(np.clip((bb+gamma*shared)/(aa+gamma),0,1)) if supported else shared,
                         supported=bool(supported),years=n,cells_by_inner_year=mask.sum(axis=1).tolist(),a=aa,b=bb)
    return dict(shared=shared,groups=fits,gamma=gamma)


def apply_group_weights(record, group, fitted):
    p,c=record['s'],record['clim'];shared=fitted['shared']
    pred=dict(climatology=c,smooth=p,shared_blend=(1-shared)*p+shared*c)
    weights={}
    for method in ['independent','regularized']:
        lam=np.full(len(group),shared,dtype=float)
        for g,fit in fitted['groups'].items():lam[group==int(g)]=fit[method]
        weights[method]=lam
        pred[method+'_regime_blend']=(1-lam[:,None])*p+lam[:,None]*c
    return pred,weights
