"""GitHub Ethiopia refinement on corrected calendar climatology.

Reproduces classification thresholds, priority, monthly peak tests and 4-connected
cleanup from the pinned source. Calendar and missing-data fixes are explicit.
Not independently certified as official EMI climatology; not an onset detector.
"""
import numpy as np
from scipy.ndimage import label

SOURCE_COMMIT='07879e42290dd5efd1d75f137961378ca7e39ea2'
SOURCE_URL='https://github.com/YonSci/-Operational-Multi-Model-Seasonal-Forecasting-System/blob/'+SOURCE_COMMIT+'/scripts/compute_seasonal_masks.py'
METHOD='github_refined_corrected_calendar_v1'
LABELS={-2:'outside_country',-1:'missing_observations',0:'arid_marginal',1:'western_unimodal_residual',2:'belg_kiremt_highland_rule',3:'gu_deyr_lowland_rule',4:'unused_in_github_refinement'}
MONTH_EDGES=np.array([0,31,59,90,120,151,181,212,243,273,304,334,365])


def remove_small(mask,min_size):
    components,n=label(mask)  # SciPy default: 4-neighbor connectivity in 2D.
    counts=np.bincount(components.ravel());keep=counts>=min_size;keep[0]=False
    return keep[components]


def classify(cycle,lat,lon,region):
    """365 x pixel cycle -> flat diagnostic fields. Uses no-leap totals as source.

    Ratio undefined for C1 <= 1e-4 remains NaN; comparisons are False, as for
    the source's zero fallback. Peak-only clauses remain available. Missing
    observations never enter the residual R1 class or cleanup reassignment.
    """
    lat=np.asarray(lat);lon=np.asarray(lon);shape=(len(lat),len(lon))
    q=np.asarray(cycle,float).reshape(365,-1);region=np.asarray(region,bool).reshape(-1)
    if q.shape[1]!=np.prod(shape):raise ValueError('Climatology/grid size mismatch.')
    if np.isinf(q).any() or (q[np.isfinite(q)]<0).any():raise ValueError('Invalid climatological rainfall.')
    valid=np.isfinite(q).all(axis=0);eligible=region&valid
    monthly=np.stack([q[a:b].sum(axis=0) for a,b in zip(MONTH_EDGES[:-1],MONTH_EDGES[1:])])
    theta=2*np.pi*(np.arange(1,366)-.5)/365
    amp=[np.hypot(2/365*np.cos(k*theta)@q,2/365*np.sin(k*theta)@q) for k in [1,2]]
    ratio=np.divide(amp[1],amp[0],out=np.full(q.shape[1],np.nan),where=amp[0]>1e-4)
    annual=q.sum(axis=0);fmam=q[31:151].sum(axis=0);jjas=q[151:273].sum(axis=0);ond=q[273:365].sum(axis=0);jja=q[151:243].sum(axis=0)
    def share(x):return np.divide(x,annual,out=np.zeros_like(annual),where=annual>10)
    sf,ss,so=share(fmam),share(jjas),share(ond)
    smooth=.25*np.roll(monthly,1,axis=0)+.5*monthly+.25*np.roll(monthly,-1,axis=0)
    p1=np.argmax(smooth,axis=0)+1;p2=np.zeros(q.shape[1],dtype=int)
    for i in np.flatnonzero(valid):
        peaks=[m for m in range(12) if smooth[m,i]>smooth[(m-1)%12,i] and smooth[m,i]>smooth[(m+1)%12,i]]
        peaks.sort(key=lambda m:smooth[m,i],reverse=True)
        if peaks:p2[i]=peaks[1 if len(peaks)>1 else 0]+1
    p1[~valid]=-1;p2[~valid]=-1
    LON,LAT=np.meshgrid(lon,lat);geo=((LON>=38)|((LON>=37.5)&(LAT>=10))).ravel()
    arid=((annual<200)|((annual<300)&(ond<30)))&eligible
    lowland=((ond>=30)&(so>=.08)&(jja<1.3*ond)&((ratio>=.70)|np.isin(p1,[10,11])|np.isin(p2,[10,11])))&eligible
    highland=((fmam>=50)&(sf>=.10)&(jjas>=120)&(ss>=.25)&geo&((ratio>=.38)|np.isin(p2,[3,4,5])))&eligible
    r3=lowland&~arid;r2=highland&~arid&~r3
    raw=np.full(len(region),-2,dtype='int8');raw[region]=-1;raw[eligible]=1;raw[arid]=0;raw[r2]=2;raw[r3]=3
    cleaned=raw.copy();cleaned[eligible]=1
    for code,mask,size in [(0,arid,2),(2,r2,3),(3,r3,3)]:cleaned[remove_small(mask.reshape(shape),size).ravel()]=code
    rainfall=(jjas>=120)&(ss>=.20)&eligible
    r12_raw=np.isin(raw,[1,2])&rainfall;r12=np.isin(cleaned,[1,2])&rainfall
    onset_candidate=(cleaned==2)&rainfall
    return dict(regime_raw=raw,regime_cleaned=cleaned,cleanup_changed=(cleaned!=raw),
                observation_valid=valid,C1=amp[0],C2=amp[1],harmonic_ratio=ratio,ratio_defined=valid&(amp[0]>1e-4),
                monthly_peak1=p1,monthly_peak2=p2,annual_noleap_mm=annual,FMAM_noleap_mm=fmam,
                JJAS_noleap_mm=jjas,OND_noleap_mm=ond,JJA_noleap_mm=jja,JJAS_noleap_share=ss,
                criterion_arid=arid,criterion_lowland_before_priority=lowland,criterion_highland_before_priority=highland,
                criterion_highland_geography=geo,rainfall_threshold_pass=rainfall,
                jjas_r12_rainfall_raw=r12_raw,jjas_r12_rainfall=r12,
                jjas_r12_rainfall_cleaned=remove_small(r12.reshape(shape),3).ravel(),
                onset_candidate_r2=onset_candidate)


def onset_layers(fields,region,rate=None):
    """Unknown onset evidence stays -1; never substitute 100% detection.

    False candidates are 0. Missing-observation cells remain -1; outside is 0.
    Eligibility is a separate mask and never restricts the rainfall product.
    """
    region=np.asarray(region,bool).ravel();candidate=fields['onset_candidate_r2']
    rate=np.full(len(region),np.nan) if rate is None else np.asarray(rate,float).ravel()
    if rate.shape!=region.shape or np.isinf(rate).any() or ((rate[np.isfinite(rate)]<0)|(rate[np.isfinite(rate)]>1)).any():raise ValueError('Detection rate must be 0..1 or NaN on the same grid.')
    status=np.zeros(len(region),dtype='int8');status[region&~fields['observation_valid']]=-1
    status[candidate]=-1;known=candidate&np.isfinite(rate);status[known]=(rate[known]>=.60).astype('int8')
    return dict(onset_detection_rate=rate,onset_evidence_available=np.isfinite(rate)&region,
                onset_eligibility_r2=status)
