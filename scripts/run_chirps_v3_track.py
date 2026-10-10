r"""Run the whole calibration chain with CHIRPS v3 observations (branch chirps-v3, separate worktree).

Same scripts and settings as the published CHIRPS v2.0 chain; only the observation source differs (project configs
point at data/raw/chirps/et/et_chirps3_monthly_r25.nc, "chirps_temporal": "monthly"). Every output lands in this
worktree's own git-ignored folders (data/interim, data/processed, outputs, models), so nothing of the v2 track is
touched. Per cycle: seasonal and monthly preparation, nested historical evaluation (training 1993-2016 and
operational 2017 onwards), the final shared blend, regional skill, historical diagnostics, and the development
calibration with its amount verification. Then the JJAS decision gates.

    python scripts\run_chirps_v3_track.py                 (all cycles)
    python scripts\run_chirps_v3_track.py --cycles ondj   (one)
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
MASK = 'data/masks/ethiopia_common.nc'
CYCLES = {   # name: (cycle file, project config, last complete season)
    'jjas': ('config/operational.json', 'config/project.json', 2025),
    'fmam_jan': ('config/cycles/jan_2026_fmam.json', 'config/fmam/project.json', 2025),
    'fmam_feb': ('config/cycles/feb_2026_fmam.json', 'config/fmam_feb/project.json', 2025),
    'ondj': ('config/cycles/sep_2026_ondj.json', 'config/ondj/project.json', 2024),
}


def steps(cycle, project, last):
    s = lambda name, *args: (name, [PY, f'scripts/{name}.py', *map(str, args)])
    return [
        s('prepare_seasonal', '--config', project, '--all-years'),
        s('regrid_seasonal', '--config', project),
        s('run_monthly', '--config', project, '--stage', 'prepare'),
        s('local_blend', '--config', project, '--mode', 'training', '--region-mask', MASK),
        s('local_blend', '--config', project, '--mode', 'operational', '--region-mask', MASK),
        s('run_monthly', '--config', project, '--stage', 'training'),
        s('run_monthly', '--config', project, '--stage', 'operational'),
        s('final_shared_blend', '--config', project, '--region-mask', MASK),
        s('regional_skill', '--cycle', cycle),
        s('run_calibration', '--config', project, '--mode', 'development', '--last-year', last),
        s('verify_calibration', '--config', project, '--region-mask', MASK, '--region-name', 'Ethiopia', '--last-year', last),
        s('historical_diagnostics', '--cycle', cycle),
    ]


def run(name, command, env, log):
    t0 = time.time()
    with log.open('a', encoding='utf-8') as out:
        out.write(f'\n$ {" ".join(command)}\n')
        out.flush()
        code = subprocess.run(command, cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT).returncode
    print(f'  {name:22s} {"ok" if code == 0 else "FAILED"} ({time.time() - t0:.0f} s)', flush=True)
    if code:
        raise SystemExit(f'{name} failed; see {log}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cycles', nargs='+', choices=list(CYCLES), default=list(CYCLES))
    ap.add_argument('--skip-gates', action='store_true')
    a = ap.parse_args()
    logs = ROOT / 'outputs/v3_track_logs'
    logs.mkdir(parents=True, exist_ok=True)
    for name in a.cycles:
        cycle, project, last = CYCLES[name]
        env = dict(os.environ, CALIBRATION_CYCLE=cycle, PYTHONIOENCODING='utf-8')
        print(f'== {name} ({cycle})', flush=True)
        for step, command in steps(cycle, project, last):
            run(step, command, env, logs / f'{name}.log')
    if not a.skip_gates and 'jjas' in a.cycles:
        print('== decision gates (JJAS)', flush=True)
        run('decision_gates', [PY, 'scripts/decision_gates.py', '--config', 'config/project.json', '--region-mask', MASK],
            dict(os.environ, CALIBRATION_CYCLE='config/operational.json', PYTHONIOENCODING='utf-8'), logs / 'decision_gates.log')
    print('Done.')


if __name__ == '__main__':
    main()
