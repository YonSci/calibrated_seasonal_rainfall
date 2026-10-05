"""Run development/holdout calibration, or final 1993-2025 refit for 2026.

Inputs: Stage-2 *_common.nc files. Outputs are separate from those inputs.
Optional static land_mask NetCDF: 1=land, 0=water, exactly on common lat/lon grid.
"""
import argparse
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import xarray as xr
from common import ROOT,load_config,save_json,save_netcdf,source_path
from cycle import CYCLE
from calibration_core import (fit_amount,correct_amount,probabilities,labels,
    fit_dirichlet,apply_dirichlet,EPS)


def load_inputs(cfg,years,observation_years):
    tag = f"init{cfg['initialization_month']:02d}_{cfg['season']['name']}"
    folder = ROOT/'data/processed'/tag
    models,observations,members = {},{},{}
    lat = lon = None
    for year in years:
        for kind in (['ecmwf','chirps'] if year in observation_years else ['ecmwf']):
            path = folder/f'{kind}_{year}_common.nc'
            with xr.open_dataset(path) as d:
                previous = json.loads(d.attrs['config_json'])
                if previous['season'] != cfg['season'] or previous['initialization_month'] != cfg['initialization_month']:
                    raise ValueError(f'Season mismatch: {path}')
                if d.precip_season.attrs.get('units') != 'mm':
                    raise ValueError(f'Expected mm: {path}')
                if lat is None:
                    lat,lon = d.lat.values.copy(),d.lon.values.copy()
                if not np.array_equal(lat,d.lat) or not np.array_equal(lon,d.lon):
                    raise ValueError(f'Grid mismatch: {path}')
                if kind == 'ecmwf':
                    if not str(d.attrs.get('season_start','')).startswith(f'{year}-'):
                        raise ValueError(f'Model year mismatch: {path}')
                    a = d.precip_season.transpose('member','lat','lon').values.astype(float)
                    if a.shape[0] != CYCLE.members(year):
                        raise ValueError(f'Unexpected member count: {path}')
                    if not np.isfinite(a).all() or (a<0).any():
                        raise ValueError(f'Invalid model values: {path}')
                    members[year] = d.member.values.copy()
                    models[year] = a.reshape(len(members[year]),-1)
                else:
                    if d.sizes.get('year') != 1 or int(d.year.values[0]) != year:
                        raise ValueError(f'Observation year mismatch: {path}')
                    a = d.precip_season.transpose('year','lat','lon').values.astype(float).reshape(-1)
                    if np.isinf(a).any() or (a[np.isfinite(a)]<0).any():
                        raise ValueError(f'Invalid observations: {path}')
                    observations[year] = a
    return tag,models,observations,members,lat,lon


def load_land(path,lat,lon):
    if path is None:
        return np.ones(len(lat)*len(lon),bool),{'applied':False,'note':'No explicit land-ocean mask; training-observation eligibility still applied.'}
    path = source_path(path)
    with xr.open_dataset(path) as d:
        mask = d['land_mask'].transpose('lat','lon')
        if not np.array_equal(mask.lat,lat) or not np.array_equal(mask.lon,lon):
            raise ValueError('land_mask coordinates must exactly match the common grid, including order.')
        a = mask.values
        if not np.isfinite(a).all() or not np.isin(a,[0,1]).all() or not (a==1).any():
            raise ValueError('land_mask must contain only 0=water, 1=land, with at least one land cell.')
    return (a==1).reshape(-1),dict(applied=True,path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        source_description=d.attrs.get('source','Not supplied'),land_cells=int((a==1).sum()))


def cell_area(lat,lon):
    def edges(c):
        c=np.asarray(c,float);step=np.diff(c)
        if len(c)<2 or not (step>0).all() or not np.allclose(step,step[0]):
            raise ValueError('Expected regular ascending common grid.')
        return np.r_[c[0]-step[0]/2,(c[:-1]+c[1:])/2,c[-1]+step[-1]/2]
    la,lo=np.deg2rad(edges(lat)),np.deg2rad(edges(lon))
    return (np.diff(np.sin(la))[:,None]*np.diff(lo)[None,:]).reshape(-1)


def params_dataset(params,lat,lon,attrs):
    d=xr.Dataset(coords={'lat':lat,'lon':lon},attrs=attrs)
    for k,v in params.items():
        d[k]=( ('lat','lon'),v.reshape(len(lat),len(lon)).astype('int8') if v.dtype==bool else v.reshape(len(lat),len(lon)))
        d[k].attrs['units']='1' if k in ('scale','amount_eligible','probability_eligible') else 'mm'
    return d


