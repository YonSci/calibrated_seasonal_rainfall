"""Nested year-wise evaluation of shared versus regime-specific probability blends.

Does not generate or replace operational forecasts. See docs/25_REGIME_CALIBRATION.md.
"""
import argparse
import calendar
import hashlib
import json
import numpy as np
import xarray as xr
from common import ROOT,load_config,save_json,save_netcdf,source_path
from output_runs import staged_output,check_destination
from calibration_core import fit_amount,correct_amount
from compare_calibration import make_record,score
from run_calibration import load_inputs,load_land,cell_area
from verification_core import crps,weighted_mean,probability_losses
from regime_core import SETTINGS,TARGETS,REGIMES,fit_group_weights,apply_group_weights
from prepare_regimes import CACHE,RegimeCache,load_region,sha256

TRAIN=list(range(1993,2017))
METHODS=['climatology','smooth','shared_blend','independent_regime_blend','regularized_regime_blend']


def target_config(cfg,target):
    if cfg['initialization_month']!=5:raise ValueError('This experiment expects May initialization.')
    cfg=json.loads(json.dumps(cfg))
    months=TARGETS[target][0];first,last=months[0],months[-1]
    cfg['season']=dict(name=target,start=f'{first:02d}-01',end=f'{last:02d}-{calendar.monthrange(2001,last)[1]:02d}')
    return cfg


def continuous_fields(train,target,models,obs,land):
    pars=fit_amount([models[y] for y in train],np.stack([obs[y] for y in train]),land)
    corrected=correct_amount(models[target],pars)
    out={}
    for name,ensemble in [('raw',models[target]),('corrected',corrected),('climatology',np.stack([obs[y] for y in train]))]:
        err=ensemble.mean(axis=0)-obs[target]
        out[name]=dict(crps_mm=crps(ensemble,obs[target]),bias_mm=err,mse_mm2=err**2)
    return pars,out


def score_domains(pred,y,continuous,fields,area,region,target):
    probvalid=region&(y>=0)
    for p in pred.values():probvalid &= np.isfinite(p).all(axis=-1)
    amountvalid=region.copy()
    for v in continuous.values():
        for a in v.values():amountvalid &= np.isfinite(a)
    domains={'all_country':region,'seasonally_relevant':fields[target+'_relevant']&region,
             'not_seasonally_relevant':region&fields['observation_valid']&~fields[target+'_relevant']}
    domains.update({'regime_'+str(g):region&(fields['regime']==g) for g in range(-1,5)})
    result={}
    for name,domain in domains.items():
        pv=probvalid&domain;av=amountvalid&domain
        amount={}
        if av.any():
            for method,v in continuous.items():
                amount[method]={k:weighted_mean(a,area,av) for k,a in v.items()}
                amount[method]['rmse_mm']=float(np.sqrt(amount[method]['mse_mm2']))
        result[name]=dict(domain_cells=int(domain.sum()),probability_cells=int(pv.sum()),amount_cells=int(av.sum()),
                          domain_country_area_fraction=float(area[domain].sum()/area[region].sum()),
                          probability_country_area_fraction=float(area[pv].sum()/area[region].sum()),
                          amount_country_area_fraction=float(area[av].sum()/area[region].sum()),
                          probability=score(pred,y,area,pv) if pv.any() else {},amount=amount)
    return result,probvalid,amountvalid


def summarize(rows):
    result={};rng=np.random.default_rng(20261004)
    for domain in rows[0]['domains']:
        selected=[r for r in rows if r['domains'][domain]['probability']]
        out=dict(probability_years=[r['year'] for r in selected],probability={},amount={})
        if selected:
            n=len(selected);draws=rng.integers(n,size=(5000,n))
            for method in METHODS:
                metrics={k:np.mean([r['domains'][domain]['probability'][method][k] for r in selected],axis=0).tolist() for k in ['rps','brier_by_category','log_loss']}
                delta=np.array([r['domains'][domain]['probability'][method]['rps']-r['domains'][domain]['probability']['shared_blend']['rps'] for r in selected])
                metrics['rps_difference_vs_shared']=float(delta.mean());metrics['paired_year_bootstrap_95_range']=np.quantile(delta[draws].mean(axis=1),[.025,.975]).tolist()
                metrics['years_better_than_shared']=int((delta<0).sum());out['probability'][method]=metrics
            ref=out['probability']['climatology']
            for v in out['probability'].values():
                v['rpss']=1-v['rps']/ref['rps'] if ref['rps']>0 else None
                v['bss_by_category']=[1-a/b if b>0 else None for a,b in zip(v['brier_by_category'],ref['brier_by_category'])]
        selected_amount=[r for r in rows if r['domains'][domain]['amount']]
        out['amount_years']=[r['year'] for r in selected_amount]
        if selected_amount:
            for method in ['raw','corrected','climatology']:
                v={k:float(np.mean([r['domains'][domain]['amount'][method][k] for r in selected_amount])) for k in ['crps_mm','bias_mm','mse_mm2']}
                v['rmse_mm']=float(np.sqrt(v['mse_mm2']));out['amount'][method]=v
            ref=out['amount']['climatology']['crps_mm']
            for v in out['amount'].values():v['crpss']=1-v['crps_mm']/ref if ref>0 else None
        result[domain]=out
    return result


