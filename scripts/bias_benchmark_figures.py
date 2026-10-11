"""Figures of the bias-correction benchmark (scripts/bias_benchmark.py)."""
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                       # noqa: E402
from matplotlib.colors import TwoSlopeNorm            # noqa: E402
from bias_methods import ALL as METHODS                      # noqa: E402

DPI = 150


def label(m):
    if m in ('_raw', 'raw'):
        return 'Raw ECMWF'
    return METHODS[m].label.replace(' (operational)', '*').replace('Square-root-space ', 'Sqrt ')


def to_grid(values, idx, lat, lon):
    out = np.full(len(lat) * len(lon), np.nan)
    out[idx] = values
    return out.reshape(len(lat), len(lon))


def edges(c):
    c = np.asarray(c, float)
    return np.r_[c[0] - (c[1] - c[0]) / 2, (c[:-1] + c[1:]) / 2, c[-1] + (c[-1] - c[-2]) / 2]


def outline(ax, lat, lon, mask, **kw):
    ax.contour(lon, lat, mask.astype(float), levels=[.5], **kw)


def heatmaps(path, results, gates, methods, targets, region, ref):
    panels = [('training', 'crpss', 'CRPSS amounts, leave-one-year-out 1993-2016'),
              ('training', 'rpss', 'RPSS terciles (smoothed counts, no blend), 1993-2016'),
              ('operational', 'crpss', 'CRPSS amounts, fit 1993-2016, scored 2017-2024')]
    fig, axes = plt.subplots(1, 3, figsize=(17, 0.42 * len(methods) + 2.4), sharey=True)
    for ax, (design, key, title) in zip(axes, panels):
        v = np.array([[results[t]['methods'][m][design][region][key] for t in targets] for m in methods])
        lim = max(np.nanmax(np.abs(v)), .05)
        ax.imshow(v, cmap='RdBu', vmin=-lim, vmax=lim, aspect='auto')
        for i, m in enumerate(methods):
            for j, t in enumerate(targets):
                mark = ''
                if m != ref and m in gates and design == 'training':
                    g = gates[m]['crps' if key == 'crpss' else 'rps'][t]['decision']
                    mark = ' *' if g['adopt'] else (' +' if g['training_significant'] else '')
                ax.text(j, i, f'{v[i, j]:+.3f}{mark}', ha='center', va='center', fontsize=8,
                        fontweight='bold' if m == ref else 'normal')
        ax.set_xticks(range(len(targets)), targets)
        ax.set_title(title, fontsize=10)
    axes[0].set_yticks(range(len(methods)), [label(m) for m in methods])
    fig.suptitle(f'Bias-correction benchmark, September initialization ({region.replace("_", " ")}; area-weighted, equal years)', fontsize=12)
    fig.text(.5, .005, '* passes the gate against MVS (Holm-adjusted p < 0.05 on 1993-2016 and no harm 2017-2024); '
             '+ significant on 1993-2016 only. Skill is against the CHIRPS training climatology. *MVS = operational.',
             ha='center', fontsize=8)
    fig.tight_layout(rect=(0, .03, 1, .95))
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def maps(path, values_by_method, methods, lat, lon, cells, domain, title, cbar, vlim, cmap='RdBu'):
    n = len(methods)
    cols = 5
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(3.3 * cols, 3.0 * rows + .8), squeeze=False)
    norm = TwoSlopeNorm(0, -vlim, vlim) if cmap == 'RdBu' else None
    for ax, m in zip(axes.flat, methods):
        im = ax.pcolormesh(edges(lon), edges(lat), values_by_method[m], cmap=cmap, norm=norm,
                           **({} if norm else dict(vmin=vlim[0], vmax=vlim[1])))
        outline(ax, lat, lon, cells, colors='#333', linewidths=.6)
        outline(ax, lat, lon, domain, colors='#555', linewidths=.6, linestyles='--')
        v = values_by_method[m][cells]
        ax.set_title(f'{label(m)}\nmedian {np.nanmedian(v):+.3f}' if cmap == 'RdBu' else label(m), fontsize=8.5)
        ax.set_aspect('equal')
        ax.set_xticks([])
        ax.set_yticks([])
    for ax in list(axes.flat)[n:]:
        ax.axis('off')
    fig.colorbar(im, ax=axes, shrink=.6, label=cbar)
    fig.suptitle(title + '\nSolid: Ethiopia. Dashed: ONDJ R3 (Deyr) domain.', fontsize=11)
    fig.savefig(path, dpi=DPI, bbox_inches='tight')
    plt.close(fig)


