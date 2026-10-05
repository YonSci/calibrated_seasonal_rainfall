"""Conservative remapping for aligned, nested regular latitude/longitude grids.

Each target cell must lie wholly inside one source cell. This is first-order
conservative remapping with piecewise-constant source cells, not downscaling.
Requires the starter project's scripts/common.py and existing dependencies.
"""
import argparse
import calendar
import json
from datetime import date, datetime, timezone
import numpy as np
import xarray as xr
from common import ROOT, load_config, save_json, save_netcdf
from cycle import CYCLE


def edges(values):
    """Infer regular cell bounds from centres; reject unsupported grids."""
    a = np.asarray(values, dtype=float)
    if a.ndim != 1 or len(a) < 2 or not np.isfinite(a).all():
        raise ValueError('Coordinates must be finite one-dimensional arrays.')
    delta = np.diff(a)
    if not (delta > 0).all() or not np.allclose(delta, delta[0], atol=1e-7, rtol=0):
        raise ValueError('Only ascending, unique, regular coordinates are supported.')
    return np.r_[a[0]-delta[0]/2, (a[:-1]+a[1:])/2, a[-1]+delta[0]/2]


def nested_indices(source, target):
    s, t = edges(source), edges(target)
    if not np.allclose(s[[0,-1]], t[[0,-1]], atol=1e-7, rtol=0):
        raise ValueError('Source and target outer cell bounds differ; no extrapolation allowed.')
    idx = np.searchsorted(s, np.asarray(target), side='right')-1
    if (idx < 0).any() or (idx >= len(source)).any():
        raise ValueError('Target outside source grid.')
    if (t[:-1] < s[idx]-1e-7).any() or (t[1:] > s[idx+1]+1e-7).any():
        raise ValueError('Target cells cross source boundaries; this nested-grid method cannot be used.')
    return idx


def area_weights(lat, lon):
    """Spherical cell area / Earth radius squared; sufficient for conservation."""
    la, lo = np.deg2rad(edges(lat)), np.deg2rad(edges(lon))
    if la[0] < -np.pi/2 or la[-1] > np.pi/2:
        raise ValueError('Latitude bounds outside Earth.')
    return np.diff(np.sin(la))[:,None]*np.diff(lo)[None,:]


def remap(model, target):
    model = model.sortby('lat').sortby('lon')
    target = target.sortby('lat').sortby('lon')
    ilat = nested_indices(model.lat.values, target.lat.values)
    ilon = nested_indices(model.lon.values, target.lon.values)
    a = model.precip_season.transpose('member','lat','lon').values
    if not np.isfinite(a).all() or (a < 0).any():
        raise ValueError('ECMWF totals must be complete, finite and nonnegative.')
    b = a[:,ilat,:][:,:,ilon]
    source_integral = np.sum(a*area_weights(model.lat.values, model.lon.values), axis=(1,2))
    target_integral = np.sum(b*area_weights(target.lat.values, target.lon.values), axis=(1,2))
    if not np.allclose(source_integral, target_integral, atol=1e-9, rtol=1e-12):
        raise ValueError('Area-integral conservation check failed.')
    err = float(np.max(np.abs(source_integral-target_integral)/np.maximum(np.abs(source_integral),1e-12)))
    out = xr.Dataset({'precip_season': (('member','lat','lon'), b)},
        coords={'member':model.member.values, 'lat':target.lat.values, 'lon':target.lon.values},
        attrs=dict(model.attrs))
    out.precip_season.attrs = dict(model.precip_season.attrs)
    out.attrs.update(grid='CHIRPS coordinate grid; ECMWF remapped',
        remapping='first-order conservative, aligned nested regular cells',
        bounds_assumption='cell edges inferred as midpoints, half spacing at outer edges',
        spatial_information='Original ECMWF resolution; no added subgrid forecast information',
        conservation_max_relative_error=err)
    for coord in ('lat','lon'):
        out[coord].attrs.update(units='degrees_north' if coord=='lat' else 'degrees_east', bounds=coord+'_bounds')
        e = edges(out[coord].values)
        out[coord+'_bounds'] = ((coord,'bounds'), np.column_stack((e[:-1],e[1:])))
    return out, err


