r"""Digitize Ethiopia's homogeneous rainfall regions (I-VIII) from a published map.

Source figure: Korecha, D., and A. Sorteberg (2013), Validation of operational seasonal rainfall
forecast in Ethiopia, Water Resources Research, 49(11), 7681-7697, doi:10.1002/2013WR013760
("Homogeneous rainfall regions currently used for the preparation of seasonal rainfall forecast
in Ethiopia"). The figure is under the publisher's terms, so it is kept locally (data/raw/reference,
not tracked) and only the derived region grid is stored and published, with this citation.

Method (deterministic): georeference from the axis ticks; keep the thick region boundaries
(morphological opening removes thin admin lines and station marks); flood-fill each region from a
seed near its label, inside this project's Ethiopia boundary; give line/label/marker pixels to the
nearest region; take the majority region of the pixels in each grid cell.

    python scripts\digitize_rainfall_regions.py --image data\raw\reference\ethiopia_homogeneous_rainfall_regions_10.1002_2013WR013760.png
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / 'config/external_forecasts/extractions/emi_rainfall_regions.json'
OUT = ROOT / 'data/masks/emi_rainfall_regions_korecha2013.nc'
GRID = ROOT / 'data/masks/init09_ONDJ_regime_domain.nc'
BOUNDARY = ROOT / 'data/boundaries/ethiopia/eth_admin0.shp'


def digitize(image, template):
    import sys
    sys.path.insert(0, str(ROOT / 'scripts'))
    from PIL import Image
    from scipy import ndimage as ndi
    from matplotlib.path import Path as MPath
    import delivery_map_base as base
    a = np.asarray(Image.open(image).convert('RGB')).astype(int)
    H, W, _ = a.shape
    fx = np.polyfit(template['x_ticks_deg'], template['x_ticks_px'], 1)
    fy = np.polyfit(template['y_ticks_deg'], template['y_ticks_px'], 1)
    res = [float(np.max(np.abs(np.polyval(fx, template['x_ticks_deg']) - template['x_ticks_px']))),
           float(np.max(np.abs(np.polyval(fy, template['y_ticks_deg']) - template['y_ticks_px'])))]
    lon = (np.arange(W) - fx[1]) / fx[0]
    lat = (np.arange(H) - fy[1]) / fy[0]
    LON, LAT = np.meshgrid(lon, lat)
    inside = np.zeros((H, W), bool)
    pts = np.column_stack([LON.ravel(), LAT.ravel()])
    for x, y in base.boundary_lines(BOUNDARY):
        inside |= MPath(np.column_stack([x, y])).contains_points(pts).reshape(H, W)
    k = template['line_opening_px']
    thick = ndi.binary_dilation(ndi.binary_opening(a.sum(-1) < template['dark_threshold'], np.ones((k, k))), np.ones((3, 3)))
    free = inside & ~thick
    lab, n = ndi.label(free)
    sizes = ndi.sum(free, lab, range(n + 1))
    names = list(template['regions'])
    region = np.zeros((H, W), int)                       # 0 = unassigned, 1..8 = regions I..VIII
    comps = {}
    for idx, key in enumerate(names, 1):
        lo, la = template['regions'][key]['seed']
        i, j = np.polyval(fy, la), np.polyval(fx, lo)
        d = (np.arange(H)[:, None] - i) ** 2 + (np.arange(W)[None] - j) ** 2
        d = np.where(free & (sizes[lab] > template['minimum_region_px']), d, np.inf)
        ii, jj = np.unravel_index(np.argmin(d), d.shape)
        comps[key] = int(lab[ii, jj])
        region[lab == lab[ii, jj]] = idx
    if len(set(comps.values())) != len(names):
        raise ValueError(f'Regions leak into each other: {comps}')
    assigned = float((region > 0).sum() / inside.sum())
    # Lines, labels and station marks inside Ethiopia go to the nearest region.
    _, (ni, nj) = ndi.distance_transform_edt(region == 0, return_indices=True)
    region = np.where(inside, region[ni, nj], 0)
    return region, lon, lat, dict(tick_fit_max_residual_px=res, px_per_degree=[float(fx[0]), float(-fy[0])],
                                  pixels_assigned_by_fill=assigned, components=comps)


def to_grid(region, lon_px, lat_px, glat, glon, step):
    """Majority region of the source pixels in each grid cell (0 = none)."""
    out = np.zeros((len(glat), len(glon)), int)
    for i, la in enumerate(glat):
        r = np.where(np.abs(lat_px - la) <= step / 2)[0]
        if not len(r):
            continue
        for j, lo in enumerate(glon):
            c = np.where(np.abs(lon_px - lo) <= step / 2)[0]
            if not len(c):
                continue
            v = region[np.ix_(r, c)].ravel()
            v = v[v > 0]
            if len(v):
                out[i, j] = np.bincount(v).argmax()
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--image', required=True)
    ap.add_argument('--qc', help='Optional PNG overlay for review')
    a = ap.parse_args()
    image = Path(a.image) if Path(a.image).is_absolute() else ROOT / a.image
    rec = json.loads(RECORD.read_text(encoding='utf-8'))
    sha = hashlib.sha256(image.read_bytes()).hexdigest()
    if sha != rec['source_sha256']:
        raise ValueError(f'{image}: SHA-256 {sha[:12]} differs from the record ({rec["source_sha256"][:12]})')
    region, lon, lat, qc = digitize(image, rec['template'])
    with xr.open_dataset(GRID) as g:
        glat, glon = g.lat.values.astype(float), g.lon.values.astype(float)
    grid = to_grid(region, lon, lat, glat, glon, float(abs(glat[1] - glat[0])))
    flat = np.arange(3.0, 15.0001, 0.05)
    flon = np.arange(33.0, 48.0001, 0.05)
    fine = to_grid(region, lon, lat, flat, flon, 0.05)
    names = list(rec['template']['regions'])
    ds = xr.Dataset(dict(region=(('lat', 'lon'), grid.astype('int8')), region_fine=(('lat_fine', 'lon_fine'), fine.astype('int8'))),
                    coords=dict(lat=glat, lon=glon, lat_fine=flat, lon_fine=flon))
    ds.region.attrs.update(long_name='Homogeneous rainfall region (1..8 = I..VIII, 0 = none)', flag_values=list(range(1, 9)),
                           flag_meanings=' '.join(names))
    ds.attrs.update(title='Ethiopia homogeneous rainfall regions used for seasonal forecasts (digitized)',
                    citation=rec['citation'], doi=rec['doi'], region_names=json.dumps({k: v['name'] for k, v in rec['template']['regions'].items()}),
                    source_image_sha256=sha, method=__doc__.split('\n\n')[2].strip().replace('\n', ' '),
                    qc=json.dumps(qc), created_utc=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    note='Derived product; the source figure is not redistributed. Region layout as published in 2013.')
    ds.to_netcdf(OUT)
    print('Saved:', OUT, '| cells per region:', {n: int((grid == i).sum()) for i, n in enumerate(names, 1)}, '| QC:', qc)
    if a.qc:
        qc_figure(a.qc, image, region, lon, lat, rec)


def qc_figure(path, image, region, lon, lat, rec):
    """Original figure beside the digitized regions (for the reviewer)."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from PIL import Image
    import sys
    sys.path.insert(0, str(ROOT / 'scripts'))
    import delivery_map_base as base
    fig, ax = plt.subplots(1, 2, figsize=(13, 5.5))
    ax[0].imshow(Image.open(image))
    ax[0].set_title('Source figure (local review copy, not published)', fontsize=10)
    ax[0].axis('off')
    ax[1].imshow(np.where(region > 0, region, np.nan), extent=[lon[0], lon[-1], lat[-1], lat[0]], cmap='tab10', vmin=0.5, vmax=10.5)
    for x, y in base.boundary_lines(BOUNDARY):
        ax[1].plot(x, y, color='k', lw=.8)
    for i, (k, v) in enumerate(rec['template']['regions'].items(), 1):
        m = region == i
        if m.any():
            yy, xx = np.nonzero(m)
            ax[1].text(lon[int(np.median(xx))], lat[int(np.median(yy))], k, ha='center', va='center', fontsize=11, weight='bold')
    ax[1].set_xlim(33, 48); ax[1].set_ylim(3, 15); ax[1].set_aspect('equal')
    ax[1].set_title('Digitized regions (this project)', fontsize=10)
    fig.savefig(path, dpi=110, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print('QC figure:', path)


if __name__ == '__main__':
    main()
