"""Forecast-year maps of the Leung–Dirichlet pipelines on the native 0.25° grid cells (no interpolation or smoothing), for the
season's rainfall domain (the seasonal mask) and All Ethiopia, drawn as the published grid-cell outlook map
(presentation_layers.tercile_cells: same classes, colours, background and legend), so each pipeline can be compared map
for map with the published one (docs/51). Never published as a forecast.

Input: outputs/leung_dirichlet/<cycle>/forecast/ld_<year>_<target>.nc (scripts/leung_dirichlet_benchmark.py).
Output, per view (e.g. ondj_rainfall_domain, all_ethiopia), under outputs/leung_dirichlet/<cycle>/forecast/maps/<view>/:
  <pipeline>/<target>.png       the rainfall tercile outlook (leading tercile where it reaches 40%)
  probabilities/<target>.png    below-, near- and above-normal probabilities, published and every pipeline

    set CALIBRATION_CYCLE=config\\cycles\\sep_2026_ondj.json
    python scripts\\leung_dirichlet_maps.py --name sep_ondj
"""
import argparse
import shutil
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
import leung_dirichlet as ldc

PIPELINES = {k: (ldc.SHORT[k], ldc.LONG[k]) for k in ('ld_full', 'ld_no_dirichlet', 'iad_on_mvs', 'leung_blend')}
BANNER = f'NOT PUBLISHED: {ldc.NAME} comparison (docs/51)'


def outlook_cells(p, valid, forecast, country, domain, lines, target, view, title, path, settings):
    """The published grid-cell tercile outlook (presentation_layers.tercile_cells) for probabilities p."""
    _, shown, peak, _ = base.classify(p, valid, settings['minimum_leading_probability'])
    ext = layers.cell_axes(None, forecast, country, domain, valid)
    fig = plt.figure(figsize=(10.6, 8.5))
    gs = fig.add_gridspec(3, 2, width_ratios=[17, 1], left=.08, right=.86, bottom=.19, top=.83, hspace=.45, wspace=.14)
    ax = fig.add_subplot(gs[:, 0])
    layers.cell_background(ax, ext, country, domain, valid)
    norm = BoundaryNorm(base.PROB_BOUNDS, 7)
    for row, k in enumerate([2, 1, 0]):
        cmap = ListedColormap(base.COLORS[k])
        ax.imshow(np.where(domain & valid & (shown == k), 100 * peak, np.nan), origin='lower', extent=ext, cmap=cmap, norm=norm,
                  interpolation='nearest', zorder=2)
        cb = fig.colorbar(ScalarMappable(norm=norm, cmap=cmap), cax=fig.add_subplot(gs[row, 1]), ticks=[40, 50, 60, 70, 80, 90, 100])
        cb.set_label(['Below normal (%)', 'Near normal (%)', 'Above normal (%)'][k])
    layers.cell_finish(ax, ext, lines)
    fig.suptitle(f'{CYCLE.target_label(target)} | rainfall tercile outlook', fontsize=18, y=.965)
    fig.text(.5, .918, f'{CYCLE.init_month_name} initialization · {title} · CHIRPS reference {REF_DASH}', ha='center', fontsize=9.5)
    fig.text(.5, .883, f'{layers.VIEWS[view]} · grid cells (0.25°) · {BANNER}', ha='center', fontsize=11, color='#b3401b')
    fig.legend(handles=[Patch(facecolor='white', edgecolor='gray', label=f"Weak (<{100 * settings['minimum_leading_probability']:g}%) or tied"),
                        Patch(facecolor='#c3c9cf', label='No probability in view'), Patch(facecolor='#edf0f3', label='Outside focus')],
               loc='lower center', bbox_to_anchor=(.5, .09), ncol=3, frameon=False, fontsize=9)
    fig.text(.5, .018, layers.CELLS_NOTE, ha='center', va='bottom', fontsize=8, color='#48535d')
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=settings['dpi'], facecolor='white')
    plt.close(fig)


