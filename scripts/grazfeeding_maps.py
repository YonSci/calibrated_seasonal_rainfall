"""Tercile-outlook maps of the GrazFeediNG pipelines for the forecast year, drawn exactly as the published outlook map
(presentation_layers.forecast_maps: same interpolation, smoothing, classes, colours, boundary and legend), so each
pipeline can be compared map for map with the published "rainfall tercile outlook" (docs/51). Never published as a forecast.

Input: outputs/grazfeeding/<cycle>/forecast/gf_<year>_<target>.nc (scripts/grazfeeding_benchmark.py).
Output: outputs/grazfeeding/<cycle>/forecast/outlook/<pipeline>/<target>.png (All Ethiopia view).

    set CALIBRATION_CYCLE=config\\cycles\\sep_2026_ondj.json
    python scripts\\grazfeeding_maps.py --name sep_ondj
"""
import argparse
from pathlib import Path

import numpy as np
import xarray as xr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.cm import ScalarMappable
from matplotlib.patches import Patch

from cycle import CYCLE, REF_DASH
import presentation_layers as layers
import delivery_map_base as base

PIPELINES = {
    'gf_full': 'GrazFeediNG as uploaded (modified-Leung affine + member counts + IAD Dirichlet)',
    'gf_no_dirichlet': 'Modified-Leung affine + member counts (no Dirichlet)',
    'iad_on_mvs': 'Published MVS + member counts + IAD Dirichlet',
    'leung_blend': 'Modified-Leung affine + published smoothed counts and climatology blend',
}


def outlook(p, valid, forecast, country_native, lines, target, title, path, settings):
    """The published tercile-outlook figure (presentation_layers.forecast_maps, All Ethiopia view) for probabilities p."""
    grid = layers.DisplayGrid(forecast, settings)
    country = grid.support(country_native)
    q = np.stack([grid.continuous(p[..., k], valid) for k in range(3)], -1)
    q = np.clip(q, 0, 1)
    sums = q.sum(-1, keepdims=True)
    q = np.divide(q, sums, out=np.full_like(q, np.nan), where=sums > 0)
    qvalid = np.isfinite(q).all(-1) & country
    _, shown, peak, _ = base.classify(q, qvalid, settings['minimum_leading_probability'])
    fig = plt.figure(figsize=(10.6, 8.5))
    gs = fig.add_gridspec(3, 2, width_ratios=[17, 1], left=.08, right=.86, bottom=.19, top=.83, hspace=.45, wspace=.14)
    ax = fig.add_subplot(gs[:, 0])
    layers.background(ax, grid, country, country, qvalid)
    ax.contourf(grid.lon, grid.lat, np.where(country & (shown == -1), 1., np.nan), levels=[.5, 1.5], colors=['white'], corner_mask=False)
    norm = BoundaryNorm(base.PROB_BOUNDS, 7)
    for row, k in enumerate([2, 1, 0]):
        cmap = ListedColormap(base.COLORS[k])
        ax.contourf(grid.lon, grid.lat, np.where(country & (shown == k), 100 * peak, np.nan), levels=base.PROB_BOUNDS, cmap=cmap, norm=norm,
                    corner_mask=False)
        cb = fig.colorbar(ScalarMappable(norm=norm, cmap=cmap), cax=fig.add_subplot(gs[row, 1]), ticks=[40, 50, 60, 70, 80, 90, 100])
        cb.set_label(['Below normal (%)', 'Near normal (%)', 'Above normal (%)'][k])
    layers.finish_axis(ax, grid, lines)
    fig.suptitle(f'{CYCLE.target_label(target)} | rainfall tercile outlook', fontsize=18, y=.965)
    fig.text(.5, .918, f'{CYCLE.init_month_name} initialization · {title} · CHIRPS reference {REF_DASH}', ha='center', fontsize=9.5)
    fig.text(.5, .883, 'All Ethiopia · NOT PUBLISHED: GrazFeediNG comparison (docs/51)', ha='center', fontsize=11, color='#b3401b')
    fig.legend(handles=[Patch(facecolor='white', edgecolor='gray', label=f"Weak (<{100 * settings['minimum_leading_probability']:g}%) or tied"),
                        Patch(facecolor='#c3c9cf', label='No probability'), Patch(facecolor='#edf0f3', label='Outside focus')],
               loc='lower center', bbox_to_anchor=(.5, .09), ncol=3, frameon=False, fontsize=9)
    layers.footer(fig, settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=settings['dpi'], facecolor='white')
    plt.close(fig)


def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument('--name', default='sep_ondj')
    a.add_argument('--targets', nargs='+', default=list(CYCLE.targets))
    args = a.parse_args()
    root = Path(__file__).resolve().parents[1] / 'outputs/grazfeeding' / args.name / 'forecast'
    settings = CYCLE.raw['display']
    lines = base.boundary_lines(CYCLE.root('boundary'))
    mask_path = CYCLE.root('season_domain_mask') if layers.SEASON_VIEW else CYCLE.root('regime_mask')
    for target in args.targets:
        gf_file = root / f'gf_{CYCLE.year}_{target}.nc'
        if not gf_file.is_file():
            print('missing', gf_file)
            continue
        with xr.open_dataset(CYCLE.forecast_file(CYCLE.root('forecast_root'), target)) as f:
            forecast = f.load()
        _, domains = layers.load_mask(mask_path, forecast)
        country = np.asarray(domains['all_ethiopia'], bool)
        with xr.open_dataset(gf_file) as g:
            if not (np.allclose(g.lat, forecast.lat) and np.allclose(g.lon, forecast.lon)):
                raise ValueError('GrazFeediNG and published grids differ')
            for k, title in PIPELINES.items():
                p = g[f'{k}_probability'].transpose('lat', 'lon', 'category').values
                valid = country & np.isfinite(p).all(-1)
                outlook(p, valid, forecast, country, lines, target, title, root / 'outlook' / k / f'{target}.png', settings)
        print('Rendered', CYCLE.target_label(target), flush=True)


if __name__ == '__main__':
    main()
