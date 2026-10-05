"""Bundle JJAS and monthly local summary reports into one small labelled JSON."""
import argparse
from common import ROOT, save_json
import json


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=['training','operational'],default='training')
    args=p.parse_args();reports=[];missing=[]
    for target in ['JJAS','Jun','Jul','Aug','Sep']:
        relative=f'outputs/local_calibration/init05_{target}/{args.mode}/local_comparison_summary.json'
        path=ROOT/relative
        if not path.exists():missing.append(relative);continue
        d=json.loads(path.read_text(encoding='utf-8-sig'))
        if d.get('mode')!=args.mode:raise ValueError(f'Mode mismatch: {path}')
        if not all(k in d.get('equal_year_summary',{}) for k in ['shared_blend','local_blend','regularized_local_blend']):
            raise ValueError(f'Not a local comparison summary: {path}')
        if 'target_period' in d and d['target_period']['name']!=target:raise ValueError(f'Target mismatch: {path}')
        reports.append(dict(target=target,source=relative,report=d))
    if not reports:raise FileNotFoundError('No local summary reports found.')
    out=ROOT/f'outputs/local_calibration/all_local_summaries_{args.mode}.json'
    save_json(out,dict(mode=args.mode,reports=reports,missing=missing,
                      note='Target labels follow project folder names. This bundles summaries only and does not recompute results.'))
    print('Saved:',out)
    print('Included:',', '.join(r['target'] for r in reports))
    for path in missing:print('Missing:',path)


if __name__=='__main__':main()
