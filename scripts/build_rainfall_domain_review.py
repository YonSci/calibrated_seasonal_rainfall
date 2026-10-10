"""Figures, tables, JSON results and the offline HTML report of the rainfall-domain review.

Called by run_rainfall_domain_review.py --stage report. Four views, matching the site section:
Climatology, References, Candidate domains, Assessment. Every figure states its period and source.
"""
import html
import json
import shutil
from pathlib import Path
import numpy as np
import xarray as xr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
from common import ROOT, source_path, save_json
import rainfall_climatology_core as rc
import climatology_reference_core as cr
import rainfall_domain_assessment as ra

SURF, INK, INK2, LINE = '#fcfcfb', '#0b0b0b', '#52514e', '#c3c2b7'
BLUES = ['#f0f6fe', '#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b']
plt.rcParams.update({'font.size': 9, 'text.color': INK, 'axes.labelcolor': INK2, 'xtick.color': INK2, 'ytick.color': INK2,
                     'axes.edgecolor': LINE, 'figure.facecolor': SURF, 'axes.facecolor': SURF, 'savefig.facecolor': SURF})


class Ctx:
    def __init__(self, cfg, folders):
        self.cfg, self.folders = cfg, folders
        first, last = cfg['application_period']
        self.period = f'{first}–{last}'
        with xr.open_dataset(folders['climatology'] / f'{cfg["season_name"].lower()}_climatology_{first}_{last}.nc') as c:
            self.clim = c.load()
        with xr.open_dataset(folders['inspect'] / 'area_weights.nc') as w:
            self.w = w.load()
        self.lat, self.lon = self.clim.lat.values, self.clim.lon.values
        self.area = self.w.ethiopia_cell_area_km2.values
        self.country = self.area > 0
        self.regions, self.labels = ra.region_layer(cfg['regions_mask'], self.lat, self.lon)
        with xr.open_dataset(source_path(cfg['regions_mask'])) as r:
            self.region_fine = (r.lon_fine.values, r.lat_fine.values, r.region_fine.values.astype(float))
        import shapefile
        shp = shapefile.Reader(str(source_path(cfg['country_boundary']))).shapes()
        self.border = []
        for s in shp:
            pts = np.array(s.points)
            parts = list(s.parts) + [len(pts)]
            self.border += [pts[a:b] for a, b in zip(parts[:-1], parts[1:])]
        self.season = cfg['season_name']


def edges(v):
    v = np.asarray(v, float)
    return np.r_[v - (v[1] - v[0]) / 2, v[-1] + (v[1] - v[0]) / 2]


def base_map(ax, ctx, regions=True):
    for b in ctx.border:
        ax.plot(b[:, 0], b[:, 1], color=INK2, lw=.8)
    if regions:
        x, y, z = ctx.region_fine
        ax.contour(x, y, z, levels=np.arange(.5, 9), colors='white', linewidths=.6)
    ax.set_aspect('equal')
    ax.set_xlim(32.8, 48.2)
    ax.set_ylim(3.2, 15.1)
    ax.set_xticks([])
    ax.set_yticks([])


def field_map(ctx, values, levels, colors, title, label, path, extend='max'):
    fig, ax = plt.subplots(figsize=(6.4, 5.4), constrained_layout=True)
    z = np.where(ctx.country, values, np.nan)
    norm = BoundaryNorm(levels, len(colors))
    m = ax.pcolormesh(edges(ctx.lon), edges(ctx.lat), z, cmap=ListedColormap(colors), norm=norm)
    base_map(ax, ctx)
    ax.set_title(title, loc='left', fontsize=10)
    cb = fig.colorbar(m, ax=ax, shrink=.85, ticks=levels, extend=extend)
    cb.set_label(label)
    cb.outline.set_visible(False)
    fig.savefig(path, dpi=130)
    plt.close(fig)


