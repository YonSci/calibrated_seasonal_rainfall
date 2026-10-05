"""Build a season's rainfall-domain mask for the presentation layer.

Same rule as the JJAS R1+R2 rainfall domain: Ethiopia cells where the season's
climatological CHIRPS rainfall is at least 120 mm AND at least 20 % of the mean
annual rainfall. Climatologies use the project's observation years (the season
window may cross the year boundary, e.g. ONDJ). Presentation and summaries only;
never used in calibration.

    python scripts\\build_season_domain.py --config config\\ondj\\project.json
"""
import argparse
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import xarray as xr
from common import ROOT, load_config, source_path, save_netcdf, season_window

MIN_MM, MIN_SHARE = 120.0, 0.20


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--config', required=True)
    p.add_argument('--region-mask', default='data/masks/ethiopia_common.nc')
    p.add_argument('--output', help='Default: data/masks/init<MM>_<SEASON>_rainfall_domain.nc')
    a = p.parse_args()
    cfg = load_config(a.config)
    name = cfg['season']['name']
    tag = f"init{cfg['initialization_month']:02d}_{name}"
    first, last = cfg['observation_years']
    with xr.open_dataset(source_path(a.region_mask)) as m:
        region = m.region_mask.load()
    with xr.open_dataset(source_path(cfg['chirps_file'])) as ds:
        daily = ds[cfg.get('chirps_variable', 'precip')].sortby('lat').sortby('lon')
        daily = daily.sel(lat=region.lat, lon=region.lon, method='nearest', tolerance=1e-4)
        if not (np.allclose(daily.lat, region.lat) and np.allclose(daily.lon, region.lon)):
            raise ValueError('CHIRPS archive grid does not match the common grid')
        seasons = []
        for y in range(first, last + 1):
            s, e = season_window(cfg, y)
            block = daily.sel(time=slice(pd.Timestamp(s), pd.Timestamp(e)))
            if len(block.time) != (e - s).days + 1:
                raise ValueError(f'Incomplete CHIRPS {name} {y}')
            seasons.append(block.sum('time', skipna=False).values)
        annual = [daily.sel(time=str(y)).sum('time', skipna=False).values for y in range(first, last + 1)]
    clim = np.mean(seasons, axis=0)
    ann = np.mean(annual, axis=0)
    share = np.divide(clim, ann, out=np.full_like(clim, np.nan), where=ann > 0)
    country = region.values == 1
    domain = country & np.isfinite(clim) & (clim >= MIN_MM) & (share >= MIN_SHARE)
    if not domain.any():
        raise ValueError('Empty rainfall domain')
    coords = dict(lat=region.lat, lon=region.lon)
    out = xr.Dataset({'season_domain': (('lat', 'lon'), domain.astype('int8')),
                      'season_climatology_mm': (('lat', 'lon'), clim),
                      'annual_climatology_mm': (('lat', 'lon'), ann),
                      'season_share_of_annual': (('lat', 'lon'), share)}, coords=coords)
    w = np.cos(np.deg2rad(region.lat.values))[:, None] * np.ones(len(region.lon))
    pct = float(100 * w[domain].sum() / w[country].sum())
    out.attrs.update(
        season=name, initialization_month=cfg['initialization_month'], reference_years=f'{first}-{last}',
        domain_definition=(f'Fixed {first}-{last} descriptive domain: {name} climatological CHIRPS rainfall '
                           f'>={MIN_MM:g} mm and >={MIN_SHARE:.0%} of mean annual rainfall (same rule as the JJAS R1+R2 '
                           f'rainfall criteria). The same domain is used for the season and each of its months.'),
        domain_cells=int(domain.sum()), domain_country_area_percent=pct,
        created_utc=datetime.now(timezone.utc).isoformat(), source=str(cfg['chirps_file']))
    path = source_path(a.output) if a.output else ROOT / f'data/masks/{tag}_rainfall_domain.nc'
    save_netcdf(out, path)
    print(f'{name} rainfall domain: {int(domain.sum())} cells, {pct:.1f}% of Ethiopia -> {path}')


if __name__ == '__main__':
    main()
