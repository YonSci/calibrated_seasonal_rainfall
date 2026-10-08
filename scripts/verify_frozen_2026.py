"""Score frozen cycle-year forecasts against complete CHIRPS v2 observations; no fitting (cycle.py)."""
import argparse,sys
import numpy as np
import xarray as xr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap,BoundaryNorm
from verify2026_common import *
from verify2026_outputs import staged_output
from verify2026_math import crps,probability_losses
from cycle import CYCLE, YEAR, REF, REF_DASH, REF_YEARS, MEMBERS, REGIME, REGIME_YEARS, OVERLAP_YEAR, EVALUATION_STUDY


def category(x,q1,q2):return np.where(x<q1,0,np.where(x>q2,2,1))

def load_reference(folder,f,target):
    arrays=[];hashes={}
    for year in REF_YEARS:
        p=folder/f'chirps_{year}_common.nc'
        with xr.open_dataset(p) as d:
            same_grid(d,f)
            if d.precip_season.attrs.get('units')!='mm' or d.sizes.get('year')!=1 or int(d.year.values[0])!=year:raise ValueError('Historical observation year/units mismatch: '+str(p))
            cfg=__import__('json').loads(d.attrs['config_json'])
            if cfg['season']!={'name':target,'start':PERIODS[target][0],'end':PERIODS[target][1]}:raise ValueError('Historical season mismatch')
            arrays.append(d.precip_season.transpose('year','lat','lon').values[0].astype(float))
        hashes[str(p)]=sha(p)
    h=np.stack(arrays);eligible=f.amount_eligible.values==1;pv=f.probability_eligible.values==1
    if not np.isfinite(h[:,eligible]).all() or (h[:,eligible]<0).any():raise ValueError('Historical observations incomplete in frozen eligible cells')
    if not np.allclose(h[:,eligible].mean(0),f.observed_training_mean.values[eligible],atol=.001,rtol=1e-6):raise ValueError('Historical observations do not reproduce frozen reference mean')
    q=np.quantile(h[:,eligible],[1/3,2/3],axis=0)
    if not np.allclose(q,np.stack([f.q1.values[eligible],f.q2.values[eligible]]),atol=.001,rtol=1e-6):raise ValueError('Historical observations do not reproduce frozen thresholds')
    y=category(h,f.q1.values,f.q2.values)
    p=np.stack([(y==k).mean(0) for k in range(3)],-1)
    if not np.allclose(p[pv],f.climatology_probability.values[pv],atol=1e-6,rtol=0):raise ValueError('Historical category counts do not reproduce frozen climatology probabilities')
    return h,hashes

