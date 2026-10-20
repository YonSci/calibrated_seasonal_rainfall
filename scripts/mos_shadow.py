"""Shadow statistical-downscaling forecasts (CCA, PCR; docs/53): the independent validation seasons of the MOS candidates.

Never a published forecast. For one cycle file (one forecast year, from config/mos/shadow.json `from_year` on), both methods
are fitted on the cycle's reference years exactly as in the benchmark (version 2: first 25 members, SST / rainfall fields
chosen by inner leave-one-year-out, leverage spread, climatology blend) and forecast every target of the forecast year. The
published probabilities are recomputed by the same code and the MVS-corrected ensemble is computed, for comparison.

The forecast is frozen the first time it is made (normally when the cycle is run, before its season): later runs reuse the
saved arrays while the forecast inputs are unchanged, and only score them once the target's CHIRPS exists. Each record keeps
the time the forecast was made and whether the observation already existed then.

The SEAS5 sea-surface temperature of a missing year is downloaded first (scripts/download_seas5_sst.py). A target that cannot
be forecast (for example SST not yet on the CDS) is recorded in status.json and retried at the next run: this script never
fails a cycle run.

Results: <output_root>/<year>/<method>__<target>.json, forecast_<target>.npz, status.json.

  python scripts/mos_shadow.py --cycle config/cycles/may_2027.json
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def parse():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--cycle', default='config/operational.json', help='operational cycle file (one forecast year)')
    p.add_argument('--config', default='config/mos/shadow.json')
    p.add_argument('--targets', nargs='+')
    return p.parse_args()


ARGS = parse() if __name__ == '__main__' else None
ROOT_DIR = Path(__file__).resolve().parents[1]
if ARGS is not None:
    os.environ.setdefault('CALIBRATION_CYCLE', str((ROOT_DIR / ARGS.cycle).resolve()))

from common import ROOT, load_config, save_json                         # noqa: E402

CODE = ['scripts/mos_shadow.py', 'scripts/mos_benchmark.py', 'scripts/download_seas5_sst.py', 'scripts/leung_dirichlet_benchmark.py',
        'scripts/prob_calibration.py', 'scripts/prob_benchmark.py', 'scripts/bias_methods.py', 'scripts/run_calibration.py']
METHODS = ('cca', 'pcr')


def read(p):
    return json.loads((ROOT / p).read_text(encoding='utf-8'))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def entry_for(scfg, project):
    return next((e for e in scfg['cycles'] if e['initialization_month'] == project['initialization_month']
                 and e['season'] == project['season']['name']), None)


def ensure_sst(init, years):
    """Download the SEAS5 SST of the years still missing (one request per chunk; the CDS queues requests)."""
    import mos_benchmark as mb
    missing = [y for y, f in zip(years, mb.sst_files(init, years)) if not f.is_file()]
    if missing:
        r = subprocess.run([sys.executable, str(ROOT / 'scripts/download_seas5_sst.py'), '--month', str(init),
                            '--years', str(min(missing)), str(max(missing))], cwd=ROOT, capture_output=True, text=True)
        still = [y for y, f in zip(years, mb.sst_files(init, years)) if not f.is_file()]
        if still:
            raise RuntimeError(f'SEAS5 SST unavailable for init {init:02d}, years {still}: {r.stderr.strip()[-300:]}')


def forecast_key(cycle_path, scfg_path, entry, cycle, project, target, years):
    """Everything the forecast depends on (not the observation): code, configurations, masks, model inputs, SST files."""
    import mos_benchmark as mb
    from bias_benchmark import target_config
    mcfg = read(entry['mos_config'])
    bench = read(mcfg['benchmark_config'])
    tc = target_config(project, target)
    h = hashlib.sha256(json.dumps(dict(target=target, entry=entry, settings=mcfg['settings']), sort_keys=True).encode())
    for f in [*CODE, cycle_path, scfg_path, entry['mos_config'], mcfg['benchmark_config'], cycle['project_config'],
              bench['cells']['path'], *[v['path'] for v in bench['regions'].values()]]:
        h.update(str(f).encode() + sha256(ROOT / f).encode())
    folder = ROOT / cycle.get('processed_root', 'data/processed') / f"init{tc['initialization_month']:02d}_{tc['season']['name']}"
    ref = years[:-1]
    for f in [folder / f'ecmwf_{y}_common.nc' for y in years] + [folder / f'chirps_{y}_common.nc' for y in ref] + \
            list(mb.sst_files(tc['initialization_month'], years)):
        h.update(f.name.encode() + sha256(f).encode())
    return h.hexdigest()


def run_target(cycle_path, scfg_path, scfg, entry, target):
    import mos_benchmark as mb
    import bias_benchmark as bb
    from run_calibration import load_inputs, cell_area
    cycle = read(cycle_path)
    project = load_config(cycle['project_config'])
    mcfg = read(entry['mos_config'])
    bench = read(mcfg['benchmark_config'])
    s = mcfg['settings']
    year = cycle['forecast_year']
    ref = list(range(cycle['reference_years'][0], cycle['reference_years'][1] + 1))
    tc = bb.target_config(project, target)
    if any('sst' in f for f in s.get('fields', [])):
        ensure_sst(tc['initialization_month'], ref + [year])
    folder = ROOT / scfg['output_root'].format(name=entry['name']) / str(year)
    folder.mkdir(parents=True, exist_ok=True)
    key = forecast_key(cycle_path, scfg_path, entry, cycle, project, target, ref + [year])
    arrays = folder / f'forecast_{target}.npz'
    meta = folder / f'forecast_{target}.json'
    tag, models, obs, _, lat, lon = load_inputs(tc, ref + [year], ref)
    idx = np.flatnonzero(bb.load_mask(bench['cells'], lat, lon))
    m = json.loads(meta.read_text(encoding='utf-8')) if meta.is_file() else {}
    if arrays.is_file() and m.get('key') == key:                       # the frozen forecast
        with np.load(arrays) as z:
            v = dict(probs={k: z[f'p_{k}'] for k in m['probabilities']}, ens={k: z[f'e_{k}'] for k in m['ensembles']},
                     O=z['O'], q1=z['q1'], q2=z['q2'], primary=z['primary'], area=z['area'], year=year)
        created, observed_at_creation, choices = m['created_utc'], m['observed_at_creation'], m.get('choices')
    else:
        area_all = cell_area(lat, lon)
        primary = bb.load_mask(bench['regions'][bench['primary_region']], lat, lon)[idx]
        Xall, widths = mb.predictors(s, tc, {z: models[z][:s.get('members')] for z in models}, sorted(ref + [year]), (len(lat), len(lon)))
        v, choices = mb.forecast_validation(mcfg, dict(bench, cycle=cycle_path), {z: models[z][:s.get('members')] for z in models}, obs,
                                            lat, lon, idx, Xall, widths, dict(bench['methods'].get('mvs', {})), area_all, primary,
                                            with_choices=True)
        created = datetime.now(timezone.utc).isoformat()
        from bias_validation import observation_path
        observed_at_creation = observation_path(cycle, target, year).is_file()
        np.savez_compressed(arrays, O=v['O'], q1=v['q1'], q2=v['q2'], primary=v['primary'], area=v['area'],
                            **{f'p_{k}': p for k, p in v['probs'].items()}, **{f'e_{k}': e for k, e in v['ens'].items()})
        save_json(meta, dict(key=key, created_utc=created, observed_at_creation=observed_at_creation, target=target, forecast_year=year,
                             reference_years=cycle['reference_years'], probabilities=list(v['probs']), ensembles=list(v['ens']),
                             choices=choices))
    scores = mb.validate_target(cycle, target, v, lat, lon, idx)
    from bias_benchmark import git
    prov = dict(commit=git('rev-parse', 'HEAD'), uncommitted_changes=bool(git('status', '--porcelain', '--', *CODE, cycle_path, scfg_path)))
    for k in METHODS:
        save_json(folder / f'{k}__{target}.json',
                  dict(method=k, label=mb.LABELS[k], target=target, cycle=Path(cycle_path).as_posix(), forecast_year=year, shadow=True,
                       since=scfg['since'], forecast_created_utc=created, observed_at_creation=observed_at_creation,
                       choice=(choices or {}).get(k), primary_region=bench['primary_region'], observed=scores is not None,
                       scores=None if scores is None else dict(
                           rps=dict(method=scores['rps'][k], published=scores['rps']['incumbent'], climatology=scores['rps_clim']),
                           crps=dict(method=scores['crps'][k], mvs_ensemble=scores['crps']['mvs_ensemble'], climatology=scores['crps_clim']),
                           cells=scores['cells'], amount_cells=scores['amount_cells'], observation=scores['observation']),
                       provenance=prov, scored_utc=datetime.now(timezone.utc).isoformat() if scores else None))
    return 'scored' if scores is not None else 'forecast saved, not yet observed'


def main(args):
    scfg = read(args.config)
    cycle = read(args.cycle)
    project = load_config(cycle['project_config'])
    entry = entry_for(scfg, project)
    year = cycle['forecast_year']
    if entry is None or year < scfg.get('from_year', 0):
        print(f'No MOS shadow for {args.cycle} (forecast year {year}; shadows from {scfg.get("from_year")}).')
        return
    folder = ROOT / scfg['output_root'].format(name=entry['name']) / str(year)
    folder.mkdir(parents=True, exist_ok=True)
    status = {}
    for t in args.targets or cycle['targets']:
        try:
            status[t] = run_target(args.cycle, args.config, scfg, entry, t)
        except Exception as exc:                        # recorded and retried at the next run; never fails the cycle run
            status[t] = f'failed: {exc!r}'
            traceback.print_exc()
        print(f'{entry["name"]} {year} {t}: {status[t]}', flush=True)
    save_json(folder / 'status.json', dict(cycle=Path(args.cycle).as_posix(), forecast_year=year, targets=status,
                                           updated_utc=datetime.now(timezone.utc).isoformat()))


if __name__ == '__main__':
    main(ARGS)
