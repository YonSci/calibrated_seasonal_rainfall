r"""CHIRPS v3.0 monthly rainfall on the project's 0.25 degree Ethiopia grid (parallel v3 track; v2 is unchanged).

CHIRPS v3 is published at 0.05 degrees only (no p25 product). Its native product is monthly (blended with
stations); daily values are disaggregated from pentads, and every target of this project is a whole month or
a season of whole months, so the v3 track works from monthly totals.

    official monthly GeoTIFF (Africa, 0.05 deg, LZW)  ->  geotags checked  ->  5 x 5 block mean onto the
    0.25 deg cells of the existing grid (edges at multiples of 0.25 deg, so the blocks align exactly)

A 0.25 deg cell gets the mean of its valid 0.05 deg cells when at least `--min-valid` of the 25 are valid
(-9999 is missing), otherwise it is missing; the valid count is stored. Every download keeps a receipt
(URL, size, SHA-256, Last-Modified) and is reused only while it still matches.

    python scripts\prepare_chirps_v3.py --first 1993-01 --last 2026-08
"""
import argparse
import hashlib
import http.client
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://data.chc.ucsb.edu/products/CHIRPS/v3.0/monthly/africa/tifs/'
PIXEL, WEST, NORTH, SHAPE = 0.05, -20.0, 40.0, (1600, 1500)        # the Africa tiles' grid, checked per file
GRID = ROOT / 'data/raw/chirps/et/et_chirps_pr_r25_1993_2025.nc'     # the project grid (lat/lon only are read)
CACHE = ROOT / 'data/raw/chirps/v3/africa_monthly'
OUT = ROOT / 'data/raw/chirps/et/et_chirps3_monthly_r25.nc'


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def months(first, last):
    y, m = map(int, first.split('-'))
    ly, lm = map(int, last.split('-'))
    while (y, m) <= (ly, lm):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def fetch(y, m, cache):
    """One official monthly file, downloaded once; the receipt must match the file on disk."""
    name = f'chirps-v3.0.{y}.{m:02d}.tif'
    dest, receipt = cache / name, cache / (name + '.download.json')
    if dest.is_file() and receipt.is_file():
        r = json.loads(receipt.read_text(encoding='utf-8'))
        if r.get('sha256') == sha(dest) and r.get('url') == BASE + name:
            return dest
    cache.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix('.part')
    for attempt in range(1, 6):          # the server sometimes drops a transfer: retry with a short back-off
        try:
            with urllib.request.urlopen(BASE + name, timeout=120) as resp:
                body = resp.read()
                size, modified = resp.headers.get('Content-Length'), resp.headers.get('Last-Modified')
            if size and len(body) != int(size):
                raise ValueError('incomplete download')
            part.write_bytes(body)
            part.replace(dest)
            receipt.write_text(json.dumps(dict(url=BASE + name, bytes=len(body), sha256=hashlib.sha256(body).hexdigest(),
                                               http_last_modified=modified, retrieved_utc=now(),
                                               product='CHIRPS v3.0 monthly, Africa, 0.05 deg GeoTIFF (final)'), indent=1),
                               encoding='utf-8')
            return dest
        except urllib.error.HTTPError as exc:
            if exc.code < 500 or attempt == 5:     # a missing file is final; a server error is retried
                raise
            time.sleep(10 * attempt)
        except (OSError, ValueError, http.client.HTTPException):
            if attempt == 5:
                raise
            time.sleep(5 * attempt)
        finally:
            if part.exists():
                part.unlink()


