r"""Compare CHIRPS v2.0 (the project's current observations) with CHIRPS v3.0 over Ethiopia, before any switch.

Both on the project's 0.25 degree grid: v2 from the daily archive (whole months only), v3 from
prepare_chirps_v3.py (monthly). Over Ethiopia, 1993-2025 (ONDJ seasons 1993/94-2024/25):

* climatology: annual, FMAM, JJAS and ONDJ means and each season's share of annual rainfall;
* year-to-year agreement: per-cell correlation of seasonal totals and of national (area-mean) totals;
* categories: each product's own 1993-2025 terciles; share of cell-years in the same category and in
  opposite outer categories (what a verification would see), and the change in the tercile limits;
* domains: membership under the FMAM rule (>= 100 mm and >= 20% of annual) and the same-shaped JJAS/ONDJ rules;
* 2026: v3 against the v2 files the 2026 verification used (data/raw/chirps/verification_p25).

No forecast, calibration or published result is changed.

    python scripts\compare_chirps_versions.py
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / 'data/raw/chirps/et/et_chirps_pr_r25_1993_2025.nc'
V3 = ROOT / 'data/raw/chirps/et/et_chirps3_monthly_r25.nc'
MASK = ROOT / 'data/masks/ethiopia_common.nc'
V2_2026 = ROOT / 'data/raw/chirps/verification_p25'
OUT = ROOT / 'outputs/chirps_v3_comparison'
SEASONS = {'FMAM': [2, 3, 4, 5], 'JJAS': [6, 7, 8, 9], 'ONDJ': [10, 11, 12, 1]}
RULES = {'FMAM': (100, 20), 'JJAS': (120, 20), 'ONDJ': (120, 20)}      # (mm, % of annual), same shape for all three


def v2_monthly(first, last):
    """Monthly totals from the v2 daily archive; a month is missing where any of its days is missing."""
    with xr.open_dataset(V2) as d:
        p = d.precip.sel(time=slice(f'{first}-01-01', f'{last}-12-31')).load()
    n = p.time.dt.days_in_month.groupby(p.time.dt.strftime('%Y-%m')).first()
    tot = p.groupby(p.time.dt.strftime('%Y-%m')).sum('time', skipna=False)
    cnt = p.notnull().groupby(p.time.dt.strftime('%Y-%m')).sum('time')
    tot = tot.where(cnt == n)
    return tot.rename(strftime='month_id')


def v3_monthly(first, last):
    with xr.open_dataset(V3) as d:
        m = d.monthly_total.sel(time=slice(f'{first}-01-01', f'{last}-12-31')).load()
    m = m.assign_coords(month_id=('time', m.time.dt.strftime('%Y-%m').values)).swap_dims(time='month_id').drop_vars('time')
    return m


def to_year_month(a, first, last):
    """(year, month, lat, lon) array from month_id-indexed totals."""
    years = list(range(first, last + 1))
    out = np.full((len(years), 12, a.sizes['lat'], a.sizes['lon']), np.nan)
    idx = {k: i for i, k in enumerate(a.month_id.values)}
    for yi, y in enumerate(years):
        for m in range(1, 13):
            k = f'{y}-{m:02d}'
            if k in idx:
                out[yi, m - 1] = a.values[idx[k]]
    return years, out


def season_totals(ym, months, cross_year):
    """Seasonal totals per season year; a cross-year season (ONDJ) takes January of the next year."""
    if not cross_year:
        return ym[:, [m - 1 for m in months]].sum(axis=1)
    ond = ym[:-1, [9, 10, 11]].sum(axis=1)
    return ond + ym[1:, 0]


def wmean(x, w):
    ok = np.isfinite(x)
    return float(np.average(x[ok], weights=w[ok])) if ok.any() else None


def terciles(x):
    return np.nanquantile(x, [1 / 3, 2 / 3], axis=0)


def category(x, q):
    return np.where(np.isnan(x), -1, np.where(x < q[0], 0, np.where(x > q[1], 2, 1)))


def corr(a, b):
    am, bm = a - np.nanmean(a, 0), b - np.nanmean(b, 0)
    num = np.nansum(am * bm, 0)
    den = np.sqrt(np.nansum(am ** 2, 0) * np.nansum(bm ** 2, 0))
    with np.errstate(invalid='ignore', divide='ignore'):
        return np.where(den > 0, num / den, np.nan)


def v2_2026(lat, lon):
    """2026 monthly totals from the v2 files the 2026 verification downloaded (global p25 daily, by month)."""
    out = {}
    for f in sorted(V2_2026.glob('chirps-v2.0.2026.*.days_p25.nc')):
        m = int(f.name.split('.')[3])          # chirps-v2.0.YYYY.MM.days_p25.nc
        with xr.open_dataset(f) as d:
            p = d.precip.rename({k: v for k, v in [('latitude', 'lat'), ('longitude', 'lon')] if k in d.precip.dims})
            p = p.sel(lat=xr.DataArray(lat, dims='lat'), lon=xr.DataArray(lon, dims='lon'), method='nearest', tolerance=1e-3).load()
            out[m] = p.sum('time', skipna=False).values
    return out


def figures(out, lat, lon, w, country, clim, corr_maps, agree_maps, domains, ts):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    ext = [lon[0] - .125, lon[-1] + .125, lat[0] - .125, lat[-1] + .125]
    show = lambda a: np.where(country, a, np.nan)
    # 1. climatology: v2, v3, difference (%), per season and annual
    names = ['annual', *SEASONS]
    fig, axes = plt.subplots(len(names), 3, figsize=(12, 3.4 * len(names)), squeeze=False)
    for i, n in enumerate(names):
        a2, a3 = clim[n]['v2'], clim[n]['v3']
        vmax = np.nanpercentile(show(np.maximum(a2, a3)), 98)
        for j, (a, t) in enumerate([(a2, 'CHIRPS v2.0'), (a3, 'CHIRPS v3.0')]):
            im = axes[i, j].imshow(show(a), origin='lower', extent=ext, cmap='YlGnBu', vmin=0, vmax=vmax)
            axes[i, j].set_title(f'{n} mean, {t} (mm)', fontsize=9)
            plt.colorbar(im, ax=axes[i, j], shrink=.8)
        with np.errstate(invalid='ignore', divide='ignore'):
            d = 100 * (a3 - a2) / np.where(a2 > 0, a2, np.nan)
        im = axes[i, 2].imshow(show(d), origin='lower', extent=ext, cmap='BrBG', vmin=-40, vmax=40)
        axes[i, 2].set_title(f'{n}: v3 minus v2 (% of v2)', fontsize=9)
        plt.colorbar(im, ax=axes[i, 2], shrink=.8)
    for ax in axes.flat:
        ax.set_aspect('equal'); ax.tick_params(labelsize=7)
    fig.suptitle('CHIRPS v2.0 vs v3.0 climatology over Ethiopia, 1993-2025 (ONDJ 1993/94-2024/25)', fontsize=11)
    fig.tight_layout(); fig.savefig(out / 'climatology_v2_v3.png', dpi=110); plt.close(fig)
    # 2. year-to-year correlation and same-category share, per season
    fig, axes = plt.subplots(2, 3, figsize=(12, 7.5))
    for j, s in enumerate(SEASONS):
        im = axes[0, j].imshow(show(corr_maps[s]), origin='lower', extent=ext, cmap='viridis', vmin=.5, vmax=1)
        axes[0, j].set_title(f'{s}: correlation of seasonal totals', fontsize=9); plt.colorbar(im, ax=axes[0, j], shrink=.8)
        im = axes[1, j].imshow(show(agree_maps[s]), origin='lower', extent=ext, cmap='viridis', vmin=.33, vmax=1)
        axes[1, j].set_title(f'{s}: same tercile category (share of years)', fontsize=9); plt.colorbar(im, ax=axes[1, j], shrink=.8)
    for ax in axes.flat:
        ax.set_aspect('equal'); ax.tick_params(labelsize=7)
    fig.suptitle('Year-to-year agreement of CHIRPS v2.0 and v3.0 (each with its own 1993-2025 terciles)', fontsize=11)
    fig.tight_layout(); fig.savefig(out / 'agreement_v2_v3.png', dpi=110); plt.close(fig)
    # 3. domain membership under the same rule
    from matplotlib.colors import ListedColormap
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.4))
    for j, s in enumerate(SEASONS):
        code = np.where(~country, np.nan, domains[s]['v2'] * 1 + domains[s]['v3'] * 2)   # 0 none, 1 v2 only, 2 v3 only, 3 both
        axes[j].imshow(code, origin='lower', extent=ext, cmap=ListedColormap(['#f2f2f2', '#d95f02', '#1b9e77', '#7570b3']), vmin=-.5, vmax=3.5,
                       interpolation='nearest')
        mm, sh = RULES[s]
        axes[j].set_title(f'{s} >= {mm} mm and >= {sh}% of annual', fontsize=9)
        axes[j].set_aspect('equal'); axes[j].tick_params(labelsize=7)
    from matplotlib.patches import Patch
    fig.legend(handles=[Patch(color='#7570b3', label='in both'), Patch(color='#d95f02', label='v2 only'), Patch(color='#1b9e77', label='v3 only'),
                        Patch(color='#f2f2f2', label='in neither')], loc='lower center', ncol=4, frameon=False)
    fig.suptitle('Domain membership under the same rule: CHIRPS v2.0 vs v3.0 climatology', fontsize=11)
    fig.subplots_adjust(bottom=.14); fig.savefig(out / 'domains_v2_v3.png', dpi=110); plt.close(fig)
    # 4. national seasonal series
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.6))
    for j, s in enumerate(SEASONS):
        y, a2, a3 = ts[s]['years'], ts[s]['v2'], ts[s]['v3']
        axes[j].plot(y, a2, '-o', ms=3, label='v2.0'); axes[j].plot(y, a3, '-o', ms=3, label='v3.0')
        axes[j].set_title(f'{s}: Ethiopia area-mean total (mm), r = {np.corrcoef(a2, a3)[0, 1]:.3f}', fontsize=9)
        axes[j].tick_params(labelsize=7)
    axes[0].legend(fontsize=8)
    fig.tight_layout(); fig.savefig(out / 'national_series_v2_v3.png', dpi=110); plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--first', type=int, default=1993)
    ap.add_argument('--last', type=int, default=2025)
    a = ap.parse_args()
    m2, m3 = v2_monthly(a.first, a.last), v3_monthly(a.first, a.last)
    lat, lon = m2.lat.values.astype(float), m2.lon.values.astype(float)
    if not (np.allclose(m3.lat.values, lat) and np.allclose(m3.lon.values, lon)):
        raise ValueError('v2 and v3 grids differ')
    with xr.open_dataset(MASK) as mk:
        country = mk.region_mask.values == 1
    w = np.cos(np.deg2rad(lat))[:, None] * np.ones((1, len(lon)))
    years, y2 = to_year_month(m2, a.first, a.last)
    _, y3 = to_year_month(m3, a.first, a.last)
    both = np.isfinite(y2).all(axis=(0, 1)) & np.isfinite(y3).all(axis=(0, 1)) & country
    res = dict(created_utc=datetime.now(timezone.utc).isoformat(timespec='seconds'), period=f'{a.first}-{a.last}',
               cells=dict(country=int(country.sum()), complete_in_both=int(both.sum()),
                          v2_missing_in_country=int((country & ~np.isfinite(y2).all(axis=(0, 1))).sum()),
                          v3_missing_in_country=int((country & ~np.isfinite(y3).all(axis=(0, 1))).sum())),
               inputs=dict(v2=str(V2.relative_to(ROOT)), v3=str(V3.relative_to(ROOT))), seasons={})
    wb = np.where(both, w, 0)
    ann2, ann3 = y2.sum(1).mean(0), y3.sum(1).mean(0)
    clim = {'annual': dict(v2=ann2, v3=ann3)}
    res['annual'] = dict(v2_mm=wmean(np.where(both, ann2, np.nan), w), v3_mm=wmean(np.where(both, ann3, np.nan), w))
    corr_maps, agree_maps, domains, ts = {}, {}, {}, {}
    for s, months in SEASONS.items():
        cross = s == 'ONDJ'
        t2, t3 = season_totals(y2, months, cross), season_totals(y3, months, cross)
        sy = years[:-1] if cross else years
        c2, c3 = t2.mean(0), t3.mean(0)
        clim[s] = dict(v2=c2, v3=c3)
        with np.errstate(invalid='ignore', divide='ignore'):
            sh2, sh3 = 100 * c2 / ann2, 100 * c3 / ann3
        q2, q3 = terciles(t2), terciles(t3)
        k2, k3 = category(t2, q2), category(t3, q3)
        valid = (k2 >= 0) & (k3 >= 0) & both[None]
        same = (k2 == k3) & valid
        opp = (np.abs(k2 - k3) == 2) & valid
        agree_maps[s] = np.where(both, same.sum(0) / np.maximum(valid.sum(0), 1), np.nan)
        corr_maps[s] = np.where(both, corr(t2, t3), np.nan)
        wy = np.broadcast_to(w, t2.shape)
        mm, share = RULES[s]
        d2, d3 = both & (c2 >= mm) & (sh2 >= share), both & (c3 >= mm) & (sh3 >= share)
        domains[s] = dict(v2=d2, v3=d3)
        n2 = np.array([np.average(t2[i][both], weights=w[both]) for i in range(len(sy))])
        n3 = np.array([np.average(t3[i][both], weights=w[both]) for i in range(len(sy))])
        ts[s] = dict(years=sy, v2=n2, v3=n3)
        with np.errstate(invalid='ignore', divide='ignore'):
            rel_q1 = 100 * (q3[0] - q2[0]) / np.where(q2[0] > 0, q2[0], np.nan)
            rel_q2 = 100 * (q3[1] - q2[1]) / np.where(q2[1] > 0, q2[1], np.nan)
        res['seasons'][s] = dict(
            season_years=f'{sy[0]}' + (f'/{(sy[0] + 1) % 100:02d}-{sy[-1]}/{(sy[-1] + 1) % 100:02d}' if cross else f'-{sy[-1]}'),
            mean_mm=dict(v2=wmean(np.where(both, c2, np.nan), w), v3=wmean(np.where(both, c3, np.nan), w)),
            share_percent=dict(v2=wmean(np.where(both, sh2, np.nan), w), v3=wmean(np.where(both, sh3, np.nan), w)),
            mean_abs_difference_percent=wmean(np.where(both & (c2 > 10), np.abs(100 * (c3 - c2) / np.where(c2 > 0, c2, np.nan)), np.nan), w),
            cell_correlation=dict(median=float(np.nanmedian(corr_maps[s][both])), p10=float(np.nanpercentile(corr_maps[s][both], 10)),
                                  area_mean=wmean(corr_maps[s], w)),
            national_series_correlation=float(np.corrcoef(n2, n3)[0, 1]),
            national_mean_bias_mm=float(np.mean(n3 - n2)),
            same_category_share=float(np.sum(np.where(same, wy, 0)) / np.sum(np.where(valid, wy, 0))),
            opposite_category_share=float(np.sum(np.where(opp, wy, 0)) / np.sum(np.where(valid, wy, 0))),
            tercile_limit_change_percent=dict(lower_median=float(np.nanmedian(rel_q1[both & (q2[0] > 10)])),
                                              upper_median=float(np.nanmedian(rel_q2[both & (q2[1] > 10)]))),
            domain_rule=f'>= {mm} mm and >= {share}% of annual',
            domain=dict(v2_share=float(w[d2].sum() / w[both].sum()), v3_share=float(w[d3].sum() / w[both].sum()),
                        in_both=float(w[d2 & d3].sum() / w[both].sum()), v2_only=float(w[d2 & ~d3].sum() / w[both].sum()),
                        v3_only=float(w[d3 & ~d2].sum() / w[both].sum())))
    # 2026: v3 against the v2 files used for the 2026 verification
    v2026 = v2_2026(lat, lon)
    if v2026:
        with xr.open_dataset(V3) as d:
            v3m = {int(t.dt.month): d.monthly_total.sel(time=t).values for t in d.time if int(t.dt.year) == 2026}
        rows = {}
        for m, a2 in v2026.items():
            if m in v3m:
                ok = both & np.isfinite(a2) & np.isfinite(v3m[m])
                rows[f'2026-{m:02d}'] = dict(v2_mm=wmean(np.where(ok, a2, np.nan), w), v3_mm=wmean(np.where(ok, v3m[m], np.nan), w),
                                            cell_correlation=float(np.corrcoef(a2[ok], v3m[m][ok])[0, 1]))
        res['verification_2026_months'] = rows
    out = OUT
    out.mkdir(parents=True, exist_ok=True)
    figures(out, lat, lon, w, both, clim, corr_maps, agree_maps, domains, ts)
    (out / 'comparison.json').write_text(json.dumps(res, indent=1), encoding='utf-8')
    for s, r in res['seasons'].items():
        print(f"{s}: mean {r['mean_mm']['v2']:.0f} -> {r['mean_mm']['v3']:.0f} mm; share {r['share_percent']['v2']:.1f} -> {r['share_percent']['v3']:.1f}%; "
              f"cell r median {r['cell_correlation']['median']:.3f}; national r {r['national_series_correlation']:.3f}; "
              f"same category {100 * r['same_category_share']:.0f}%, opposite {100 * r['opposite_category_share']:.1f}%; "
              f"domain {100 * r['domain']['v2_share']:.1f}% -> {100 * r['domain']['v3_share']:.1f}% (v2 only {100 * r['domain']['v2_only']:.1f}%, v3 only {100 * r['domain']['v3_only']:.1f}%)")
    print('Saved', out)


if __name__ == '__main__':
    main()
