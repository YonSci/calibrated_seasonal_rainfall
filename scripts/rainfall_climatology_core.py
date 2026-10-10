"""Observational climatology for the rainfall-domain review (FMAM first).

Input contract: monthly_total(year, month, lat, lon) in mm, actual-calendar monthly accumulations
(February 29 retained), from the CHIRPS calendar cache written by prepare_regimes.py. Daily CHIRPS
values are mm per one-day interval, so monthly and seasonal totals are plain sums (no 86 400 factor).

Climatology = ratio of climatological means: share = 100 * mean(FMAM) / mean(annual), computed only
where every requested year is complete (no partial baselines). A requested period that is not fully
inside the data is reported as unavailable, never shortened.

Area weights come from intersecting each grid cell with the Ethiopia polygon, measured on the WGS84
ellipsoid, so coverage percentages are areas of Ethiopia, not cell counts.
"""
import hashlib
import json
from pathlib import Path
import numpy as np
import xarray as xr
from common import ROOT, load_config, season_months as project_season_months, source_path

SCHEMA_VERSION = 1
METHOD_VERSION = 'rainfall_domain_review_v1'
SHARE_METHODS = {'ratio_of_climatological_means'}
PERIOD_POLICIES = {'record_unavailable', 'fail'}
CLEANUP = {'none'}


class IncompleteBaseline(ValueError):
    """The requested reference period is not complete in the data."""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def rel(path):
    path = Path(path)
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


# ----------------------------------------------------------------------------------- configuration
def load_review_config(path):
    """Validate the review configuration (it is not a forecast project file)."""
    path = source_path(path)
    cfg = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    problems = []
    def need(key, kind):
        if key not in cfg:
            problems.append(f'missing "{key}"')
        elif not isinstance(cfg[key], kind):
            problems.append(f'"{key}" must be {kind.__name__ if isinstance(kind, type) else kind}')
    if cfg.get('schema_version') != SCHEMA_VERSION:
        problems.append(f'schema_version must be {SCHEMA_VERSION}')
    for key, kind in [('assessment_id', str), ('project_config', str), ('monthly_cache', str), ('monthly_variable', str),
                      ('country_mask', str), ('country_boundary', str), ('season_name', str), ('season_months', list),
                      ('annual_months', list), ('application_period', list), ('additional_reference_periods', list),
                      ('candidate_thresholds', dict), ('reference_registry', str), ('output_root', str)]:
        need(key, kind)
    if problems:
        raise ValueError(f'{path}: ' + '; '.join(problems))
    months = cfg['season_months']
    if not months or len(set(months)) != len(months) or not all(isinstance(m, int) and 1 <= m <= 12 for m in months):
        problems.append('season_months must be distinct month numbers 1..12')
    if sorted(cfg['annual_months']) != list(range(1, 13)):
        problems.append('annual_months must list all twelve months')
    for p in [cfg['application_period'], *cfg['additional_reference_periods']]:
        if not (isinstance(p, list) and len(p) == 2 and all(isinstance(y, int) for y in p) and p[0] <= p[1]):
            problems.append(f'invalid period {p!r}')
    if cfg.get('annual_share_method', 'ratio_of_climatological_means') not in SHARE_METHODS:
        problems.append(f'annual_share_method must be one of {sorted(SHARE_METHODS)}')
    if cfg.get('unavailable_optional_period', 'record_unavailable') not in PERIOD_POLICIES:
        problems.append(f'unavailable_optional_period must be one of {sorted(PERIOD_POLICIES)}')
    if cfg.get('candidate_cleanup', 'none') not in CLEANUP:
        problems.append('candidate_cleanup must be "none" (cleanup changes membership; assess it separately)')
    if cfg.get('require_complete_baseline', True) is not True:
        problems.append('require_complete_baseline must be true')
    th = cfg['candidate_thresholds']
    for key in ('seasonal_rainfall_mm', 'annual_share_percent'):
        v = th.get(key)
        if not (isinstance(v, list) and v and all(isinstance(x, (int, float)) and x >= 0 for x in v) and v == sorted(set(v))):
            problems.append(f'candidate_thresholds.{key} must be an increasing list of non-negative numbers')
    sel = cfg.get('selected_candidate')
    if sel is not None and not isinstance(sel, str):
        problems.append('selected_candidate must be null or a candidate id')
    if problems:
        raise ValueError(f'{path}: ' + '; '.join(problems))
    project = load_config(cfg['project_config'])
    if project['season']['name'] != cfg['season_name'] or project_season_months(project) != months:
        raise ValueError(f'{path}: season {cfg["season_name"]} {months} does not match {cfg["project_config"]}')
    cfg['_path'] = str(path)
    cfg['_project'] = project
    return cfg


