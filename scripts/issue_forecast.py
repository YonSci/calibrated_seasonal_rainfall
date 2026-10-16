"""Issue a cycle's forecast in real time (docs/52): freeze it before its target period and record the issue.

Run as soon as the cycle's forecast files exist (after final_shared_blend.py), before the first day of the target period:

    set CALIBRATION_CYCLE=config\\cycles\\jan_2027_fmam.json
    python scripts/issue_forecast.py                 # checks, freeze, issue record, local git tag
    python scripts/issue_forecast.py --publish       # also pushes the tag and creates the public GitHub release

Refuses when every target period has started, when observations of a target month are already in the project, when a
forecast file is missing, or when code or configuration have uncommitted changes. A target whose period has already begun
is issued *in season* and recorded as such (e.g. February and FMAM of a February-initialized FMAM cycle). The public GitHub release (forecast
NetCDF files, freeze manifest and issue record) carries an independent timestamp: anyone can check the forecast existed,
unchanged, before its season. Never overwrites an existing issue.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from cycle import CYCLE
import forecast_issue as fi

ROOT = Path(__file__).resolve().parents[1]
GH = r'C:\Program Files\GitHub CLI\gh.exe'


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def git(*args, check=True):
    r = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f'git {" ".join(args)} failed: {r.stderr.strip()}')
    return r.stdout.strip()


def forecast_files(cycle):
    tag = f'init{cycle.init_month:02d}'
    return {t: ROOT / cycle.raw['forecast_root'] / f'{tag}_{t}' / str(cycle.year) / f'forecast_{cycle.year}.nc' for t in cycle.targets}


def observed_targets(cycle):
    vr = ROOT / cycle.raw['verification_root'] / 'observations'
    return [t for t in cycle.targets if list((vr / t).glob(f'chirps_{cycle.year}*_common.nc'))]


def checks(cycle, now):
    """The reasons not to issue (empty when the forecast can be issued)."""
    problems = []
    last = fi.last_start(cycle)
    if now.date() >= last:
        problems.append(f'every target period has started (the last on {last.isoformat()}): too late to issue (it stays a reconstruction)')
    if observed_targets(cycle):
        problems.append(f'observations already in the project for {", ".join(observed_targets(cycle))}')
    missing = [t for t, p in forecast_files(cycle).items() if not p.is_file()]
    if missing:
        problems.append(f'forecast files missing for {", ".join(missing)} (run final_shared_blend.py first)')
    dirty = git('status', '--porcelain', '--', 'scripts', 'config', check=False)
    if dirty:
        problems.append('uncommitted changes in scripts/ or config/: commit first so the issue points at the code that made it')
    if fi.read_record(cycle):
        problems.append(f'already issued: {fi.record_path(cycle)}')
    return problems


def freeze(cycle):
    """The existing freeze step (runbook step 10); kept if it exists and still matches the forecast files."""
    manifest = ROOT / cycle.raw['verification_root'] / 'frozen_forecasts' / 'freeze_manifest.json'
    if not manifest.is_file():
        subprocess.run([sys.executable, 'scripts/prepare_verification_2026.py', '--config', cycle.raw['project_config'],
                        '--input-root', cycle.raw['forecast_root'], '--root', cycle.raw['verification_root'], '--freeze-only'],
                       cwd=ROOT, check=True)
    m = json.loads(manifest.read_text(encoding='utf-8'))
    for t, p in forecast_files(cycle).items():
        if m['targets'][t]['sha256'] != sha256(p):
            raise SystemExit(f'the freeze manifest does not match the forecast file of {t}; investigate before issuing')
    return manifest


def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument('--publish', action='store_true', help='push the tag and create the public GitHub release')
    a.add_argument('--check', action='store_true', help='only report whether the forecast can be issued')
    args = a.parse_args()
    now = datetime.now(timezone.utc)
    cycle = CYCLE
    site_id = cycle.raw.get('site_id') or f'{cycle.targets[-1].lower()}{cycle.year}'
    tag = f'forecast-{site_id}'
    rec_path = fi.record_path(cycle)
    if args.publish and rec_path.is_file():                       # publish an issue made earlier (same record, same files)
        return publish(cycle, json.loads(rec_path.read_text(encoding='utf-8')), rec_path)
    problems = checks(cycle, now)
    started = [t for t in cycle.targets if now.date() >= fi.target_start(cycle, t)]
    print(f'{cycle.path.name}: target period starts {fi.period_start(cycle).isoformat()}; '
          + ('ready to issue' + (f' (in season for {", ".join(started)})' if started else '') if not problems else 'cannot issue: ' + '; '.join(problems)))
    if problems or args.check:
        raise SystemExit(1 if problems else 0)
    manifest = freeze(cycle)
    commit = git('rev-parse', 'HEAD')
    record = dict(
        cycle=str(cycle.path.relative_to(ROOT)).replace('\\', '/'), site_id=site_id, forecast_year=cycle.year,
        initialization_month=cycle.init_month, target_period_start=fi.period_start(cycle).isoformat(), issued_utc=now.isoformat(),
        targets={t: dict(period_start=fi.target_start(cycle, t).isoformat(), issued_before_period=now.date() < fi.target_start(cycle, t))
                 for t in cycle.targets},
        members=cycle.members(cycle.year), members_downloaded=cycle.archive_members(cycle.year), commit=commit, tag=tag,
        freeze_manifest=str(manifest.relative_to(ROOT)).replace('\\', '/'), freeze_manifest_sha256=sha256(manifest),
        forecasts={t: dict(file=str(p.relative_to(ROOT)).replace('\\', '/'), sha256=sha256(p)) for t, p in forecast_files(cycle).items()},
        release_url=None,
        statement=('Issued with the published method before the target periods marked issued_before_period, in season for the others; '
                   'no observation of any target period was in the project. The public GitHub release of this tag holds these exact files.'))
    rec_path.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    git('tag', '-a', tag, commit, '-m', f'Forecast {site_id} issued {now.isoformat()} before {record["target_period_start"]}; '
                                        f'freeze manifest {record["freeze_manifest_sha256"]}')
    print(f'Issued: {rec_path} · tag {tag} on {commit[:7]}')
    if args.publish:
        publish(cycle, record, rec_path)
    else:
        print('Publish it before the season starts: python scripts/issue_forecast.py --publish')


def publish(cycle, record, rec_path):
    """Push the tag and create the GitHub release with the frozen files (the independent timestamp)."""
    if record.get('release_url'):
        print(f'Already published: {record["release_url"]}')
        return
    for t, f in record['forecasts'].items():                      # the files must still be the issued ones
        if sha256(ROOT / f['file']) != f['sha256']:
            raise SystemExit(f'{t} changed since it was issued; do not publish')
    git('push', 'origin', record['tag'])
    assets = []
    for t, f in record['forecasts'].items():
        named = rec_path.parent / f'forecast_{record["site_id"]}_{t}.nc'
        named.write_bytes((ROOT / f['file']).read_bytes())
        assets.append(str(named))
    assets += [str(ROOT / record['freeze_manifest']), str(rec_path)]
    notes = (f'Forecast {record["site_id"]} issued {record["issued_utc"]} (target period from {record["target_period_start"]}). '
             f'Commit {record["commit"]}; {record["members"]} of {record["members_downloaded"]} SEAS5 members. {record["statement"]} '
             f'Research forecast; {fi.NOT_OFFICIAL}.')
    r = subprocess.run([GH, 'release', 'create', record['tag'], *assets, '--title', f'Forecast {record["site_id"]}', '--notes', notes],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f'gh release create failed: {r.stderr.strip()}')
    record['release_url'] = r.stdout.strip().splitlines()[-1]
    record['published_utc'] = datetime.now(timezone.utc).isoformat()
    rec_path.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print(f'Published: {record["release_url"]}')


if __name__ == '__main__':
    main()
