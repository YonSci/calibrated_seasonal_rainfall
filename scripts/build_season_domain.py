"""Build a season's rainfall-domain mask for the presentation layer.

Same rule as the JJAS R1+R2 rainfall domain: Ethiopia cells where the season's
climatological CHIRPS rainfall is at least 120 mm AND at least 20 % of the mean
annual rainfall. Climatologies use the project's observation years (the season
window may cross the year boundary, e.g. ONDJ). Presentation and summaries only;
never used in calibration.

    python scripts\\build_season_domain.py --config config\\ondj\\project.json

--method regime (recommended; scientific masking walkthrough, notebooks/Rainfall_domains_JJAS_FMAM_ONDJ.ipynb)
keeps only the rainfall regimes for which the season is a real rainy season, with a seasonal rainfall floor,
using the GitHub-refined regime classification of the CHIRPS 1993-2025 daily climatology:
    JJAS: R1 + R2, JJAS >= 120 mm and >= 20 % of annual   (Kiremt; identical to the R1+R2 domain)
    FMAM: R2, FMAM >= 80 mm                                (Belg)
    ONDJ: R3, ONDJ >= 30 mm                                (Deyr / Hagaya; walkthrough rule defined on OND)
Patches smaller than 3 cells are removed (4-connected). Output: data/masks/init<MM>_<SEASON>_regime_domain.nc

    python scripts\\build_season_domain.py --config config\\ondj\\project.json --method regime
"""
import argparse
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import xarray as xr
from common import ROOT, load_config, source_path, save_netcdf, season_window

MIN_MM, MIN_SHARE = 120.0, 0.20
REGIME_RULES = {'JJAS': dict(regimes=[1, 2], min_mm=120, min_share=0.20, label='JJAS R1+R2 rainfall domain', local='Kiremt'),
                'FMAM': dict(regimes=[2], min_mm=80, min_share=None, label='FMAM R2 (Belg) rainfall domain', local='Belg'),
                'ONDJ': dict(regimes=[3], min_mm=30, min_share=None, label='ONDJ R3 (Deyr) rainfall domain',
                             local='Deyr / Hagaya')}
REGIME_CLIMATOLOGY = 'data/processed/regime_climatology/descriptive_1993_2025.nc'


def regime_domain(cfg, region_path, output):
    """Walkthrough logic: regime classification, then the season's regimes and rainfall floor."""
    import json
    from common import season_months
    from github_regime_core import classify, remove_small, MONTH_EDGES, METHOD, LABELS
    name = cfg['season']['name']
    if name not in REGIME_RULES:
        raise ValueError(f'No regime rule for season {name}; add one to REGIME_RULES')
    rule = REGIME_RULES[name]
    with xr.open_dataset(source_path(REGIME_CLIMATOLOGY)) as c:
        q = c.daily_climatology.transpose('day', 'lat', 'lon').values
        lat, lon = c.lat.values, c.lon.values
        years = json.loads(c.attrs['training_years'])
    with xr.open_dataset(source_path(region_path)) as m:
        region = m.region_mask.load()
    if not (np.allclose(region.lat, lat) and np.allclose(region.lon, lon)):
        raise ValueError('Regime climatology grid differs from the region mask')
    country = region.values == 1
    regime = classify(q, lat, lon, country)['regime_cleaned'].reshape(country.shape)
    total = sum(q[MONTH_EDGES[mo - 1]:MONTH_EDGES[mo]].sum(axis=0) for mo in season_months(cfg))
    annual = q.sum(axis=0)
    share = np.divide(total, annual, out=np.zeros_like(total), where=annual > 10)
    keep = np.isin(regime, rule['regimes']) & (total >= rule['min_mm']) & country
    if rule['min_share'] is not None:
        keep &= share >= rule['min_share']
    domain = remove_small(keep, 3)
    w = np.cos(np.deg2rad(lat))[:, None] * np.ones(len(lon))
    pct = float(100 * w[domain].sum() / w[country].sum())
    regs = ' + '.join(f'R{g}' for g in rule['regimes'])
    floor = f'{name} climatological CHIRPS rainfall >={rule["min_mm"]:g} mm' + (
        f' and >={rule["min_share"]:.0%} of annual rainfall' if rule['min_share'] else '')
    out = xr.Dataset({'season_domain': (('lat', 'lon'), domain.astype('int8')),
                      'regime': (('lat', 'lon'), regime.astype('int8')),
                      'season_climatology_mm': (('lat', 'lon'), total),
                      'annual_climatology_mm': (('lat', 'lon'), annual),
                      'season_share_of_annual': (('lat', 'lon'), share)}, coords=dict(lat=region.lat, lon=region.lon))
    out.regime.attrs['codes'] = json.dumps(LABELS)
    out.attrs.update(
        season=name, initialization_month=cfg['initialization_month'], method='regime', regime_method=METHOD,
        view_label=rule['label'], reference_years=f'{years[0]}-{years[-1]}', domain_cells=int(domain.sum()),
        domain_country_area_percent=pct, created_utc=datetime.now(timezone.utc).isoformat(),
        domain_definition=(f'Fixed {years[0]}-{years[-1]} descriptive domain ({rule["local"]}): rainfall regime {regs} '
                           f'(GitHub-refined classification of the CHIRPS daily climatology) with {floor}; patches '
                           f'smaller than 3 cells removed. Scientific masking walkthrough logic; no onset gate. The same '
                           f'domain is used for the season and each of its months.'))
    tag = f"init{cfg['initialization_month']:02d}_{name}"
    path = source_path(output) if output else ROOT / f'data/masks/{tag}_regime_domain.nc'
    save_netcdf(out, path)
    print(f'{rule["label"]}: {int(domain.sum())} cells, {pct:.1f}% of Ethiopia -> {path}')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--config', required=True)
    p.add_argument('--region-mask', default='data/masks/ethiopia_common.nc')
    p.add_argument('--output', help='Default: data/masks/init<MM>_<SEASON>_{rainfall,regime}_domain.nc')
    p.add_argument('--method', choices=['threshold', 'regime'], default='threshold',
                   help='threshold: >=120 mm and >=20%% of annual in any regime; regime: walkthrough regime rules')
    a = p.parse_args()
    cfg = load_config(a.config)
    if a.method == 'regime':
        return regime_domain(cfg, a.region_mask, a.output)
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
