"""The observation dataset a project config uses: CHIRPS v2.0 (daily p25) or CHIRPS v3.0 (monthly, 0.05 deg).

A project config with "chirps_temporal": "monthly" uses CHIRPS v3.0 (data/raw/chirps/et/et_chirps3_monthly_r25.nc,
built by prepare_chirps_v3.py); otherwise CHIRPS v2.0 (the daily p25 archive). Every script that names, downloads
or checks observations takes these facts from here, so the label, product, listing and file names stay consistent.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

V2 = dict(version='2.0', label='CHIRPS v2.0', product='CHIRPS Version 2.0 daily p25', temporal='daily',
          listing='https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/netcdf/p25/by_month/',
          month_file='chirps-v2.0.{year}.{month:02d}.days_p25.nc', listing_pattern=r'chirps-v2\.0\.(\d{4})\.(\d{2})\.days_p25\.nc',
          description='0.25° daily rainfall (official p25 product)',
          citation='Funk et al. (2015), The climate hazards infrared precipitation with stations, Scientific Data 2, 150066')
V3 = dict(version='3.0', label='CHIRPS v3.0', product='CHIRPS Version 3.0 monthly', temporal='monthly',
          listing='https://data.chc.ucsb.edu/products/CHIRPS/v3.0/monthly/africa/tifs/',
          month_file='chirps-v3.0.{year}.{month:02d}.tif', listing_pattern=r'chirps-v3\.0\.(\d{4})\.(\d{2})\.tif',
          description='monthly rainfall, official 0.05° Africa product averaged onto the 0.25° grid (5 × 5 cells)',
          citation='Funk et al. (2026), The Climate Hazards Center Infrared Precipitation with Stations, Version 3, '
                   'Scientific Data 13, 718, doi:10.1038/s41597-026-07096-4')
PRODUCTS = {V2['product']: V2, V3['product']: V3}


def for_project(cfg):
    """V2 or V3 for a project configuration (dict)."""
    return V3 if cfg.get('chirps_temporal') == 'monthly' else V2


def for_project_file(path):
    p = Path(path)
    p = p if p.is_absolute() else ROOT / p
    return for_project(json.loads(p.read_text(encoding='utf-8-sig')))


def month_url(src, year, month):
    return src['listing'] + src['month_file'].format(year=year, month=month)


def published_months(src, text):
    """(year, month) pairs of the official monthly files in a listing page."""
    return {(int(y), int(m)) for y, m in re.findall(src['listing_pattern'], text)}
