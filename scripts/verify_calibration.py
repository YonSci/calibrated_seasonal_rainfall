"""Read-only verification of the existing development run; no parameter tuning/refitting."""
import argparse
import json
import hashlib
import re
from pathlib import Path
import numpy as np
import xarray as xr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from common import ROOT,load_config,save_json,save_netcdf,source_path
from run_calibration import load_inputs,cell_area,reliability
from calibration_core import probabilities,apply_dirichlet
from verification_core import (crps,weighted_mean,mean_valid,temporal_correlation,roc_curve,
                               probability_losses,summarize_annual,bootstrap_years)

NAMES=('raw','base','dirichlet','climatology')
VARS=('raw_probability','base_probability','dirichlet_probability','climatology_probability')
CATEGORIES=('below','near','above')


def clean(value):
    if isinstance(value,dict):return {k:clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [clean(v) for v in value]
    if isinstance(value,np.ndarray):return clean(value.tolist())
    if isinstance(value,(float,np.floating)):return float(value) if np.isfinite(value) else None
    if isinstance(value,np.integer):return int(value)
    return value


def region_mask(path,lat,lon):
    if path is None:return np.ones(len(lat)*len(lon),bool),{'applied':False,'domain':'full eligible rectangle; not Ethiopia-only'}
    path=source_path(path)
    with xr.open_dataset(path) as d:
        a=d.region_mask.transpose('lat','lon')
        if not np.array_equal(a.lat,lat) or not np.array_equal(a.lon,lon) or not np.isin(a,[0,1]).all():
            raise ValueError('region_mask must be binary and exactly on the common grid.')
        mask=a.values.astype(bool).reshape(-1)
    if not mask.any():raise ValueError('Region mask selects no cells.')
    return mask,dict(applied=True,path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def savefig(fig,path):
    fig.savefig(path,dpi=160,bbox_inches='tight');plt.close(fig)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',default='config/project.json')
    p.add_argument('--region-mask',help='Optional NetCDF region_mask(lat,lon), 1=inside, 0=outside.')
    p.add_argument('--region-name',default='full_domain')
    p.add_argument('--bootstrap',type=int,default=5000)
    p.add_argument('--subsamples',type=int,default=100)
    p.add_argument('--seed',type=int,default=20261003)
    args=p.parse_args()
    if args.bootstrap<100 or args.subsamples<2:raise ValueError('Use at least 100 bootstrap draws and 2 subsamples.')
    if not re.fullmatch(r'[A-Za-z0-9_-]+',args.region_name):raise ValueError('Use a simple region name: letters, numbers, underscore or hyphen.')
    if args.region_mask and args.region_name=='full_domain':raise ValueError('Give --region-name when supplying a regional mask.')
    if not args.region_mask and args.region_name!='full_domain':raise ValueError('A regional label requires --region-mask.')
    cfg=load_config(args.config);train=list(range(1993,2017));years=list(range(2017,2026))
    tag,models,obs,members,lat,lon=load_inputs(cfg,train+years,train+years)
    source=ROOT/'outputs/calibration'/tag/'development';fitted=ROOT/'models'/tag/'development'
    report=json.loads((source/'calibration_report.json').read_text())
    dm=json.loads((fitted/'dirichlet_parameters.json').read_text())
    if report['training_years']!=train or report['target_years']!=years or dm['training_year_list']!=train:
        raise ValueError('Expected frozen 1993-2016 development fit and 2017-2025 evaluation.')
    with xr.open_dataset(fitted/'amount_parameters.nc') as d:
        if not np.array_equal(d.lat,lat) or not np.array_equal(d.lon,lon):raise ValueError('Parameter grid mismatch.')
        pars={k:d[k].values.reshape(-1) for k in d.data_vars}
    for k in ('amount_eligible','probability_eligible'):pars[k]=pars[k].astype(bool)
    region,region_info=region_mask(args.region_mask,lat,lon);area=cell_area(lat,lon)
    weights=area*region
    out=ROOT/'outputs/verification'/tag/args.region_name;out.mkdir(parents=True,exist_ok=True)
    figures=out/'figures';figures.mkdir(exist_ok=True)
    with xr.open_dataset(source/'probabilities.nc') as d:
        if list(d.year.values)!=years or not np.array_equal(d.lat,lat) or not np.array_equal(d.lon,lon):raise ValueError('Probability coordinates mismatch.')
        if list(d.category.values)!=list(CATEGORIES):raise ValueError('Category order mismatch.')
        probs={name:d[v].transpose('year','lat','lon','category').values.reshape(len(years),-1,3) for name,v in zip(NAMES,VARS)}
        labels=d.observed_category.values.reshape(len(years),-1).copy()
    labels[:,~region]=-1
    for name in NAMES:probs[name][:,~region]=np.nan
    observations=np.stack([obs[y] for y in years]);historical=np.stack([obs[y] for y in train])
    clim=pars['mu_obs'];raw_means=[];corrected_means=[];raw_arrays=[];corrected_arrays=[]
    fields={};annual=[];records=[]
    for i,year in enumerate(years):
        print(f'Verifying {year}',flush=True)
        with xr.open_dataset(source/f'corrected_{year}.nc') as d:
            if not np.array_equal(d.member,members[year]) or not np.array_equal(d.lat,lat) or not np.array_equal(d.lon,lon):raise ValueError('Corrected amount coordinate mismatch.')
            corr=d.precip_corrected.values.reshape(len(members[year]),-1).astype(float)
        raw=models[year];o=obs[year]
        valid=region&pars['amount_eligible']&np.isfinite(o)&np.isfinite(corr).all(axis=0)
        if not valid.any() or not (labels[i]>=0).any():raise ValueError('No verification data inside region.')
        raw_arrays.append(raw);corrected_arrays.append(corr)
        raw_means.append(np.where(valid,raw.mean(axis=0),np.nan));corrected_means.append(np.where(valid,corr.mean(axis=0),np.nan))
        row={'year':year}
        def record(key,a,validity=valid):
            a=np.where(validity,a,np.nan);fields.setdefault(key,[]).append(a)
            row[key]=weighted_mean(a,weights)
        for name,a in [('raw',raw),('corrected',corr)]:
            e=a.mean(axis=0)-o
            record(name+'_bias_mm',e);record(name+'_mae_mm',np.abs(e));record(name+'_mse_mm2',e*e)
            record(name+'_crps_mm',crps(a,o));record(name+'_fair_crps_mm',crps(a,o,True))
        e=clim-o
        record('climatology_bias_mm',e);record('climatology_mae_mm',np.abs(e));record('climatology_mse_mm2',e*e)
        record('climatology_crps_mm',crps(historical,o))
        # Fraction clipped before writing corrected amounts, reconstructed with the frozen parameters.
        before=pars['mu_obs']+pars['scale']*(raw-pars['mu_model'])
        record('clipped_fraction',(before<0).mean(axis=0))
        pv=labels[i]>=0
        for name in NAMES:
            bs,rps,ll=probability_losses(probs[name][i],labels[i])
            for k,category in enumerate(CATEGORIES):record(name+'_bs_'+category,bs[:,k],pv)
            record(name+'_rps',rps,pv);record(name+'_log_loss',ll,pv)
        annual.append(row)
        records.append(dict(zip(VARS,[probs[name][i] for name in NAMES]),observed_category=labels[i]))
    summary=summarize_annual(annual)
    print('Bootstrapping whole evaluation years...',flush=True)
    intervals=bootstrap_years(annual,args.bootstrap,args.seed)
    save_json(out/'verification_summary.json',clean(dict(region=region_info,original_land_mask=report['land_mask'],
        evaluation_years=years,annual=annual,summary=summary,year_bootstrap_95_percent=intervals,
        bootstrap_draws=args.bootstrap,seed=args.seed,
        uncertainty_note='Paired iid resampling of 9 whole years; preserves within-year spatial/member dependence. Does not model interannual dependence or fitting uncertainty.')))

    # Spatial maps: temporal means and ratios of means, never spatially averaged skill ratios.
    maps=xr.Dataset(coords={'lat':lat,'lon':lon},attrs={'region':json.dumps(region_info),'evaluation_years':'2017-2025',
        'note':'Cell-level statistics from only nine seasons. No significance claims; grid cells are dependent.'})
    spatial={k:mean_valid(np.stack(v)) for k,v in fields.items()}
    for name in ('raw','corrected'):
        for score,ref in [('mse_mm2','climatology_mse_mm2'),('crps_mm','climatology_crps_mm')]:
            den=spatial[ref];spatial[name+'_'+score+'_skill']=np.divide(den-spatial[name+'_'+score],den,out=np.full_like(den,np.nan),where=den>0)
    for name in ('raw','base','dirichlet'):
        for score in ['rps']+['bs_'+c for c in CATEGORIES]:
            den=spatial['climatology_'+score]
            spatial[name+'_'+score+'_skill']=np.divide(den-spatial[name+'_'+score],den,out=np.full_like(den,np.nan),where=den>0)
    # Both forecast and observed anomalies use the frozen training-observed climatology.
    oa=observations-clim
    for name,f in [('raw',np.stack(raw_means)),('corrected',np.stack(corrected_means))]:
        spatial[name+'_temporal_anomaly_correlation']=temporal_correlation(f-clim,oa)
    for k,a in spatial.items():maps[k]=(('lat','lon'),a.reshape(len(lat),len(lon)))
    maps['amount_verification_year_count']=(('lat','lon'),np.isfinite(np.stack(corrected_means)).sum(axis=0).reshape(len(lat),len(lon)))
    save_netcdf(maps,out/'spatial_verification.nc')
    keys=['corrected_mse_mm2_skill','corrected_crps_mm_skill','base_rps_skill','dirichlet_rps_skill','corrected_temporal_anomaly_correlation','clipped_fraction']
    fig,axes=plt.subplots(2,3,figsize=(14,8),constrained_layout=True)
    for ax,key in zip(axes.flat,keys):
        scale=dict(cmap='viridis',vmin=0,vmax=1) if key=='clipped_fraction' else dict(cmap='RdBu',vmin=-1,vmax=1)
        im=ax.pcolormesh(lon,lat,maps[key].values,shading='auto',**scale);ax.set_title(key.replace('_',' '),fontsize=9)
        ax.set_xlabel('Longitude');ax.set_ylabel('Latitude');fig.colorbar(im,ax=ax,shrink=.8)
    fig.suptitle(f'2017–2025: {args.region_name} (no country boundaries supplied)')
    savefig(fig,figures/'spatial_diagnostics.png')

    # Regional anomaly time series; a zero-anomaly line is the climatology forecast.
    anomaly={name:[] for name in ('raw','corrected','observed')}
    for i in range(len(years)):
        valid=np.isfinite(corrected_means[i])
        for name,a in [('raw',raw_means[i]-clim),('corrected',corrected_means[i]-clim),('observed',oa[i])]:
            anomaly[name].append(weighted_mean(a,weights,valid))
    save_json(out/'regional_anomalies.json',clean(dict(years=years,anomalies_mm=anomaly,baseline='CHIRPS 1993-2016 mean at each cell')))
    fig,ax=plt.subplots(figsize=(10,4))
    for name,a in anomaly.items():ax.plot(years,a,'o-',label=name)
    ax.axhline(0,color='grey',ls='--',label='climatology forecast');ax.legend();ax.set_ylabel('Seasonal rainfall anomaly (mm)');ax.set_title(args.region_name+' — area-weighted anomalies')
    savefig(fig,figures/'regional_anomalies.png')

    # Reliability and weighted probability histograms (not rank histograms).
    rel=reliability(records,weights);save_json(out/'reliability_bins.json',clean(rel))
    fig,axes=plt.subplots(2,3,figsize=(13,8),constrained_layout=True)
    colors={'raw':'#999999','base':'#2878b5','dirichlet':'#d65f27'}
    for k,category in enumerate(CATEGORIES):
        ax=axes[0,k];ax.plot([0,1],[0,1],'k--',lw=1)
        for name,v in zip(NAMES[:3],VARS[:3]):
            bins=rel[v]['bins'][k];used=[b for b in bins if b['weight']>0]
            ax.plot([b['forecast_probability'] for b in used],[b['observed_frequency'] for b in used],'o-',color=colors[name],label=name)
            axes[1,k].stairs([b['weight'] for b in bins],np.linspace(0,1,11),color=colors[name],label=name)
        ax.set(xlim=(0,1),ylim=(0,1),xlabel='Forecast probability',ylabel='Observed frequency',title=category)
        axes[1,k].set(xlim=(0,1),xlabel='Forecast probability',ylabel='Weighted fraction of cases')
    axes[0,0].legend();axes[1,0].legend();fig.suptitle('Reliability (top) and probability histograms (bottom) — '+args.region_name)
    savefig(fig,figures/'reliability_and_histograms.png')

    # Pooled ROC per category with equal-year and area weights, exact handling of ties.
    case_weights=[]
    for i in range(len(years)):
        w=np.where(labels[i]>=0,weights,0);case_weights.append(w/w.sum()/len(years))
    case_weights=np.stack(case_weights);auc={}
    fig,axes=plt.subplots(1,3,figsize=(13,4),constrained_layout=True)
    for k,category in enumerate(CATEGORIES):
        axes[k].plot([0,1],[0,1],'k--',lw=1)
        for name in NAMES[:3]:
            curve=roc_curve(probs[name][...,k].ravel(),(labels==k).ravel(),case_weights.ravel())
            auc.setdefault(name,{})[category]=None if curve is None else curve[2]
            if curve is not None:
                fpr,tpr,a=curve;axes[k].plot(fpr,tpr,color=colors[name],label=f'{name}: {a:.3f}')
        axes[k].set(xlim=(0,1),ylim=(0,1),xlabel='False alarm rate',ylabel='Hit rate',title=category);axes[k].legend(fontsize=8)
    savefig(fig,figures/'roc_curves.png');save_json(out/'roc_auc.json',auc)

    # Training diagnostic ONLY: applying a calibrator to its own training pairs is in-sample for that stage.
    with xr.open_dataset(source/'base_probabilities_oof.nc') as d:
        if list(d.year.values)!=train or not np.array_equal(d.lat,lat) or not np.array_equal(d.lon,lon):raise ValueError('OOF grid/year mismatch.')
        op=d.base_probability.values.reshape(len(train),-1,3).copy();oy=d.observed_category.values.reshape(len(train),-1).copy()
    op[:,~region]=np.nan;oy[:,~region]=-1
    training={}
    for name,a in [('base_oof',op),('dirichlet_in_sample',apply_dirichlet(op,dm))]:
        year_stats=[]
        for i in range(len(train)):
            valid=(oy[i]>=0)&np.isfinite(a[i]).all(axis=1)
            if not valid.any():continue
            bs,rps,ll=probability_losses(a[i],oy[i]);q=a[i]
            year_stats.append(dict(rps=weighted_mean(rps,weights),log_loss=weighted_mean(ll,weights),
                mean_max_probability=weighted_mean(np.max(q,axis=1),weights,valid),
                entropy=weighted_mean(-np.sum(q*np.log(np.maximum(q,1e-12)),axis=1),weights,valid),
                fraction_cases_with_any_zero=weighted_mean(np.any(q==0,axis=1).astype(float),weights,valid)))
        training[name]={k:float(np.mean([r[k] for r in year_stats])) for k in year_stats[0]} if year_stats else None
    save_json(out/'training_compression_diagnostics.json',clean(dict(statistics=training,A=dm['A'],b=dm['b'],
        warning='Dirichlet results here are IN-SAMPLE for the calibrator, not independent skill. No tuning performed. Base probabilities are year-withheld.')))

    # Paired 25-of-51 member sensitivity, no replacement, one subset shared by all cells in a year.
    print(f'Comparing 51 members with {args.subsamples} repeated 25-member subsets...',flush=True)
    rng=np.random.default_rng(args.seed+1);experiments=[]
    for repeat in range(args.subsamples):
        scores=[]
        for i,year in enumerate(years):
            idx=rng.choice(len(members[year]),25,replace=False)
            a=raw_arrays[i][idx];b=corrected_arrays[i][idx];y=labels[i]
            row={}
            for name,m in [('raw',a),('base',b)]:
                q=probabilities(m,pars);q[~region]=np.nan
                _,rps,ll=probability_losses(q,y);row[name+'_rps']=weighted_mean(rps,weights);row[name+'_log_loss']=weighted_mean(ll,weights)
                if name=='base':
                    _,rps,ll=probability_losses(apply_dirichlet(q,dm),y)
                    row['dirichlet_rps']=weighted_mean(rps,weights);row['dirichlet_log_loss']=weighted_mean(ll,weights)
            valid=np.isfinite(corrected_means[i])
            for name,m in [('raw',a),('corrected',b)]:
                row[name+'_crps_mm']=weighted_mean(crps(m,obs[year]),weights,valid)
                row[name+'_fair_crps_mm']=weighted_mean(crps(m,obs[year],True),weights,valid)
                row[name+'_mse_mm2']=weighted_mean((m.mean(axis=0)-obs[year])**2,weights,valid)
            scores.append(row)
        experiments.append({k:float(np.mean([s[k] for s in scores])) for k in scores[0]})
    comparison={}
    for key in experiments[0]:
        a=np.array([e[key] for e in experiments]);full=summary[key]
        comparison[key]=dict(full_51=full,subset_25_mean=float(a.mean()),subset_25_p2_5=float(np.quantile(a,.025)),
            subset_25_p97_5=float(np.quantile(a,.975)),subset_minus_full_mean=float(a.mean()-full))
    save_json(out/'member_count_sensitivity.json',clean(dict(repeats=args.subsamples,subset_size=25,comparison=comparison,
        note='Frozen amount parameters, thresholds and Dirichlet matrix. Subset variation is Monte Carlo variation, not confidence across independent seasons. Subsampling does not correct model-system changes.')))
    fig,ax=plt.subplots(figsize=(8,4))
    for j,name in enumerate(('raw','base','dirichlet')):
        c=comparison[name+'_rps'];ax.plot(j-.1,c['full_51'],'o',color='#2878b5',label='all 51' if j==0 else None)
        ax.vlines(j+.1,c['subset_25_p2_5'],c['subset_25_p97_5'],color='#d65f27')
        ax.plot(j+.1,c['subset_25_mean'],'s',color='#d65f27',label='25-member subsets: mean and 95% range' if j==0 else None)
    ax.set_xticks(range(3),['raw','base','Dirichlet']);ax.set_ylabel('RPS (lower is better)');ax.legend(fontsize=8)
    savefig(fig,figures/'member_count_sensitivity.png')
    print(f'Complete: {out}',flush=True)


if __name__=='__main__':main()
