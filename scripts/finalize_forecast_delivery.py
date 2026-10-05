"""Validate and package the selected May-initialized shared-blend forecasts for the cycle year (cycle.py).

No fitting, regridding or forecast changes. Run from the existing project on Windows CMD.
Relative paths resolve against the project root (the parent of scripts).
"""
import argparse
from datetime import datetime,timezone
import hashlib
import html
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
import numpy as np
import xarray as xr
import delivery_map_base as base
from delivery_output_runs import staged_output,check_destination
from cycle import CYCLE, YEAR, REF, REF_DASH, REF_YEARS, MEMBERS, REGIME, REGIME_YEARS, OVERLAP_YEAR, EVALUATION_STUDY
ROOT=Path(__file__).resolve().parents[1]
TARGETS=['JJAS','Jun','Jul','Aug','Sep']
PERIODS={'JJAS':('06-01','09-30'),'Jun':('06-01','06-30'),'Jul':('07-01','07-31'),'Aug':('08-01','08-31'),'Sep':('09-01','09-30')}
METHODS={'current_peak_refinement','github_refined_corrected_calendar_v1'}
STATUS=f'Retrospective reconstruction of May-initialized {YEAR} forecasts; no verification against {YEAR} observations in this package.'

def path(s):
    p=Path(s);return p if p.is_absolute() else ROOT/p

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def write_json(p,d):p.write_text(json.dumps(d,indent=2,allow_nan=False),encoding='utf-8')

def read_json(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))

def forecast_check(p,target):
    with xr.open_dataset(p) as f:d=f.load()
    g=base.derive(d)
    period=json.loads(d.attrs['target_period'])
    if period!={'name':target,'start':PERIODS[target][0],'end':PERIODS[target][1]}:raise ValueError('Wrong target period')
    years=d.attrs.get('training_years')
    if years!=f'{REF}':raise ValueError(f'Expected training_years={REF}')
    if 'shared climatology blend' not in d.attrs.get('method',''):raise ValueError('Source is not the selected shared blend')
    lam=float(d.attrs['climatology_weight'])
    if not np.isfinite(lam) or not 0<=lam<=1:raise ValueError('Invalid climatology weight')
    n=d.sizes['member']
    if n!=MEMBERS or len(np.unique(d.member))!=n:raise ValueError(f'Expected {MEMBERS} unique members for {YEAR}')
    for c in ['lat','lon']:
        if not np.allclose(np.diff(d[c]),.25,atol=1e-6,rtol=0):raise ValueError('Expected common 0.25 degree grid')
    av=np.asarray(d.amount_eligible)==1;pv=np.asarray(d.probability_eligible)==1
    members=d.precip_corrected.transpose('member','lat','lon').values
    if d.precip_corrected.attrs.get('units')!='mm' or not np.isfinite(members[:,av]).all() or np.any(members[:,av]<0):raise ValueError('Invalid corrected member amounts')
    mean=d.corrected_ensemble_mean.values
    if not np.allclose(mean[av],members[:,av].mean(0),atol=.001,rtol=1e-6):raise ValueError('Stored mean differs from member mean')
    q1=d.q1.values;q2=d.q2.values
    if not np.isfinite(q1[pv]).all() or not np.isfinite(q2[pv]).all() or np.any(q2[pv]<=q1[pv]):raise ValueError('Invalid tercile thresholds')
    cats=base.CATEGORIES
    prob={k:d[k].sel(category=cats).transpose('lat','lon','category').values for k in ['base_probability','smoothed_probability','climatology_probability','blend_probability']}
    for k,v in prob.items():
        if not np.isfinite(v[pv]).all() or np.any(v[pv]<0) or np.any(v[pv]>1) or not np.allclose(v[pv].sum(-1),1,atol=1e-6,rtol=0):raise ValueError('Invalid '+k)
    counts=np.stack([(members<q1).mean(0),((members>=q1)&(members<=q2)).mean(0),(members>q2).mean(0)],-1)
    if not np.allclose(prob['base_probability'][pv],counts[pv],atol=1e-6,rtol=0):raise ValueError('Base probabilities differ from corrected-member counts')
    if not np.allclose(prob['smoothed_probability'][pv],(n*counts[pv]+.5)/(n+1.5),atol=1e-6,rtol=0):raise ValueError('Count smoothing does not reproduce')
    if not np.allclose(prob['blend_probability'][pv],((1-lam)*prob['smoothed_probability']+lam*prob['climatology_probability'])[pv],atol=1e-6,rtol=0):raise ValueError('Shared blend formula does not reproduce')
    region=d.region_mask.values==1;v=g.probability_valid.values==1;a=g.amount_valid.values==1
    area=np.broadcast_to(np.cos(np.deg2rad(d.lat.values.astype(float)))[:,None],region.shape)
    def avg(z,mask):return float(np.average(z[mask],weights=area[mask]))
    stats={'target':target,'members':n,'climatology_weight':lam,'country_cells':int(region.sum()),'probability_cells':int(v.sum()),'amount_cells':int(a.sum()),'probability_country_area_percent':float(100*area[v].sum()/area[region].sum()),'amount_country_area_percent':float(100*area[a].sum()/area[region].sum()),'area_mean_local_probabilities':[avg(prob['blend_probability'][...,k],v) for k in range(3)],'area_mean_corrected_rainfall_mm':avg(mean,a),'area_mean_reference_rainfall_mm':avg(d.observed_training_mean.values,a),'area_mean_anomaly_mm':avg(g.rainfall_anomaly_mm.values,a),'area_fraction_leading_display_category':{label:avg((g.display_tercile.values==code).astype(float),v) for code,label in [(-1,'weak_or_tied'),(0,'below'),(1,'near'),(2,'above')]},'source_sha256':sha(p),'source_path':str(p),'source_status':d.attrs.get('status','unspecified'),'checks':'PASS: periods, units, masks, 51 members, member mean, counts, smoothing and blend'}
    return stats,d

