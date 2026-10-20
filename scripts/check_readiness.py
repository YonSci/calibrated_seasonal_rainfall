"""Readiness of the real-time cycles (docs/52): everything that can be checked before the initialization's SEAS5 exists.

For each cycle (default: `issue_cycles` of config/observation_watch.json):
  configuration  the cycle and its project configuration load; the project's archive years reach the forecast year and its
                 observation years the end of the reference period; the member policy; referenced files exist
  inputs         SEAS5 raw files of every reference year; the CHIRPS archive covers the last reference season; processed
                 files of the reference years (those still missing are made by step 4, prepare_seasonal.py --all-years);
                 SEAS5 SST of the reference years (shadow forecasts and SST inputs)
  leakage        no SEAS5 or CHIRPS file of the forecast year in the project yet (the first is downloaded at step 1)
  shadows        the amount shadow, the bias-correction validation and the statistical-downscaling shadow match the cycle
  issue          the issue window: SEAS5 on the CDS (the 13th of the initialization month) and the first target period;
                 whether the cycle is already issued
  tools          CDS credentials, cdsapi, the GitHub CLI and its login (for issue_forecast.py --publish), free disk space

Statuses: ok; todo (an action needed before the cycle is run or issued, with its date); fail (a defect to fix now).
Nothing is downloaded, run or changed.

  python scripts/check_readiness.py                       # every issue cycle
  python scripts/check_readiness.py --cycle config/cycles/jan_2027_fmam.json
Output: outputs/readiness/readiness.json (and the table on screen)
"""
import argparse
import calendar
import json
import shutil
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GH = Path(r'C:\Program Files\GitHub CLI\gh.exe')
MIN_FREE_GB = 5


def read(p):
    return json.loads((ROOT / p).read_text(encoding='utf-8-sig'))


def season_months(project):
    a, b = int(project['season']['start'][:2]), int(project['season']['end'][:2])
    return [(a - 1 + i) % 12 + 1 for i in range((b - a) % 12 + 1)]


def targets_of(project):
    return [calendar.month_abbr[m] for m in season_months(project)] + [project['season']['name']]


def season_year_months(project, year):
    """(year, month) of every month of the season that starts in `year` (seasons may cross the year)."""
    months = season_months(project)
    out, y = [], year
    for i, m in enumerate(months):
        if i and m < months[i - 1]:
            y += 1
        out.append((y, m))
    return out


def chirps_last_month(project):
    import xarray as xr
    with xr.open_dataset(ROOT / project['chirps_file']) as d:
        t = d.time.values[-1]
    s = str(t)[:7]
    return int(s[:4]), int(s[5:7])


def previous_cycle(init, season, year):
    """The cycle file of the same initialization and season for `year` (whose verification gives that year's observations)."""
    for f in sorted((ROOT / 'config/cycles').glob('*.json')) + [ROOT / 'config/operational.json']:
        try:
            c = json.loads(f.read_text(encoding='utf-8-sig'))
            pr = read(c['project_config'])
        except Exception:
            continue
        if c.get('forecast_year') == year and c.get('initialization_month') == init and pr['season']['name'] == season:
            return dict(c, path=f.relative_to(ROOT).as_posix())
    return None