def probability_dataset(years,records,lat,lon,attrs):
    d=xr.Dataset(coords={'year':years,'lat':lat,'lon':lon,'category':['below','near','above']},attrs=attrs)
    for key in records[0]:
        a=np.stack([r[key] for r in records])
        if a.ndim==3:
            d[key]=( ('year','lat','lon','category'),a.reshape(len(years),len(lat),len(lon),3))
            d[key].attrs['units']='1'
        else:
            d[key]=( ('year','lat','lon'),a.reshape(len(years),len(lat),len(lon)))
    if 'observed_category' in d:
        d.observed_category.attrs.update(codes='-1: unavailable; 0: below; 1: near; 2: above')
    for key in ('q1','q2'): 
        if key in d:d[key].attrs['units']='mm'
    return d


def score_year(year,raw,corrected,obs,record,area):
    valid=np.isfinite(corrected).all(axis=0)&np.isfinite(obs)
    row={'year':year,'amount_cells':int(valid.sum())}
    if not valid.any():raise ValueError('No valid amount verification cells.')
    w=area[valid]/area[valid].sum()
    for name,m in [('raw',raw),('corrected',corrected)]:
        e=m.mean(axis=0)[valid]-obs[valid]
        row[name+'_bias_mm']=float(w@e)
        row[name+'_mae_mm']=float(w@np.abs(e))
        row[name+'_mse_mm2']=float(w@(e*e))
        row[name+'_rmse_mm']=float(np.sqrt(w@(e*e)))
    y=record['observed_category'];valid=(y>=0)&np.isfinite(record['dirichlet_probability']).all(axis=1)
    row['probability_cells']=int(valid.sum())
    if not valid.any():raise ValueError('No valid probability verification cells.')
    w=area[valid]/area[valid].sum();truth=np.eye(3)[y[valid]]
    for name in ('raw_probability','base_probability','dirichlet_probability','climatology_probability'):
        p=record[name][valid]
        row[name+'_brier_by_category']=(w@((p-truth)**2)).tolist()
        row[name+'_rps']=float(w@np.sum((np.cumsum(p,axis=1)[:,:2]-np.cumsum(truth,axis=1)[:,:2])**2,axis=1))
        row[name+'_log_loss']=float(-w@np.log(np.maximum(p[np.arange(len(p)),y[valid]],EPS)))
    return row


def summary_scores(rows):
    result={}
    for key in rows[0]:
        if key not in ('year','amount_cells','probability_cells'):
            value=np.mean([r[key] for r in rows],axis=0)
            result[key]=value.tolist()
    for name in ('raw','corrected'):
        result[name+'_rmse_mm']=float(np.sqrt(result[name+'_mse_mm2']))
    for name in ('raw_probability','base_probability','dirichlet_probability'):
        baseline=result['climatology_probability_rps']
        result[name+'_rps_skill_vs_training_climatology']=1-result[name+'_rps']/baseline if baseline>0 else None
    return result