def candidate_id(mm, share):
    fmt = lambda x: f'{x:g}'.replace('.', 'p')
    return f'mm{fmt(mm)}_share{fmt(share)}'


def candidates(cfg):
    th = cfg['candidate_thresholds']
    return [dict(id=candidate_id(mm, sh), seasonal_rainfall_mm=mm, annual_share_percent=sh)
            for mm in th['seasonal_rainfall_mm'] for sh in th['annual_share_percent']]


# ----------------------------------------------------------------------------------- monthly input
def monthly_totals_from_daily(time, values):
    """Actual-calendar monthly totals per year from daily mm amounts; the calendar must be complete.

    Returns (years, monthly[year, month, ...]). Missing, duplicate or unordered dates raise ValueError
    (a date absent from the coordinate cannot be caught by skipna=False alone).
    """
    from regime_core import calendar_arrays
    time = np.asarray(time).astype('datetime64[D]')
    values = np.asarray(values, float)
    if len(np.unique(time)) != len(time):
        raise ValueError('Duplicate dates in the daily input')
    years = sorted({int(str(t)[:4]) for t in time})
    out = []
    for y in years:
        pick = (time >= np.datetime64(f'{y}-01-01')) & (time < np.datetime64(f'{y + 1}-01-01'))
        _, monthly = calendar_arrays(time[pick], values[pick], y)
        out.append(monthly)
    return years, np.stack(out)


