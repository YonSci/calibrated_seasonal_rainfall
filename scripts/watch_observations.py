"""Score each season as its observations arrive (scheduled daily; docs/49 § Operations).

For every cycle in config/observation_watch.json, ask the operational runner which targets have CHIRPS published
(`run_operational.py --workflow verify --plan`, read-only). When a target becomes ready that was not ready at the last check,
run the verification workflow for the cycle — observations, scores, report, views, the official-outlook comparison when the
cycle enables it, the bias-correction validation of every method and the amount/range shadow — then the steps listed in
`after_scoring` (the bias-correction suggestions). Nothing is published: the site is rebuilt and released separately.

It also reminds about real-time issues (docs/52): for every cycle in `issue_cycles`, from the 13th of its initialization
month (SEAS5 on CDS) until its last target period starts, it logs that the forecast is due and how many days are left,
and it logs a missed issue once every target period has started. It never downloads, runs or issues a forecast itself.

State and history: outputs/observation_watch/status.json (targets ready per cycle, every run with its outcome) and
outputs/observation_watch/watch.log. A failed scoring run is retried at the next check.

  python scripts/watch_observations.py            # check, and score what is new
  python scripts/watch_observations.py --check    # check only, report what would be scored
  python scripts/watch_observations.py --mark-current   # first setup: targets already scored are not rerun
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'config/observation_watch.json'
PY = sys.executable


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


def log(msg, path):
    line = f'{now()}  {msg}'
    print(line, flush=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def ready_targets(cycle):
    """Targets whose verification observations are available (the runner's read-only preflight)."""
    r = subprocess.run([PY, 'scripts/run_operational.py', '--config', cycle, '--workflow', 'verify', '--plan'], cwd=ROOT,
                       capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=1800)
    m = re.search(r'Verification targets ready: (.*)', r.stdout)
    if r.returncode != 0 or not m:
        raise RuntimeError(f'preflight failed for {cycle}: {(r.stderr or r.stdout).strip()[-400:]}')
    return [t.strip() for t in m.group(1).split(',') if t.strip() and t.strip().lower() != 'none']


def score(cycle, logfile):
    c = json.loads((ROOT / cycle).read_text(encoding='utf-8-sig'))
    cmd = [PY, 'scripts/run_operational.py', '--config', cycle, '--workflow', 'verify', '--bias-validation']
    if (c.get('external_comparison') or {}).get('enabled'):
        cmd.append('--compare-external')
    with open(logfile, 'a', encoding='utf-8') as f:
        f.write(f'{now()}  $ {" ".join(cmd[1:])}\n')
        f.flush()
        r = subprocess.run(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
    return r.returncode


def issue_reminders(cycles, logfile, today=None):
    """Due and missed real-time issues of the cycles in `issue_cycles` (docs/52); returns the log lines."""
    from datetime import date
    sys.path.insert(0, str(ROOT / 'scripts'))
    from cycle import load_cycle
    import forecast_issue as fi
    today = today or datetime.now(timezone.utc).date()
    lines = []
    for path in cycles:
        c = load_cycle(ROOT / path)
        due, start, last = date(c.year, c.init_month, 13), fi.period_start(c), fi.last_start(c)
        s = fi.issue_status(c)
        if s['issued']:
            if not s['release_url'] and today < last:
                lines.append(f'{path}: issued {s["date"]} but not yet published; run issue_forecast.py --publish now')
            continue
        if due <= today < last:
            lines.append(f'{path}: ISSUE DUE: run the cycle (docs/40 section 2) and issue_forecast.py; '
                         + (f'{(start - today).days} days before the target period starts ({start})' if today < start
                            else f'the target period began {start}: in season for the targets already started, issue as soon as possible'))
        elif today >= last and not fi.read_record(c):
            lines.append(f'{path}: issue missed (every target period has started); this forecast can only be a reconstruction')
    for line in lines:
        log(line, logfile)
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--check', action='store_true', help='Only report newly available targets')
    ap.add_argument('--mark-current', action='store_true', help='Record the targets ready now as already scored (first setup)')
    a = ap.parse_args()
    cfg = json.loads(CONFIG.read_text(encoding='utf-8'))
    status_path = ROOT / cfg['status']
    status_path.parent.mkdir(parents=True, exist_ok=True)
    logfile = status_path.parent / 'watch.log'
    status = json.loads(status_path.read_text(encoding='utf-8')) if status_path.is_file() else dict(cycles={}, runs=[])
    scored_any = False
    for cycle in cfg['cycles']:
        state = status['cycles'].setdefault(cycle, dict(scored=[], last_check=None))
        try:
            ready = ready_targets(cycle)
        except Exception as exc:
            log(f'{cycle}: {exc}', logfile)
            status['runs'].append(dict(time=now(), cycle=cycle, outcome='preflight failed', detail=str(exc)[:400]))
            continue
        state['last_check'] = now()
        if a.mark_current:
            state['scored'] = ready
            log(f'{cycle}: recorded as already scored: {", ".join(ready) or "none"}', logfile)
            continue
        new = [t for t in ready if t not in state['scored']]
        if not new:
            log(f'{cycle}: nothing new (ready: {", ".join(ready) or "none"})', logfile)
            continue
        log(f'{cycle}: newly available: {", ".join(new)}' + (' (check only)' if a.check else ''), logfile)
        if a.check:
            continue
        code = score(cycle, logfile)
        outcome = 'scored' if code == 0 else f'failed (exit {code}); retried at the next check'
        log(f'{cycle}: {outcome}', logfile)
        status['runs'].append(dict(time=now(), cycle=cycle, targets=new, outcome=outcome))
        if code == 0:
            state['scored'] = sorted(set(state['scored']) | set(ready), key=ready.index)
            state['pending_publication'] = sorted(set(state.get('pending_publication', [])) | set(new))
            scored_any = True
    try:
        issue_reminders(cfg.get('issue_cycles', []), logfile)
    except Exception as exc:                                       # a reminder failure never stops the scoring
        log(f'issue reminders failed: {exc}', logfile)
    if scored_any:
        for step in cfg.get('after_scoring', []):
            r = subprocess.run([PY, step], cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
            log(f'{step}: exit {r.returncode}', logfile)
        log('New scores are ready; rebuild and release the site to publish them.', logfile)
    status_path.write_text(json.dumps(status, indent=1) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
