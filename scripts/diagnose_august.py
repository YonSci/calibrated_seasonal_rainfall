"""Review held-out August shared versus regularized regime probabilities; no refitting."""
import argparse,hashlib,json,warnings
from pathlib import Path
import numpy as np
import xarray as xr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from review_output_runs import staged_output
ROOT=Path(__file__).resolve().parents[1]
METHODS=['shared_blend','regularized_regime_blend']
CATS=['below','near','above']
def resolve(p):
    p=Path(p);return p if p.is_absolute() else ROOT/p

def calculate(d):
    """Equal year weight; cosine-latitude area weights within each year's common support."""
    if list(map(str,d.category.values))!=CATS:raise ValueError('Expected category order below, near, above')
    y=d.observed_category.transpose('year','lat','lon').values
    p=[d[k+'_probability'].transpose('year','lat','lon','category').values.astype(float) for k in METHODS]
    support=d.probability_common_support.transpose('year','lat','lon').values==1
    support &= np.asarray(d.region_mask)==1
    if not np.isin(y[support],[0,1,2]).all():raise ValueError('Invalid observed category on common support')
    for v in p:
        if not np.isfinite(v[support]).all() or np.any(v[support]<0) or np.any(v[support]>1) or not np.allclose(v[support].sum(-1),1,atol=1e-6,rtol=0):raise ValueError('Invalid probabilities on common support')
    if not support.reshape(len(y),-1).any(1).all():raise ValueError('A year has no eligible cells')
    area=np.broadcast_to(np.cos(np.deg2rad(d.lat.values))[None,:,None],y.shape)
    w=np.where(support,area,0);w=w/w.sum((1,2),keepdims=True)
    event=y[...,None]==np.arange(3)
    bins=np.linspace(0,1,11);reports={};rps=[];bs=[]
    for name,v in zip(METHODS,p):
        loss=np.where(support,np.sum((np.cumsum(v,-1)[...,:2]-np.cumsum(event,-1)[...,:2])**2,-1),np.nan)
        b=np.where(support[...,None],(v-event)**2,np.nan)
        rps.append(loss);bs.append(b)
        reliability=[]
        for k in range(3):
            rows=[]
            for i in range(10):
                valid=support&(v[...,k]>=bins[i])&((v[...,k]<bins[i+1]) if i<9 else (v[...,k]<=1))
                wb=np.where(valid,w/len(y),0);mass=wb.sum()
                rows.append({'lower':float(bins[i]),'upper':float(bins[i+1]),'weight_fraction':float(mass),'mean_probability':float(np.sum(np.where(valid,v[...,k],0)*wb)/mass) if mass else None,'observed_frequency':float(np.sum(event[...,k]*wb)/mass) if mass else None,'cell_year_count':int(valid.sum()),'years_contributing':int(valid.reshape(len(y),-1).any(1).sum())})
            reliability.append(rows)
        reports[name]={'annual_rps':np.nansum(loss*w,(1,2)).tolist(),'reliability':dict(zip(CATS,reliability))}
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',RuntimeWarning)
        fields=xr.Dataset(coords={'lat':d.lat,'lon':d.lon,'category':d.category})
        fields['rps_difference']=(('lat','lon'),np.nanmean(rps[1]-rps[0],0))
        fields['brier_difference']=(('lat','lon','category'),np.nanmean(bs[1]-bs[0],0))
        fields['probability_difference']=(('lat','lon','category'),np.nanmean(np.where(support[...,None],p[1]-p[0],np.nan),0))
    fields['valid_year_count']=(('lat','lon'),support.sum(0))
    fields.attrs['difference']='regularized regime minus shared; negative RPS/Brier favors regime'
    return reports,fields

def save(fig,p):
    fig.savefig(p.with_suffix('.png'),dpi=180,bbox_inches='tight');fig.savefig(p.with_suffix('.pdf'),bbox_inches='tight');plt.close(fig)

