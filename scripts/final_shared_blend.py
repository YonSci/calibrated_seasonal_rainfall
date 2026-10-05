"""Final shared-blend refit on the cycle reference period; May-initialized forecast for the cycle year.

Cycle settings come from cycle.py (default config/operational.json: 1993-2025 -> 2026).
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import xarray as xr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from common import ROOT, load_config, source_path, save_json, save_netcdf
from calibration_core import fit_amount, correct_amount, probabilities, labels
from compare_calibration import make_record, smooth
from local_blend import fit_weights
from run_calibration import load_inputs, load_land, cell_area, params_dataset
from output_runs import check_destination, staged_output
from cycle import CYCLE

TRAIN=CYCLE.reference_years
YEAR=CYCLE.year
TARGETS=['JJAS','Jun','Jul','Aug','Sep']


def fit_final(models, observations, land, area, progress=print):
    """Target forecasts and observations never enter any parameter estimation."""
    records=[]
    for y in TRAIN:
        records.append(make_record([z for z in TRAIN if z!=y],y,models,observations,land))
        progress(f'OOF training {y}: {len(models[y])} members')
    lam=fit_weights(records,area)['shared_lambda']
    pars=fit_amount([models[y] for y in TRAIN],np.stack([observations[y] for y in TRAIN]),land)
    categories=np.stack([labels(observations[y],pars) for y in TRAIN])
    clim=np.stack([(categories==k).mean(axis=0) for k in range(3)],axis=-1)
    clim[~pars['probability_eligible']]=np.nan
    return pars,clim,lam


def forecast(model,pars,clim,lam):
    corrected=correct_amount(model,pars)
    base=probabilities(corrected,pars)
    smoothed=smooth(base,len(model))
    blended=(1-lam)*smoothed+lam*clim
    for p in [base,smoothed,clim,blended]:
        valid=np.isfinite(p).all(axis=1)
        if not valid.any() or (p[valid]<0).any() or not np.allclose(p[valid].sum(axis=1),1,atol=1e-12):
            raise ValueError('Invalid or empty probability output.')
    return corrected,dict(base_probability=base,smoothed_probability=smoothed,
                          climatology_probability=clim,blend_probability=blended)


def load_region(path,lat,lon):
    path=source_path(path)
    with xr.open_dataset(path) as d:
        a=d.region_mask.transpose('lat','lon')
        if not np.array_equal(a.lat,lat) or not np.array_equal(a.lon,lon):raise ValueError('Region grid mismatch.')
        if not np.isin(a.values,[0,1]).all() or not (a.values==1).any():raise ValueError('Expected nonempty binary region mask.')
        region=a.values.reshape(-1)==1
    return region,dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                       use='display and regional summaries only; calibration fit uses common domain')


def write_result(out,cfg,models,members,lat,lon,pars,clim,lam,region,area,land_info,region_info):
    corrected,prob=forecast(models[YEAR],pars,clim,lam)
    shape=(len(lat),len(lon));eligible=pars['probability_eligible']&region
    if not eligible.any():raise ValueError('No eligible probability cells in region.')
    attrs=dict(config_json=json.dumps(cfg),training_years=CYCLE.reference_label,target_year=YEAR,
        target_period=json.dumps(cfg['season']),initialization_month=cfg['initialization_month'],
        method='equal-year mean-variance rainfall correction; alpha=0.5 count smoothing; shared climatology blend',
        climatology_weight=float(lam),processing_utc=datetime.now(timezone.utc).isoformat(),
        status=f'Retrospective reconstruction of {CYCLE.init_month_name}-initialized {YEAR} forecast; no {YEAR} observations used',
        mask_json=json.dumps(dict(land=land_info,region=region_info)))
    d=xr.Dataset(coords=dict(member=members[YEAR],lat=lat,lon=lon,category=['below','near','above']),attrs=attrs)
    d['precip_corrected']=(('member','lat','lon'),corrected.reshape(len(members[YEAR]),*shape))
    d.precip_corrected.attrs.update(units='mm',note='Amount correction only; probability blending does not modify these members.')
    d['corrected_ensemble_mean']=(('lat','lon'),corrected.mean(axis=0).reshape(shape))
    d['observed_training_mean']=(('lat','lon'),pars['mu_obs'].reshape(shape))
    d['corrected_mean_anomaly']=(('lat','lon'),(corrected.mean(axis=0)-pars['mu_obs']).reshape(shape))
    for n in ['corrected_ensemble_mean','observed_training_mean','corrected_mean_anomaly']:d[n].attrs['units']='mm'
    for name,p in prob.items():
        d[name]=(('lat','lon','category'),p.reshape(*shape,3));d[name].attrs['units']='1'
    for key in ['q1','q2']:
        d[key]=(('lat','lon'),pars[key].reshape(shape));d[key].attrs['units']='mm'
    d['region_mask']=(('lat','lon'),region.reshape(shape).astype('int8'))
    for key in ['amount_eligible','probability_eligible']:d[key]=(('lat','lon'),pars[key].reshape(shape).astype('int8'))
    save_netcdf(d,out/f'forecast_{YEAR}.nc')
    save_netcdf(params_dataset(pars,lat,lon,attrs),out/'amount_parameters.nc')
    save_json(out/'blend_parameters.json',dict(training_years=TRAIN,climatology_weight=lam,forecast_weight=1-lam,
        alpha_per_category=.5,category_order=['below','near','above'],target_period=cfg['season'],
        weighting='Each year equal; spherical area within each year; actual member count for smoothing',
        note='Shared blend only. No local weight or Dirichlet mapping used in final product.'))
    w=area[eligible]/area[eligible].sum()
    before=pars['mu_obs']+pars['scale']*(models[YEAR]-pars['mu_model'])
    report=dict(target_period=cfg['season'],training_years=TRAIN,target_year=YEAR,
        target_members=len(members[YEAR]),training_members={str(y):len(members[y]) for y in TRAIN},
        climatology_weight=lam,forecast_weight=1-lam,land_mask=land_info,region_mask=region_info,
        region_probability_cells=int(eligible.sum()),region_amount_cells=int((region&pars['amount_eligible']).sum()),
        area_mean_gridcell_probabilities=(w@prob['blend_probability'][eligible]).tolist(),
        probability_summary_note='Spatial average of grid-cell probabilities, not probabilities for country-mean rainfall.',
        maximum_probability_sum_error=float(np.max(np.abs(prob['blend_probability'][eligible].sum(axis=1)-1))),
        fraction_corrected_member_cell_values_clipped=float((before[:,pars['amount_eligible']]<0).mean()),
        verification=f'No {YEAR} observations available in supplied archive; no final-fit skill estimated.',
        code_sha256={n:hashlib.sha256((Path(__file__).parent/n).read_bytes()).hexdigest() for n in ['final_shared_blend.py','calibration_core.py','compare_calibration.py','local_blend.py']})
    save_json(out/'final_report.json',report)
    fig,axes=plt.subplots(1,3,figsize=(13,5))
    for k,ax in enumerate(axes):
        field=np.where(eligible,prob['blend_probability'][:,k]*100,np.nan).reshape(shape)
        im=ax.pcolormesh(lon,lat,field,vmin=0,vmax=100,cmap='viridis',shading='auto')
        ax.set(title=['Below normal','Near normal','Above normal'][k],xlabel='Longitude',ylabel='Latitude',aspect='equal')
        fig.colorbar(im,ax=ax,shrink=.7,label='Probability (%)')
    fig.suptitle(f"{CYCLE.target_label(cfg['season']['name'])} | {CYCLE.init_month_name} initialization | shared blend reconstruction")
    fig.tight_layout();fig.savefig(out/f'probabilities_{YEAR}.png',dpi=180);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,5))
    valid=region&pars['amount_eligible'];mean=corrected.mean(axis=0);anomaly=mean-pars['mu_obs']
    for ax,value,title,cmap in zip(axes,[mean,anomaly],['Amount-corrected ensemble mean (mm)',f'Mean anomaly vs {CYCLE.reference_label} (mm)'],['YlGnBu','BrBG']):
        field=np.where(valid,value,np.nan).reshape(shape)
        options={}
        if cmap=='BrBG':
            limit=max(float(np.nanmax(np.abs(field))),1.);options=dict(vmin=-limit,vmax=limit)
        im=ax.pcolormesh(lon,lat,field,cmap=cmap,shading='auto',**options)
        ax.set(title=title,xlabel='Longitude',ylabel='Latitude',aspect='equal');fig.colorbar(im,ax=ax,shrink=.7)
    fig.suptitle(f"{CYCLE.target_label(cfg['season']['name'])} | rainfall correction only; separate from probability blending")
    fig.tight_layout();fig.savefig(out/f'rainfall_{YEAR}.png',dpi=180);plt.close(fig)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',default=CYCLE.raw.get('project_config','config/project.json'))
    p.add_argument('--targets',nargs='+',choices=list(CYCLE.targets),default=list(CYCLE.targets))
    p.add_argument('--region-mask',default='data/masks/ethiopia_common.nc');p.add_argument('--land-mask');p.add_argument('--regenerate',action='store_true')
    p.add_argument('--output-root',default=None,help='Default: forecast_root of the cycle (outputs/final_shared_blend)')
    args=p.parse_args();base=load_config(args.config)
    out_root=source_path(args.output_root) if args.output_root else CYCLE.root('forecast_root','outputs/final_shared_blend')
    if base['initialization_month']!=CYCLE.init_month or base['season']!=CYCLE.project['season']:
        raise ValueError('Project configuration does not match the selected cycle (initialization month or season).')
    from run_monthly import monthly_config
    import calendar
    season=base['season']['name']
    configs={target:base if target==season else monthly_config(base,list(calendar.month_abbr).index(target)) for target in args.targets}
    for target in configs:check_destination(CYCLE.forecast_dir(out_root,target),args.regenerate)
    reports=[]
    for target,cfg in configs.items():
        tag,models,obs,members,lat,lon=load_inputs(cfg,TRAIN+[YEAR],TRAIN)
        land,land_info=load_land(args.land_mask,lat,lon);region,region_info=load_region(args.region_mask,lat,lon);area=cell_area(lat,lon)
        print('Final target:',target,flush=True)
        pars,clim,lam=fit_final(models,obs,land,area,lambda s:print(s,flush=True))
        out=CYCLE.forecast_dir(out_root,target)
        with staged_output(out,args.regenerate) as stage:
            report=write_result(stage,cfg,models,members,lat,lon,pars,clim,lam,region,area,land_info,region_info)
        reports.append(report);print('Saved:',out,flush=True)
    save_json(out_root/f'final_reports_{YEAR}.json',dict(targets_in_this_run=list(configs),reports=reports,
        note='Contains only targets processed in this invocation. Monthly and seasonal products fitted separately.'))


if __name__=='__main__':main()