def read_block(path, lat, lon):
    """The 0.05 deg values covering the 0.25 deg grid, as (nlat, 5, nlon, 5) with NaN for missing."""
    import tifffile
    with tifffile.TiffFile(path) as t:
        page = t.pages[0]
        scale = page.tags['ModelPixelScaleTag'].value
        tie = page.tags['ModelTiepointTag'].value
        if page.shape != SHAPE or abs(scale[0] - PIXEL) > 1e-6 or abs(scale[1] - PIXEL) > 1e-6 or \
                abs(tie[3] - WEST) > 1e-6 or abs(tie[4] - NORTH) > 1e-6:
            raise ValueError(f'{path.name}: unexpected grid {page.shape}, scale {scale[:2]}, origin {tie[3:5]}')
        a = page.asarray().astype('float64')
    a[a < 0] = np.nan                                       # -9999: missing (ocean / no data)
    half = 0.125
    south, north = float(lat.min()) - half, float(lat.max()) + half
    west, east = float(lon.min()) - half, float(lon.max()) + half
    r0, r1 = round((NORTH - north) / PIXEL), round((NORTH - south) / PIXEL)
    c0, c1 = round((west - WEST) / PIXEL), round((east - WEST) / PIXEL)
    sub = a[r0:r1, c0:c1][::-1]                             # south to north, like the project grid
    return sub.reshape(len(lat), 5, len(lon), 5)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--first', default='1993-01')
    ap.add_argument('--last', default='2026-08')
    ap.add_argument('--min-valid', type=int, default=13, help='valid 0.05 deg cells needed out of 25 (default: a majority)')
    ap.add_argument('--workers', type=int, default=2)
    ap.add_argument('--out', default=str(OUT))
    a = ap.parse_args()
    with xr.open_dataset(GRID) as g:
        lat, lon = g.lat.values.astype('float64'), g.lon.values.astype('float64')
    if not (np.allclose(np.diff(lat), .25) and np.allclose(np.diff(lon), .25) and np.allclose((lat - .125) % .25, 0)):
        raise ValueError('The project grid is not a 0.25 deg grid with edges at multiples of 0.25 deg')
    todo = list(months(a.first, a.last))
    with ThreadPoolExecutor(a.workers) as pool:
        paths = list(pool.map(lambda ym: fetch(*ym, CACHE), todo))
    print(f'{len(paths)} monthly files ready in {CACHE.relative_to(ROOT)}', flush=True)
    totals = np.full((len(todo), len(lat), len(lon)), np.nan, 'float32')
    counts = np.zeros((len(todo), len(lat), len(lon)), 'int8')
    for i, p in enumerate(paths):
        block = read_block(p, lat, lon)
        n = np.isfinite(block).sum(axis=(1, 3))
        with np.errstate(invalid='ignore'):
            mean = np.nanmean(block, axis=(1, 3))
        totals[i] = np.where(n >= a.min_valid, mean, np.nan)
        counts[i] = n
    receipts = {p.name: json.loads((p.parent / (p.name + '.download.json')).read_text(encoding='utf-8'))['sha256'] for p in paths}
    stamps = np.array([np.datetime64(f'{y}-{m:02d}-01') for y, m in todo]).astype('datetime64[ns]')
    ds = xr.Dataset({'monthly_total': (('time', 'lat', 'lon'), totals),
                     'valid_subcells': (('time', 'lat', 'lon'), counts)},
                    coords=dict(time=stamps, lat=lat.astype('float32'), lon=lon.astype('float32')))
    ds.monthly_total.attrs.update(units='mm', long_name='CHIRPS v3.0 monthly precipitation total (0.25 deg block mean)')
    ds.valid_subcells.attrs.update(long_name='valid 0.05 deg cells in the 0.25 deg cell (of 25)')
    ds.time.attrs['note'] = 'first day of the month'
    ds.attrs.update(title='CHIRPS v3.0 monthly precipitation on the project 0.25 degree Ethiopia grid',
                    version='CHIRPS v3.0', source=BASE, product='monthly, final, Africa, 0.05 degree GeoTIFF',
                    aggregation=f'mean of the valid 0.05 degree cells in each 0.25 degree cell; missing when fewer than {a.min_valid} of 25 are valid',
                    reference='Funk, C., Peterson, P., Harrison, L., et al. (2026). The Climate Hazards Center Infrared Precipitation '
                              'with Stations, Version 3. Scientific Data, 13, 718. https://doi.org/10.1038/s41597-026-07096-4',
                    grid_source=str(GRID.relative_to(ROOT)), first_month=a.first, last_month=a.last,
                    source_files_sha256=hashlib.sha256(json.dumps(receipts, sort_keys=True).encode()).hexdigest(),
                    created_utc=now(), script='scripts/prepare_chirps_v3.py')
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix('.part.nc')
    ds.to_netcdf(tmp, encoding={'monthly_total': {'zlib': True, 'complevel': 4}, 'valid_subcells': {'zlib': True}})
    tmp.replace(out)
    (out.parent / (out.stem + '.receipts.json')).write_text(json.dumps(receipts, indent=1), encoding='utf-8')
    print(f'Saved {out}: {len(todo)} months, {int(np.isfinite(totals[0]).sum())} valid cells in the first month')


if __name__ == '__main__':
    main()
