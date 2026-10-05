"""Re-evaluate GitHub-derived regimes using existing nested calibration workflow.

Uses year-wise CHIRPS cache; never uses a full-baseline descriptive mask to fit
or evaluate past years. Separate outputs; does not change operational forecasts.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import xarray as xr
from common import ROOT,load_config,source_path,save_json,save_netcdf
from output_runs import staged_output
from prepare_regimes import RegimeCache,CACHE,load_region,sha256
from regime_core import diagnose,TARGETS
from github_regime_core import classify,LABELS,METHOD,SOURCE_URL,onset_layers
import run_regime_calibration as base


class GithubRegimeCache(RegimeCache):
    def __init__(self,path,region):
        super().__init__(path,region);self.github_memo={}
    def fit(self,years):
        key=tuple(sorted(years))
        if key not in self.memo:
            q,m=self.means(key);current=diagnose(q,m,self.region)
            github=classify(q,self.lat,self.lon,self.region);self.github_memo[key]=github
            current['regime']=github['regime_cleaned'];current['refinement_reason']=github['regime_raw']
            # Keep original threshold-only seasonal relevance for like-for-like reports.
            self.memo[key]=current
        return self.memo[key]


def baseline_check(report,path):
    if not path.exists():return dict(available=False,note='Prior current-peak evaluation not found; run it for a direct baseline reproduction check.')
    old=json.loads(path.read_text(encoding='utf-8-sig'))
    if old['target']!=report['target'] or old['mode']!=report['mode'] or old['evaluation_years']!=report['evaluation_years']:raise ValueError('Prior comparison years/target/mode differ.')
    worst=0.
    for oldr,newr in zip(old['years'],report['years']):
        a=oldr['domains']['all_country'];b=newr['domains']['all_country']
        if a['probability_cells']!=b['probability_cells']:raise ValueError('Prior shared-baseline support counts changed; inspect inputs.')
        for method in ['climatology','smooth','shared_blend']:
            for metric in ['rps','log_loss','brier_by_category']:
                x=np.asarray(a['probability'][method][metric]);y=np.asarray(b['probability'][method][metric])
                worst=max(worst,float(np.max(np.abs(x-y))))
                if not np.allclose(x,y,atol=1e-10,rtol=1e-9):raise ValueError('Prior baseline scores differ; do not attribute changes solely to regime definitions.')
    return dict(available=True,passed=True,maximum_absolute_metric_difference=worst,source_sha256=sha256(path))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',default='config/project.json');p.add_argument('--region-mask',default='data/masks/ethiopia_common.nc');p.add_argument('--land-mask');p.add_argument('--targets',nargs='+',choices=list(TARGETS),default=['JJAS']);p.add_argument('--mode',choices=['training','operational'],default='training');p.add_argument('--regenerate',action='store_true');args=p.parse_args()
    cfg=load_config(args.config);mask=load_region(args.region_mask);region=(mask.values==1).ravel()
    cache=GithubRegimeCache(CACHE/'chirps_calendar_cache.nc',region)
    if not np.array_equal(cache.lat,mask.lat) or not np.array_equal(cache.lon,mask.lon):raise ValueError('Country/cache grid mismatch.')
    if str(source_path(cfg['chirps_file']))!=cache.attrs['source_path']:raise ValueError('CHIRPS source differs from cache; rebuild preparation first.')
    cache.attrs.update(cache_sha256=sha256(CACHE/'chirps_calendar_cache.nc'),evaluation_country_mask_sha256=sha256(source_path(args.region_mask)),classification_method=METHOD,classification_source=SOURCE_URL)
    base.REGIMES=LABELS
    for target in args.targets:
        tag=f'init05_{target}';out=ROOT/'outputs/regime_calibration_github'/tag/args.mode
        with staged_output(out,args.regenerate) as stage:
            base.run(base.target_config(cfg,target),cache,region,args.mode,args.land_mask,stage)
            report=json.loads((stage/'regime_comparison_summary.json').read_text())
            report['classification_method']=METHOD;report['classification_source']=SOURCE_URL
            report['classification_note']='GitHub threshold/priority/cleanup rules on corrected noleap climatology. base settings describe unchanged probability fit and auxiliary peak diagnostics, not this classifier.'
            report['code_sha256'].update({n:sha256(Path(__file__).parent/n) for n in ['github_regime_core.py','evaluate_github_regimes.py']})
            report['baseline_reproduction']=baseline_check(report,ROOT/'outputs/regime_calibration'/tag/args.mode/'regime_comparison_summary.json')
            with xr.open_dataset(stage/'regime_probabilities_and_weights.nc') as ds:d=ds.load()
            extra={k:[] for k in ['regime_raw','cleanup_changed','jjas_r12_rainfall','jjas_r12_rainfall_cleaned','onset_candidate_r2']}
            extra['onset_eligibility_r2']=[]
            for row in report['years']:
                g=cache.github_memo[tuple(row['training_years'])]
                for k in extra:
                    value=onset_layers(g,region)['onset_eligibility_r2'] if k=='onset_eligibility_r2' else g[k]
                    extra[k].append(value.reshape(len(cache.lat),len(cache.lon)))
            for k,v in extra.items():d['github_'+k]=(('year','lat','lon'),np.asarray(v).astype('int8'))
            d.attrs.update(classification_method=METHOD,classification_source=SOURCE_URL,onset_note='No onset evidence supplied for fold-specific evaluation; -1 unknown, 0 excluded. Never used for calibration support.')
            d.refinement_reason.attrs['note']='GitHub pre-cleanup classification code; compare regime for post-cleanup code.'
            save_netcdf(d,stage/'regime_probabilities_and_weights.nc');save_json(stage/'regime_comparison_summary.json',report)
        print('Ready:',out,flush=True)


if __name__=='__main__':main()