def climatology_figures(ctx, out):
    c, src = ctx.clim, f'CHIRPS v2.0 {ctx.period}'
    field_map(ctx, c.season_mean_mm.values, [0, 50, 100, 200, 300, 400, 500, 800, 1200], BLUES,
              f'{ctx.season} mean rainfall (mm)\n{src}, actual-calendar monthly totals', 'mm', out / 'fmam_total_mm.png')
    field_map(ctx, c.annual_mean_mm.values, [0, 200, 400, 600, 800, 1000, 1400, 1800, 2600], BLUES,
              f'Mean annual rainfall (mm): the share denominator\n{src}', 'mm', out / 'annual_total_mm.png')
    field_map(ctx, c.season_share_percent.values, [0, 10, 15, 20, 25, 30, 40, 50, 100], BLUES,
              f'{ctx.season} share of annual rainfall (%)\n{src}, ratio of climatological means', '%', out / 'fmam_share_percent.png', extend='neither')
    # monthly cycle per EMI rainfall region (area-weighted)
    keys = list(ctx.labels)
    fig, axes = plt.subplots(2, 4, figsize=(12, 5.2), sharey=True, constrained_layout=True)
    mon = c.monthly_mean_mm.values
    for ax, k in zip(axes.ravel(), keys):
        sel = (ctx.regions == k) & ctx.country & np.isfinite(mon).all(axis=0)
        w = ctx.area[sel]
        vals = [(mon[m][sel] * w).sum() / w.sum() for m in range(12)]
        colors = ['#256abf' if m + 1 in ctx.cfg['season_months'] else '#c3c2b7' for m in range(12)]
        ax.bar(range(1, 13), vals, color=colors, width=.8)
        share = 100 * sum(vals[m - 1] for m in ctx.cfg['season_months']) / sum(vals)
        ax.set_title(f'{ctx.labels[k]}\n{ctx.season} {share:.0f}% of {sum(vals):.0f} mm', loc='left', fontsize=8.5)
        ax.set_xticks(range(1, 13))
        ax.set_xticklabels('JFMAMJJASOND')
        ax.grid(axis='y', color='#e6e5e0', lw=.6)
        ax.set_axisbelow(True)
    axes[0, 0].set_ylabel('mm per month')
    axes[1, 0].set_ylabel('mm per month')
    fig.suptitle(f'Monthly rainfall cycle by EMI rainfall region (area-weighted mean, {src}); {ctx.season} months in blue', x=.01, ha='left', fontsize=10)
    fig.savefig(out / 'monthly_cycle_review.png', dpi=130)
    plt.close(fig)


def reference_figures(ctx, out, refs):
    """Six panels: CHIRPS field, EMI image, CHIRPS in EMI classes, for amount and share; plus georeference QC."""
    if not refs:
        return
    fig, axes = plt.subplots(len(refs), 3, figsize=(15, 4.6 * len(refs)), constrained_layout=True, squeeze=False)
    for row, ref in zip(axes, refs):
        rec = ref['record']
        classes = rec['representation']['classes']
        ext = json.loads((ROOT / 'config/climatology_references/extractions' / f'{rec["id"]}.json').read_text(encoding='utf-8'))
        colours = np.array([c['rgb'] for c in ext['legend']]) / 255
        field = ctx.clim[rec['quantity']['comparable_field']].values
        e = cr.class_edges(classes)
        bounds = [max(e[0][0], 0) if np.isfinite(e[0][0]) else 0] + [hi for _, hi in e[:-1]] + \
                 [e[-1][1] if np.isfinite(e[-1][1]) else (100 if rec['quantity']['units'] == 'percent' else 1200)]
        ax = row[0]
        ax.pcolormesh(edges(ctx.lon), edges(ctx.lat), np.where(ctx.country, field, np.nan), cmap=ListedColormap(BLUES),
                      norm=BoundaryNorm(np.linspace(np.nanmin(bounds), np.nanmax(bounds), len(BLUES) + 1), len(BLUES)))
        base_map(ax, ctx, regions=False)
        ax.set_title(f'CHIRPS {ctx.period}: {rec["quantity"]["name"].replace("_", " ")} ({rec["quantity"]["units"]})', loc='left', fontsize=9.5)
        ax = row[1]
        ax.imshow(plt.imread(ref['panel']))
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_title(f'EMI map {rec["location"]["panel"].split(" - ")[0]} as published (p. {rec["location"]["page"]})\n'
                     f'reference period: {rec["temporal"]["reference_years"] or "not documented"}', loc='left', fontsize=9.5)
        ax = row[2]
        k = cr.classify_values(field, classes)
        ax.pcolormesh(edges(ctx.lon), edges(ctx.lat), np.where(ctx.country & (k >= 0), k, np.nan),
                      cmap=ListedColormap(colours), norm=BoundaryNorm(np.arange(-.5, len(classes)), len(classes)))
        base_map(ax, ctx, regions=False)
        ax.set_title('CHIRPS in the EMI classes (EMI colours)', loc='left', fontsize=9.5)
        from matplotlib.patches import Patch
        ax.legend(handles=[Patch(fc=colours[i], ec=LINE, label=c['source_label']) for i, c in enumerate(classes)],
                  loc='lower left', fontsize=7, frameon=True, facecolor=SURF, edgecolor='#e0dfda')
    fig.savefig(out / 'reference_comparison.png', dpi=120)
    plt.close(fig)
    for ref in refs:
        rec, st = ref['record'], ref['status']
        ext = json.loads((ROOT / 'config/climatology_references/extractions' / f'{rec["id"]}.json').read_text(encoding='utf-8'))
        colours = np.array([c['rgb'] for c in ext['legend']]) / 255
        img = plt.imread(ref['panel'])
        A, Ai = np.array(st['registration']['affine']), np.array(st['registration']['inverse'])
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5), constrained_layout=True)
        a1.imshow(img)
        for b in ctx.border:
            px, py = cr.apply_affine(Ai, b[:, 0], b[:, 1])
            a1.plot(px, py, color='#e34948', lw=1)
        for p in ext['registration']['control_points'] + ext['registration'].get('check_points', []):
            used = not p.get('clipped_by_frame')
            a1.plot(*p['pixel'], 'o' if p['role'] == 'control' else '^', ms=7, mfc='#2a78d6' if p['role'] == 'control' else '#eb6834',
                    mec=INK, alpha=1 if used else .3)
        a1.set_xticks([])
        a1.set_yticks([])
        reg = st['registration']
        a1.set_title(f'{rec["id"]}: registration ({ext["status"]})\nred: Ethiopia boundary through the fitted transform; '
                     f'IoU {reg["outline_iou"]}, control RMSE {reg["control_rmse_km"]:.1f} km, '
                     f'check RMSE {(reg["check_rmse_km"] or 0):.1f} km (faded points touch the frame, unused)', loc='left', fontsize=8.5)
        with xr.open_dataset(ctx.folders['references'] / rec['id'] / 'reference_classes.nc') as d:
            g = d.reference_class.values.astype(float)
        shown = np.where(g >= 0, g, np.nan)
        a2.pcolormesh(edges(ctx.lon), edges(ctx.lat), shown, cmap=ListedColormap(colours),
                      norm=BoundaryNorm(np.arange(-.5, len(colours)), len(colours)))
        a2.pcolormesh(edges(ctx.lon), edges(ctx.lat), np.where(g == -1, 1, np.nan), cmap=ListedColormap(['#52514e']))
        base_map(a2, ctx, regions=False)
        a2.set_title(f'Digitized classes on the 0.25° grid ({ext["status"]}); dark grey = uncertain', loc='left', fontsize=8.5)
        fig.savefig(out / f'georeference_qc_{rec["id"]}.png', dpi=110)
        plt.close(fig)


