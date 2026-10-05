"""Compare two definitions on one corrected CHIRPS climatology and country grid."""
import argparse
import json
from pathlib import Path
import numpy as np
import xarray as xr
from common import ROOT,source_path,save_json,save_netcdf
from output_runs import staged_output
from prepare_regimes import sha256
from regime_core import diagnose
from github_regime_core import classify,onset_layers,LABELS,METHOD,SOURCE_COMMIT,SOURCE_URL


def area_km2(lat,lon):
    from run_calibration import cell_area
    return cell_area(lat,lon)*6371.0088**2


def contributions(group,region,monthly,area):
    annual=monthly.sum(axis=0);jjas=monthly[5:9].sum(axis=0)
    valid=region&np.isfinite(annual)&np.isfinite(jjas)
    country_area=area[region].sum();observed_volume=np.sum(area[valid]*jjas[valid])*1e-6
    rows=[]
    for g in [-1,0,1,2,3,4]:
        selected=region&(group==g);ok=selected&valid;a=area[ok].sum()
        v=float(np.sum(area[ok]*jjas[ok])*1e-6)
        annual_v=float(np.sum(area[ok]*annual[ok])*1e-6)
        rows.append(dict(code=g,cells=int(selected.sum()),country_area_percent=float(100*area[selected].sum()/country_area),
                         observed_cells=int(ok.sum()),mean_JJAS_mm=float(v/a*1e6) if a else None,
                         mean_annual_mm=float(annual_v/a*1e6) if a else None,
                         JJAS_fraction_of_regime_annual_volume=float(v/annual_v) if annual_v else None,
                         JJAS_volume_km3=v,JJAS_volume_percent=float(v/observed_volume*100) if observed_volume else None))
    return dict(rows=rows,observed_country_area_percent=float(100*area[valid].sum()/country_area),total_observed_JJAS_km3=float(observed_volume))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--climatology',default='data/processed/regime_climatology/descriptive_1993_2025.nc')
    p.add_argument('--output',default='outputs/regime_reconciliation/descriptive_1993_2025')
    p.add_argument('--onset-rates',help='Optional NetCDF onset_detection_rate(lat,lon), 0..1; must match training_years metadata.')
    p.add_argument('--regenerate',action='store_true');args=p.parse_args()
    path=source_path(args.climatology)
    with xr.open_dataset(path) as ds:d=ds.load()
    lat=d.lat.values;lon=d.lon.values;shape=(len(lat),len(lon))
    if d.sizes.get('day')!=365 or d.sizes.get('month')!=12:raise ValueError('Expected 365-day and 12-month climatologies.')
    if not np.isin(d.region_mask.values,[0,1]).all():raise ValueError('Country mask must be binary.')
    if 'excludes Feb29 by month-day' not in d.attrs.get('calendar_policy',''):raise ValueError('Require corrected calendar policy from prepare_regimes.py.')
    region=(d.region_mask.values==1).ravel();q=d.daily_climatology.transpose('day','lat','lon').values.reshape(365,-1)
    monthly=d.monthly_climatology.transpose('month','lat','lon').values.reshape(12,-1)
    if not region.any():raise ValueError('Empty country mask.')
    current=diagnose(q,monthly,region);github=classify(q,lat,lon,region)
    if not np.array_equal(current['regime'],d.regime.values.ravel()):raise ValueError('Uploaded classification does not reproduce with installed regime_core.py; inspect code/settings before comparison.')
    rate=None;rate_info={'available':False}
    if args.onset_rates:
        rp=source_path(args.onset_rates)
        with xr.open_dataset(rp) as r:
            if not np.array_equal(r.lat,lat) or not np.array_equal(r.lon,lon):raise ValueError('Onset rate grid mismatch.')
            if json.loads(r.attrs.get('training_years','[]'))!=json.loads(d.attrs.get('training_years','[]')):raise ValueError('Onset-rate baseline must match climatology training_years.')
            rate=r.onset_detection_rate.transpose('lat','lon').values.ravel()
        rate_info=dict(available=True,path=str(rp),sha256=sha256(rp))
    onset=onset_layers(github,region,rate)
    old=current['regime'];new=github['regime_cleaned'];changed=region&(old!=new);area=area_km2(lat,lon)
    report=dict(method=METHOD,source_url=SOURCE_URL,source_commit=SOURCE_COMMIT,
                input_sha256=sha256(path),training_years=json.loads(d.attrs['training_years']),
                comparison='Same corrected daily cycle, grid, baseline and country mask. GitHub thresholds use corrected noleap totals; contribution statistics use actual-calendar monthly totals.',
                country_cells=int(region.sum()),changed_cells=int(changed.sum()),
                changed_country_area_percent=float(100*area[changed].sum()/area[region].sum()),
                cleanup_changed_cells=int(github['cleanup_changed'].sum()),
                onset=rate_info,code_sha256={n:sha256(Path(__file__).parent/n) for n in ['github_regime_core.py','compare_regime_definitions.py']},
                attribution='GitHub-derived Ethiopia refinement; official EMI endorsement and station validation not independently established.',
                deviations=['Correct month-day alignment excludes Feb29; noleap totals retained for classification thresholds.',
                            'Missing observations coded -1 and never assigned to residual R1.',
                            'Undefined C1 ratio stays NaN; numerical ratio clauses fail, peak clauses remain eligible.',
                            'Use existing 1484-cell project country mask rather than rebuilding the GitHub boundary.',
                            'Rainfall masks exclude onset-detection gates; onset evidence remains separate and unknown when absent.'])
    report['rainfall_contributions']={name:contributions(group,region,monthly,area) for name,group in [('current_peak_refinement',old),('github_raw',github['regime_raw']),('github_cleaned',new)]}
    report['mask_coverage']={}
    for name,v in [('current_JJAS_relevant',current['JJAS_relevant']),('github_R1_R2_rainfall',github['jjas_r12_rainfall']),('github_R1_R2_rainfall_cleaned',github['jjas_r12_rainfall_cleaned']),('github_onset_candidate_R2',github['onset_candidate_r2']),('onset_eligibility_unknown',onset['onset_eligibility_r2']==-1),('onset_eligibility_pass',onset['onset_eligibility_r2']==1)]:
        v=v&region;report['mask_coverage'][name]=dict(cells=int(v.sum()),country_area_percent=float(100*area[v].sum()/area[region].sum()))
    report['transitions']=[dict(old_code=a,new_code=b,cells=int((region&(old==a)&(new==b)).sum()),country_area_percent=float(100*area[region&(old==a)&(new==b)].sum()/area[region].sum())) for a in range(-1,5) for b in range(-1,5) if (region&(old==a)&(new==b)).any()]
    LON,LAT=np.meshgrid(lon,lat)
    ledger=[dict(lat=float(LAT.ravel()[i]),lon=float(LON.ravel()[i]),current_code=int(old[i]),github_raw=int(github['regime_raw'][i]),github_cleaned=int(new[i]),cleanup_changed=bool(github['cleanup_changed'][i]),harmonic_ratio=float(github['harmonic_ratio'][i]) if np.isfinite(github['harmonic_ratio'][i]) else None,monthly_peak1=int(github['monthly_peak1'][i]),monthly_peak2=int(github['monthly_peak2'][i])) for i in np.flatnonzero(changed|github['cleanup_changed'])]
    outds=xr.Dataset(coords=dict(lat=lat,lon=lon),attrs=dict(method=METHOD,source_url=SOURCE_URL,training_years=d.attrs['training_years'],calendar_policy=d.attrs['calendar_policy'],onset_status='Separate tri-state eligibility: -1 unavailable, 0 excluded/fails, 1 passes',physical_land_mask='Not supplied; region_mask is a country mask.'))
    fields=dict(region_mask=region,current_regime=old,classification_changed=changed,current_JJAS_relevant=current['JJAS_relevant'],**{'github_'+k:v for k,v in github.items()},**onset)
    for k,v in fields.items():
        a=np.asarray(v);outds[k]=(('lat','lon'),a.reshape(shape).astype('int8') if a.dtype==bool else a.reshape(shape))
    outds.github_regime_raw.attrs['codes']=json.dumps(LABELS);outds.github_regime_cleaned.attrs['codes']=json.dumps(LABELS)
    for key in ['jjas_r12_rainfall','jjas_r12_rainfall_raw','jjas_r12_rainfall_cleaned']:
        outds['github_'+key].attrs['note']='Rainfall domain only, no onset detection requirement; threshold totals use corrected noleap climatology.'
    with staged_output(source_path(args.output),args.regenerate) as out:
        save_netcdf(outds,out/'regime_comparison_and_masks.nc');save_json(out/'changed_cell_ledger.json',ledger)
        sites=plots(d,current,github,out,area);report['representative_cycles']=sites
        save_json(out/'regime_reconciliation_report.json',report)
    print('Completed:',source_path(args.output));print('Changed cells:',report['changed_cells'])
    print(json.dumps(report['rainfall_contributions']['github_cleaned'],indent=2))


