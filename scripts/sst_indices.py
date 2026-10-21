"""Large-scale and regional inputs for the neural network (docs/54), all available at issue time and not built from the
verification years:

  nino34, dmi   SEAS5 forecast sea-surface temperature indices of the target months (first 25 members; the files of
                scripts/download_seas5_sst.py): Nino 3.4 (5S-5N, 170W-120W) and the Indian Ocean Dipole mode index
                (west 10S-10N, 50E-70E minus east 10S-0, 90E-110E); area means weighted by cos(latitude), in kelvin
                (each input is standardized with the training samples by the network)
  region_1..8   one-hot EMI homogeneous rainfall regions of Korecha & Sorteberg (2013), digitized
                (data/masks/emi_rainfall_regions_korecha2013.nc): a published regionalization, independent of the CHIRPS
                years used here (the project's own regime masks are built from 1993-2025 CHIRPS, held-out years included)

  inputs = extra_inputs(['nino34', 'dmi', 'regions'], target_config, years, lat, lon, idx)
  -> {name: {year: per-cell array}}
"""
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BOXES = dict(nino34=[(-5, 5, 190, 240, 1)], dmi=[(-10, 10, 50, 70, 1), (-10, 0, 90, 110, -1)])
REGIONS = tuple(f'region_{i}' for i in range(1, 9))
REGION_FILE = 'data/masks/emi_rainfall_regions_korecha2013.nc'


def target_months(tc):
    """Calendar months of a target (its season's start and end months; seasons may cross the year)."""
    a, b = int(tc['season']['start'][:2]), int(tc['season']['end'][:2])
    return [(a - 1 + i) % 12 + 1 for i in range((b - a) % 12 + 1)]


def sst_files(init, years):
    return [ROOT / f'data/raw/ecmwf_sst/init{init:02d}/sst_{y}.nc' for y in years]


def ensure_sst(init, years):
    """Download the SEAS5 SST of the years still missing (scripts/download_seas5_sst.py)."""
    missing = [y for y, f in zip(years, sst_files(init, years)) if not f.is_file()]
    if missing:
        subprocess.run([sys.executable, str(ROOT / 'scripts/download_seas5_sst.py'), '--month', str(init),
                        '--years', str(min(missing)), str(max(missing))], cwd=ROOT, capture_output=True, text=True)
    still = [y for y, f in zip(years, sst_files(init, years)) if not f.is_file()]
    if still:
        raise FileNotFoundError(f'SEAS5 SST missing for init {init:02d}, years {still}: run scripts/download_seas5_sst.py')


def index_values(init, months, years):
    """{index: {year: value}} of the SEAS5 SST indices averaged over the target months."""
    import xarray as xr
    leads = [(m - init) % 12 + 1 for m in months]
    out = {k: {} for k in BOXES}
    for y, f in zip(years, sst_files(init, years)):
        with xr.open_dataset(f) as d:
            sst = d.sst.sel(lead_month=leads).mean('lead_month')
            for k, boxes in BOXES.items():
                v = 0.
                for s, n, w, e, sign in boxes:
                    box = sst.sel(lat=slice(n, s) if sst.lat[0] > sst.lat[-1] else slice(s, n), lon=slice(w, e))
                    wts = np.cos(np.deg2rad(box.lat)) * xr.ones_like(box)
                    v += sign * float((box * wts).sum() / wts.where(np.isfinite(box)).sum())
                if not np.isfinite(v):
                    raise ValueError(f'SEAS5 SST {k} of {y} (init {init:02d}) is not finite: check {f.name} (missing values in the box)')
                out[k][y] = v
    return out


def region_onehot(lat, lon, idx):
    """{region_i: 0/1 per cell} on the project grid (cells outside the regions are 0 everywhere)."""
    import xarray as xr
    with xr.open_dataset(ROOT / REGION_FILE) as d:
        r = d.region.sel(lat=xr.DataArray(lat, dims='lat'), lon=xr.DataArray(lon, dims='lon'), method='nearest')
        if not (np.allclose(r.lat, lat) and np.allclose(r.lon, lon)):
            raise ValueError('EMI region grid does not match the project grid')
        cells = r.values.reshape(-1)[idx]
    return {name: (cells == i + 1).astype(float) for i, name in enumerate(REGIONS)}


def extra_inputs(names, tc, years, lat, lon, idx):
    """{input: {year: per-cell array}} for the requested names ('nino34', 'dmi', 'regions')."""
    out = {}
    n = len(idx)
    sst = [k for k in names if k in BOXES]
    if sst:
        init = tc['initialization_month']
        ensure_sst(init, years)
        vals = index_values(init, target_months(tc), years)
        for k in sst:
            out[k] = {y: np.full(n, vals[k][y]) for y in years}
    if 'regions' in names:
        for k, v in region_onehot(lat, lon, idx).items():
            out[k] = {y: v for y in years}
    return out