def calculate(f,raw,history,obs):
    """Common area-weighted support for each family; single-year descriptive scores."""
    region=f.region_mask.values==1;av=region&(f.amount_eligible.values==1)&np.isfinite(obs)
    av &= np.isfinite(raw).all(0)&np.isfinite(history).all(0)&np.isfinite(f.precip_corrected.values).all(0)
    pv=av&(f.probability_eligible.values==1)
    if not av.any() or not pv.any():raise ValueError('No common eligible evaluation support')
    w=area(f)
    def avg(z,v):return float(np.average(z[v],weights=w[v]))
    def skill(loss,reference):return float(1-loss/reference) if reference>0 else None
    y=category(obs,f.q1.values,f.q2.values);y=np.where(pv,y,-1)
    groups=category(raw,f.q1.values,f.q2.values)
    probs={'raw_observed_thresholds':np.stack([(groups==k).mean(0) for k in range(3)],-1),'corrected_member_counts':f.base_probability.values,'corrected_smoothed':f.smoothed_probability.values,'shared_blend':f.blend_probability.values,'climatology':f.climatology_probability.values}
    probability={};losses={}
    for name,p in probs.items():
        p=np.where(pv[...,None],p,np.nan);bs,rps,ll=probability_losses(p,y)
        losses[name]=(bs,rps,ll)
        selected=np.take_along_axis(p,np.maximum(y,0)[...,None],-1)[...,0]
        probability[name]={'rps':avg(rps,pv),'brier_by_category':[avg(bs[...,k],pv) for k in range(3)],'log_loss':avg(ll,pv),'zero_probability_observed_event_cells':int(((selected==0)&pv).sum()),'area_mean_probabilities':[avg(p[...,k],pv) for k in range(3)]}
    reference=probability['climatology']
    for name,row in probability.items():
        row['rpss']=skill(row['rps'],reference['rps']);row['bss_by_category']=[skill(x,y) for x,y in zip(row['brier_by_category'],reference['brier_by_category'])]
    ensembles={'raw':raw,'corrected':f.precip_corrected.values,'climatology':history}
    amount={};crps_fields={};errors={}
    for name,x in ensembles.items():
        mean=x.mean(0);error=mean-obs;loss=crps(x,obs)
        errors[name]=error;crps_fields[name]=loss
        amount[name]={'bias_mm':avg(error,av),'mae_mm':avg(np.abs(error),av),'rmse_mm':float(np.sqrt(avg(error**2,av))),'crps_mm':avg(loss,av),'ensemble_size':len(x)}
    for name,row in amount.items():row['crpss']=skill(row['crps_mm'],amount['climatology']['crps_mm'])
    fields=xr.Dataset(coords={'lat':f.lat,'lon':f.lon,'category':f.category})
    items={'observed_total_mm':obs,'corrected_mean_mm':f.corrected_ensemble_mean.values,'observed_anomaly_mm':obs-f.observed_training_mean.values,'corrected_mean_anomaly_mm':f.corrected_mean_anomaly.values,'raw_error_mm':errors['raw'],'corrected_error_mm':errors['corrected'],'raw_crps_mm':crps_fields['raw'],'corrected_crps_mm':crps_fields['corrected'],'climatology_crps_mm':crps_fields['climatology']}
    for k,v in items.items():fields[k]=(('lat','lon'),np.where(av,v,np.nan));fields[k].attrs['units']='mm'
    fields['amount_support']=(('lat','lon'),av.astype('int8'));fields['probability_support']=(('lat','lon'),pv.astype('int8'));fields['country_mask']=f.region_mask
    fields['observed_category']=(('lat','lon'),y.astype('int8'))
    fields['shared_blend_probability']=(('lat','lon','category'),np.where(pv[...,None],f.blend_probability.values,np.nan))
    for name,(bs,rps,ll) in losses.items():
        fields[name+'_rps']=(('lat','lon'),rps);fields[name+'_brier']=(('lat','lon','category'),bs);fields[name+'_log_loss']=(('lat','lon'),ll)
    fields['shared_minus_climatology_rps']=fields.shared_blend_rps-fields.climatology_rps
    fields.attrs.update(evaluation_year=YEAR,initialization_month=5,reference_years=f'{REF}',note='Single-year scores; native-grid fields. Negative shared-minus-climatology RPS favors the shared forecast. No cell-level significance test.')
    report={'amount_cells':int(av.sum()),'probability_cells':int(pv.sum()),'amount_country_area_percent':float(100*w[av].sum()/w[region].sum()),'probability_country_area_percent':float(100*w[pv].sum()/w[region].sum()),'observed_category_area_fractions':[avg((y==k).astype(float),pv) for k in range(3)],'amount':amount,'probability':probability,'interpretation':'Single-year area-weighted performance, not multi-year reliability. June-September and JJAS are overlapping/dependent evaluation targets, not five independent seasons.','log_loss_note':'Natural log; probabilities floored at 1e-12 for scoring; zero-probability observed-event counts reported.','raw_probability_note':'Raw member counts against frozen observed thresholds; not a model-climatology tercile forecast.','crps_note':'Empirical ensemble CRPS: raw/corrected 51 members, climatology 33 historical observed years. This scores these finite predictive distributions; no fair/iid ensemble correction.'}
    return report,fields