def evidence_check(e,targets):
    records=e['experiments'];lookup={}
    for t in targets:
        subset=[r for r in records if r['target']==t]
        keys=[(r['method'],r['mode']) for r in subset]
        if len(keys)!=4 or set(keys)!={(m,s) for m in METHODS for s in ['training','operational']}:raise ValueError(f'{t}: expected four unique experiment records')
        for r in subset:
            mode=r['mode'];p=r['report'];years=list(range(1993,2017)) if mode=='training' else EVALUATION_STUDY
            if [z['year'] for z in p['years']]!=years:raise ValueError(f'{t}: unexpected verification years')
            if r['method']=='github_refined_corrected_calendar_v1':
                if not p.get('baseline_reproduction',{}).get('passed'):raise ValueError(f'{t}: baseline reproduction did not pass')
                lookup[t,mode]=p['equal_year_summary']['all_country']['probability']
    return lookup

def preflight(a):
    targets=list(dict.fromkeys(a.targets));sources={t:path(a.forecast) if a.forecast else path(a.input_root)/f'init05_{t}/{YEAR}/forecast_{YEAR}.nc' for t in targets}
    ep=path(a.evidence);bp=path(a.boundary);mp=path(a.mask)
    required=[ep,bp,bp.with_suffix('.shx'),bp.with_suffix('.dbf'),bp.with_suffix('.prj'),*sources.values()]
    if 'JJAS' in targets:required.append(mp)
    missing=[p for p in required if not p.is_file()]
    if missing:
        raise ValueError('Missing required inputs:\n'+'\n'.join('  '+str(p) for p in missing)+'\nExtract the evidence folder from this update. For a missing regime mask, run:\n  python scripts\\compare_regime_definitions.py --climatology data\\processed\\regime_climatology\\descriptive_1993_2025.nc --regenerate\nOr supply its existing location with --mask. Final forecast inputs can be redirected with --input-root.')
    output=path(a.output)
    if any(p.resolve().is_relative_to(output.resolve()) for p in required):raise ValueError('Output folder must not contain any input file')
    ev=read_json(ep);lookup=evidence_check(ev,targets)
    base.boundary_lines(bp) # Fail before plotting if CRS or shape is unreadable.
    errors=[];stats=[];ref=None;mask=None
    if 'JJAS' in targets:
        with xr.open_dataset(mp) as f:mask=f.load()
        if mask.attrs.get('method')!='github_refined_corrected_calendar_v1':errors.append('Wrong descriptive-mask method')
        if json.loads(mask.attrs.get('training_years','[]'))!=REGIME_YEARS:errors.append('Wrong descriptive-mask years')
        v=mask.github_jjas_r12_rainfall.values
        if not np.isin(v,[0,1]).all() or not (v==1).any() or ((v==1)&(mask.region_mask.values!=1)).any():errors.append('Invalid JJAS rainfall domain')
    for t,p in sources.items():
        try:
            s,d=forecast_check(p,t)
            if ref is None:ref=d
            for c in ['lat','lon','region_mask']:
                if not np.array_equal(d[c],ref[c]):raise ValueError('Cross-target grid or country mask mismatch')
                if mask is not None and not np.array_equal(d[c],mask[c]):raise ValueError('Forecast and descriptive-mask grid/country mismatch')
            stats.append(s);print(f'PASS {t}: {s["members"]} members; {s["probability_cells"]} probability cells',flush=True)
        except (ValueError,KeyError,OSError) as exc:errors.append(f'{t}: {exc}')
    if errors:raise ValueError('Preflight failed:\n'+'\n'.join(errors))
    inputs={str(p):sha(p) for p in required}
    return targets,sources,stats,lookup,inputs

