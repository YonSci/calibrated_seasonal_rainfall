"""Score each season as its observations arrive (scheduled daily; docs/49 § Operations).

For every cycle in config/observation_watch.json, ask the operational runner which targets have CHIRPS published
(`run_operational.py --workflow verify --plan`, read-only). When a target becomes ready that was not ready at the last check,
run the verification workflow for the cycle — observations, scores, report, views, the official-outlook comparison when the
cycle enables it, the bias-correction validation of every method and the amount/range shadow — then the steps listed in
`after_scoring` (the bias-correction suggestions). Nothing is published: the site is rebuilt and released separately.

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
    if scored_any:
        for step in cfg.get('after_scoring', []):
            r = subprocess.run([PY, step], cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
            log(f'{step}: exit {r.returncode}', logfile)
        log('New scores are ready; rebuild and release the site to publish them.', logfile)
    status_path.write_text(json.dumps(status, indent=1) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