def plots(d,out,target):
    fig,axs=plt.subplots(2,3,figsize=(14,9),layout='constrained')
    anomaly_limit=max(10.,float(np.nanquantile(np.abs(np.r_[d.observed_anomaly_mm.values.ravel(),d.corrected_mean_anomaly_mm.values.ravel()]),.98)))
    panels=[('Observed anomaly (mm)','observed_anomaly_mm',anomaly_limit,'BrBG'),('Forecast mean anomaly (mm)','corrected_mean_anomaly_mm',anomaly_limit,'BrBG'),('Forecast minus observed (mm)','corrected_error_mm',None,'RdBu_r'),('Observed tercile','observed_category',None,None),('Shared minus climatology RPS','shared_minus_climatology_rps',None,'RdBu_r'),('Corrected ensemble CRPS (mm)','corrected_crps_mm',None,'viridis')]
    for ax,(title,key,limit,cmap) in zip(axs.flat,panels):
        z=d[key].values.copy()
        if key=='observed_category':
            z=np.where(z>=0,z,np.nan);kw={'cmap':ListedColormap(['#c77728','#d9dddf','#278a45']),'norm':BoundaryNorm([-.5,.5,1.5,2.5],3)}
        else:
            kw={'cmap':cmap}
            if cmap in ['BrBG','RdBu_r']:
                limit=limit or max(.001,float(np.nanquantile(np.abs(z),.98)));kw.update(vmin=-limit,vmax=limit)
        ax.set_facecolor('#ededed');im=ax.pcolormesh(d.lon,d.lat,z,shading='auto',**kw)
        ax.contour(d.lon,d.lat,d.country_mask,levels=[.5],colors='#333333',linewidths=.65)
        cb=fig.colorbar(im,ax=ax,shrink=.8,extend='neither' if key=='observed_category' else 'both')
        if key=='observed_category':cb.set_ticks([0,1,2]);cb.set_ticklabels(['Below','Near','Above'])
        ax.set(title=title,aspect='equal',xlabel='Longitude',ylabel='Latitude')
    fig.suptitle(f'{CYCLE.target_label(target)} | frozen shared-blend forecast verification\nCHIRPS v2 observations; native grid; descriptive single-year assessment',fontsize=15)
    fig.savefig(out/'verification_maps.png',dpi=180);plt.close(fig)