def plots(report,f,stage,mode):
    fig,axes=plt.subplots(2,3,figsize=(13,7),layout='constrained')
    for k,cat in enumerate(CATS):
        axes[0,k].plot([0,1],[0,1],'k--',lw=1)
        for name,color in zip(METHODS,['#2166ac','#b2182b']):
            rows=report[name]['reliability'][cat]
            axes[0,k].plot([r['mean_probability'] for r in rows],[r['observed_frequency'] for r in rows],'o-',color=color,label=name.replace('_',' '))
            axes[1,k].step(np.arange(.05,1,.1),[r['weight_fraction'] for r in rows],where='mid',color=color)
        axes[0,k].set(title=cat.capitalize(),xlim=(0,1),ylim=(0,1),xlabel='Mean forecast probability',ylabel='Observed frequency')
        axes[1,k].set(xlim=(0,1),xlabel='Forecast probability',ylabel='Weighted fraction')
    axes[0,0].legend(fontsize=8)
    fig.suptitle(f'August | {mode} | equal-year, area-weighted reliability\nDescriptive curves; spatial cells are not independent samples')
    save(fig,stage/'reliability_and_histograms')
    fig,axes=plt.subplots(2,3,figsize=(13,8),layout='constrained')
    for row,key in enumerate(['brier_difference','probability_difference']):
        for k in range(3):
            z=f[key].values[...,k];limit=max(.005,float(np.nanquantile(np.abs(z),.98)))
            im=axes[row,k].pcolormesh(f.lon,f.lat,z,cmap='RdBu_r',vmin=-limit,vmax=limit,shading='auto');fig.colorbar(im,ax=axes[row,k],extend='both')
            axes[row,k].set(title=f'{CATS[k]} | {key}',aspect='equal',xlabel='Longitude',ylabel='Latitude')
    fig.suptitle('August: regime minus shared | native-grid differences\nNegative Brier difference favors regime; probability differences are not skill')
    save(fig,stage/'category_differences')
    fig,axes=plt.subplots(1,2,figsize=(10,5),layout='constrained')
    for ax,key in zip(axes,['rps_difference','valid_year_count']):
        z=f[key].values
        opts={'cmap':'viridis'}
        if key=='rps_difference':
            limit=max(.005,float(np.nanquantile(np.abs(z),.98)));opts={'cmap':'RdBu_r','vmin':-limit,'vmax':limit}
        im=ax.pcolormesh(f.lon,f.lat,z,shading='auto',**opts);fig.colorbar(im,ax=ax,extend='both' if key=='rps_difference' else 'neither');ax.set(title=key,aspect='equal')
    fig.suptitle(f'August {mode}: native-grid RPS difference and support\nNegative RPS difference favors regime')
    save(fig,stage/'spatial_rps_and_support')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input-root',default='outputs/regime_calibration_github/init05_Aug')
    ap.add_argument('--output-root',default='outputs/august_review')
    ap.add_argument('--modes',nargs='+',choices=['training','operational'],default=['training','operational'])
    ap.add_argument('--evidence',default='evidence/all_regime_experiments.json')
    ap.add_argument('--regenerate',action='store_true');a=ap.parse_args()
    evidence=json.loads(resolve(a.evidence).read_text(encoding='utf-8'))['experiments']
    for mode in dict.fromkeys(a.modes):
        source=resolve(a.input_root)/mode/'regime_probabilities_and_weights.nc'
        with xr.open_dataset(source) as ds:d=ds.load()
        expected=list(range(1993,2017)) if mode=='training' else list(range(2017,2026))
        if d.year.values.tolist()!=expected:raise ValueError('Unexpected evaluation years')
        if d.attrs.get('classification_method')!='github_refined_corrected_calendar_v1':raise ValueError('Wrong regime classification method')
        records=[e for e in evidence if e['target']=='Aug' and e['mode']==mode and e['method']=='github_refined_corrected_calendar_v1']
        if len(records)!=1:raise ValueError('Expected one matching August evidence record')
        report,f=calculate(d)
        for name in METHODS:
            actual=float(np.mean(report[name]['annual_rps']))
            expected_rps=records[0]['report']['equal_year_summary']['all_country']['probability'][name]['rps']
            if not np.isclose(actual,expected_rps,atol=2e-6,rtol=0):raise ValueError(f'{name} RPS does not reproduce August evidence: {actual} vs {expected_rps}; check target, support and file version')
        delta=np.array(report[METHODS[1]]['annual_rps'])-report[METHODS[0]]['annual_rps']
        rng=np.random.default_rng(2026);ci=np.quantile(delta[rng.integers(len(delta),size=(10000,len(delta)))].mean(1),[.025,.975])
        summary={'mode':mode,'years':d.year.values.tolist(),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'rps_difference':float(delta.mean()),'whole_year_bootstrap_95_interval':ci.tolist(),'years_better':int((delta<0).sum()),'methods':report,'weighting':'Equal years; area weights normalized on each year common support','limitations':'Exploratory comparison, repeated inspection of operational years. No independent-cell confidence intervals. No automatic method selection or refit.'}
        out=resolve(a.output_root)/mode
        if source.resolve().is_relative_to(out.resolve()):raise ValueError('Output contains source')
        with staged_output(out,a.regenerate) as stage:
            plots(report,f,stage,mode);f.to_netcdf(stage/'diagnostic_fields.nc')
            (stage/'diagnostic_report.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        print('Saved',out,flush=True)
if __name__=='__main__':main()
