"""Collect uniquely keyed existing/new regime summaries without duplicate ZIP names."""
import json
from common import ROOT,save_json


def main():
    records=[];seen=set()
    for folder,method in [('regime_calibration','current_peak_refinement'),('regime_calibration_github','github_refined_corrected_calendar_v1')]:
        for target in ['JJAS','Jun','Jul','Aug','Sep']:
            for mode in ['training','operational']:
                path=ROOT/'outputs'/folder/f'init05_{target}'/mode/'regime_comparison_summary.json'
                if not path.exists():continue
                report=json.loads(path.read_text(encoding='utf-8-sig'))
                if report['target']!=target or report['mode']!=mode:raise ValueError(f'Metadata mismatch: {path}')
                key=(method,target,mode)
                if key in seen:raise ValueError('Duplicate experiment.')
                seen.add(key);records.append(dict(method=method,target=target,mode=mode,report=report))
    if not records:raise FileNotFoundError('No regime evaluation reports found.')
    path=ROOT/'outputs/all_regime_experiments.json';save_json(path,dict(experiments=records))
    print(f'Collected {len(records)} uniquely identified reports: {path}')


if __name__=='__main__':main()