def probability_cells(panels, forecast, country, domain, lines, target, view, path):
    """Below-, near- and above-normal probabilities of each pipeline (rows) on the grid cells, inside the view only."""
    ext = layers.cell_axes(None, forecast, country, domain, None)
    cats = [('Below normal', 'YlOrBr'), ('Near normal', 'Greys'), ('Above normal', 'YlGn')]
    fig, axes = plt.subplots(len(panels), 3, figsize=(11, 3.2 * len(panels) + .8), squeeze=False, layout='constrained')
    w = np.asarray(layers.area(forecast))                     # cell areas, for the area means in the titles
    for i, (name, p) in enumerate(panels):
        ok = country & domain & np.isfinite(p).all(-1)
        for j, (cat, cmap) in enumerate(cats):
            ax = axes[i, j]
            layers.cell_background(ax, ext, country, domain, ok)
            im = ax.imshow(np.where(ok, p[..., j], np.nan), origin='lower', extent=ext, cmap=cmap, vmin=0, vmax=.8,
                           interpolation='nearest', zorder=2)
            for x, y in lines:
                ax.plot(x, y, color='#35414b', linewidth=.5, zorder=7)
            ax.set(xlim=(ext[0], ext[1]), ylim=(ext[2], ext[3]), aspect='equal', xticks=[], yticks=[])
            mean = float(np.average(p[ok, j], weights=w[ok])) if ok.any() else float('nan')
            ax.set_title(f'{name}\n{cat}: area mean {mean:.0%}', fontsize=9)
            if i == len(panels) - 1:
                fig.colorbar(im, ax=axes[:, j], orientation='horizontal', fraction=.025, pad=.01, label=f'{cat} probability',
                             ticks=[0, .2, 1 / 3, .6, .8], format=lambda x, _: f'{x:.0%}')
    fig.suptitle(f'{CYCLE.target_label(target)} | tercile probabilities · {layers.VIEWS[view]} · grid cells (0.25°)\n{BANNER}; '
                 'climatology 33%; light grey outside the view, dark grey no probability', fontsize=10.5)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110, facecolor='white')
    plt.close(fig)


def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument('--name', default='sep_ondj')
    a.add_argument('--targets', nargs='+', default=list(CYCLE.targets))
    args = a.parse_args()
    root = Path(__file__).resolve().parents[1] / 'outputs/leung_dirichlet' / args.name / 'forecast'
    settings = CYCLE.raw['display']
    lines = base.boundary_lines(CYCLE.root('boundary'))
    mask_path = CYCLE.root('season_domain_mask') if layers.SEASON_VIEW else CYCLE.root('regime_mask')
    for old in ('outlook', 'maps'):                      # earlier renderings (the smoothed maps) are replaced
        if (root / old).is_dir():
            shutil.rmtree(root / old)
    for target in args.targets:
        ld_file = root / f'ld_{CYCLE.year}_{target}.nc'
        if not ld_file.is_file():
            print('missing', ld_file)
            continue
        with xr.open_dataset(CYCLE.forecast_file(CYCLE.root('forecast_root'), target)) as f:
            forecast = f.load()
        _, domains = layers.load_mask(mask_path, forecast)
        country = np.asarray(domains['all_ethiopia'], bool)
        with xr.open_dataset(ld_file) as g:
            if not (np.allclose(g.lat, forecast.lat) and np.allclose(g.lon, forecast.lon)):
                raise ValueError('Leung–Dirichlet and published grids differ')
            # near normal = 1 - below - above can be -1e-16 (rounding); clipped for display only
            probs = {k: np.clip(g[f'{k}_probability'].transpose('lat', 'lon', 'category').values, 0, 1) for k in PIPELINES}
        published = forecast.blend_probability.sel(category=['below', 'near', 'above']).transpose('lat', 'lon', 'category').values
        for view, domain in domains.items():
            domain = np.asarray(domain, bool) & country
            out = root / 'maps' / view
            for k, (title, _) in PIPELINES.items():           # the short name fits the subtitle line
                valid = country & np.isfinite(probs[k]).all(-1)
                outlook_cells(probs[k], valid, forecast, country, domain, lines, target, view, title, out / k / f'{target}.png', settings)
            panels = [('Published (MVS + climatology blend)', published)] + [(PIPELINES[k][0], probs[k]) for k in PIPELINES]
            probability_cells(panels, forecast, country, domain, lines, target, view, out / 'probabilities' / f'{target}.png')
        print('Rendered', CYCLE.target_label(target), flush=True)


if __name__ == '__main__':
    main()