def candidate_figures(ctx, out, res, cube):
    cands = res['candidates']
    mms = sorted({c['rainfall_threshold_mm'] for c in cands})
    shs = sorted({c['share_threshold_percent'] for c in cands})
    grid = np.array([[next(c['included_country_percent'] for c in cands if c['rainfall_threshold_mm'] == m and c['share_threshold_percent'] == s)
                      for s in shs] for m in mms])
    fig, ax = plt.subplots(figsize=(6.2, 4), constrained_layout=True)
    im = ax.imshow(grid, cmap=ListedColormap(BLUES[1:]), norm=BoundaryNorm(np.linspace(np.floor(grid.min() / 5) * 5, np.ceil(grid.max() / 5) * 5, 8), 7))
    for i in range(len(mms)):
        for j in range(len(shs)):
            ax.text(j, i, f'{grid[i, j]:.1f}%', ha='center', va='center', fontsize=8.5, color='white' if grid[i, j] > np.percentile(grid, 60) else INK)
    ax.set_xticks(range(len(shs)))
    ax.set_xticklabels([f'≥ {s:g}%' for s in shs])
    ax.set_yticks(range(len(mms)))
    ax.set_yticklabels([f'≥ {m:g} mm' for m in mms])
    ax.set_xlabel(f'{ctx.season} share of annual rainfall')
    ax.set_ylabel(f'{ctx.season} rainfall')
    ax.set_title(f'Included share of Ethiopia for each candidate (CHIRPS {ctx.period})', loc='left', fontsize=10)
    fig.savefig(out / 'candidate_area_heatmap.png', dpi=130)
    plt.close(fig)
    ids = [c['candidate_id'] for c in cands]
    count = (cube.membership.sel(candidate=ids).values == 1).sum(axis=0).astype(float)
    count[~ctx.country] = np.nan
    fig, ax = plt.subplots(figsize=(6.4, 5.4), constrained_layout=True)
    seq = ['#f0f6fe', '#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b']
    m = ax.pcolormesh(edges(ctx.lon), edges(ctx.lat), count, cmap=ListedColormap(seq), norm=BoundaryNorm([0, 1, 4, 8, 12, 16, 19, 20, 21], 8))
    base_map(ax, ctx)
    cb = fig.colorbar(m, ax=ax, shrink=.85, ticks=[0, 1, 4, 8, 12, 16, 19, 20])
    cb.set_label(f'candidates including the cell (of {len(ids)})')
    cb.outline.set_visible(False)
    ax.set_title('How robust is inclusion to the cutoffs?\n20 = included by every candidate; 0 = by none', loc='left', fontsize=10)
    fig.savefig(out / 'candidate_inclusion_map.png', dpi=130)
    plt.close(fig)
    names = list(cands[0]['regional_inclusion_percent'])
    mat = np.array([[c['regional_inclusion_percent'][n] or 0 for c in cands] for n in names])
    fig, ax = plt.subplots(figsize=(12, 3.6), constrained_layout=True)
    ax.imshow(mat, cmap=ListedColormap(BLUES), norm=BoundaryNorm([0, 10, 25, 40, 55, 70, 85, 95, 100.1], 8), aspect='auto')
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            ax.text(j, i, f'{mat[i, j]:.0f}', ha='center', va='center', fontsize=7, color='white' if mat[i, j] > 70 else INK)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names)
    ax.set_xticks(range(len(cands)))
    ax.set_xticklabels([f'{c["rainfall_threshold_mm"]:g}/{c["share_threshold_percent"]:g}' for c in cands], rotation=90, fontsize=7.5)
    ax.set_xlabel('candidate: mm / % of annual')
    ax.set_title('Share of each EMI rainfall region included (%)', loc='left', fontsize=10)
    fig.savefig(out / 'regional_inclusion.png', dpi=130)
    plt.close(fig)
    domain_maps(ctx, out, res, cube)