def run(cfg,cache,region,mode,land_path,out):
    targets=TRAIN if mode=='training' else list(range(2017,2026));years=sorted(set(TRAIN+targets))
    tag,models,obs,members,lat,lon=load_inputs(cfg,years,years)
    if not np.array_equal(lat,cache.lat) or not np.array_equal(lon,cache.lon):raise ValueError('Cache and forecast grid mismatch.')
    land,land_info=load_land(land_path,lat,lon);area=cell_area(lat,lon);target=cfg['season']['name']
    rows=[];saved=[];fitlog=[];fixed=None
    for year in targets:
        train=[y for y in TRAIN if y!=year] if mode=='training' else TRAIN
        if fixed is None:
            inner=[];groups=[]
            for y in train:
                subset=[z for z in train if z!=y]
                inner.append(make_record(subset,y,models,obs,land));groups.append(cache.fit(subset)['regime'])
            fitted=fit_group_weights(inner,groups,area,region)
            if mode=='operational':fixed=fitted
        else:fitted=fixed
        fields=cache.fit(train);outer=make_record(train,year,models,obs,land)
        pred,weights=apply_group_weights(outer,fields['regime'],fitted)
        pars,continuous=continuous_fields(train,year,models,obs,land)
        domains,pv,av=score_domains(pred,outer['y'],continuous,fields,area,region,target)
        if not pv.any():raise ValueError(f'{target} {year}: no common probability support inside the country.')
        rows.append(dict(year=year,training_years=train,domains=domains))
        fitlog.append(dict(target_year=year,**fitted))
        saved.append(dict(pred=pred,weights=weights,y=outer['y'],q1=outer['q1'],q2=outer['q2'],
                          regime=fields['regime'],refinement_reason=fields['refinement_reason'],raw_harmonic_class=fields['raw_harmonic_class'],
                          observation_valid=fields['observation_valid'],seasonal_relevant=fields[target+'_relevant'],
                          probability_common_support=pv,amount_common_support=av,
                          amount_eligible=pars['amount_eligible'],probability_eligible=pars['probability_eligible']))
        print(f'{tag} {mode}: completed {year}, shared lambda={fitted["shared"]:.4f}',flush=True)
    summary=summarize(rows)
    report=dict(target=target,config=cfg,mode=mode,training_period=[1993,2016],evaluation_years=targets,
                settings=SETTINGS,regime_codes=REGIMES,equal_year_summary=summary,years=rows,weights=fitlog,
                land_mask=land_info,cache_source=cache.attrs,
                code_sha256={n:sha256(ROOT/'scripts'/n) for n in ['regime_core.py','prepare_regimes.py','run_regime_calibration.py','calibration_core.py','compare_calibration.py']},
                adoption_status='Experimental comparison only; existing final forecasts unchanged.',
                validation='Nested outer/inner leave-one-year-out for training; 2017-2025 exploratory, all fits frozen on 1993-2016.',
                uncertainty='5000 paired whole-year resamples of fixed-fit annual scores. Descriptive, not selection-adjusted; no correction for serial dependence or overlapping training sets.',
                masks='Country and optional physical land are static; all observed climatologies, relevance masks, thresholds and regimes are training-fold-only. Onset detection is unavailable and not a gate.',
                metrics='Equal-year averages of area-weighted scores. RPS is sum of two cumulative squared errors. Empirical ensemble CRPS; members are not assumed iid. Regime labels may change between folds.',
                comparison_support='Identical year/cell support across probability methods; separate identical support across amount methods. No skill claim from removing cells.')
    save_json(out/'regime_comparison_summary.json',report)
    ds=xr.Dataset(coords=dict(year=targets,lat=lat,lon=lon,category=['below','near','above']),attrs=dict(mode=mode,target=target,settings_json=json.dumps(SETTINGS),note=report['validation']))
    shape=(len(targets),len(lat),len(lon))
    for method in METHODS:
        ds[method+'_probability']=(('year','lat','lon','category'),np.stack([r['pred'][method] for r in saved]).reshape(*shape,3))
    for key in ['y','q1','q2','regime','refinement_reason','raw_harmonic_class','observation_valid','seasonal_relevant','probability_common_support','amount_common_support','amount_eligible','probability_eligible']:
        a=np.stack([r[key] for r in saved]).reshape(shape)
        ds['observed_category' if key=='y' else key]=(('year','lat','lon'),a.astype('int8') if a.dtype==bool else a)
    for method in ['independent','regularized']:
        ds[method+'_lambda']=(('year','lat','lon'),np.stack([r['weights'][method] for r in saved]).reshape(shape))
    ds['shared_lambda']=('year',[f['shared'] for f in fitlog]);ds['region_mask']=(('lat','lon'),region.reshape(shape[1:]).astype('int8'))
    ds['physical_land_mask']=(('lat','lon'),land.reshape(shape[1:]).astype('int8')) if land_info['applied'] else ((),np.int8(-1))
    ds.physical_land_mask.attrs['note']='-1 scalar means not supplied; no physical mask inferred.'
    ds.regime.attrs['codes']=json.dumps(REGIMES);ds.q1.attrs['units']='mm';ds.q2.attrs['units']='mm'
    save_netcdf(ds,out/'regime_probabilities_and_weights.nc')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(11,4))
    for method in METHODS:ax.plot(targets,[r['domains']['all_country']['probability'][method]['rps'] for r in rows],label=method)
    ax.set(xlabel='Year',ylabel='RPS (lower is better)',title=f'{target}: same-support Ethiopia comparison | {mode}')
    ax.legend(fontsize=7,ncol=2);fig.tight_layout();fig.savefig(out/'annual_regime_rps.png',dpi=160);plt.close(fig)
    spatial=xr.Dataset(coords=dict(lat=lat,lon=lon));valid=ds.probability_common_support.values.astype(bool)
    for method in METHODS:
        _,rps,_=probability_losses(ds[method+'_probability'].values,ds.observed_category.values)
        count=valid.sum(axis=0);value=np.divide(np.where(valid,rps,0).sum(axis=0),count,out=np.full(count.shape,np.nan),where=count>0)
        spatial[method+'_rps']=(('lat','lon'),value)
    spatial['valid_year_count']=(('lat','lon'),valid.sum(axis=0));save_netcdf(spatial,out/'regime_spatial_scores.nc')
    v=summary['all_country']['probability']['regularized_regime_blend']
    print(f'{target}: regularized minus shared RPS={v["rps_difference_vs_shared"]:.6f}; negative favors candidate.',flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',default='config/project.json');p.add_argument('--region-mask',default='data/masks/ethiopia_common.nc');p.add_argument('--land-mask');p.add_argument('--targets',nargs='+',choices=list(TARGETS),default=['JJAS']);p.add_argument('--mode',choices=['training','operational'],default='training');p.add_argument('--regenerate',action='store_true')
    args=p.parse_args();cfg=load_config(args.config);mask=load_region(args.region_mask)
    cache=RegimeCache(CACHE/'chirps_calendar_cache.nc',mask.values==1)
    if not np.array_equal(cache.lat,mask.lat) or not np.array_equal(cache.lon,mask.lon):raise ValueError('Cache/country grid mismatch.')
    cache.attrs['cache_sha256']=sha256(CACHE/'chirps_calendar_cache.nc')
    cache.attrs['evaluation_country_mask_sha256']=sha256(source_path(args.region_mask))
    if str(source_path(cfg['chirps_file']))!=cache.attrs['source_path']:
        raise ValueError('Configured CHIRPS path differs from the cache source; rebuild with prepare_regimes.py.')
    for target in args.targets:
        out=ROOT/'outputs/regime_calibration'/f'init05_{target}'/args.mode
        check_destination(out,args.regenerate)
        with staged_output(out,args.regenerate) as stage:run(target_config(cfg,target),cache,(mask.values==1).reshape(-1),args.mode,args.land_mask,stage)
        print('Ready:',out,flush=True)


if __name__=='__main__':main()