def plots(d,current,github,out,area):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap,BoundaryNorm
    from matplotlib.patches import Patch
    from scipy.ndimage import gaussian_filter1d
    region=d.region_mask.values==1;shape=region.shape;old=current['regime'].reshape(shape);new=github['regime_cleaned'].reshape(shape)
    colors=['#bdbdbd','#dec79f','#168f70','#7970b1','#d86500','#eedb45']
    cmap=ListedColormap(colors);norm=BoundaryNorm(np.arange(-1.5,5),6)
    fig,axes=plt.subplots(1,3,figsize=(16,6),layout='constrained')
    for ax,z,title in zip(axes,[old,new,np.where(old==new,0,1)],['Current peak refinement','GitHub refinement: corrected calendar','Changed classification']):
        kwargs=dict(cmap=cmap,norm=norm) if ax is not axes[2] else dict(cmap=ListedColormap(['#eeeeee','#cc3377']),vmin=0,vmax=1)
        ax.pcolormesh(d.lon,d.lat,np.where(region,z,np.nan),shading='auto',**kwargs)
        ax.set(title=title,xlabel='Longitude',ylabel='Latitude',aspect='equal')
    fig.suptitle('Same CHIRPS 1993–2025 climatology and country grid',fontsize=15)
    labels=['Missing','Arid','Annual / R1','Spring–summer / R2','Spring–autumn / R3','Uncertain (current only)']
    fig.legend(handles=[Patch(color=c,label=t) for c,t in zip(colors,labels)],loc='outside lower center',ncol=3,fontsize=9)
    fig.savefig(out/'classification_comparison.png',dpi=160);plt.close(fig)
    fig,axes=plt.subplots(1,3,figsize=(16,6),layout='constrained')
    for ax,z,title in zip(axes,[github['jjas_r12_rainfall'],github['onset_candidate_r2'],current['JJAS_relevant']],['GitHub R1 + R2 rainfall domain','GitHub R2 onset candidate\nDetection evidence still required','Current rainfall-threshold domain']):
        ax.pcolormesh(d.lon,d.lat,np.where(region,z.reshape(shape),np.nan),cmap=ListedColormap(['#eeeeee','#2278a5']),vmin=0,vmax=1,shading='auto')
        ax.set(title=title,xlabel='Longitude',ylabel='Latitude',aspect='equal')
    fig.suptitle('Separate domain definitions | blue = included | gray = excluded')
    fig.savefig(out/'JJAS_separate_domains.png',dpi=160);plt.close(fig)
    # Four typical-class locations and up to four changed-cell examples.
    monthly=d.monthly_climatology.values.reshape(12,-1);q=d.daily_climatology.values.reshape(365,-1)
    flatnew=new.ravel();flatold=old.ravel();selected=[]
    for g in range(4):
        ids=np.flatnonzero(flatnew==g)
        if not len(ids):continue
        patterns=monthly[:,ids]/monthly[:,ids].sum(axis=0)
        dist=np.sum((patterns-np.median(patterns,axis=1)[:,None])**2,axis=0)
        selected.append((int(ids[np.argmin(dist)]),'Typical R'+str(g)))
    transitions=[]
    for a in range(5):
        for b in range(4):
            ids=np.flatnonzero((flatold==a)&(flatnew==b))
            if a!=b and len(ids):transitions.append((len(ids),a,b,ids))
    for _,a,b,ids in sorted(transitions,key=lambda x:-x[0])[:4]:
        patterns=monthly[:,ids]/monthly[:,ids].sum(axis=0)
        idx=int(ids[np.argmin(np.sum((patterns-np.median(patterns,axis=1)[:,None])**2,axis=0))]);selected.append((idx,f'Changed {a} → {b}'))
    fig,axes=plt.subplots(2,4,figsize=(16,8),layout='constrained');sites=[]
    for ax in axes.ravel():ax.set_visible(False)
    for ax,(i,tag) in zip(axes.ravel(),selected):
        ax.set_visible(True);iy,ix=np.unravel_index(i,shape)
        ax.plot(np.arange(1,366),q[:,i],color='#999999',lw=.5,alpha=.7,label='Daily climatology')
        ax.plot(np.arange(1,366),gaussian_filter1d(q[:,i],10,mode='wrap'),color='#175787',label='10-day sigma display')
        ax.axvspan(152,273,color='#c5e8d2',alpha=.5);ax.set(title=f'{tag} | {float(d.lat[iy]):.3f}°N, {float(d.lon[ix]):.3f}°E',xlabel='No-leap day of year',ylabel='Rainfall (mm/day)')
        sites.append(dict(label=tag,lat=float(d.lat[iy]),lon=float(d.lon[ix]),current_code=int(flatold[i]),github_code=int(flatnew[i]),selection='Closest normalized monthly profile to within-group median; illustrative grid cell, not station validation.'))
    axes[0,0].legend(fontsize=7);fig.suptitle('Representative climatological cycles | shaded interval: JJAS')
    fig.savefig(out/'representative_rainfall_cycles.png',dpi=160);plt.close(fig)
    return sites


if __name__=='__main__':main()