def reliability(records,area):
    """Equal-year, area-weighted bins; descriptive only, no independent-pixel CIs."""
    result={}
    for name in ('raw_probability','base_probability','dirichlet_probability'):
        classes=[]
        for k in range(3):
            bins=[]
            for j in range(10):
                mass=pred=obs=0.;count=0
                for r in records:
                    valid=(r['observed_category']>=0)&np.isfinite(r[name]).all(axis=1)
                    w=np.where(valid,area,0);w=w/w.sum()/len(records)
                    p=r[name][:,k];chosen=valid&(p>=j/10)&((p<(j+1)/10) if j<9 else (p<=1))
                    mass+=w[chosen].sum();pred+=w[chosen]@p[chosen]
                    obs+=w[chosen]@(r['observed_category'][chosen]==k);count+=int(chosen.sum())
                bins.append(dict(lower=j/10,upper=(j+1)/10,weight=float(mass),pairs=count,
                    forecast_probability=float(pred/mass) if mass else None,
                    observed_frequency=float(obs/mass) if mass else None))
            classes.append(bins)
        result[name]=dict(category_order=['below','near','above'],bins=classes)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',default='config/project.json')
    p.add_argument('--mode',choices=['development','final'],default='development')
    p.add_argument('--land-mask',help='Optional common-grid NetCDF containing land_mask(lat,lon), 1=land/0=water.')
    args=p.parse_args();cfg=load_config(args.config)
    # Explicit fixed archive split for this project; no automatic hyperparameter tuning.
    train=list(range(1993,2017 if args.mode=='development' else 2026))
    targets=list(range(2017,2026)) if args.mode=='development' else [2026]
    obs_years=train+targets if args.mode=='development' else train
    tag,models,obs,members,lat,lon=load_inputs(cfg,train+targets,obs_years)
    land,mask_info=load_land(args.land_mask,lat,lon);area=cell_area(lat,lon)
    print('Land-ocean mask:',mask_info)
    out=ROOT/'outputs/calibration'/tag/args.mode
    fitted=ROOT/'models'/tag/args.mode
    attrs=dict(method='Pooled equal-year mean-variance correction + regularized Dirichlet probability calibration',
        training_years=','.join(map(str,train)),mode=args.mode,land_mask_json=json.dumps(mask_info),
        config_json=json.dumps(cfg),processing_utc=datetime.now(timezone.utc).isoformat(),
        category_definition='below x<q1; near q1<=x<=q2; above x>q2',
        note='No land mask unless explicitly supplied. Fixed regularization, no hyperparameter selection.')
    # Each base-probability training row is made without its own year's model or observations in fitting.
    oof=[];fold_reports=[]
    for year in train:
        other=[y for y in train if y!=year]
        pars=fit_amount([models[y] for y in other],np.stack([obs[y] for y in other]),land)
        corrected=correct_amount(models[year],pars)
        record=dict(base_probability=probabilities(corrected,pars),observed_category=labels(obs[year],pars),q1=pars['q1'],q2=pars['q2'])
        oof.append(record)
        fold_reports.append(dict(held_out_year=year,training_years=other,
            amount_cells=int(pars['amount_eligible'].sum()),probability_cells=int(pars['probability_eligible'].sum())))
        print(f'OOF {year}: trained on {len(other)} other years; {fold_reports[-1]["probability_cells"]} probability cells')
    dm=fit_dirichlet([r['base_probability'] for r in oof],[r['observed_category'] for r in oof],area)
    pars=fit_amount([models[y] for y in train],np.stack([obs[y] for y in train]),land)
    if not pars['probability_eligible'].any():raise ValueError('No eligible probability cells.')
    train_labels=np.stack([labels(obs[y],pars) for y in train])
    clim=np.stack([(train_labels==k).mean(axis=0) for k in range(3)],axis=-1)
    clim[~pars['probability_eligible']]=np.nan
    records=[];rows=[];target_qc=[]
    for year in targets:
        raw=models[year];corrected=correct_amount(raw,pars)
        base=probabilities(corrected,pars)
        record=dict(raw_probability=probabilities(raw,pars),base_probability=base,
                    dirichlet_probability=apply_dirichlet(base,dm),climatology_probability=clim)
        if year in obs:
            record['observed_category']=labels(obs[year],pars)
            rows.append(score_year(year,raw,corrected,obs[year],record,area))
        for name,a in record.items():
            if a.ndim==2:
                valid=np.isfinite(a).all(axis=1)
                if not np.allclose(a[valid].sum(axis=1),1,atol=1e-12) or (a[valid]<0).any():
                    raise ValueError('Invalid output probabilities.')
        eligible=pars['amount_eligible']
        unclipped=pars['mu_obs']+pars['scale']*(raw-pars['mu_model'])
        target_qc.append(dict(year=year,members=len(members[year]),
            fraction_corrected_values_clipped_to_zero=float((unclipped[:,eligible]<0).mean()),
            amount_cells=int(eligible.sum()),probability_cells=int(pars['probability_eligible'].sum())))
        d=xr.Dataset({'precip_corrected':(('member','lat','lon'),corrected.reshape(len(members[year]),len(lat),len(lon)))},
                     coords={'member':members[year],'lat':lat,'lon':lon},attrs=dict(attrs,target_year=year))
        d.precip_corrected.attrs.update(units='mm',long_name='Bias-corrected seasonal precipitation, clipped at zero')
        save_netcdf(d,out/f'corrected_{year}.nc')
        records.append(record)
    save_netcdf(params_dataset(pars,lat,lon,attrs),fitted/'amount_parameters.nc')
    save_json(fitted/'dirichlet_parameters.json',dict(dm,training_year_list=train,mask=mask_info))
    save_netcdf(probability_dataset(train,oof,lat,lon,attrs),out/'base_probabilities_oof.nc')
    save_netcdf(probability_dataset(targets,records,lat,lon,attrs),out/'probabilities.nc')
    report=dict(mode=args.mode,training_years=train,target_years=targets,land_mask=mask_info,
        observation_mask_note='Recomputed from training years only in every fold; not a land-ocean mask.',
        full_fit_amount_cells=int(pars['amount_eligible'].sum()),full_fit_probability_cells=int(pars['probability_eligible'].sum()),
        low_model_sd_cells=int(np.sum(pars['sd_model']<1)),folds=fold_reports,targets=target_qc,dirichlet=dm)
    if rows:
        save_json(out/'validation_metrics.json',dict(years=rows,equal_year_summary=summary_scores(rows),
            note='Area-weighted within each year; equal year weights. RPS is unnormalized sum over two boundaries. Log loss floor=1e-12. No independent-pixel confidence intervals.'))
        save_json(out/'reliability.json',reliability(records,area))
    save_json(out/'calibration_report.json',report)
    print(f'Complete: {out}')
    if args.mode=='development':print('Review validation_metrics.json before interpreting skill or doing the final refit.')


if __name__=='__main__':main()