def check_cycle(path, today):
    rows = []
    add = lambda area, status, text: rows.append(dict(area=area, status=status, text=text))
    try:
        cycle = read(path)
        project = read(cycle['project_config'])
    except Exception as exc:
        add('configuration', 'fail', f'cannot read the cycle or its project configuration: {exc}')
        return rows, None
    year, init = cycle['forecast_year'], cycle['initialization_month']
    ref0, ref1 = cycle['reference_years']
    season = project['season']['name']
    # ---------------------------------------------------------------- configuration
    if project.get('initialization_month') != init:
        add('configuration', 'fail', f"initialization month {init} differs from the project's {project.get('initialization_month')}")
    a0, a1 = project['archive_years']
    o0, o1 = project['observation_years']
    if a1 < year:
        add('configuration', 'fail', f"{cycle['project_config']}: archive_years end {a1}, before the forecast year {year}: "
                                     f'step 4 (prepare_seasonal.py --all-years) would not prepare {year}')
    if o1 < ref1:
        add('configuration', 'fail', f"{cycle['project_config']}: observation_years end {o1}, before the reference period ends "
                                     f'({ref1}): CHIRPS {ref1} would not be prepared')
    if o1 >= year:
        add('configuration', 'fail', f'observation_years reach the forecast year {year}: its observations must not be used')
    if a1 >= year and ref1 <= o1 < year:
        add('configuration', 'ok', f'project years: archive {a0}-{a1}, observations {o0}-{o1}; reference {ref0}-{ref1}')
    mp = cycle.get('member_policy') or {}
    if year >= 2027 and not (mp.get('use_first') == 25 and mp.get('from_year', 9999) <= year):
        add('configuration', 'fail', 'member_policy should use the first 25 members from 2027 (docs/52)')
    elif mp:
        add('configuration', 'ok', f"members: first {mp['use_first']} from {mp['from_year']}")
    for key in ('regime_mask', 'boundary', 'season_domain_mask'):
        if cycle.get(key) and not (ROOT / cycle[key]).exists():
            add('configuration', 'fail', f'{key}: {cycle[key]} is missing')
    # historical_review is optional: the verification report uses it only when it exists
    for m in cycle.get('extra_domain_masks', []):
        if not (ROOT / m['mask']).exists():
            add('configuration', 'fail', f"extra domain mask {m['mask']} is missing")
    bad = [t for t in cycle['targets'] if t not in targets_of(project)]
    if bad:
        add('configuration', 'fail', f'targets {bad} are not targets of {season}')
    # ---------------------------------------------------------------- inputs
    raw = ROOT / project['ecmwf_directory']
    missing = [y for y in range(ref0, ref1 + 1) if not (raw / project['ecmwf_pattern'].format(year=y, month=init)).is_file()]
    add('inputs', 'fail' if missing else 'ok', f'SEAS5 raw files of the reference years: missing {missing}' if missing
        else f'SEAS5 raw files {ref0}-{ref1} present ({raw.relative_to(ROOT)})')
    # observations of the last reference year: from the verified cycle of that year (extend_observations.py, docs/40 section 5)
    # or, without one, from the CHIRPS archive when it covers the season (prepare_seasonal.py --years)
    proc = ROOT / cycle.get('processed_root', 'data/processed')
    prev = previous_cycle(init, season, ref1)
    try:
        ly, lm = chirps_last_month(project)
    except Exception as exc:
        ly, lm = 0, 0
        add('inputs', 'fail', f"cannot read the CHIRPS archive {project['chirps_file']}: {exc}")
    archive_covers = (ly, lm) >= season_year_months(project, ref1)[-1]
    missing_obs = [t for t in cycle['targets'] if not (proc / f'init{init:02d}_{t}' / f'chirps_{ref1}_common.nc').is_file()]
    if not missing_obs:
        add('inputs', 'ok', f'CHIRPS {ref1} (the last reference year) in the training archive')
    elif prev and all((ROOT / prev['verification_root'] / 'observations' / t / f'chirps_{ref1}_common.nc').is_file() for t in missing_obs):
        add('inputs', 'todo', f"CHIRPS {ref1} not yet in the training archive: set CALIBRATION_CYCLE={prev['path']} and run "
                              f"extend_observations.py --year {ref1} --source {prev['verification_root']}/observations "
                              '(--check-only first; docs/40 section 5)')
    elif prev:
        add('inputs', 'todo', f'CHIRPS {ref1}: the {season} {ref1} cycle is not fully verified yet ({prev["path"]}); '
                              'extend_observations.py once every target is verified')
    elif archive_covers:
        add('inputs', 'todo', f'CHIRPS {ref1} not yet prepared: prepare_seasonal.py --years {ref1} (the archive covers the season) '
                              'and the regrid and monthly steps for that year')
    else:
        add('inputs', 'fail', f'CHIRPS {ref1}: no verified cycle of that year and the archive ends {ly}-{lm:02d}')
    absent = {}
    for t in cycle['targets']:
        folder = proc / f'init{init:02d}_{t}'
        for y in range(ref0, ref1):
            for kind in ('ecmwf', 'chirps'):
                if not (folder / f'{kind}_{y}_common.nc').is_file():
                    absent.setdefault(f'{kind} {y}', []).append(t)
        if not (folder / f'ecmwf_{ref1}_common.nc').is_file():
            absent.setdefault(f'ecmwf {ref1}', []).append(t)
    if absent:
        add('inputs', 'fail', 'processed reference-year files missing: ' + '; '.join(f'{k} ({", ".join(v)})' for k, v in sorted(absent.items())))
    else:
        add('inputs', 'ok', f'processed SEAS5 and CHIRPS of every target, {ref0}-{ref1 - 1}, and SEAS5 {ref1} present')
    sst = [y for y in range(ref0, ref1 + 1) if not (ROOT / f'data/raw/ecmwf_sst/init{init:02d}/sst_{y}.nc').is_file()]
    add('inputs', 'todo' if sst else 'ok', f'SEAS5 SST missing for {sst} (scripts/download_seas5_sst.py)' if sst else
        f'SEAS5 SST {ref0}-{ref1} present; the forecast year is downloaded by the shadow forecast')
    # ---------------------------------------------------------------- leakage
    early = [f for f in [raw / project['ecmwf_pattern'].format(year=year, month=init)] if f.is_file()]
    obs = [str(p.relative_to(ROOT)) for t in cycle['targets'] for p in [proc / f'init{init:02d}_{t}' / f'chirps_{year}_common.nc'] if p.is_file()]
    if obs:
        add('leakage', 'fail', f'CHIRPS of the forecast year {year} already in the project: {obs}')
    else:
        add('leakage', 'ok', f'no CHIRPS of {year} in the processed inputs' + ('; SEAS5 of the forecast year already downloaded' if early else ''))
    # ---------------------------------------------------------------- shadows
    for name, cfg_path, extra in (('amount shadow', 'config/probability_calibration/amount_shadow.json', None),
                                  ('statistical-downscaling shadow', 'config/mos/shadow.json', 'from_year')):
        s = read(cfg_path)
        e = next((e for e in s['cycles'] if e['initialization_month'] == init and e['season'] == season), None)
        if e is None:
            add('shadows', 'fail', f'{name}: no entry for {season} from month {init} ({cfg_path})')
        elif extra and year < s.get(extra, 0):
            add('shadows', 'fail', f'{name}: starts in {s[extra]}, after {year}')
        else:
            add('shadows', 'ok', f"{name}: {e['name']}")
    try:
        bv = read('config/bias_correction/validation.json')
        e = next((e for e in bv.get('cycles', []) if e.get('initialization_month') == init and e.get('season') == season), None)
        add('shadows', 'ok' if e else 'todo', f"bias-correction validation: {e['benchmark_config'] if e else 'no entry (validation of the candidates will not run)'}")
    except FileNotFoundError:
        pass
    # ---------------------------------------------------------------- issue window
    cds = date(year, init, 13)
    months = season_year_months(project, year)                 # the season starts in the forecast year
    starts = {calendar.month_abbr[m]: date(y, m, 1) for y, m in months}
    starts[season] = min(starts.values())
    starts = {t: d for t, d in starts.items() if t in cycle['targets']}
    in_season = [t for t, d in starts.items() if d < cds]
    ahead = sorted((d, t) for t, d in starts.items() if d >= cds)
    first_target = min(starts.values())
    issued = (ROOT / cycle['verification_root'] / 'issue_record.json').is_file()
    if issued:
        add('issue', 'ok', 'already issued (issue_record.json)')
    elif today >= max(starts.values()):
        add('issue', 'fail', 'every target period has begun: only a reconstructed forecast is possible')
    else:
        deadline = ahead[0][0] if ahead else max(starts.values())
        note = (f'; {", ".join(in_season)} start before SEAS5 arrives and are issued in season (docs/52)' if in_season else '')
        if today >= deadline:
            add('issue', 'todo', f'overdue: the target period began {deadline}; issue at once (the remaining targets in season)')
        else:
            add('issue', 'todo', f'run from {cds} (SEAS5 on the CDS) and issue before {deadline}{note}: {(deadline - today).days} days '
                                 'from today; the run itself takes about a day')
    return rows, dict(cycle=path, forecast_year=year, season=season, initialization_month=init, cds_date=str(cds),
                      first_target_period=str(first_target))


