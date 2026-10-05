"""Add a verified CHIRPS year to the training archive for the next cycle.

The project CHIRPS file ends in 2025. Verification of a frozen forecast builds the
same-grid seasonal and monthly totals from the official CHIRPS v2.0 p25 monthly
files (after checking their overlap with the archive). This script copies those
totals into data/processed/init05_<target>/chirps_<year>_common.nc in the
training format, so the next cycle can use the year as reference data.

Checks: all targets present, year/target/expected-day metadata, identical grid and
missing-cell pattern to the previous archive year, and JJAS = Jun+Jul+Aug+Sep.
Existing archive files are never overwritten.

    python scripts\\extend_observations.py --year 2026 --source outputs\\verification_2026\\observations
"""
import argparse
import hashlib
from datetime import datetime, timezone
import numpy as np
import xarray as xr
from common import ROOT, source_path, save_netcdf
from cycle import ORDER

MONTHS = ['Jun', 'Jul', 'Aug', 'Sep']


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build(year, target, source_root):
    src = source_root / target / f'chirps_{year}_common.nc'
    dest = ROOT / f'data/processed/init05_{target}/chirps_{year}_common.nc'
    template = ROOT / f'data/processed/init05_{target}/chirps_{year - 1}_common.nc'
    if dest.exists():
        raise FileExistsError(f'{dest} exists; archive files are never overwritten.')
    for p in (src, template):
        if not p.is_file():
            raise FileNotFoundError(p)
    with xr.open_dataset(src) as s, xr.open_dataset(template) as t:
        s, t = s.load(), t.load()
    if int(s.attrs.get('year', -1)) != year or s.attrs.get('target') != target:
        raise ValueError(f'{src}: year/target metadata mismatch')
    if int(s.attrs['expected_days']) != int(t.attrs['expected_days']):
        raise ValueError(f'{src}: expected_days differs from the archive')
    if s.precip_season.attrs.get('units') != 'mm':
        raise ValueError(f'{src}: expected mm')
    if not (np.array_equal(s.lat, t.lat) and np.array_equal(s.lon, t.lon)):
        raise ValueError(f'{src}: grid differs from the archive; no interpolation is allowed')
    new = s.precip_season.values
    old = t.precip_season.isel(year=0).values
    if not np.array_equal(np.isnan(new), np.isnan(old)):
        raise ValueError(f'{src}: missing-cell pattern differs from {template.name}; investigate before extending')
    if (new[np.isfinite(new)] < 0).any():
        raise ValueError(f'{src}: negative totals')
    out = xr.Dataset(coords=dict(year=[year], lat=t.lat, lon=t.lon), attrs=dict(t.attrs))
    out['precip_season'] = (('year', 'lat', 'lon'), new[None].astype('float64'))
    out.precip_season.attrs.update(t.precip_season.attrs)
    out['valid_day_count'] = (('year', 'lat', 'lon'), s.valid_day_count.values[None].astype('int16'))
    out['observation_valid'] = (('year', 'lat', 'lon'), np.isfinite(new)[None].astype('int8'))
    out.observation_valid.attrs.update(t.observation_valid.attrs)
    out.attrs.update(source_file=str(src), source_sha256=sha(src), product=s.attrs.get('product', ''),
                     source_url=s.attrs.get('source_url', ''), season_start=s.attrs.get('season_start', ''),
                     season_end=s.attrs.get('season_end', ''),
                     extended_utc=datetime.now(timezone.utc).isoformat(),
                     note='Promoted from frozen-forecast verification observations (official CHIRPS v2.0 p25 monthly '
                          'files, overlap with the archive checked). Not part of the original 1993-2025 archive file.')
    return dest, out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--year', type=int, required=True)
    p.add_argument('--source', required=True, help='Verification observations folder (contains <target>/chirps_<year>_common.nc)')
    p.add_argument('--check-only', action='store_true')
    a = p.parse_args()
    source = source_path(a.source)
    built = {t: build(a.year, t, source) for t in ORDER}
    months = sum(built[m][1].precip_season.values for m in MONTHS)
    jjas = built['JJAS'][1].precip_season.values
    ok = np.isfinite(jjas)
    err = float(np.max(np.abs(months[ok] - jjas[ok]))) if ok.any() else 0.
    if err > 0.001 + 1e-6 * float(np.nanmax(jjas)):
        raise ValueError(f'JJAS differs from the sum of months by up to {err:.4g} mm')
    print(f'Checks passed for {a.year}: 5 targets, grid and missing-cell pattern match, JJAS-month max difference {err:.2e} mm.')
    if a.check_only:
        print('Check only; nothing written.')
        return
    for t, (dest, ds) in built.items():
        save_netcdf(ds, dest)
        print('Added:', dest)


if __name__ == '__main__':
    main()
