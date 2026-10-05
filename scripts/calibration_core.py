"""Seasonal mean/variance adjustment and identity-regularized Dirichlet mapping."""
import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp, softmax

EPS = 1e-12
REG_OFF, REG_DIAG, REG_BIAS = 0.01, 0.001, 0.001


def fit_amount(models, observations, land):
    """Fit on supplied years ONLY. Each year has equal weight, however many members.

    models: list of (member, pixel) arrays; observations: (year, pixel).
    Complete observations in every supplied training year are required.
    """
    obs = np.asarray(observations, dtype=float)
    if len(models) != len(obs) or len(obs) < 20:
        raise ValueError('At least 20 matched training years are required.')
    n = obs.shape[1]
    eligible = np.asarray(land, bool) & np.isfinite(obs).all(axis=0)
    means, seconds = [], []
    for m in models:
        if m.ndim != 2 or m.shape[1] != n or not np.isfinite(m).all() or (m < 0).any():
            raise ValueError('Model arrays must be complete nonnegative member x pixel arrays.')
        means.append(m.mean(axis=0))
        seconds.append((m*m).mean(axis=0))
    mu_h = np.mean(means,axis=0)
    sd_h = np.sqrt(np.maximum(np.mean(seconds,axis=0)-mu_h**2,0))
    # Avoid calculations/warnings on ineligible observation pixels.
    safe_obs = np.where(eligible[None,:],obs,0)
    mu_o = safe_obs.mean(axis=0)
    sd_o = safe_obs.std(axis=0,ddof=0)
    ratio = np.ones(n)
    np.divide(sd_o,sd_h,out=ratio,where=sd_h>=1.0)
    ratio = np.clip(ratio,0.5,2.0) # if model SD < 1 mm, mean-only correction
    q1,q2 = np.quantile(safe_obs,[1/3,2/3],axis=0,method='linear')
    categorical = eligible & (sd_o >= 1.0) & (q1 > 0) & ((q2-q1)>1e-6)
    params = dict(mu_model=mu_h,sd_model=sd_h,mu_obs=mu_o,sd_obs=sd_o,
                  scale=ratio,q1=q1,q2=q2,amount_eligible=eligible,probability_eligible=categorical)
    for name in ('mu_model','sd_model','mu_obs','sd_obs','scale','q1','q2'):
        params[name] = np.where(eligible,params[name],np.nan)
    return params


def correct_amount(m,params):
    before = params['mu_obs'] + params['scale']*(m-params['mu_model'])
    result = np.maximum(before,0)
    result[:,~params['amount_eligible']] = np.nan
    return result


def categories(values,q1,q2):
    """Below: x<q1; near: q1<=x<=q2; above: x>q2."""
    return np.where(values<q1,0,np.where(values>q2,2,1))


def probabilities(m,params):
    c = categories(m,params['q1'],params['q2'])
    p = np.stack([(c==k).mean(axis=0) for k in range(3)],axis=-1)
    p[~params['probability_eligible']] = np.nan
    return p


def labels(obs,params):
    y = categories(obs,params['q1'],params['q2']).astype('int16')
    y[~(params['probability_eligible'] & np.isfinite(obs))] = -1
    return y


def log_inputs(p):
    p = np.maximum(np.asarray(p,float),EPS)
    p = p/p.sum(axis=-1,keepdims=True)
    return np.log(p)


def objective(theta,x,y,w):
    a,b = theta[:9].reshape(3,3),theta[9:]
    logits = x@a.T+b
    loss = np.sum(w*(logsumexp(logits,axis=1)-logits[np.arange(len(y)),y]))
    penalty = np.full((3,3),REG_OFF)
    np.fill_diagonal(penalty,REG_DIAG)
    delta = a-np.eye(3)
    loss += np.sum(penalty*delta**2)+REG_BIAS*np.sum(b*b)
    diff = softmax(logits,axis=1)
    diff[np.arange(len(y)),y]-=1
    diff *= w[:,None]
    grad = np.r_[(diff.T@x+2*penalty*delta).ravel(),diff.sum(axis=0)+2*REG_BIAS*b]
    return float(loss),grad


def fit_dirichlet(p_by_year,y_by_year,area):
    """One global map, pooled over valid cells; equal years, area-weighted within year."""
    xs,ys,ws = [],[],[]
    for p,y in zip(p_by_year,y_by_year):
        valid = np.isfinite(p).all(axis=1)&(y>=0)
        if not valid.any():
            raise ValueError('A training year has no eligible calibration pairs.')
        xs.append(log_inputs(p[valid]));ys.append(y[valid])
        w = area[valid];ws.append(w/w.sum()/len(p_by_year))
    x,y,w = np.concatenate(xs),np.concatenate(ys),np.concatenate(ws)
    if len(np.unique(y)) != 3:
        raise ValueError('Dirichlet training requires all three observed categories.')
    initial = np.r_[np.eye(3).ravel(),np.zeros(3)]
    result = minimize(objective,initial,args=(x,y,w),jac=True,method='L-BFGS-B',
                      options={'maxiter':1000,'ftol':1e-12,'gtol':1e-7})
    if not result.success or not np.isfinite(result.x).all():
        raise RuntimeError('Dirichlet optimizer failed: '+str(result.message))
    return dict(A=result.x[:9].reshape(3,3).tolist(),b=result.x[9:].tolist(),
                objective=float(result.fun),iterations=int(result.nit),training_pairs=int(len(y)),
                training_years=len(p_by_year),converged=True,epsilon=EPS,
                reg_off=REG_OFF,reg_diag=REG_DIAG,reg_bias=REG_BIAS,
                weighting='equal total weight per year; spherical area within each year')


def apply_dirichlet(p,model):
    out = np.full_like(p,np.nan,dtype=float)
    valid = np.isfinite(p).all(axis=-1)
    out[valid] = softmax(log_inputs(p[valid])@np.asarray(model['A']).T+np.asarray(model['b']),axis=-1)
    return out