DOMAIN_COLOURS = ['#e6e5e0', '#52514e', '#256abf']        # excluded, insufficient data, included


def domain_text(ctx, row, is_candidate):
    st = row.get('reference_comparison_status') or {}
    agree = ('EMI agreement: not applicable' if st.get('agreement') is None
             else f'EMI agreement {100 * st["agreement"]:.0f}%' + (' (draft preview)' if 'draft' in str(st.get('mode')) else ''))
    if is_candidate:
        title = f'FMAM ≥ {row["rainfall_threshold_mm"]:g} mm and ≥ {row["share_threshold_percent"]:g}% of annual'
    else:
        title = row['label'].split(':')[0]
    return title, f'{row["included_area_km2"]:,.0f} km² · {row["included_country_percent"]:.1f}% of Ethiopia · {agree}'


def draw_domain(ax, ctx, codes, title, sub, fs=9, labels=True):
    z = np.where(ctx.country, np.where(codes == 1, 2, np.where(codes == -1, 1, 0)), np.nan).astype(float)
    ax.pcolormesh(edges(ctx.lon), edges(ctx.lat), z, cmap=ListedColormap(DOMAIN_COLOURS), vmin=-.5, vmax=2.5)
    base_map(ax, ctx)
    if labels:
        x, y, r = ctx.region_fine
        for k in range(1, 9):
            yy, xx = np.nonzero(r == k)
            if len(yy):
                ax.text(np.median(x[xx]), np.median(y[yy]), ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII'][k - 1], ha='center', va='center',
                        fontsize=fs - 1.5, color=INK, bbox=dict(boxstyle='round,pad=.12', fc=SURF, ec='none', alpha=.8))
    ax.set_title(f'{title}\n{sub}', loc='left', fontsize=fs)


def domain_legend(fig, y=0.0, ncol=4):
    from matplotlib.patches import Patch
    fig.legend(handles=[Patch(fc=DOMAIN_COLOURS[2], label='Included'), Patch(fc=DOMAIN_COLOURS[0], ec=LINE, label='Excluded'),
                        Patch(fc=DOMAIN_COLOURS[1], label='Insufficient data'),
                        plt.Line2D([], [], color='#9e9d98', lw=1.2, label='EMI rainfall regions I–VIII (drawn in white)')],
               loc='lower center', ncol=ncol, fontsize=8.5, frameon=False, bbox_to_anchor=(.5, y))