def check_tools():
    rows = []
    add = lambda status, text: rows.append(dict(area='tools', status=status, text=text))
    rc = Path.home() / '.cdsapirc'
    add('ok' if rc.is_file() else 'fail', 'CDS credentials ~/.cdsapirc ' + ('present' if rc.is_file() else 'missing'))
    try:
        import cdsapi  # noqa: F401
        add('ok', 'cdsapi installed')
    except ImportError:
        add('fail', 'cdsapi not installed (requirements.txt)')
    gh = shutil.which('gh') or (str(GH) if GH.is_file() else None)
    if not gh:
        add('fail', 'GitHub CLI not found (needed by issue_forecast.py --publish)')
    else:
        r = subprocess.run([gh, 'auth', 'status'], capture_output=True, text=True)
        add('ok' if r.returncode == 0 else 'fail', 'GitHub CLI logged in' if r.returncode == 0 else 'GitHub CLI not logged in: gh auth login')
    free = shutil.disk_usage(ROOT).free / 1e9
    add('ok' if free >= MIN_FREE_GB else 'todo', f'free disk space {free:.1f} GB' + ('' if free >= MIN_FREE_GB else
        f' (a cycle needs a few GB: SEAS5 downloads, processed files, outputs; free at least {MIN_FREE_GB} GB)'))
    r = subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True)
    add('ok' if not r.stdout.strip() else 'todo', 'working tree clean' if not r.stdout.strip() else
        'uncommitted changes: issue_forecast.py refuses to issue until code and configuration are committed')
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cycle', nargs='+')
    ap.add_argument('--today', help='YYYY-MM-DD (default: today)')
    a = ap.parse_args()
    today = date.fromisoformat(a.today) if a.today else date.today()
    cycles = a.cycle or read('config/observation_watch.json')['issue_cycles']
    out = dict(checked_utc=datetime.now(timezone.utc).isoformat(), today=str(today), cycles=[], tools=check_tools())
    for c in cycles:
        rows, info = check_cycle(c, today)
        out['cycles'].append(dict(info or dict(cycle=c), checks=rows))
    mark = dict(ok='  ok ', todo=' TODO', fail=' FAIL')
    for c in out['cycles']:
        print(f"\n{c['cycle']}" + (f"  (forecast {c['forecast_year']}, CDS {c['cds_date']}, first target {c['first_target_period']})" if 'cds_date' in c else ''))
        for r in c['checks']:
            print(f"{mark[r['status']]}  {r['area']:<13} {r['text']}")
    print('\ntools')
    for r in out['tools']:
        print(f"{mark[r['status']]}  {r['text']}")
    n = {s: sum(r['status'] == s for c in out['cycles'] for r in c['checks']) + sum(r['status'] == s for r in out['tools']) for s in mark}
    print(f"\n{n['ok']} ok, {n['todo']} to do, {n['fail']} to fix")
    f = ROOT / 'outputs/readiness/readiness.json'
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, indent=1) + '\n', encoding='utf-8')
    print('Saved:', f.relative_to(ROOT))


if __name__ == '__main__':
    main()