def pit_panel(path, results, methods, target, region, bins):
    cols = 5
    rows = int(np.ceil(len(methods) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(3.1 * cols, 2.3 * rows + .6), sharey=True, squeeze=False)
    for ax, m in zip(axes.flat, methods):
        r = results[target]['methods'][m]['training'][region]
        ax.bar(np.arange(bins) + .5, np.array(r['pit_histogram']) * bins, width=.9, color='#4a7fb0')
        ax.axhline(1, color='k', lw=.8)
        ax.set_title(f"{label(m)}\nRI {r['pit_reliability_index']:.2f} · spread/error {r['spread_error_ratio']:.2f}", fontsize=8)
        ax.set_xticks([])
    for ax in list(axes.flat)[len(methods):]:
        ax.axis('off')
    fig.suptitle(f'{target}: rank (PIT) histograms of CHIRPS within the corrected ensemble, 1993-2016 leave-one-year-out\n'
                 'Flat = reliable; U = too narrow; dome = too wide; slope = biased. RI: sum of |frequency - 1/bins|.', fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, .9))
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def distribution_panel(path, results, methods, targets, region):
    keys = [('mean_ratio', 'mean'), ('sd_ratio', 'standard deviation'), ('q10_ratio', '10th percentile'),
            ('q90_ratio', '90th percentile')]
    fig, axes = plt.subplots(1, len(targets), figsize=(3.6 * len(targets), 0.32 * len(methods) + 2.2), sharey=True)
    y = np.arange(len(methods))
    for ax, t in zip(np.atleast_1d(axes), targets):
        for (k, lab), mk in zip(keys, ['o', 's', 'v', '^']):
            v = [results[t]['methods'][m]['distribution_full'][region][k]['area_median'] for m in methods]
            ax.scatter(v, y, marker=mk, s=22, label=lab)
        ax.axvline(1, color='k', lw=.8)
        ax.set_xlim(.2, 1.8)
        ax.set_title(t)
        ax.grid(alpha=.3)
    np.atleast_1d(axes)[0].set_yticks(y, [label(m) for m in methods])
    np.atleast_1d(axes)[0].invert_yaxis()
    np.atleast_1d(axes)[-1].legend(fontsize=7, loc='lower right')
    fig.suptitle('Distribution of the corrected members against CHIRPS (pooled 1993-2024 leave-one-year-out, equal years; '
                 'area-weighted median of cell ratios; 1 = same)', fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, .93))
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def members_panel(path, forecasts, methods, target, lat, lon, cfg):
    f = forecasts[target]
    clim = f['_clim']
    order = np.argsort(clim)
    picks = [order[int(q * (len(order) - 1))] for q in cfg['example_cell_quantiles']]
    idx = f['_idx']
    methods = [m for m in methods if m != 'raw']
    names = ['Raw ECMWF'] + [label(m) for m in methods]
    fig, axes = plt.subplots(len(picks), 1, figsize=(13, 3.0 * len(picks)), sharex=True)
    rng = np.random.default_rng(0)
    for ax, j in zip(np.atleast_1d(axes), picks):
        cols = [f['_raw'][:, j]] + [f[m][:, j] for m in methods]
        for i, v in enumerate(cols):
            ax.scatter(i + rng.uniform(-.18, .18, len(v)), v, s=7, alpha=.7, color='#888' if i == 0 else '#2f6f9f')
            ax.plot([i - .3, i + .3], [np.nanmean(v)] * 2, color='k', lw=1.4)
        q1, q2 = f['_terciles'][:, j]
        ax.axhspan(q1, q2, color='#d9d9d9', alpha=.5, zorder=0)
        ax.axhline(clim[j], color='#c0392b', lw=.9, ls='--')
        flat = idx[j]
        la, lo = lat[flat // len(lon)], lon[flat % len(lon)]
        ax.set_title(f'{la:.3f}°N {lo:.3f}°E · CHIRPS mean {clim[j]:.0f} mm (dashed); grey band: near-normal tercile', fontsize=9)
        ax.set_ylabel('mm')
    np.atleast_1d(axes)[-1].set_xticks(range(len(names)), names, rotation=35, ha='right', fontsize=8)
    fig.suptitle(f"{target} {cfg['forecast_year']}: every member after each correction, at three cells "
                 f"(10th, 50th and 90th percentile of CHIRPS climatology)\nBlack bar: ensemble mean. "
                 f"Delta Change shows its {len(f['dc']) if 'dc' in f else 0} rescaled CHIRPS years instead of members.", fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, .95))
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def make_all(out, results, gates, cell_maps, forecasts, lat, lon, methods, targets, cfg):
    import xarray as xr
    from common import source_path
    region = cfg['primary_region']
    ref = cfg['reference_method']
    fig_dir = out / 'figures'
    fig_dir.mkdir(parents=True, exist_ok=True)
    heatmaps(fig_dir / 'skill_summary.png', results, gates, methods, targets, region, ref)
    distribution_panel(fig_dir / 'distribution.png', results, methods, targets, region)
    spec = cfg['regions']['ondj_domain'] if 'ondj_domain' in cfg['regions'] else cfg['cells']
    with xr.open_dataset(source_path(spec['path'])) as d:
        domain = d[spec['variable']].transpose('lat', 'lon').values == 1
    for t in targets:
        idx = forecasts[t]['_idx']
        cells = np.isfinite(to_grid(np.zeros(len(idx)), idx, lat, lon))
        crpss = {m: to_grid(cell_maps[t][m]['crpss'], idx, lat, lon) for m in methods}
        maps(fig_dir / f'crpss_maps_{t}.png', crpss, methods, lat, lon, cells, domain,
             f'{t}: CRPSS per cell against the CHIRPS climatology (leave-one-year-out 1993-2024)', 'CRPSS', .4)
        others = [m for m in methods if m not in (ref, 'raw')]
        maps(fig_dir / f'crpss_minus_mvs_{t}.png', {m: crpss[m] - crpss[ref] for m in others}, others, lat, lon, cells, domain,
             f'{t}: CRPSS minus operational MVS per cell (blue: method better)', 'CRPSS difference', .15)
        pit_panel(fig_dir / f'pit_{t}.png', results, methods, t, region, cfg['pit_bins'])
        members_panel(fig_dir / f'members_{cfg["forecast_year"]}_{t}.png', forecasts, methods, t, lat, lon, cfg)
        clim = forecasts[t]['_clim']
        shown = [m for m in methods if m != 'raw']
        pct = {m: to_grid(100 * np.nanmean(forecasts[t][m], 0) / np.where(clim > 1, clim, np.nan), idx, lat, lon)
               for m in shown}
        pct['_raw'] = to_grid(100 * forecasts[t]['_raw'].mean(0) / np.where(clim > 1, clim, np.nan), idx, lat, lon)
        maps(fig_dir / f'forecast_{cfg["forecast_year"]}_percent_{t}.png', pct, ['_raw'] + shown, lat, lon, cells, domain,
             f'{t} {cfg["forecast_year"]}: corrected ensemble mean, % of CHIRPS 1993-2024 mean', '% of normal', (40, 160),
             cmap='BrBG')
