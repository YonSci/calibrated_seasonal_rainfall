"""Per-cell forecast data and areas for the interactive outlook map and the area search (site_data/cells/, site_data/areas.json).

Per cycle (run with the cycle selected, so the view domains are exactly those of the maps: presentation_layers.load_mask):
  cells/<cycle>/grid.json        the 0.25-degree grid, the cells of Ethiopia (row-major index lat * nlon + lon) and, per
                                 view, which of them are in the view's domain
  cells/<cycle>/<target>.json    per cell of Ethiopia (aligned with grid.cells): the published tercile probabilities
                                 (below, near, above; null where not eligible), the corrected ensemble mean, its 10% and 90%
                                 quantiles and the reference-period mean (mm; null where amounts are not eligible), the
                                 cross-validated RPS of the published probabilities and of climatology over the training
                                 years and the test years (local_calibration/.../local_spatial_scores.nc), and, once
                                 verified, the observed total (mm)
Once for all cycles:
  areas.json                     regions, zones and woredas (OCHA COD-AB, data/shapefiles/eth, admin 1-3) with the grid
                                 cells whose centres fall inside (the nearest cell when none does), and simplified outlines
                                 of the country and the regions for drawing

  python scripts/site_cells.py --cycle config/cycles/sep_2026_ondj.json --id ondj2026 --out site_data/cells/ondj2026
  (build_site.py runs it for every published cycle through site_data.export)
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / 'data/shapefiles/eth'
ADMIN_SOURCE = 'OCHA Common Operational Datasets, Ethiopia administrative boundaries (COD-AB, v04, 2025), CC BY-IGO'


def compact(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(',', ':'), allow_nan=False), encoding='utf-8', newline='\n')
    return path.stat().st_size


def r(a, nd):
    """Rounded list with None for missing values."""
    return [None if not np.isfinite(v) else round(float(v), nd) for v in a]


# ---------------------------------------------------------------- one cycle (run with CALIBRATION_CYCLE set)
def export_cycle(out):
    import xarray as xr
    from cycle import CYCLE
    import presentation_layers as pl
    root = CYCLE.root('forecast_root', 'outputs/final_shared_blend')
    first = CYCLE.forecast_file(root, CYCLE.targets[0])
    with xr.open_dataset(first) as ref:
        ref = ref.load()
    lat, lon = ref.lat.values.astype(float), ref.lon.values.astype(float)
    _, views = pl.load_mask(mask_path(), ref)
    country = views['all_ethiopia'].reshape(-1)
    cells = np.flatnonzero(country)
    sizes = {}
    sizes['grid.json'] = compact(out / 'grid.json', dict(
        lat0=float(lat[0]), lon0=float(lon[0]), dlat=float(lat[1] - lat[0]), dlon=float(lon[1] - lon[0]), nlat=len(lat), nlon=len(lon),
        cells=cells.tolist(), views={v: [int(i) for i, ok in enumerate(m.reshape(-1)[cells]) if ok] for v, m in views.items()},
        reference=CYCLE.reference_dash, year=CYCLE.year))
    vr = CYCLE.root('verification_root', '') if CYCLE.raw.get('verification_root') else None
    for t in CYCLE.targets:
        with xr.open_dataset(CYCLE.forecast_file(root, t)) as f:
            f = f.load()
        p = f.blend_probability.transpose('lat', 'lon', 'category').values.reshape(-1, 3)[cells]
        pe = f.probability_eligible.values.reshape(-1)[cells] == 1
        ae = f.amount_eligible.values.reshape(-1)[cells] == 1
        p[~pe] = np.nan
        members = f.precip_corrected.transpose('member', 'lat', 'lon').values.reshape(f.sizes['member'], -1)[:, cells]
        q10, q90 = np.nanquantile(members, [.1, .9], axis=0)
        mean = f.corrected_ensemble_mean.values.reshape(-1)[cells]
        normal = f.observed_training_mean.values.reshape(-1)[cells]
        for a in (q10, q90, mean, normal):
            a[~ae] = np.nan
        row = dict(target=t, pb=r(p[:, 0], 3), pn=r(p[:, 1], 3), pa=r(p[:, 2], 3), mean=r(mean, 1), q10=r(q10, 1), q90=r(q90, 1),
                   normal=r(normal, 1))
        tag = f'{CYCLE.tag}_{t}'
        for design, key in (('training', 'tr'), ('operational', 'op')):
            sp = ROOT / f'outputs/local_calibration/{tag}/{design}/local_spatial_scores.nc'
            if sp.is_file():
                with xr.open_dataset(sp) as s:
                    row[f'rb_{key}'] = r(s.shared_blend_rps.values.reshape(-1)[cells], 4)
                    row[f'rc_{key}'] = r(s.climatology_rps.values.reshape(-1)[cells], 4)
                    row[f'n_{key}'] = int(np.nanmax(s.valid_year_count.values))
        if vr is not None:
            o = vr / 'observations' / t / f'chirps_{CYCLE.year}_common.nc'
            if o.is_file():
                with xr.open_dataset(o) as d:
                    row['obs'] = r(d.precip_season.transpose('lat', 'lon').values.reshape(-1)[cells], 1)
        sizes[f'{t}.json'] = compact(out / f'{t}.json', row)
    return sizes


def mask_path():
    from cycle import CYCLE
    key = 'regime_mask' if CYCLE.project['season']['name'] == 'JJAS' else 'season_domain_mask'
    return CYCLE.root(key, '')


# ---------------------------------------------------------------- areas (regions, zones, woredas)
def outline(geom, tol):
    """Simplified exterior rings of a (multi)polygon as [[lon, lat], ...] lists (3 decimals)."""
    g = geom.simplify(tol, preserve_topology=True)
    polys = getattr(g, 'geoms', [g])
    return [[[round(x, 3), round(y, 3)] for x, y in p.exterior.coords] for p in polys if not p.is_empty and p.area > 1e-4]


def export_areas(out, lat, lon):
    import shapefile
    import shapely
    from shapely.geometry import shape
    glat, glon = np.meshgrid(lat, lon, indexing='ij')
    x, y = glon.ravel(), glat.ravel()
    areas, shapes = [], {}
    for level in (1, 2, 3):
        rd = shapefile.Reader(str(ADMIN / f'eth_admin{level}'))
        for sr in rd.iterShapeRecords():
            rec = sr.record.as_dict()
            g = shape(sr.shape.__geo_interface__)
            inside = np.flatnonzero(shapely.contains_xy(g, x, y))
            if not len(inside):                                # small woredas: the cell nearest its centre
                c = g.representative_point()
                inside = np.array([int(np.argmin((x - c.x) ** 2 + (y - c.y) ** 2))])
            a = dict(id=rec[f'adm{level}_pcode'], name=rec[f'adm{level}_name'], level=level, cells=inside.tolist())
            if level >= 2:
                a['region'] = rec['adm1_name']
            if level == 3:
                a['zone'] = rec['adm2_name']
            areas.append(a)
            if level == 1:
                shapes[a['id']] = outline(g, .01)
    rd = shapefile.Reader(str(ADMIN / 'eth_admin0'))
    country = outline(shape(rd.shape(0).__geo_interface__), .01)
    return compact(out / 'areas.json', dict(source=ADMIN_SOURCE, levels={'1': 'Region', '2': 'Zone', '3': 'Woreda'},
                                            areas=areas, outlines=dict(country=country, regions=shapes)))


def export_all(out, page_data):
    """Every published cycle (a subprocess each, with the cycle selected) and the areas; returns {file: bytes}."""
    sizes = {}
    grid = None
    for c in page_data['cycles']:
        dest = out / 'cells' / c['id']
        env = dict(os.environ, CALIBRATION_CYCLE=str(ROOT / c['cfg']))
        res = subprocess.run([sys.executable, str(ROOT / 'scripts/site_cells.py'), '--cycle', c['cfg'], '--id', c['id'], '--out', str(dest)],
                             cwd=ROOT, env=env, capture_output=True, text=True)
        if res.returncode:
            raise RuntimeError(f"site_cells.py failed for {c['id']}:\n{res.stderr[-2000:]}")
        for f in sorted(dest.glob('*.json')):
            sizes[f'cells/{c["id"]}/{f.name}'] = f.stat().st_size
        if grid is None:
            grid = json.loads((dest / 'grid.json').read_text(encoding='utf-8'))
    if grid:
        lat = grid['lat0'] + grid['dlat'] * np.arange(grid['nlat'])
        lon = grid['lon0'] + grid['dlon'] * np.arange(grid['nlon'])
        sizes['areas.json'] = export_areas(out, lat, lon)
    return sizes


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cycle', required=True)
    ap.add_argument('--id', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    os.environ.setdefault('CALIBRATION_CYCLE', str((ROOT / a.cycle).resolve()))
    sys.path.insert(0, str(ROOT / 'scripts'))
    sizes = export_cycle(Path(a.out))
    print(a.id, sum(sizes.values()) // 1000, 'kB')
