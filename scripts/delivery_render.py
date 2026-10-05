"""Package existing shared forecasts and a separate JJAS R1+R2 display domain."""
import argparse, hashlib, json
from pathlib import Path
import numpy as np
import xarray as xr
import delivery_map_base as base
import delivery_contours as smooth
from delivery_output_runs import staged_output
ROOT=Path(__file__).resolve().parents[1]
def path(p):
    p=Path(p);return p if p.is_absolute() else ROOT/p

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--targets',nargs='+',choices=base.TARGETS,default=base.TARGETS)
    ap.add_argument('--input-root',default='outputs/final_shared_blend')
    ap.add_argument('--forecast',help='Single-target source override')
    ap.add_argument('--mask',default='outputs/regime_reconciliation/descriptive_1993_2025/regime_comparison_and_masks.nc')
    ap.add_argument('--evidence',default='evidence/all_regime_experiments.json')
    ap.add_argument('--boundary',default='data/boundaries/ethiopia/eth_admin0.shp')
    ap.add_argument('--output-root',default='outputs/forecast_review')
    ap.add_argument('--regenerate',action='store_true')
    a=ap.parse_args()
    if a.forecast and len(a.targets)!=1:ap.error('--forecast requires one target')
    evidence=json.loads(path(a.evidence).read_text(encoding='utf-8'))
    lines=base.boundary_lines(path(a.boundary))
    base.decorate=smooth.decorate;base.background=smooth.background
    for target in dict.fromkeys(a.targets):
        source=path(a.forecast) if a.forecast else path(a.input_root)/f'init05_{target}/2026/forecast_2026.nc'
        with xr.open_dataset(source) as f:d=f.load()
        if json.loads(d.attrs['target_period'])['name']!=target:raise ValueError('Target mismatch')
        g=base.derive(d)
        records=[e for e in evidence['experiments'] if e['target']==target]
        if len(records)!=4:raise ValueError(f'Expected four experiment records for {target}')
        verification=[{'method':e['method'],'mode':e['mode'],'all_country':e['report']['equal_year_summary']['all_country']} for e in records]
        domains={'all_ethiopia':np.asarray(g.region_mask)==1}
        if target=='JJAS':
            with xr.open_dataset(path(a.mask)) as f:m=f.load()
            for c in ['lat','lon']:
                if not np.array_equal(m[c],d[c]):raise ValueError('Domain and forecast coordinates differ')
            if not np.array_equal(m.region_mask,d.region_mask):raise ValueError('Country masks differ')
            if json.loads(m.attrs['training_years'])!=list(range(1993,2026)):raise ValueError('Unexpected descriptive mask years')
            domains['jjas_r12_rainfall_domain']=np.asarray(m.github_jjas_r12_rainfall)==1
        for view,domain in domains.items():
            h=g.copy(deep=True)
            domain=xr.DataArray(domain,dims=('lat','lon'),coords={'lat':d.lat,'lon':d.lon})
            for v in ['region_mask','probability_valid','amount_valid']:h[v]=h[v].where(domain,0).astype('int8')
            for v in ['rainfall_anomaly_mm','rainfall_anomaly_percent','blend_probability','maximum_probability']:h[v]=h[v].where(domain)
            for v in ['dominant_tercile','display_tercile']:h[v]=h[v].where(domain,-2).astype('int8')
            h['country_mask']=d.region_mask;h['display_domain']=(('lat','lon'),domain.values.astype('int8'))
            label='All Ethiopia' if view=='all_ethiopia' else 'JJAS R1+R2 rainfall domain only (not an onset mask)'
            definition='Country mask intersected with variable-specific eligibility' if view=='all_ethiopia' else 'Cleaned GitHub-refined R1/R2; JJAS climatology >=120 mm and annual share >=0.20; 1993-2025 descriptive mask'
            metadata={'target':target,'view':view,'domain_definition':definition,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'forecast_source':str(source),'method':'Existing shared probability blend; existing cell-specific rainfall amount correction','reference_years':d.attrs['training_years'],'display_only':'Normalized Gaussian sigma 0.6 native cells and 16x bilinear contours; not downscaling','verification_scope':'All-country historical metrics; not verification of the 2026 forecast or of the R1+R2 subset','verification':verification,'selection':'Shared blend retained for all targets. August regime blend remains experimental. Operational years have been inspected repeatedly.'}
            if target=='JJAS':metadata['domain_mask_source']=str(path(a.mask));metadata['domain_mask_sha256']=hashlib.sha256(path(a.mask).read_bytes()).hexdigest()
            valid=h.probability_valid.values==1
            w=np.broadcast_to(np.cos(np.deg2rad(h.lat.values))[:,None],valid.shape)[valid];w=w/w.sum()
            metadata['area_mean_local_probabilities']=(w@h.blend_probability.values[valid]).tolist()
            metadata['probability_note']='Mean of local probabilities; not probability of country-total rainfall'
            metadata['domain_cells']=int(domain.sum());metadata['probability_cells']=int(valid.sum())
            h.attrs.update(view=view,mask_note=definition,source_sha256=metadata['source_sha256'],verification_file='product_metadata.json')
            out=path(a.output_root)/f'init05_{target}/2026'/view
            if source.resolve().is_relative_to(out.resolve()):raise ValueError('Output contains source')
            original_save=base.save
            def annotated_save(fig,p):
                fig.text(.5,.882,label,ha='center',fontsize=10,color='#333333')
                original_save(fig,p)
            with staged_output(out,a.regenerate) as stage:
                base.save=annotated_save
                try:
                    smooth.probability(h,target,stage/'dominant_tercile_2026',lines)
                    smooth.anomaly(h,target,stage/'rainfall_anomaly_mm_2026',lines,limit=300 if target=='JJAS' else 100)
                    smooth.anomaly(h,target,stage/'rainfall_anomaly_percent_2026',lines,percent=True,limit=100)
                finally:base.save=original_save
                h.to_netcdf(stage/'map_fields_2026.nc')
                (stage/'product_metadata.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
            print('Saved',out,flush=True)
if __name__=='__main__':main()