def check_season(ds, cfg, year, is_model):
    start = date.fromisoformat(f'{year}-'+cfg['season']['start'])
    end = date.fromisoformat(f'{year}-'+cfg['season']['end'])
    days = (end-start).days+1
    if ds.precip_season.attrs.get('units') != 'mm' or ds.attrs.get('expected_days') != days:
        raise ValueError('Incorrect rainfall units or season length.')
    previous = json.loads(ds.attrs['config_json'])
    if previous['season'] != cfg['season'] or previous['initialization_month'] != cfg['initialization_month']:
        raise ValueError('Prepared file season differs from active configuration.')
    if is_model:
        if ds.attrs.get('season_start') != start.isoformat() or ds.attrs.get('season_end') != end.isoformat():
            raise ValueError('Model season dates do not match requested year.')
        expected = CYCLE.members(year)
        if ds.sizes['member'] != expected or len(np.unique(ds.member)) != expected:
            raise ValueError('Unexpected or duplicate ensemble members.')
        if not (ds.valid_day_count.values == days).all():
            raise ValueError('Incomplete ECMWF daily coverage.')
    else:
        if ds.sizes.get('year') != 1 or int(ds.year.values[0]) != year:
            raise ValueError('CHIRPS year mismatch.')
        a = ds.precip_season.values
        good = np.isfinite(a)
        if np.isinf(a).any() or (a[good] < 0).any() or not good.any():
            raise ValueError('Invalid CHIRPS seasonal rainfall.')
        if not np.array_equal(good, ds.valid_day_count.values == days):
            raise ValueError('CHIRPS totals and daily coverage disagree.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='config/project.json')
    parser.add_argument('--years',nargs='+',type=int,help='Explicit years; omit to process configured archive.')
    args = parser.parse_args()
    cfg = load_config(args.config)
    years = args.years if args.years else list(range(cfg['archive_years'][0],cfg['archive_years'][1]+1))
    if len(set(years)) != len(years) or any(y < cfg['archive_years'][0] or y > cfg['archive_years'][1] for y in years):
        raise ValueError('Years must be unique and inside archive_years.')
    tag = f"init{cfg['initialization_month']:02d}_{cfg['season']['name']}"
    source = ROOT/'data/interim'/tag
    dest = ROOT/'data/processed'/tag
    reference_year = cfg['observation_years'][0]
    with xr.open_dataset(source/f'chirps_{reference_year}_native.nc') as ds:
        target = ds.load().sortby('lat').sortby('lon')
    check_season(target,cfg,reference_year,False)
    reports = []
    for year in years:
        model_path = source/f'ecmwf_{year}_native.nc'
        with xr.open_dataset(model_path) as ds:
            model = ds.load()
        check_season(model,cfg,year,True)
        out, error = remap(model,target)
        row = dict(year=year,members=out.sizes['member'],lat_count=out.sizes['lat'],lon_count=out.sizes['lon'],
                   conservation_max_relative_error=error,missing_model_fraction=0.0)
        obs = None
        if cfg['observation_years'][0] <= year <= cfg['observation_years'][1]:
            with xr.open_dataset(source/f'chirps_{year}_native.nc') as ds:
                obs = ds.load().sortby('lat').sortby('lon')
            check_season(obs,cfg,year,False)
            if not np.array_equal(obs.lat,target.lat) or not np.array_equal(obs.lon,target.lon):
                raise ValueError('CHIRPS coordinates changed between years.')
            obs['observation_valid'] = np.isfinite(obs.precip_season).astype('int8')
            obs.observation_valid.attrs['long_name'] = '1: complete seasonal observation; 0: missing'
            row.update(observation_valid_cells=int(obs.observation_valid.sum()),
                       observation_missing_cells=int((obs.observation_valid==0).sum()))
            obs.attrs['grid'] = 'CHIRPS coordinate grid; observations not remapped'
        else:
            row['observations'] = 'Outside configured observation period'
        out.attrs.update(native_seasonal_file=str(model_path),processing_utc=datetime.now(timezone.utc).isoformat())
        save_netcdf(out,dest/f'ecmwf_{year}_common.nc')
        if obs is not None:
            save_netcdf(obs,dest/f'chirps_{year}_common.nc')
        reports.append(row)
        print(f'Regridded {year}: {out.sizes["member"]} members; {out.sizes["lat"]} x {out.sizes["lon"]}; conservation error {error:.3g}')
    report_path = ROOT/'outputs/qc'/f'regridding_{tag}.json'
    save_json(report_path,dict(method='first-order conservative nested-grid remapping',years=reports))
    print(f'Finished. Report: {report_path}')


if __name__ == '__main__':
    main()
