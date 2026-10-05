"""Check official CHIRPS availability; explicitly run complete September/JJAS verification."""
import argparse
import subprocess
import sys
import urllib.error
import urllib.request
from followup_common import *

BASE = 'https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/netcdf/p25/by_month/'
MONTHS = {'Jun': 6, 'Jul': 7, 'Aug': 8, 'Sep': 9}


def probe(url, opener=None):
    """404 means unavailable; transport/server errors are unknown, never readiness."""
    opener = urllib.request.urlopen if opener is None else opener
    try:
        try:
            response = opener(urllib.request.Request(url, method='HEAD'), timeout=20)
        except urllib.error.HTTPError as exc:
            if exc.code != 405:
                raise
            response = opener(urllib.request.Request(url, headers={'Range': 'bytes=0-0'}), timeout=20)
        with response:
            code = response.status
        return {'status': 'available' if code in [200, 206] else 'unknown', 'http_status': code}
    except urllib.error.HTTPError as exc:
        return {'status': 'unavailable' if exc.code == 404 else 'unknown', 'http_status': exc.code, 'detail': str(exc)}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {'status': 'unknown', 'detail': str(exc)}


def availability():
    records = []
    for name, month in MONTHS.items():
        url = BASE + f'chirps-v2.0.2026.{month:02d}.days_p25.nc'
        r = {'month': name, 'url': url, **probe(url)}
        records.append(r)
        print(name, r['status'], flush=True)
    ready = all(r['status'] == 'available' for r in records)
    return {'checked_utc': now(), 'files': records, 'ready_to_attempt_preparation': ready,
            'note': 'Availability alone is not completeness. Step 30 preparation must still pass daily-calendar, historical-overlap, units, grid and observation-support checks. Only CHIRPS v2 official daily p25 files are accepted.'}


def commands(args):
    """The established preparation script creates JJAS only when all four months run."""
    python = sys.executable
    scripts = ROOT / 'scripts'
    common = ['--root', str(path(args.verification_root))]
    regen = ['--regenerate'] if args.regenerate else []
    return [
        [python, str(scripts / 'prepare_verification_2026.py'), '--config', str(path(args.config)),
         '--months', *MONTHS, *common, *regen],
        [python, str(scripts / 'verify_frozen_2026.py'), '--targets', *MONTHS, 'JJAS', *common, *regen],
        [python, str(scripts / 'verify_2026_regimes.py'), '--targets', *MONTHS, 'JJAS',
         '--verification-root', str(path(args.verification_root)), '--mask', str(path(args.mask)), *regen]
    ]


def execute_if_ready(status, args, runner=None):
    runner = subprocess.run if runner is None else runner
    if not status['ready_to_attempt_preparation']:
        print('WAITING: all four official monthly files are not yet confirmed available. Existing verification remains unchanged.', flush=True)
        return False
    if not args.run:
        print('Available. Add --run --regenerate to prepare and verify the complete season.', flush=True)
        return False
    for command in commands(args):
        print('Running:', Path(command[1]).name, flush=True)
        runner(command, cwd=ROOT, check=True)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group()
    group.add_argument('--check', action='store_true', help='Availability check only (default).')
    group.add_argument('--run', action='store_true', help='Run preparation, scoring and regime review only if all months are available.')
    ap.add_argument('--config', default='config/project.json')
    ap.add_argument('--verification-root', default='outputs/verification_2026')
    ap.add_argument('--mask', default='evidence/followup_regime_comparison_and_masks.nc')
    ap.add_argument('--regenerate', action='store_true')
    a = ap.parse_args()
    try:
        root = path(a.verification_root)
        protect_output(ROOT / 'outputs/verification_followup', [root, path(a.config), path(a.mask)])
        snapshot = freeze_snapshot(root)
        status = availability()
        status['frozen_forecasts'] = snapshot
        if a.run and status['ready_to_attempt_preparation']:
            required = [path(a.config), path(a.mask)] + [Path(c[1]) for c in commands(a)]
            missing = [str(p) for p in required if not p.is_file()]
            if missing:
                raise ValueError('Completion inputs/scripts missing: ' + ', '.join(missing))
        status['completed_this_run'] = execute_if_ready(status, a)
        unchanged(root, snapshot)
        dest = ROOT / 'outputs/verification_followup/season_status.json'
        write(dest, status)
        print('Status:', dest, flush=True)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    main()