def load_monthly(cfg):
    """Validated monthly_total(year, month, lat, lon) and a QC record."""
    path = source_path(cfg['monthly_cache'])
    qc = dict(cache=rel(path), cache_sha256=sha256_file(path), variable=cfg['monthly_variable'], checks={})
    with xr.open_dataset(path) as ds:
        if cfg['monthly_variable'] not in ds:
            raise ValueError(f'{path}: no variable {cfg["monthly_variable"]}')
        da = ds[cfg['monthly_variable']].load()
        attrs = dict(ds.attrs)
        noleap = ds['daily_noleap'].astype('float64').sum('day', skipna=False).load() if 'daily_noleap' in ds else None
    checks = qc['checks']
    if set(da.dims) != {'year', 'month', 'lat', 'lon'}:
        raise ValueError(f'monthly_total dims must be year, month, lat, lon; got {da.dims}')
    da = da.transpose('year', 'month', 'lat', 'lon')
    units = str(da.attrs.get('units', '')).strip().lower()
    if units != 'mm':
        raise ValueError(f'monthly_total units must be mm (accumulation), got {units!r}')
    checks['units'] = 'mm (monthly accumulation of daily mm amounts; no rate conversion)'
    years = da.year.values.astype(int)
    if len(np.unique(years)) != len(years) or not np.all(np.diff(years) > 0):
        raise ValueError('Years must be unique and increasing')
    gaps = sorted(set(range(years[0], years[-1] + 1)) - set(years.tolist()))
    checks['years'] = dict(first=int(years[0]), last=int(years[-1]), count=len(years), gaps=gaps)
    if da.month.values.tolist() != list(range(1, 13)):
        raise ValueError('Months must be exactly 1..12')
    v = da.values
    if np.isinf(v).any():
        raise ValueError('Infinite monthly rainfall')
    if (v[np.isfinite(v)] < 0).any():
        raise ValueError('Negative monthly rainfall')
    missing = ~np.isfinite(v)
    checks['missing_values'] = dict(total=int(missing.sum()), by_year={int(y): int(missing[i].sum()) for i, y in enumerate(years) if missing[i].any()},
                                    note='Ocean / outside-CHIRPS cells are missing in every year; they are reported, never set to zero.')
    with xr.open_dataset(source_path(cfg['country_mask'])) as m:
        mlat, mlon = m.lat.values, m.lon.values
    if not (np.array_equal(da.lat.values, mlat) and np.array_equal(da.lon.values, mlon)):
        raise ValueError('Monthly cache grid differs from the country mask grid')
    lat, lon = da.lat.values.astype(float), da.lon.values.astype(float)
    dlat, dlon = np.diff(lat), np.diff(lon)
    if not (np.allclose(dlat, dlat[0]) and np.allclose(dlon, dlon[0])):
        raise ValueError('Grid must be regular')
    checks['grid'] = dict(lat=[float(lat[0]), float(lat[-1])], lon=[float(lon[0]), float(lon[-1])],
                          resolution_deg=[float(abs(dlat[0])), float(abs(dlon[0]))], shape=[len(lat), len(lon)])
    checks['calendar_policy'] = attrs.get('calendar_policy', 'not recorded')
    if 'Feb29' not in checks['calendar_policy']:
        raise ValueError('The cache does not document that monthly totals retain February 29')
    qc['source'] = dict(path=attrs.get('source_path'), sha256=attrs.get('source_sha256'), dataset='CHIRPS v2.0 (0.25 deg)')
    if not qc['source']['sha256']:
        raise ValueError('The cache does not record its CHIRPS source hash')
    if noleap is not None:                     # actual-calendar totals = 365-day cycle + Feb 29 rain only
        diff = da.sum('month', skipna=False) - noleap
        leap = np.array([y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) for y in years])
        d = diff.values
        non_leap = np.nanmax(np.abs(d[~leap])) if (~leap).any() else 0.0
        checks['calendar_consistency'] = dict(
            max_abs_difference_non_leap_years_mm=float(non_leap),
            min_difference_leap_years_mm=float(np.nanmin(d[leap])) if leap.any() else None,
            passed=bool(non_leap < 1e-3 and (not leap.any() or np.nanmin(d[leap]) > -1e-3)),
            note='Annual monthly-total sum minus the 365-day cycle sum: zero in non-leap years, Feb 29 rain (>= 0) in leap years.')
        if not checks['calendar_consistency']['passed']:
            raise ValueError('Monthly totals are inconsistent with the daily cycle (calendar problem)')
    return da, qc


# ----------------------------------------------------------------------------------- climatology
def period_status(available_years, period):
    years = list(range(period[0], period[1] + 1))
    missing = [y for y in years if y not in set(int(x) for x in available_years)]
    return dict(period=f'{period[0]}-{period[1]}', first=period[0], last=period[1],
                status='available' if not missing else 'unavailable', missing_years=missing,
                note=None if not missing else (f'{len(missing)} of {len(years)} years are not in the data '
                                               f'({missing[0]}-{missing[-1]}); the period is not shortened.'))


def climatology(monthly, first_year, last_year, season_months, annual_months=tuple(range(1, 13))):
    """FMAM / annual climatology for one complete period (ratio of climatological means)."""
    years = list(range(first_year, last_year + 1))
    have = set(int(y) for y in monthly.year.values)
    missing = [y for y in years if y not in have]
    if missing:
        raise IncompleteBaseline(f'{first_year}-{last_year} needs years {missing} that the data does not contain')
    sel = monthly.sel(year=years)
    season_by_year = sel.sel(month=list(season_months)).sum('month', skipna=False)
    annual_by_year = sel.sel(month=list(annual_months)).sum('month', skipna=False)
    valid_year = season_by_year.notnull() & annual_by_year.notnull()
    season = season_by_year.mean('year', skipna=False)
    annual = annual_by_year.mean('year', skipna=False)
    share = 100.0 * season / annual.where(annual > 0)
    result = xr.Dataset({'season_mean_mm': season, 'annual_mean_mm': annual, 'season_share_percent': share,
                         'monthly_mean_mm': sel.mean('year', skipna=False),
                         'valid_year_count': valid_year.sum('year').astype('int16')})
    for name in ('season_mean_mm', 'annual_mean_mm', 'monthly_mean_mm'):
        result[name].attrs['units'] = 'mm'
    result['season_share_percent'].attrs['units'] = '%'
    result.attrs.update(reference_period=f'{first_year}-{last_year}', years=len(years),
                        season_months=','.join(str(m) for m in season_months),
                        annual_share_method='ratio_of_climatological_means',
                        completeness_policy='all requested years required per cell')
    return result


