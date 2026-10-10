"""Export a rainfall-domain mask as one boundary (shapefile + GeoJSON).

The mask's 0.25-degree cells are dissolved into a single (multi)polygon and clipped to the
Ethiopia boundary, so the outline follows the national border instead of cell edges.

    python scripts\\export_domain_boundary.py --mask data\\masks\\FMAM_dominant_domain.nc --out data\\boundaries\\fmam_dominant\\fmam_dominant_domain

Writes <out>.shp/.shx/.dbf/.prj/.cpg and <out>.geojson (WGS84, lon/lat), one feature.

--smooth draws the outline as a smooth curve instead of cell edges: the 0/1 mask is smoothed
(Gaussian, --sigma cells, the same 0.6 the site maps use), resampled 10x and contoured at 0.5,
so the enclosed area stays close to the cell mask. Pieces smaller than --min-km2 are dropped.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import xarray as xr
from scipy.ndimage import gaussian_filter, zoom
import shapefile
from pyproj import Geod
from shapely.geometry import box, shape, mapping, MultiPolygon, Polygon
from shapely.ops import unary_union, orient
from common import ROOT, source_path

PRJ = ('GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],'
       'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]')


def country_shape(path):
    return unary_union([shape(s.__geo_interface__) for s in shapefile.Reader(str(path)).shapes()])


def domain_polygon(mask, border):
    lat, lon = mask.lat.values.astype(float), mask.lon.values.astype(float)
    dy, dx = abs(lat[1] - lat[0]) / 2, abs(lon[1] - lon[0]) / 2
    rows, cols = np.nonzero(mask.season_domain.values == 1)
    cells = unary_union([box(lon[j] - dx, lat[i] - dy, lon[j] + dx, lat[i] + dy) for i, j in zip(rows, cols)])
    clipped = cells.intersection(border)
    parts = [g for g in getattr(clipped, 'geoms', [clipped]) if isinstance(g, Polygon) and not g.is_empty]
    return MultiPolygon([orient(p, -1) for p in parts]), int(len(rows))   # clockwise outer rings (shapefile order)


def smooth_polygon(mask, border, sigma, min_km2, factor=10):
    """Smooth outline: contour of the Gaussian-smoothed 0/1 mask at 0.5 on a 10x finer grid."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    lat, lon = mask.lat.values.astype(float), mask.lon.values.astype(float)
    field = gaussian_filter((mask.season_domain.values == 1).astype(float), sigma, mode='constant')
    fine = np.pad(zoom(field, factor, order=1), 1)                                   # pad: rings close at the edges
    step_y, step_x = (lat[1] - lat[0]) / factor, (lon[1] - lon[0]) / factor
    fy = np.linspace(lat[0], lat[-1], fine.shape[0] - 2)
    fx = np.linspace(lon[0], lon[-1], fine.shape[1] - 2)
    fy = np.r_[fy[0] - step_y, fy, fy[-1] + step_y]
    fx = np.r_[fx[0] - step_x, fx, fx[-1] + step_x]
    cs = plt.contour(fx, fy, fine, levels=[0.5])
    region = Polygon()
    for path in cs.allsegs[0]:                       # XOR of closed rings handles holes and islands
        if len(path) >= 4:
            ring = Polygon(path).buffer(0)
            region = region.symmetric_difference(ring)
    plt.close('all')
    clipped = region.intersection(border)
    geod = Geod(ellps='WGS84')
    parts = [g for g in getattr(clipped, 'geoms', [clipped]) if isinstance(g, Polygon) and not g.is_empty
             and abs(geod.geometry_area_perimeter(g)[0]) / 1e6 >= min_km2]
    return MultiPolygon([orient(p, -1) for p in parts]), int((mask.season_domain.values == 1).sum())


def write(geom, out, attrs):
    out.parent.mkdir(parents=True, exist_ok=True)
    w = shapefile.Writer(str(out), shapeType=shapefile.POLYGON)
    fields = [('name', 'C', 80), ('season', 'C', 8), ('method', 'C', 16), ('cells', 'N', 6, 0),
              ('area_km2', 'N', 12, 0), ('pct_eth', 'N', 6, 1), ('ref_years', 'C', 12)]
    for f in fields:
        w.field(*f)
    rings = []
    for poly in geom.geoms:
        rings.append(list(poly.exterior.coords))
        rings += [list(r.coords)[::-1] for r in poly.interiors]   # holes counter-clockwise
    w.poly(rings)
    w.record(*[attrs[f[0]] for f in fields])
    w.close()
    out.with_suffix('.prj').write_text(PRJ, encoding='ascii')
    out.with_suffix('.cpg').write_text('UTF-8', encoding='ascii')
    geojson = MultiPolygon([orient(p, 1) for p in geom.geoms])          # RFC 7946: counter-clockwise outer rings
    feature = dict(type='Feature', properties=attrs, geometry=mapping(geojson))
    out.with_suffix('.geojson').write_text(json.dumps(dict(type='FeatureCollection', features=[feature])), encoding='utf-8')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--mask', required=True)
    p.add_argument('--out', required=True, help='Output path without extension')
    p.add_argument('--boundary', default='data/boundaries/ethiopia/eth_admin0.shp')
    p.add_argument('--smooth', action='store_true', help='Smooth outline instead of 0.25-degree cell edges')
    p.add_argument('--sigma', type=float, default=0.6, help='--smooth: Gaussian sigma in grid cells')
    p.add_argument('--min-km2', type=float, default=500, help='--smooth: drop pieces smaller than this')
    a = p.parse_args()
    with xr.open_dataset(source_path(a.mask)) as d:
        mask = d.load()
    border = country_shape(source_path(a.boundary))
    geom, cells = smooth_polygon(mask, border, a.sigma, a.min_km2) if a.smooth else domain_polygon(mask, border)
    geod = Geod(ellps='WGS84')
    area = abs(geod.geometry_area_perimeter(geom)[0]) / 1e6
    country = abs(geod.geometry_area_perimeter(border)[0]) / 1e6
    attrs = dict(name=mask.attrs.get('view_label', 'rainfall domain'), season=mask.attrs.get('season', ''),
                 method=mask.attrs.get('method', ''), cells=cells, area_km2=round(area), pct_eth=round(100 * area / country, 1),
                 ref_years=mask.attrs.get('reference_years', ''))
    out = source_path(a.out)
    write(geom, out, attrs)
    meta = dict(attrs, definition=mask.attrs.get('domain_definition', ''), source_mask=str(Path(a.mask).as_posix()),
                boundary=str(Path(a.boundary).as_posix()), polygons=len(geom.geoms),
                created_utc=datetime.now(timezone.utc).isoformat(),
                note=(f'Smooth outline: Gaussian-smoothed (sigma {a.sigma} cells) 0/1 mask contoured at 0.5, clipped to the national '
                      f'boundary, pieces < {a.min_km2:g} km2 dropped. The forecast statistics use the 0.25-degree cell mask.') if a.smooth else
                     '0.25-degree mask cells dissolved and clipped to the national boundary; edges inside the country follow cell edges.')
    out.with_name(out.name + '_metadata.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
    print(f'{attrs["name"]}: {len(geom.geoms)} polygon(s), {area:,.0f} km2 ({attrs["pct_eth"]}% of Ethiopia) -> {out}.shp / .geojson')


if __name__ == '__main__':
    main()
