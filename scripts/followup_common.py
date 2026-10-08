"""Shared utilities for Step 31. No forecast or calibration writes."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from cycle import CYCLE, YEAR, REF, REF_DASH, REF_YEARS, MEMBERS, REGIME, REGIME_YEARS, OVERLAP_YEAR, EVALUATION_STUDY

ROOT = Path(__file__).resolve().parents[1]
from cycle import SEASON, SEASON_MONTHS
TARGETS = [SEASON, *SEASON_MONTHS]          # e.g. JJAS, Jun, Jul, Aug, Sep
METHOD = 'github_refined_corrected_calendar_v1'
METHODS = ['climatology', 'smooth', 'shared_blend']
CATS = ['below', 'near', 'above']
LABELS = {'-1': 'Missing climatology', '0': 'R0: arid / marginal',
          '1': 'R1: western unimodal residual', '2': 'R2: Belg–Kiremt highland rule',
          '3': 'R3: Gu–Deyr lowland rule', '4': 'Unused refinement class'}


def path(value):
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def write(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, allow_nan=False), encoding='utf-8')


def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def protect_output(output, inputs):
    """Reject a destination that contains an input or is inside protected inputs."""
    out = Path(output).resolve()
    protected = [ROOT / 'outputs/final_shared_blend', ROOT / 'data', ROOT / 'config', ROOT / 'scripts', ROOT / 'evidence']
    for item in [*inputs, *protected]:
        p = Path(item).resolve()
        if p == out or p.is_relative_to(out) or (p.is_dir() and out.is_relative_to(p)):
            raise ValueError(f'Output overlaps protected input: {p}')


def freeze_snapshot(root):
    """Verify all five frozen bytes against their existing manifest; never create it."""
    root = Path(root)
    manifest = root / 'frozen_forecasts/freeze_manifest.json'
    if not manifest.is_file():
        raise ValueError('Step 30 freeze is missing. Run prepare_verification_2026.py first: ' + str(manifest))
    m = read(manifest)
    if m.get('evaluation_year') != YEAR or m.get('training_years') != f'{REF}':
        raise ValueError('Unexpected frozen forecast baseline or evaluation year')
    result = {'manifest_sha256': sha(manifest), 'forecast_sha256': {}, 'original_sources_checked': {}}
    for target in TARGETS:
        p = root / f'frozen_forecasts/{CYCLE.tag}_{target}/forecast_{YEAR}.nc'
        if sha(p) != m['targets'][target]['sha256']:
            raise ValueError('Frozen forecast has changed: ' + target)
        result['forecast_sha256'][target] = sha(p)
        original = Path(m['targets'][target].get('source', '__not_available__'))
        available = original.is_file()
        if available and sha(original) != m['targets'][target]['sha256']:
            raise ValueError('Original final forecast differs from frozen snapshot: ' + target)
        result['original_sources_checked'][target] = available
    return result


def unchanged(root, snapshot):
    if freeze_snapshot(root) != snapshot:
        raise ValueError('Frozen inputs changed while the review was running')


def same_grid(a, b):
    for key in ['lat', 'lon']:
        if not np.array_equal(a[key].values, b[key].values):
            raise ValueError('Grid mismatch: ' + key + '; no automatic regridding is allowed')


def area(d):
    for key in ['lat', 'lon']:
        v = np.asarray(d[key], float)
        if len(v) < 2 or not np.isfinite(v).all() or not np.allclose(np.diff(v), .25, atol=1e-7, rtol=0):
            raise ValueError('Expected ascending regular 0.25-degree project grid')
    return np.broadcast_to(np.cos(np.deg2rad(d.lat.values.astype(float)))[:, None], (d.sizes['lat'], d.sizes['lon']))


def skill(score, baseline):
    return float(1 - score / baseline) if baseline > 0 else None


def paired_summary(delta):
    delta = np.asarray(delta, float)
    n = len(delta)
    if not n:
        return {'years': 0, 'mean': None, 'whole_year_bootstrap_95_interval': None}
    interval = None
    if n >= 5:
        rng = np.random.default_rng(3104)
        draws = rng.integers(n, size=(5000, n))
        interval = np.quantile(delta[draws].mean(1), [.025, .975]).tolist()
    return {'years': n, 'mean': float(delta.mean()),
            'years_blend_better': int((delta < -1e-12).sum()),
            'years_blend_worse': int((delta > 1e-12).sum()),
            'whole_year_bootstrap_95_interval': interval,
            'note': 'Paired whole-year resampling of existing scores; descriptive, ignores serial dependence, overlapping fits and model selection. No interval for fewer than five years.'}
