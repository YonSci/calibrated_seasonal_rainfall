"""Accepted results: which benchmark result the site publishes for each experiment family and cycle (docs/54, docs/49).

A long benchmark rewrites outputs/probability_calibration/<cycle>/<family>/benchmark.json when it finishes, and an older file
stays in place when a run fails or is still running. File existence therefore does not tell which experiment a result belongs
to, or whether a batch is complete. For the gated families below the site publishes only *accepted* results:

  config/accepted_results.json      the registry: per family/cycle the accepted file's SHA-256, its experiment identifier,
                                    the commit and time it was produced, what was searched and when it was accepted
  outputs/accepted/<family>/<cycle>/<sha16>/   an immutable copy of the accepted benchmark.json and its figures

Acceptance checks every file of a batch first (all cycles of the family; nothing is accepted unless all pass): the expected
five targets, the training and test years, 25 members, every configured model with training and test scores for every
target, a clean-commit provenance, and the experiment's search settings as actually evaluated (read from the fitted models,
not from the code). The site (scripts/site_data.py, scripts/site_prob.py) reads results through resolve(); a newer run in
outputs/ is reported as pending until a batch with it is accepted.

  python scripts/accept_results.py status
  python scripts/accept_results.py accept neural --experiment drn-stage1-v2 --note "architecture x decay search"
  python scripts/accept_results.py accept neural --experiment drn-stage1-v1 --from-release      (the files published before)
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / 'config/accepted_results.json'
ARCHIVE = ROOT / 'outputs/accepted'
OUTPUTS = ROOT / 'outputs/probability_calibration'
GATED = ('neural', 'neural_ext', 'neural_pooled', 'neural_tuning', 'neural_pooled2', 'neural_all', 'neural_fmam_ondj', 'stacking', 'distribution', 'phase3')
CYCLES = ('jan_fmam', 'feb_fmam', 'may_jjas', 'sep_ondj')
TARGETS = 5
TARGETS_OF = {'neural_pooled': 4, 'neural_pooled2': 4, 'neural_all': 4, 'neural_fmam_ondj': 4}   # pooled networks serve the four months, not the season


def gated(reg):
    """The gated families: those of this code and any recorded in the registry (the gate only widens)."""
    return tuple(dict.fromkeys([*GATED, *reg.get('gated', [])]))


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load():
    if REGISTRY.is_file():
        return json.loads(REGISTRY.read_text(encoding='utf-8'))
    return dict(description='Accepted benchmark results published by the site (scripts/accept_results.py).', gated=list(GATED), accepted={})


def save(reg):
    REGISTRY.write_text(json.dumps(reg, indent=1, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')


def searched(d):
    """The configurations actually evaluated, from the fitted models of every target: {model: sorted option labels}."""
    out = {}
    for t in d.get('targets', {}).values():
        for m, f in (t.get('fitted') or {}).items():
            out.setdefault(m, set()).update((f.get('validation_crps') or {}).keys())
    return {m: sorted(v) for m, v in out.items()}


def describe(d):
    cc = d.get('config_contents', {})
    return dict(created_utc=d.get('created_utc'), commit=(d.get('provenance') or {}).get('commit'),
                uncommitted_changes=(d.get('provenance') or {}).get('uncommitted_changes'),
                config=d.get('config'), training_years=d.get('training_years'), test_years=d.get('test_years'),
                members=cc.get('members'), models=d.get('models'), targets=sorted(d.get('targets', {})), searched=searched(d))


def check(d, expect_models=None, targets=TARGETS, family=''):
    """Problems that keep a result from being accepted (empty: complete)."""
    bad = []
    info = describe(d)
    if len(info['targets']) != targets:
        bad.append(f'{len(info["targets"])} targets, expected {targets}')
    if info['training_years'] != [1993, 2016]:
        bad.append(f'training years {info["training_years"]}')
    if not info['test_years'] or info['test_years'][0] != 2017:
        bad.append(f'test years {info["test_years"]}')
    # 25 members (the 2027 policy) for every neural and combined result; the earlier distribution benchmarks (Phases 2 and 3)
    # used all members and are accepted as they were run; stacking combines accepted 25-member results (its members' check)
    if (family.startswith('neural') or info['members'] is not None) and family != 'stacking' and info['members'] != 25:
        bad.append(f'members {info["members"]}, expected 25')
    if info['uncommitted_changes'] is not False:
        bad.append('provenance does not show a clean commit')
    models = expect_models or (d.get('config_contents', {}).get('models') or info['models'] or [])
    used = (d.get('provenance') or {}).get('member_predictions') if family == 'stacking' else None
    for t, x in d.get('targets', {}).items():
        # stacking: the pool and the members it combined for this target (the months and the season use different DRNs)
        for m in (['stack'] + [k.split('/')[-1] for k in used.get(t, {})] if used else models):
            r = (x.get('methods') or {}).get(m)
            if not r or not r.get('training') or not r.get('test'):
                bad.append(f'{t}: no training and test scores for {m}')
    fits = any(t.get('fitted') for t in d.get('targets', {}).values())          # stacking fits nothing itself
    for m in models:
        if fits and m.startswith('drn') and not info['searched'].get(m):
            bad.append(f'{m}: no record of the configurations evaluated')
    return bad


def resolve(family, cycle):
    """(benchmark.json, figures folder) the site publishes for a family and cycle, or None. Families that are not gated
    publish what is in outputs/ (the earlier behaviour)."""
    reg = load()
    src = OUTPUTS / cycle / family
    if family not in gated(reg):
        return (src / 'benchmark.json', src / 'figures') if (src / 'benchmark.json').is_file() else None
    e = reg['accepted'].get(f'{family}/{cycle}')
    if not e:
        return None
    a = ROOT / e['archive']
    if (a / 'benchmark.json').is_file() and sha256(a / 'benchmark.json') == e['sha256']:
        return a / 'benchmark.json', a / 'figures'
    if (src / 'benchmark.json').is_file() and sha256(src / 'benchmark.json') == e['sha256']:
        return src / 'benchmark.json', src / 'figures'
    raise FileNotFoundError(f'accepted {family}/{cycle} ({e["sha256"][:16]}) is neither archived nor in outputs/')


def read_accepted(family, cycle):
    """The accepted result of a family and cycle as a dict (None when nothing is accepted): for the method summary and the
    method selection, so a newer run in outputs/ never enters them before its batch is accepted."""
    try:
        got = resolve(family, cycle)
    except FileNotFoundError:
        return None
    return json.loads(got[0].read_text(encoding='utf-8')) if got else None


def status():
    """Per family and cycle: accepted experiment, and whether outputs/ holds a different (pending) run."""
    reg, rows = load(), []
    for fam in gated(reg):
        for c in CYCLES:
            e = reg['accepted'].get(f'{fam}/{c}')
            cur = OUTPUTS / c / fam / 'benchmark.json'
            h = sha256(cur) if cur.is_file() else None
            pending = None
            if h and (not e or h != e['sha256']):
                d = json.loads(cur.read_text(encoding='utf-8'))
                pending = dict(created_utc=d.get('created_utc'), commit=(d.get('provenance') or {}).get('commit', '')[:7],
                               problems=check(d, targets=TARGETS_OF.get(fam, TARGETS), family=fam))
            rows.append(dict(family=fam, cycle=c, accepted=e and dict(experiment=e['experiment'], created_utc=e['created_utc'],
                                                                      commit=(e['commit'] or '')[:7]), pending=pending))
    return rows


def _git_bytes(rev_path):
    return subprocess.run(['git', 'show', rev_path], cwd=ROOT, capture_output=True, check=True).stdout


def accept(family, experiment, note='', from_release=False, rev='HEAD', code_commit=None, cycles=None):
    """Accept the whole batch of a family (every cycle) or nothing. from_release: the files the site published at `rev`
    (site_data download links and site/assets figures), for results whose outputs/ copy was overwritten by a rerun."""
    reg = load()
    staged = []
    cycles = cycles or CYCLES             # a diagnostic designed for fewer cycles (e.g. the JJAS tuning split) names them explicitly
    with tempfile.TemporaryDirectory() as tmp:
        for c in cycles:
            if from_release:
                meta = json.loads(_git_bytes(f'{rev}:site_data/{family}/{c}.json'))
                url = (meta.get('downloads') or [None])[0]
                if not url or not url.startswith('http'):
                    raise SystemExit(f'{family}/{c}: no release download recorded at {rev}')
                f = Path(tmp) / f'{c}.json'
                with urllib.request.urlopen(url, timeout=120) as r:
                    f.write_bytes(r.read())
                figs = {Path(a).name: _git_bytes(f'{rev}:site/{a}') for a in meta.get('assets', []) if a.endswith('.png')}
            else:
                f = OUTPUTS / c / family / 'benchmark.json'
                if not f.is_file():
                    raise SystemExit(f'{family}/{c}: no result in outputs/')
                figs = {p.name: p.read_bytes() for p in sorted((f.parent / 'figures').glob('*.png'))}
            d = json.loads(f.read_text(encoding='utf-8'))
            bad = check(d, targets=TARGETS_OF.get(family, TARGETS), family=family)
            if bad:
                raise SystemExit(f'{family}/{c} is not complete, nothing accepted:\n  ' + '\n  '.join(bad))
            staged.append((c, f.read_bytes(), figs, d))
        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        for c, raw, figs, d in staged:
            h = hashlib.sha256(raw).hexdigest()
            a = ARCHIVE / family / c / h[:16]
            (a / 'figures').mkdir(parents=True, exist_ok=True)
            (a / 'benchmark.json').write_bytes(raw)
            for n, b in figs.items():
                (a / 'figures' / n).write_bytes(b)
            info = describe(d)
            reg['accepted'][f'{family}/{c}'] = dict(experiment=experiment, sha256=h, archive=a.relative_to(ROOT).as_posix(),
                                                     accepted_utc=now, note=note, figures=sorted(figs), **info,
                                                     code_commit=code_commit or info['commit'])
    reg.setdefault('gated', list(GATED))
    save(reg)
    print(f'accepted {family}: {experiment} for {", ".join(c for c, *_ in staged)}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('status')
    a = sub.add_parser('accept')
    a.add_argument('family', choices=GATED)
    a.add_argument('--experiment', required=True)
    a.add_argument('--note', default='')
    a.add_argument('--from-release', action='store_true')
    a.add_argument('--rev', default='HEAD')
    a.add_argument('--cycles', nargs='+', choices=CYCLES, help='only for an experiment designed for fewer cycles (default: all four)')
    a.add_argument('--code-commit', help='the commit whose code produced the results, when the recorded commits are end-of-run HEADs '
                   'and the benchmark code is verified identical between them')
    x = ap.parse_args()
    if x.cmd == 'status':
        for r in status():
            acc = r['accepted'] and f'{r["accepted"]["experiment"]} ({r["accepted"]["created_utc"][:16]}, {r["accepted"]["commit"]})'
            pen = r['pending'] and f'pending run {r["pending"]["created_utc"][:16]} ({r["pending"]["commit"]})' + (
                f' INCOMPLETE: {"; ".join(r["pending"]["problems"])}' if r['pending']['problems'] else ' complete')
            print(f'{r["family"]:14} {r["cycle"]:9} accepted: {acc or "none"}' + (f' | {pen}' if pen else ''))
    else:
        accept(x.family, x.experiment, x.note, x.from_release, x.rev, x.code_commit, x.cycles)


if __name__ == '__main__':
    sys.exit(main())