def wettest_of_partition(monthly_mean):
    """Season code with the largest climatological total: 0 FMAM, 1 JJAS, 2 ONDJ (they partition the year)."""
    parts = [[2, 3, 4, 5], [6, 7, 8, 9], [10, 11, 12, 1]]
    totals = np.stack([monthly_mean.sel(month=p).sum('month', skipna=False).values for p in parts])
    out = np.full(totals.shape[1:], -1)
    ok = np.isfinite(totals).all(axis=0)
    out[ok] = np.argmax(totals[:, ok], axis=0)
    return out, totals


# ----------------------------------------------------------------------------------- area weights
def country_shape(boundary):
    import shapefile
    from shapely.geometry import shape
    from shapely.ops import unary_union
    return unary_union([shape(s.__geo_interface__) for s in shapefile.Reader(str(source_path(boundary))).shapes()])


def geodesic_km2(geom):
    from pyproj import Geod
    return abs(Geod(ellps='WGS84').geometry_area_perimeter(geom)[0]) / 1e6


def country_area_weights(lat, lon, boundary):
    """ethiopia_cell_area_km2 and ethiopia_fraction from cell-bound / polygon intersections.

    Returns (Dataset, country_km2, outside_grid_km2): the part of the country beyond the grid is
    reported separately, never silently dropped.
    """
    from shapely.geometry import box
    from shapely.prepared import prep
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    hy, hx = abs(lat[1] - lat[0]) / 2, abs(lon[1] - lon[0]) / 2
    poly = country_shape(boundary)
    fast = prep(poly)
    area = np.zeros((len(lat), len(lon)))
    frac = np.zeros_like(area)
    for i, y in enumerate(lat):
        for j, x in enumerate(lon):
            cell = box(x - hx, y - hy, x + hx, y + hy)
            if not fast.intersects(cell):
                continue
            part = cell if fast.contains(cell) else cell.intersection(poly)
            if part.is_empty:
                continue
            a = geodesic_km2(part)
            area[i, j], frac[i, j] = a, a / geodesic_km2(cell)
    country = geodesic_km2(poly)
    grid = box(lon[0] - hx, lat[0] - hy, lon[-1] + hx, lat[-1] + hy)
    outside = geodesic_km2(poly.difference(grid)) if not grid.contains(poly) else 0.0
    ds = xr.Dataset({'ethiopia_cell_area_km2': (('lat', 'lon'), area), 'ethiopia_fraction': (('lat', 'lon'), frac)},
                    coords=dict(lat=lat, lon=lon))
    ds.ethiopia_cell_area_km2.attrs.update(units='km2', long_name='Area of the cell inside Ethiopia (WGS84 geodesic)')
    ds.ethiopia_fraction.attrs.update(units='1', long_name='Fraction of the cell area inside Ethiopia')
    ds.attrs.update(country_area_km2=country, country_outside_grid_km2=outside, boundary=rel(source_path(boundary)))
    return ds, country, outside


def area_coverage(membership, area_km2):
    """Percent of the given area that is included (membership 1/0; other codes are not included)."""
    a = np.asarray(area_km2, float)
    m = np.asarray(membership) == 1
    return float(100 * a[m].sum() / a.sum()) if a.sum() > 0 else float('nan')