def domain_maps(ctx, out, res, cube):
    """One comparison-ready PNG per domain (same extent, colours and legend) and two overview sheets."""
    cands, comps = res['candidates'], res['comparators']
    cdir = out / 'candidates'
    cdir.mkdir()
    src = f'CHIRPS v2.0 {ctx.period}'
    rows = [(c['candidate_id'], c, True) for c in cands] + [(c['comparator_id'], c, False) for c in comps]
    for cid, row, is_c in rows:
        title, sub = domain_text(ctx, row, is_c)
        fig, ax = plt.subplots(figsize=(6.6, 6.4), constrained_layout=True)
        draw_domain(ax, ctx, cube.membership.sel(candidate=cid).values, title, sub, fs=10)
        fig.text(.01, .005, f'{cid} · {src} · {ctx.cfg["assessment_id"]}', fontsize=7, color=INK2)
        domain_legend(fig, .03, ncol=2)
        fig.get_layout_engine().set(rect=(0, .1, 1, .88))
        fig.savefig(cdir / f'{cid}.png', dpi=130)
        plt.close(fig)
    mms = sorted({c['rainfall_threshold_mm'] for c in cands})
    shs = sorted({c['share_threshold_percent'] for c in cands})
    fig, axes = plt.subplots(len(mms), len(shs), figsize=(3.3 * len(shs), 3.0 * len(mms) + .8), constrained_layout=True)
    for i, mm in enumerate(mms):
        for j, sh in enumerate(shs):
            c = next(x for x in cands if x['rainfall_threshold_mm'] == mm and x['share_threshold_percent'] == sh)
            st = c['reference_comparison_status']
            draw_domain(axes[i, j], ctx, cube.membership.sel(candidate=c['candidate_id']).values,
                        f'≥ {mm:g} mm, ≥ {sh:g}%', f'{c["included_country_percent"]:.1f}% of Ethiopia · EMI {100 * st["agreement"]:.0f}%',
                        fs=8.5, labels=False)
    fig.suptitle(f'All {len(cands)} FMAM threshold candidates ({src}): rows = FMAM rainfall cutoff, columns = share-of-annual cutoff.\n'
                 'EMI % = agreement with the membership the EMI maps imply (draft preview until the digitization is reviewed).',
                 fontsize=10.5, x=.01, ha='left')
    domain_legend(fig)
    fig.get_layout_engine().set(rect=(0, .03, 1, .95))
    fig.savefig(out / 'domains_all_candidates.png', dpi=110)
    plt.close(fig)
    fig, axes = plt.subplots(1, len(comps), figsize=(4.4 * len(comps), 4.6), constrained_layout=True, squeeze=False)
    for ax, c in zip(axes[0], comps):
        title, sub = domain_text(ctx, c, False)
        draw_domain(ax, ctx, cube.membership.sel(candidate=c['comparator_id']).values, title, sub.replace(' · EMI', '\nEMI'), fs=8.5)
    fig.suptitle(f'Named comparisons ({src})', fontsize=10, x=.01, ha='left')
    domain_legend(fig)
    fig.get_layout_engine().set(rect=(0, .08, 1, .88))
    fig.savefig(out / 'domains_named_comparisons.png', dpi=120)
    plt.close(fig)


def baseline_figure(ctx, out, cfg, res, focus):
    avail = [b for b in res['baselines'] if b['status'] == 'available']
    if not avail:
        return None
    b = avail[0]
    clim = xr.open_dataset(ctx.folders['climatology'] / f'{cfg["season_name"].lower()}_climatology_{b["first"]}_{b["last"]}.nc')
    c = next(x for x in res['candidates'] if x['candidate_id'] == focus)
    base = ra.classify(ctx.clim, c['rainfall_threshold_mm'], c['share_threshold_percent'], ctx.w.ethiopia_fraction.values)
    alt = ra.classify(clim, c['rainfall_threshold_mm'], c['share_threshold_percent'], ctx.w.ethiopia_fraction.values)
    z = np.full(base.shape, np.nan)
    z[ctx.country] = 0
    z[(base == 1) & (alt == 1)] = 1
    z[(base != 1) & (alt == 1)] = 2
    z[(base == 1) & (alt != 1)] = 3
    fig, ax = plt.subplots(figsize=(6.4, 5.4), constrained_layout=True)
    ax.pcolormesh(edges(ctx.lon), edges(ctx.lat), z, cmap=ListedColormap(['#e6e5e0', '#9ec5f4', '#1baf7a', '#eb6834']), vmin=-.5, vmax=3.5)
    base_map(ax, ctx)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(fc='#9ec5f4', label='included in both'), Patch(fc='#1baf7a', label=f'only with {b["period"]}'),
                       Patch(fc='#eb6834', label=f'only with {ctx.period}')], loc='lower left', fontsize=8, facecolor=SURF, edgecolor='#e0dfda')
    d = c['baseline_sensitivity'][b['period']]
    ax.set_title(f'Baseline change for {focus}: {ctx.period} vs {b["period"]}\n+{d["gained_area_km2"]:,.0f} km² / −{d["lost_area_km2"]:,.0f} km²', loc='left', fontsize=10)
    fig.savefig(out / 'baseline_changes.png', dpi=130)
    plt.close(fig)
    return b['period']


