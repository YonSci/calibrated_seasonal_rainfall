"""Build a verification addendum from current Step 30/31 outputs; preserve frozen forecasts."""
import argparse
import sys
from followup_common import ROOT, path, read, sha, freeze_snapshot, unchanged, protect_output
from verify2026_outputs import staged_output
from verification_report_core import ORDER, export_report
from cycle import CYCLE, YEAR, REF, REF_DASH, REF_YEARS, MEMBERS, REGIME, REGIME_YEARS, OVERLAP_YEAR, EVALUATION_STUDY


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--targets', nargs='+', choices=ORDER, default=ORDER[:-1])
    ap.add_argument('--verification-root', default=f'outputs/verification_{YEAR}')
    ap.add_argument('--regime-summary', help='Default: matching Step 31 target-combination folder.')
    ap.add_argument('--historical-review', default='outputs/verification_followup/historical/historical_blend_review.json')
    ap.add_argument('--output-root', default=f'outputs/verification_report_{YEAR}')
    ap.add_argument('--regenerate', action='store_true')
    args = ap.parse_args()
    try:
        targets = [t for t in ORDER if t in args.targets]
        tag = '_'.join(targets)
        root = path(args.verification_root)
        regpath = path(args.regime_summary) if args.regime_summary else ROOT / f'outputs/verification_followup/regimes/{tag}/regime_verification_summary.json'
        hp = path(args.historical_review)
        out = path(args.output_root) / tag
        protect_output(out, [root, regpath, hp])
        snapshot = freeze_snapshot(root)
        regimes = read(regpath)
        if regimes['frozen_forecasts']['forecast_sha256'] != snapshot['forecast_sha256'] or regimes['frozen_forecasts']['manifest_sha256'] != snapshot['manifest_sha256']:
            raise ValueError('Regime report belongs to a different frozen assessment')
        country = {'year': YEAR, 'targets': targets, 'results': []}
        inputs = {'regime_verification_summary.json': sha(regpath)}
        maps = {}
        for target in targets:
            folder = root / 'results' / target
            rp = folder / 'verification_report.json'
            fp = folder / 'verification_fields.nc'
            op = root / f'observations/{target}/chirps_{YEAR}_common.nc'
            report = read(rp)
            record = next((r for r in regimes['results'] if r['target'] == target), None)
            if record is None:
                raise ValueError('Missing target in regime report: ' + target)
            provenance = record['provenance']
            if provenance['verification_report_sha256'] != sha(rp) or provenance['verification_fields_sha256'] != sha(fp) or provenance['observations_sha256'] != sha(op):
                raise ValueError('Step 30 inputs changed after Step 31: ' + target + '. Regenerate the matching regime summary first.')
            country['results'].append(report)
            inputs[target + '/verification_report.json'] = sha(rp)
            mp = folder / 'verification_maps.png'
            if mp.is_file():
                maps[target] = mp
        history = read(hp) if hp.is_file() else None
        if history is not None:
            inputs['historical_blend_review.json'] = sha(hp)
        else:
            print('Historical review not found; its section will be explicitly marked unavailable.', flush=True)
        provenance = {'audit_scope': 'Built on the project computer. Frozen forecast hashes checked before and after report construction; Step 30 report, field and observation hashes matched to Step 31. Summary consistency and disjoint-regime reconstruction checked. No new calibration or scoring performed.',
                      'source_sha256': inputs, 'frozen_forecasts': snapshot}
        with staged_output(out, args.regenerate) as stage:
            export_report(country, regimes, history, targets, stage, provenance, maps)
            unchanged(root, snapshot)
        print('Report:', out / 'VERIFICATION_REPORT.html', flush=True)
        print('Forecasts unchanged. Verified targets:', ', '.join(targets), flush=True)
    except (ValueError, KeyError, OSError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    main()
