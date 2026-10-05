"""Verification mathematics, independent of I/O and plotting."""
import numpy as np


def crps(ensemble,obs,fair=False):
    """Empirical CRPS, or finite-ensemble fair CRPS; member is first axis.

    Fair interpretation assumes members are an iid sample of a distribution.
    A correlated ensemble can violate that assumption.
    """
    x=np.sort(np.asarray(ensemble,float),axis=0);n=len(x)
    if fair and n<2:raise ValueError('Fair CRPS needs at least two members.')
    coeff=(2*np.arange(1,n+1)-n-1).reshape((n,)+(1,)*(x.ndim-1))
    pair=np.sum(coeff*x,axis=0)
    return np.mean(np.abs(x-obs),axis=0)-pair/(n*(n-1) if fair else n*n)


def weighted_mean(a,w,valid=None):
    valid=np.isfinite(a) if valid is None else np.asarray(valid,bool)&np.isfinite(a)
    weights=np.where(valid,w,0.)
    total=weights.sum()
    return float(np.sum(np.where(valid,a,0)*weights)/total) if total>0 else np.nan


def mean_valid(a,axis=0):
    valid=np.isfinite(a);count=valid.sum(axis=axis)
    return np.divide(np.where(valid,a,0).sum(axis=axis),count,out=np.full(count.shape,np.nan,dtype=float),where=count>0)


def temporal_correlation(f,o,min_years=6):
    valid=np.isfinite(f)&np.isfinite(o);n=valid.sum(axis=0)
    fa=np.where(valid,f,np.nan);oa=np.where(valid,o,np.nan)
    fc=np.where(valid,fa-mean_valid(fa),0);oc=np.where(valid,oa-mean_valid(oa),0)
    denom=np.sqrt(np.sum(fc*fc,axis=0)*np.sum(oc*oc,axis=0))
    return np.divide(np.sum(fc*oc,axis=0),denom,out=np.full(denom.shape,np.nan),where=(denom>0)&(n>=min_years))


def roc_curve(prob,event,weight):
    """Weighted exact ROC with ties handled as groups. Returns None if undefined."""
    ok=np.isfinite(prob)&np.isfinite(weight)&(weight>0)
    p=np.asarray(prob)[ok];y=np.asarray(event,dtype=bool)[ok];w=np.asarray(weight)[ok]
    if not y.any() or y.all():return None
    order=np.argsort(-p,kind='stable');p,y,w=p[order],y[order],w[order]
    ends=np.r_[np.flatnonzero(np.diff(p)!=0),len(p)-1]
    tp=np.r_[0,np.cumsum(w*y)[ends]];fp=np.r_[0,np.cumsum(w*~y)[ends]]
    tpr=tp/tp[-1];fpr=fp/fp[-1]
    auc=float(np.sum(np.diff(fpr)*(tpr[:-1]+tpr[1:])/2))
    return fpr,tpr,auc


def probability_losses(p,y):
    valid=np.isfinite(p).all(axis=-1)&(y>=0)
    truth=np.eye(3)[np.maximum(y,0)]
    bs=(p-truth)**2
    rps=np.sum((np.cumsum(p,axis=-1)[...,:2]-np.cumsum(truth,axis=-1)[...,:2])**2,axis=-1)
    selected=np.take_along_axis(p,np.maximum(y,0)[...,None],axis=-1)[...,0]
    ll=-np.log(np.maximum(selected,1e-12))
    bs[~valid]=np.nan;rps[~valid]=np.nan;ll[~valid]=np.nan
    return bs,rps,ll


def summarize_annual(rows,indices=None):
    """Aggregate by equal years, then form skill ratios; never average annual skill."""
    keys=[k for k in rows[0] if k!='year']
    data={k:np.asarray([r[k] for r in rows],float) for k in keys}
    out={k:float(np.mean(a if indices is None else a[indices])) for k,a in data.items()}
    for name in ('raw','corrected','climatology'):
        out[name+'_rmse_mm']=float(np.sqrt(out[name+'_mse_mm2']))
    for name in ('raw','corrected'):
        den=out['climatology_mse_mm2']
        out[name+'_mse_skill']=1-out[name+'_mse_mm2']/den if den>0 else np.nan
        den=out['climatology_crps_mm']
        out[name+'_crps_skill']=1-out[name+'_crps_mm']/den if den>0 else np.nan
    for name in ('raw','base','dirichlet'):
        den=out['climatology_rps'];out[name+'_rps_skill']=1-out[name+'_rps']/den if den>0 else np.nan
        for k in ('below','near','above'):
            den=out['climatology_bs_'+k];out[name+'_bss_'+k]=1-out[name+'_bs_'+k]/den if den>0 else np.nan
    out['dirichlet_minus_base_rps']=out['dirichlet_rps']-out['base_rps']
    out['corrected_minus_climatology_mse_mm2']=out['corrected_mse_mm2']-out['climatology_mse_mm2']
    return out


def bootstrap_years(rows,repeats,seed):
    """Paired resampling of whole years; preserves all spatial/member dependence within years."""
    rng=np.random.default_rng(seed);samples={}
    for _ in range(repeats):
        s=summarize_annual(rows,rng.integers(0,len(rows),len(rows)))
        for key,value in s.items():samples.setdefault(key,[]).append(value)
    return {key:dict(lower_2_5=float(np.nanquantile(a,.025)),upper_97_5=float(np.nanquantile(a,.975))) for key,a in samples.items()}