# ------------------------------------------------------------------------------------------ HTML
def esc(x):
    return html.escape(str(x))


def table(head, rows):
    return ('<div class="tw"><table><thead><tr>' + ''.join(f'<th>{esc(h)}</th>' for h in head) + '</tr></thead><tbody>' +
            ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in rows) + '</tbody></table></div>')


def report_html(cfg, data):
    q, res, refs, cmp_ = data['qc'], data['candidates'], data['references'], data['comparison']
    fig = lambda f, alt: f'<figure><img src="{f}" alt="{esc(alt)}" loading="lazy"><figcaption>{esc(alt)}</figcaption></figure>'
    periods = table(['Period', 'Status', 'Note'], [[p['period'], p['status'], esc(p.get('note') or '')] for p in q['periods']])
    cand_rows = [[c['candidate_id'], f'≥ {c["rainfall_threshold_mm"]:g}', f'≥ {c["share_threshold_percent"]:g}',
                  f'{c["included_area_km2"]:,.0f}', f'{c["included_country_percent"]:.1f}', f'{c["unknown_area_km2"]:,.0f}',
                  ('—' if c['reference_comparison_status'].get('agreement') is None else f'{100 * c["reference_comparison_status"]["agreement"]:.0f}%'
                   ) + f' <span class="muted">({esc(c["reference_comparison_status"]["mode"])})</span>',
                  '; '.join(f'{k}: ' + ('unavailable' if v.get('status') == 'unavailable' else f'+{v["gained_area_km2"]:,.0f}/−{v["lost_area_km2"]:,.0f} km²')
                            for k, v in c['baseline_sensitivity'].items()),
                  f'<a href="domains/{c["candidate_id"]}.nc">NetCDF</a> · <a href="domains/{c["candidate_id"]}.geojson">GeoJSON</a>'] for c in res['candidates']]
    def agree_cell(st):
        if st.get('agreement') is None:
            return f'<span class="muted">{esc(st.get("note") or st.get("mode"))}</span>'
        return f'{100 * st["agreement"]:.0f}% <span class="muted">({esc(st["mode"])})</span>'
    files = lambda i: f'<a href="domains/{i}.nc">NetCDF</a> · <a href="domains/{i}.geojson">GeoJSON</a>'
    comp_rows = [[esc(c['label']), f'{c["included_area_km2"]:,.0f}', f'{c["included_country_percent"]:.1f}',
                  agree_cell(c['reference_comparison_status']), files(c['comparator_id'])] for c in res['comparators']]
    ref_rows = []
    for r in refs['references']:
        reg = r['registration']
        ref_rows.append([r['reference_id'], esc(r['comparison_mode']), esc('; '.join(r['mode_reasons']) or '—'), esc(r['extraction_status']),
                         f'{reg["outline_iou"]}', f'{reg["control_rmse_km"]:.1f} / {(reg["check_rmse_km"] or 0):.1f}', r['document_sha256'][:12]])
    cmp_rows = []
    for c in cmp_['comparisons']:
        m = c.get('metrics') or c.get('draft_preview')
        unit = 'pp' if c.get('deviation_units') == 'percentage points' else c['units']
        cmp_rows.append([c['reference_id'], esc(c['comparison_mode'] + (' (draft preview)' if 'draft_preview' in c else '')),
                         f'{100 * m["exact_agreement"]:.0f}%', f'{100 * m["within_one_class"]:.0f}%',
                         f'{100 * m["field_wetter_share"]:.0f}% / {100 * m["field_drier_share"]:.0f}%',
                         f'{m["interval_deviation"]["median"]:.1f} / {m["interval_deviation"]["p90"]:.1f} {unit}',
                         f'{m["comparable_area"]:,.0f} / {m["uncertain_area"]:,.0f} km²'])
    neigh = table(['From', 'To', 'Changed cutoff', 'Area switching'], [[n['from_candidate'], n['to_candidate'], n['changed'].replace('_', ' '),
                                                                         f'{n["switched_area_km2"]:,.0f} km²'] for n in res['neighbour_changes']])
    fp = data['fingerprint']
    qc_rows = [['Calendar', 'passed' if q['checks']['calendar_consistency']['passed'] else 'FAILED', esc(q['checks']['calendar_consistency']['note'])],
               ['Units', 'mm', esc(q['checks']['units'])],
               ['Years', f'{q["checks"]["years"]["first"]}–{q["checks"]["years"]["last"]} ({q["checks"]["years"]["count"]})', 'gaps: ' + (', '.join(map(str, q['checks']['years']['gaps'])) or 'none')],
               ['Completeness', f'{q["completeness"]["cells_without_complete_baseline"]} cells', esc(q['completeness']['note'])],
               ['Area', f'{q["area"]["country_area_km2"]:,.0f} km²', f'{q["area"]["country_outside_grid_km2"]:,.1f} km² beyond the grid; ' + esc(q['area']['method'])],
               ['Source', 'CHIRPS v2.0', 'sha256 ' + esc((q['source']['sha256'] or '')[:16]) + '…'],
               ['Nested candidates', 'yes' if res['monotonic'] else 'NO', 'raising either cutoff never adds a cell']]
    sel = cfg.get('selected_candidate')
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FMAM rainfall domain review</title><style>
:root{{--bg:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--line:#e0dfda;--accent:#256abf}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--line:#383835;--accent:#6da7ec}} img{{background:#fcfcfb}}}}
body{{background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif;margin:0}}main{{max-width:1100px;margin:auto;padding:16px}}
h1{{font-size:1.5rem}}h2{{margin-top:2rem;border-bottom:1px solid var(--line);padding-bottom:4px}}.muted{{color:var(--ink2);font-size:.88em}}
figure{{margin:12px 0}}img{{max-width:100%;height:auto;border:1px solid var(--line);border-radius:6px}}figcaption{{color:var(--ink2);font-size:.85rem}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}}.tw{{overflow-x:auto}}
table{{border-collapse:collapse;font-size:.86rem;width:100%}}th,td{{border-bottom:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top}}
.note{{border-left:3px solid var(--accent);padding:4px 10px;background:color-mix(in srgb,var(--accent) 8%,transparent)}}
</style></head><body><main>
<h1>{esc(cfg["season_name"])} rainfall domain review <span class="muted">{esc(cfg["assessment_id"])}</span></h1>
<p class="muted">CHIRPS v2.0 {data["period"]} · built {esc(data["created_utc"])} · fingerprint {esc(data["fingerprint_sha256"][:12])}</p>
<p class="note">Selected candidate: <b>{esc(sel) if sel else "none yet"}</b>{(" — " + esc(cfg.get("selection_rationale") or "")) if sel else ". The review shows the evidence; a domain is exported only after an explicit selection."}</p>

<h2 id="climatology">1. Climatology</h2>
<p>Ratio of climatological means from actual-calendar monthly totals (February 29 included); every year of the period required per cell.</p>
<div class="grid">{fig("fmam_total_mm.png", "FMAM mean rainfall")}{fig("annual_total_mm.png", "Mean annual rainfall")}{fig("fmam_share_percent.png", "FMAM share of annual rainfall")}</div>
{fig("monthly_cycle_review.png", "Monthly cycle by EMI rainfall region")}
<h3>Reference periods</h3>{periods}
<h3>Quality control</h3>{table(["Check", "Result", "Detail"], qc_rows)}

<h2 id="references">2. References</h2>
<p>Registered EMI climatology panels (climatologies printed in a 2026 publication; their averaging period is not documented).
The comparison mode follows the evidence: drafts stay <i>visual only</i>.</p>
{table(["Reference", "Mode", "Why not higher", "Digitization", "Outline IoU", "Control / check RMSE (km)", "Document"], ref_rows)}
{fig("reference_comparison.png", "CHIRPS, EMI as published, and CHIRPS in the EMI classes")}
<div class="grid">{"".join(fig(f"georeference_qc_{r['reference_id']}.png", "Registration and digitized classes: " + r["reference_id"]) for r in refs["references"])}</div>

<h2 id="candidates">3. Candidate domains</h2>
{fig("domains_named_comparisons.png", "Named comparisons side by side")}
{fig("domains_all_candidates.png", "All threshold candidates (one map each in candidates/)")}
<div class="grid">{fig("candidate_area_heatmap.png", "Included share of Ethiopia by candidate")}{fig("candidate_inclusion_map.png", "Number of candidates including each cell")}</div>
{fig("regional_inclusion.png", "Regional inclusion by candidate")}
{table(["Candidate", "mm", "% of annual", "Included km²", "% of Ethiopia", "Unknown km²", "Agreement with EMI-implied membership", "Baseline change", "Files"], cand_rows)}
<h3>Named comparisons</h3>{table(["Rule", "Included km²", "% of Ethiopia", "Agreement with EMI-implied membership", "Files"], comp_rows)}
<p class="muted">Domain files: one NetCDF (membership codes: 1 included, 0 excluded, -1 insufficient data, -2 outside Ethiopia) and one GeoJSON outline (cells clipped to the border) per domain, in <code>domains/</code>. They are review candidates, not operational masks.</p>

<h2 id="assessment">4. Assessment</h2>
<h3>Reference agreement</h3>
{table(["Reference", "Mode", "Exact class", "Within one class", "CHIRPS wetter / drier", "Outside-interval median / p90", "Comparable / uncertain area"], cmp_rows)}
<p class="muted">Agreement with EMI-implied membership counts only area where the EMI class lies entirely on one side of a cutoff (half a legend unit tolerance); straddling classes are undecided, never guessed.</p>
<h3>Largest changes between neighbouring cutoffs</h3>{neigh}
{fig("baseline_changes.png", "Baseline sensitivity") if data.get("baseline_period") else "<p>No alternative baseline is available in the data.</p>"}
<p class="muted">Dataset sensitivity: not assessed (CHIRPS only). Forecast skill is reported for a selected domain but never used to move its boundary.</p>
<h3>Inputs</h3><pre class="muted" style="white-space:pre-wrap">{esc(json.dumps({k: v for k, v in fp.items() if k != "code"}, indent=1))}</pre>
</main></body></html>'''


def build(cfg, out, folders, fp):
    ctx = Ctx(cfg, folders)
    climatology_figures(ctx, out)
    import run_rainfall_domain_review as runner
    refs = []
    for r in runner.load_reference_grids(cfg, folders['references']):
        folder = folders['references'] / r['record']['id']
        r['panel'] = next(folder.glob('panel.*'))
        refs.append(r)
    reference_figures(ctx, out, refs)
    res = json.loads((folders['sensitivity'] / 'candidates.json').read_text(encoding='utf-8'))
    with xr.open_dataset(folders['sensitivity'] / 'candidate_membership.nc') as cube:
        cube = cube.load()
    candidate_figures(ctx, out, res, cube)
    focus = cfg.get('selected_candidate') or rc.candidate_id(100, 20)
    if focus not in [c['candidate_id'] for c in res['candidates']]:
        focus = res['candidates'][0]['candidate_id']
    baseline_period = baseline_figure(ctx, out, cfg, res, focus)
    for r in refs:
        shutil.copy2(r['panel'], out / f'{r["record"]["id"]}_panel{r["panel"].suffix}')
    shutil.copytree(folders['sensitivity'] / 'domains', out / 'domains')
    import hashlib
    data = dict(created_utc=runner.now(), assessment_id=cfg['assessment_id'], period=ctx.period,
                qc=json.loads((folders['inspect'] / 'climatology_qc.json').read_text(encoding='utf-8')),
                climatology=json.loads((folders['climatology'] / 'climatology_summary.json').read_text(encoding='utf-8')),
                references=json.loads((folders['references'] / 'references.json').read_text(encoding='utf-8')),
                comparison=json.loads((folders['compare'] / 'reference_comparison.json').read_text(encoding='utf-8')),
                candidates=res, selected_candidate=cfg.get('selected_candidate'), selection_rationale=cfg.get('selection_rationale'),
                focus_candidate=focus, baseline_period=baseline_period, fingerprint=fp,
                fingerprint_sha256=hashlib.sha256(json.dumps(fp, sort_keys=True).encode()).hexdigest(),
                figures=dict(climatology=['fmam_total_mm.png', 'annual_total_mm.png', 'fmam_share_percent.png', 'monthly_cycle_review.png'],
                             references=['reference_comparison.png'] + [f'georeference_qc_{r["record"]["id"]}.png' for r in refs],
                             candidates=['domains_named_comparisons.png', 'domains_all_candidates.png', 'candidate_area_heatmap.png',
                                         'candidate_inclusion_map.png', 'regional_inclusion.png'],
                             assessment=['baseline_changes.png'] if baseline_period else []),
                reference_panels={r['record']['id']: f'{r["record"]["id"]}_panel{r["panel"].suffix}' for r in refs})
    save_json(out / 'assessment_results.json', data)
    save_json(out / 'fingerprint.json', fp)
    (out / 'review_report.html').write_text(report_html(cfg, data), encoding='utf-8')