def verification_rows(targets,lookup):
    rows=[]
    for t in targets:
        for mode in ['training','operational']:
            v=lookup[t,mode];s=v['shared_blend'];r=v['regularized_regime_blend']
            rows.append({'target':t,'mode':mode,'shared_rps':s['rps'],'shared_rpss':s['rpss'],'shared_log_loss':s['log_loss'],'shared_brier_by_category':s['brier_by_category'],'shared_bss_by_category':s['bss_by_category'],'regime_rps':r['rps'],'regime_minus_shared_rps':r['rps_difference_vs_shared'],'regime_difference_95_interval':r['paired_year_bootstrap_95_range']})
    return rows

def documents(stage,targets,stats,verification,created):
    full=set(targets)==set(TARGETS)
    scope='All five targets' if full else 'Partial package: '+', '.join(targets)
    decision={'selected_probability_method':'shared climatology blend','targets':targets,'experimental':'August GitHub-refined regularized regime blend; no adoption','decision_basis':'Small and spatially uneven August improvement; operational interval includes zero. Shared retained for every target. Repeated operational inspection limits independence.','scope':scope,'created_utc':created,'product_status':STATUS}
    write_json(stage/'method_decision.json',decision)
    write_json(stage/'forecast_summary.json',{'status':STATUS,'scope':scope,'summaries':stats,'probability_note':'Area mean of grid-cell probabilities, not probability of country-total rainfall','amount_note':'Area means over amount-eligible country cells; support may differ between targets'})
    write_json(stage/'historical_verification.json',{'scope':f'All-country common-support historical evaluation; not {YEAR} verification or R1+R2-domain verification','records':verification})
    text=[f'# Ethiopia rainfall forecast package — May initialization, {YEAR}','',STATUS,'',scope+'. Generated '+created+'.','','## Selected methods','','Rainfall amounts: existing equal-year mean–variance bias correction at each grid cell. Probabilities: alpha=0.5 additive count smoothing followed by the existing shared climatology blend. No Dirichlet mapping, grid-cell blend or regime blend is applied in these selected final products. All 51 members are retained.','','## Forecast summary','','Probabilities below are area averages of local probabilities, not probabilities for country-total rainfall. Rainfall means use amount-eligible cells; probability summaries use probability-eligible cells. Their support can differ.','','| Target | Below % | Near % | Above % | Corrected mean mm | Reference mean mm | Anomaly mm | Probability coverage % |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for s in stats:
        p=s['area_mean_local_probabilities'];text.append(f'| {s["target"]} | {100*p[0]:.1f} | {100*p[1]:.1f} | {100*p[2]:.1f} | {s["area_mean_corrected_rainfall_mm"]:.1f} | {s["area_mean_reference_rainfall_mm"]:.1f} | {s["area_mean_anomaly_mm"]:+.1f} | {s["probability_country_area_percent"]:.1f} |')
    text+=['',f'Reference period: CHIRPS {REF_DASH}. Monthly and JJAS products were corrected separately; corrected monthly totals need not sum to corrected JJAS totals. Percent-anomaly maps hide reference rainfall below 10 mm.','','## Historical probability verification','',f'Lower RPS and log loss are better. RPSS uses the fold-specific climatology benchmark. Historical scores do not establish the skill of the final {REF_DASH} refit on {YEAR}.','','| Target | Evaluation | Shared RPS | Shared RPSS | Shared log loss |','|---|---|---:|---:|---:|']
    for v in verification:text.append(f'| {v["target"]} | {v["mode"]} | {v["shared_rps"]:.6f} | {v["shared_rpss"]:.4f} | {v["shared_log_loss"]:.6f} |')
    text+=['','Training evaluation: nested cross-validation over 1993–2016. Operational evaluation: 2017–2025 with fits based on 1993–2016; these years have been inspected repeatedly and are exploratory evidence. Detailed Brier/BSS category scores are in historical_verification.json. These figures come from the supplied regime-comparison common support, which can differ from other earlier verification stages.','','## Maps and domains','','Nationwide maps preserve the country mask and variable-specific eligibility. JJAS also includes a separately labeled R1+R2 rainfall-domain view: cleaned GitHub-derived refinement, climatological JJAS >=120 mm and >=20% of annual rainfall. This is a descriptive display domain, not an onset mask or a separately calibrated forecast. No official EMI endorsement is implied.','','Smooth contours are for display only; native NetCDF values and statistics remain unchanged. The 0.25-degree common grid is not evidence of new forecast resolution. Country clipping is distinct from a physical land–ocean/lake mask. Source mask metadata is preserved in each forecast NetCDF.','','## Decision and next use','',f'Retain the shared blend. The August regime candidate remains experimental; do not select winning cells using these same operational years. Use this package for review and communication of the retrospective reconstruction. It is not an official EMI/ICPAC product, an observation of {YEAR} rainfall, or a validation of rainfall-driven impact forecasts.','','## Files','','Open index.html locally for maps and download links. forecasts/ contains unchanged copies of the source NetCDFs. maps/ contains PNG/PDF products, native map fields and product metadata. evidence/ contains the experiment summary and any available August review evidence. manifest.json records input, script and output hashes. bundle.zip contains the delivery files except itself and the completion receipt. completion_report.json records the final archive hash.']
    (stage/'BULLETIN.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    esc=html.escape
    cards=[]
    for s in stats:
        t=s['target'];views=['all_ethiopia']+(['jjas_r12_rainfall_domain'] if t=='JJAS' else [])
        p=s['area_mean_local_probabilities']
        pieces=[f'<section id="{t}"><h2>{t} {YEAR}</h2><p class="numbers">Below {p[0]:.1%} · Near {p[1]:.1%} · Above {p[2]:.1%}</p><p>Area averages of local probabilities. Corrected mean rainfall: {s["area_mean_corrected_rainfall_mm"]:.1f} mm; mean anomaly: {s["area_mean_anomaly_mm"]:+.1f} mm.</p><p><a href="forecasts/init05_{t}/forecast_{YEAR}.nc">Forecast NetCDF</a></p>']
        for view in views:
            label='All Ethiopia' if view=='all_ethiopia' else 'Separate JJAS R1+R2 rainfall domain'
            folder=f'maps/init05_{t}/{YEAR}/{view}'
            pieces.append(f'<h3>{label}</h3><div class="maps">')
            for name,caption in [(f'dominant_tercile_{YEAR}','Leading tercile probability'),(f'rainfall_anomaly_mm_{YEAR}','Rainfall anomaly (mm)'),(f'rainfall_anomaly_percent_{YEAR}','Rainfall anomaly (%)')]:
                pieces.append(f'<figure><a href="{folder}/{name}.png"><img loading="lazy" src="{folder}/{name}.png" alt="{esc(t+" "+label+" "+caption)}"></a><figcaption>{caption} · <a href="{folder}/{name}.pdf">PDF</a></figcaption></figure>')
            pieces.append(f'</div><p><a href="{folder}/map_fields_{YEAR}.nc">Native map fields</a> · <a href="{folder}/product_metadata.json">Method and verification metadata</a></p>')
        pieces.append('</section>');cards.append(''.join(pieces))
    page=f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Ethiopia rainfall forecast review — {YEAR}</title><style>body{{margin:0;background:#f1f5f7;color:#162c36;font:16px/1.55 system-ui,sans-serif}}main{{max-width:1280px;margin:auto;padding:30px}}header,section{{background:white;border:1px solid #dbe5e8;border-radius:12px;padding:24px;margin-bottom:24px}}h1{{font-size:32px;line-height:1.2}}h2{{border-bottom:2px solid #daece8;padding-bottom:8px}}h3{{color:#176d62}}a{{color:#075f88}}.tag{{color:#176d62;text-transform:uppercase;letter-spacing:.09em;font-size:13px}}.notice{{background:#fff6df;padding:12px;border-left:4px solid #b77c1d}}.maps{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}}figure{{margin:0}}img{{width:100%;height:auto}}figcaption{{font-size:14px}}.numbers{{font-size:20px;font-weight:600}}nav a{{margin-right:16px}}@media(max-width:850px){{.maps{{grid-template-columns:1fr}}main{{padding:12px}}}}@media print{{section{{break-before:page}}.maps{{grid-template-columns:1fr 1fr}}nav{{display:none}}}}</style><main><header><p class="tag">Research forecast review</p><h1>Ethiopia rainfall outlook · May initialization {YEAR}</h1>'''
    page+=f'<p>{esc(scope)}</p><p class="notice">{esc(STATUS)} Not an official EMI/ICPAC product.</p><p>Selected shared probability blend · CHIRPS reference {REF_DASH} · {MEMBERS} ensemble members</p><p>Click any map to enlarge. Contours are display interpolation; use NetCDF fields for analysis.</p><nav>'+''.join(f'<a href="#{t}">{t}</a>' for t in targets)+'</nav><p><a href="BULLETIN.md">Bulletin and interpretation</a> · <a href="historical_verification.json">Historical verification</a> · <a href="method_decision.json">Method decision</a> · <a href="bundle.zip">Download complete package</a></p></header>'+''.join(cards)+'</main></html>'
    (stage/'index.html').write_text(page,encoding='utf-8')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--targets',nargs='+',choices=TARGETS,default=TARGETS)
    ap.add_argument('--input-root',default='outputs/final_shared_blend')
    ap.add_argument('--forecast',help='Single-target source override; requires exactly one target')
    ap.add_argument('--mask',default='outputs/regime_reconciliation/descriptive_1993_2025/regime_comparison_and_masks.nc')
    ap.add_argument('--boundary',default='data/boundaries/ethiopia/eth_admin0.shp')
    ap.add_argument('--evidence',default='evidence/all_regime_experiments.json')
    ap.add_argument('--output',default=f'outputs/forecast_delivery/init05_{YEAR}')
    ap.add_argument('--check-only',action='store_true')
    ap.add_argument('--regenerate',action='store_true');a=ap.parse_args()
    if a.forecast and len(a.targets)!=1:ap.error('--forecast requires exactly one target')
    try:
        targets,sources,stats,lookup,inputs=preflight(a)
        print('Preflight passed for all requested targets.',flush=True)
        if a.check_only:
            print('Read-only check complete. Run without --check-only to build the delivery package.');return
        out=path(a.output);check_destination(out,a.regenerate)
        created=datetime.now(timezone.utc).isoformat()
        with staged_output(out,a.regenerate) as stage:
            cmd=[sys.executable,str(ROOT/'scripts/delivery_render.py'),'--targets',*targets,'--input-root',str(path(a.input_root)),'--mask',str(path(a.mask)),'--evidence',str(path(a.evidence)),'--boundary',str(path(a.boundary)),'--output-root',str(stage/'maps')]
            if a.forecast:cmd+=['--forecast',str(path(a.forecast))]
            subprocess.run(cmd,check=True,cwd=ROOT)
            (stage/'evidence').mkdir();shutil.copy2(path(a.evidence),stage/'evidence/all_regime_experiments.json')
            supplemental=ROOT/'evidence/august_review'
            if supplemental.is_dir():shutil.copytree(supplemental,stage/'evidence/august_review')
            for t,p in sources.items():
                dest=stage/'forecasts'/f'init05_{t}';dest.mkdir(parents=True);shutil.copy2(p,dest/f'forecast_{YEAR}.nc')
                if sha(dest/f'forecast_{YEAR}.nc')!=inputs[str(p)]:raise ValueError('Source changed during packaging: '+str(p))
            for p,digest in inputs.items():
                if sha(Path(p))!=digest:raise ValueError('Input changed during packaging: '+p)
            docs_source=ROOT/'docs/29_FORECAST_DELIVERY.md'
            if docs_source.is_file():shutil.copy2(docs_source,stage/'WORKFLOW.md')
            documents(stage,targets,stats,verification_rows(targets,lookup),created)
            scripts=['finalize_forecast_delivery.py','delivery_render.py','delivery_map_base.py','delivery_contours.py','delivery_output_runs.py']
            manifest={'created_utc':created,'targets':targets,'complete_five_target_package':set(targets)==set(TARGETS),'status':STATUS,'input_sha256':inputs,'script_sha256':{n:sha(ROOT/'scripts'/n) for n in scripts},'output_sha256':{str(p.relative_to(stage)).replace('\\','/'):sha(p) for p in stage.rglob('*') if p.is_file()}}
            write_json(stage/'manifest.json',manifest)
            with zipfile.ZipFile(stage/'bundle.zip','w',zipfile.ZIP_DEFLATED) as z:
                for p in sorted(stage.rglob('*')):
                    if p.is_file() and p.name!='bundle.zip':z.write(p,p.relative_to(stage))
            write_json(stage/'completion_report.json',{'status':'completed','targets':targets,'complete_five_target_package':set(targets)==set(TARGETS),'forecast_sources_unchanged':True,'source_forecast_copies_byte_identical':True,'bundle_sha256':sha(stage/'bundle.zip'),'bundle_bytes':(stage/'bundle.zip').stat().st_size,'map_views':len(targets)+(1 if 'JJAS' in targets else 0),'created_utc':created})
        print('Completed:',out,flush=True);print('Open:',out/'index.html',flush=True)
    except (ValueError,KeyError,OSError,subprocess.CalledProcessError) as exc:
        print('\nERROR: '+str(exc),file=sys.stderr);sys.exit(2)
if __name__=='__main__':main()