def assess(root,processed,target,regenerate):
    fp=root/'frozen_forecasts'/f'{TAG}_{target}/forecast_{YEAR}.nc';op=root/'observations'/target/f'chirps_{YEAR}_common.nc';rawp=processed/f'{TAG}_{target}/ecmwf_{YEAR}_common.nc'
    frozen=read(root/'frozen_forecasts/freeze_manifest.json')
    if sha(fp)!=frozen['targets'][target]['sha256']:raise ValueError('Frozen forecast was modified')
    with xr.open_dataset(fp) as ds:f=ds.load()
    check_forecast(f,target)
    preparation=read(op.parent/'preparation_report.json')
    if preparation.get('prepared_total_sha256')!=sha(op):raise ValueError('Prepared observations differ from their preparation report')
    with xr.open_dataset(op) as ds:o=ds.load()
    same_grid(o,f)
    expected=window_days(target);start,end=window_iso(target)
    if int(o.attrs['year'])!=YEAR or o.attrs['target']!=target or o.attrs['season_start']!=start or o.attrs['season_end']!=end or int(o.attrs['expected_days'])!=expected:raise ValueError('Wrong observation dates/target')
    if o.attrs.get('product')!='CHIRPS Version 2.0 daily p25' or o.precip_season.attrs.get('units')!='mm':raise ValueError('Wrong observation product or units')
    if o.attrs.get('forecast_freeze_sha256')!=sha(root/'frozen_forecasts/freeze_manifest.json'):raise ValueError('Observations prepared against a different freeze')
    obs=o.precip_season.values
    if np.isinf(obs).any() or (obs[np.isfinite(obs)]<0).any() or not np.array_equal(np.isfinite(obs),o.valid_day_count.values==expected):raise ValueError('Incomplete/invalid totals')
    with xr.open_dataset(rawp) as ds:r=ds.load()
    same_grid(r,f)
    if r.attrs.get('season_start')!=start or r.attrs.get('season_end')!=end or r.precip_season.attrs.get('units')!='mm' or not np.array_equal(r.member,f.member):raise ValueError('Raw forecast period, units or members differ')
    raw=r.precip_season.transpose('member','lat','lon').values.astype(float)
    if not np.isfinite(raw).all() or (raw<0).any():raise ValueError('Invalid raw forecast')
    history,hashes=load_reference(processed/f'{TAG}_{target}',f,target)
    report,fields=calculate(f,raw,history,obs)
    report.update(target=target,year=YEAR,processing_utc=now(),forecast_sha256=sha(fp),observations_sha256=sha(op),raw_forecast_sha256=sha(rawp),history_sha256=hashes)
    fields.attrs['target']=target
    with staged_output(root/'results'/target,regenerate) as stage:
        write(stage/'verification_report.json',report);fields.to_netcdf(stage/'verification_fields.nc');plots(fields,stage,target)
    print('Verified',target,'| shared RPS',round(report['probability']['shared_blend']['rps'],6),'| corrected CRPS mm',round(report['amount']['corrected']['crps_mm'],3),flush=True)
    return report

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',default=f'outputs/verification_{YEAR}');ap.add_argument('--processed-root',default='data/processed')
    ap.add_argument('--targets',nargs='+',choices=list(PERIODS),default=list(MONTHS));ap.add_argument('--regenerate',action='store_true');a=ap.parse_args()
    try:
        root=path(a.root);processed=path(a.processed_root);targets=list(dict.fromkeys(a.targets));required=[root/'frozen_forecasts/freeze_manifest.json']
        for t in targets:
            required.extend([root/'frozen_forecasts'/f'{TAG}_{t}/forecast_{YEAR}.nc',root/'observations'/t/f'chirps_{YEAR}_common.nc',processed/f'{TAG}_{t}/ecmwf_{YEAR}_common.nc'])
            required.extend(processed/f'{TAG}_{t}/chirps_{y}_common.nc' for y in REF_YEARS)
        missing=[str(p) for p in required if not p.is_file()]
        if missing:raise ValueError('Required inputs missing; run preparation for complete available targets:\n'+'\n'.join(missing))
        rows=[assess(root,processed,t,a.regenerate) for t in targets]
        with staged_output(root/'reports'/'_'.join(targets),a.regenerate) as stage:
            write(stage/'verification_summary.json',{'year':YEAR,'targets':targets,'results':rows,'note':'No aggregate score across monthly and JJAS targets because they overlap. Forecasts and calibration remain frozen.'})
            lines=[f'# Frozen {YEAR} forecast verification','','Single-year descriptive assessment against CHIRPS v2. Lower CRPS/RPS is better; positive skill means improvement over the specified historical climatology.','','| Target | Raw CRPS mm | Corrected CRPS mm | Climatology CRPS mm | Shared RPS | Climatology RPS | Shared RPSS |','|---|---:|---:|---:|---:|---:|---:|']
            for r in rows:
                am=r['amount'];pr=r['probability'];ss=pr['shared_blend']['rpss'];lines.append(f'| {r["target"]} | {am["raw"]["crps_mm"]:.3f} | {am["corrected"]["crps_mm"]:.3f} | {am["climatology"]["crps_mm"]:.3f} | {pr["shared_blend"]["rps"]:.6f} | {pr["climatology"]["rps"]:.6f} | {ss:.4f} |' if ss is not None else f'| {r["target"]} | undefined reference score |')
            lines+=['','See target verification_report.json files for category Brier/BSS, log loss, bias, MAE, RMSE, coverage and source hashes. Probability blending does not change the amount-corrected ensemble CRPS. Spatial cells are not independent cases; no single-year bootstrap or long-term reliability claim is made.']
            (stage/'VERIFICATION.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        print('Summary:',root/'reports'/'_'.join(targets)/'verification_summary.json')
    except (ValueError,KeyError,OSError) as exc:print('ERROR:',exc,file=sys.stderr);sys.exit(2)
if __name__=='__main__':main()
