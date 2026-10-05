"""Compare fixed shared, independent local, and regularized local blend procedures."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import xarray as xr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from output_runs import check_destination, staged_output
from common import ROOT, load_config, source_path, save_json, save_netcdf
from compare_calibration import make_record, score
from run_calibration import load_inputs, load_land, cell_area
from verification_core import probability_losses, mean_valid

NAMES = ['climatology','smooth','shared_blend','local_blend','regularized_local_blend']
GAMMA = .05  # Fixed experimental setting, not fitted or selected on evaluation data.
MIN_PAIRS = 20
TRAIN = list(range(1993,2017))


def fit_weights(records, area):
    p=np.stack([r['s'] for r in records]); c=np.stack([r['clim'] for r in records])
    y=np.stack([r['y'] for r in records])
    valid=(y>=0)&np.isfinite(p).all(axis=-1)&np.isfinite(c).all(axis=-1)
    w=np.where(valid,area[None,:],0.)
    if (w.sum(axis=1)==0).any(): raise ValueError('Training year without valid probability pairs.')
    w=w/w.sum(axis=1,keepdims=True)/len(records)
    truth=np.eye(3)[np.maximum(y,0)]
    residual=np.cumsum(p-truth,axis=-1)[...,:2]
    direction=np.cumsum(c-p,axis=-1)[...,:2]
    a=np.where(valid,np.sum(direction**2,axis=-1),0.)
    b=np.where(valid,-np.sum(residual*direction,axis=-1),0.)
    denom=np.sum(w*a)
    shared=float(np.clip(np.sum(w*b)/denom,0,1)) if denom>1e-15 else 1.
    n=valid.sum(axis=0)
    aa=np.divide(a.sum(axis=0),n,out=np.zeros_like(area),where=n>0)
    bb=np.divide(b.sum(axis=0),n,out=np.zeros_like(area),where=n>0)
    # When forecast and climatology coincide, local weight is not identifiable.
    supported=(n>=MIN_PAIRS)&(aa>1e-15)
    local=np.full_like(area,shared); regularized=np.full_like(area,shared)
    local[supported]=np.clip(bb[supported]/aa[supported],0,1)
    regularized[supported]=np.clip((bb[supported]+GAMMA*shared)/(aa[supported]+GAMMA),0,1)
    return dict(shared_lambda=shared,local_lambda=local,regularized_lambda=regularized,
                training_pairs=n,local_supported=supported)


def apply_weights(record, weights):
    p,c=record['s'],record['clim']
    pred=dict(climatology=c,smooth=p)
    for name,key in [('shared_blend','shared_lambda'),('local_blend','local_lambda'),('regularized_local_blend','regularized_lambda')]:
        lam=np.asarray(weights[key]);lam=lam[...,None]
        pred[name]=(1-lam)*p+lam*c
    return pred


def run(models, obs, land, area, region, mode, progress=print):
    targets=TRAIN if mode=='training' else list(range(2017,2026))
    rows,records,weights=[],[],[]
    shared_fit=None
    if mode=='operational':
        inner=[make_record([z for z in TRAIN if z!=y],y,models,obs,land) for y in TRAIN]
        shared_fit=fit_weights(inner,area)
    for y in targets:
        train=[z for z in TRAIN if z!=y] if mode=='training' else TRAIN
        if shared_fit is None:
            inner=[make_record([z for z in train if z!=t],t,models,obs,land) for t in train]
            fitted=fit_weights(inner,area)
        else:fitted=shared_fit
        outer=make_record(train,y,models,obs,land)
        pred=apply_weights(outer,fitted)
        rows.append(dict(year=y,metrics=score(pred,outer['y'],area,region)))
        records.append(dict(pred=pred,y=outer['y'],q1=outer['q1'],q2=outer['q2']))
        weights.append(fitted)
        progress(f'{mode}: completed {y}')
    return targets,rows,records,weights


def summary(rows):
    rng=np.random.default_rng(20261003);ix=rng.integers(len(rows),size=(5000,len(rows)))
    out={}
    for name in NAMES:
        out[name]={k:np.mean([r['metrics'][name][k] for r in rows],axis=0).tolist()
                   for k in ['rps','log_loss','brier_by_category','mean_max_probability']}
        delta=np.array([r['metrics'][name]['rps']-r['metrics']['shared_blend']['rps'] for r in rows])
        out[name]['rps_difference_vs_shared']=float(delta.mean())
        out[name]['paired_year_bootstrap_95_range']=np.quantile(delta[ix].mean(axis=1),[.025,.975]).tolist()
        out[name]['years_better_than_shared']=int((delta<0).sum())
    for name in NAMES:
        ref=out['climatology'];out[name]['rpss']=1-out[name]['rps']/ref['rps'] if ref['rps']>0 else None
        bs=np.array(out[name]['brier_by_category']);den=np.array(ref['brier_by_category'])
        out[name]['bss_by_category']=[float(1-a/b) if b>0 else None for a,b in zip(bs,den)]
    return out


def save_outputs(out, cfg, mode, targets, rows, records, weights, area, region, lat, lon, mask_info):
    attrs=dict(config_json=json.dumps(cfg),mode=mode,gamma=GAMMA,minimum_local_pairs=MIN_PAIRS,
               note='Fixed procedures; no hyperparameter tuning. Country mask for scoring only. Gamma multiplies mean local RPS penalty.')
    report=dict(config=cfg,target_period=cfg['season'],mode=mode,training_years=TRAIN,target_years=targets,gamma=GAMMA,minimum_local_pairs=MIN_PAIRS,
        equal_year_summary=summary(rows),years=rows,mask=mask_info,
        shared_lambda_by_target={str(y):w['shared_lambda'] for y,w in zip(targets,weights)},
        note='Training mode: outer year excluded from all inner preprocessing and fitting. Operational mode: all fits use 1993-2016 only; exploratory evaluation.',
        uncertainty='5000 paired whole-year score resamples, fixed fits; descriptive, not adjusted for selection, serial dependence or overlapping training sets.',
        code_sha256={n:hashlib.sha256((Path(__file__).parent/n).read_bytes()).hexdigest() for n in ['local_blend.py','compare_calibration.py','calibration_core.py']})
    save_json(out/'local_comparison_summary.json',report)
    d=xr.Dataset(coords=dict(year=targets,lat=lat,lon=lon,category=['below','near','above']),attrs=attrs)
    shape=(len(targets),len(lat),len(lon))
    for name in NAMES:
        d[name+'_probability']=(('year','lat','lon','category'),np.stack([r['pred'][name] for r in records]).reshape(*shape,3))
    for key in ['y','q1','q2']:
        d['observed_category' if key=='y' else key]=(('year','lat','lon'),np.stack([r[key] for r in records]).reshape(shape))
    d.q1.attrs['units']='mm';d.q2.attrs['units']='mm'
    for key in ['local_lambda','regularized_lambda','training_pairs','local_supported']:
        a=np.stack([w[key] for w in weights]).reshape(shape)
        d[key]=(('year','lat','lon'),a.astype('int8') if key=='local_supported' else a)
    d['shared_lambda']=('year',[w['shared_lambda'] for w in weights])
    d['region_mask']=(('lat','lon'),region.reshape(len(lat),len(lon)).astype('int8'))
    save_netcdf(d,out/'local_probabilities_and_weights.nc')
    truth=np.stack([r['y'] for r in records]);valid=(truth>=0)&region[None,:]
    for name in NAMES:valid &= np.isfinite(np.stack([r['pred'][name] for r in records])).all(axis=-1)
    spatial={}
    for name in NAMES:
        _,rps,_=probability_losses(np.stack([r['pred'][name] for r in records]),truth)
        spatial[name]=mean_valid(np.where(valid,rps,np.nan))
    sd=xr.Dataset(coords=dict(lat=lat,lon=lon),attrs=attrs)
    for name,v in spatial.items():sd[name+'_rps']=(('lat','lon'),v.reshape(len(lat),len(lon)))
    sd['valid_year_count']=(('lat','lon'),valid.sum(axis=0).reshape(len(lat),len(lon)))
    save_netcdf(sd,out/'local_spatial_scores.nc')
    fig,ax=plt.subplots(figsize=(11,4))
    for name in NAMES:ax.plot(targets,[r['metrics'][name]['rps'] for r in rows],label=name)
    ax.set(xlabel='Target year',ylabel='RPS (lower is better)',title=f"{cfg['season']['name']} | {mode} | region scores")
    ax.legend(fontsize=7,ncol=3);fig.tight_layout();fig.savefig(out/'annual_local_rps.png',dpi=160);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(10,5))
    for ax,key in zip(axes,['local_lambda','regularized_lambda']):
        field=np.mean([w[key] for w in weights],axis=0)
        field=np.where(region&(valid.sum(axis=0)>0),field,np.nan).reshape(len(lat),len(lon))
        im=ax.pcolormesh(lon,lat,field,vmin=0,vmax=1,cmap='viridis',shading='auto');fig.colorbar(im,ax=ax,shrink=.7)
        ax.set(title=key,xlabel='Longitude',ylabel='Latitude',aspect='equal')
    fig.suptitle('Climatology weight | fold mean in training mode; fixed fit in operational mode')
    fig.tight_layout();fig.savefig(out/'local_weights.png',dpi=160);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(10,5))
    for ax,name in zip(axes,['local_blend','regularized_local_blend']):
        field=(spatial[name]-spatial['shared_blend']).reshape(len(lat),len(lon))
        im=ax.pcolormesh(lon,lat,field,vmin=-.1,vmax=.1,cmap='RdBu_r',shading='auto');fig.colorbar(im,ax=ax,shrink=.7,extend='both')
        ax.set(title=name+' minus shared RPS',xlabel='Longitude',ylabel='Latitude',aspect='equal')
    fig.suptitle('Negative / blue favors local method | region masked; no boundary outline')
    fig.tight_layout();fig.savefig(out/'local_skill_difference.png',dpi=160);plt.close(fig)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',default='config/project.json')
    p.add_argument('--region-mask',required=True);p.add_argument('--land-mask');p.add_argument('--mode',choices=['training','operational'],default='training')
    p.add_argument('--regenerate',action='store_true',help='Rebuild outputs, preserving existing results in a dated backup.')
    args=p.parse_args();cfg=load_config(args.config)
    years=TRAIN if args.mode=='training' else TRAIN+list(range(2017,2026))
    tag,models,obs,members,lat,lon=load_inputs(cfg,years,years)
    land,land_info=load_land(args.land_mask,lat,lon);path=source_path(args.region_mask)
    with xr.open_dataset(path) as d:
        a=d.region_mask.transpose('lat','lon')
        if not np.array_equal(a.lat,lat) or not np.array_equal(a.lon,lon):raise ValueError('Region grid mismatch.')
        if not np.isin(a.values,[0,1]).all() or not (a.values==1).any():raise ValueError('Expected binary nonempty region mask.')
        region=(a.values==1).reshape(-1)
    out=ROOT/'outputs/local_calibration'/tag/args.mode
    check_destination(out,args.regenerate)
    area=cell_area(lat,lon)
    targets,rows,records,weights=run(models,obs,land,area,region,args.mode,lambda s:print(s,flush=True))
    mask_info=dict(land=land_info,region_path=str(path),region_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),use='region for evaluation only')
    with staged_output(out,args.regenerate) as staged:
        save_outputs(staged,cfg,args.mode,targets,rows,records,weights,area,region,lat,lon,mask_info)
    for name,v in summary(rows).items():print(f"{name:25s} RPS={v['rps']:.5f} RPSS={v['rpss']:.4f}")
    print('Complete:',out)


if __name__=='__main__':main()
