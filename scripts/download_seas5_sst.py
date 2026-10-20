"""SEAS5 sea-surface temperature forecasts for the statistical downscaling predictor (docs/53).

Monthly means from the Copernicus Climate Data Store (seasonal-monthly-single-levels, ECMWF system 51) over the tropical
Indian and Pacific Oceans, for one initialization month and a range of years. The years are downloaded in a few chunks
(the CDS queues each request), each reduced at once to the ensemble mean of the first 25 members per lead month (the
hindcast ensemble size; docs/52) and saved per year; the raw files are deleted. Failed chunks are retried
and the script resumes where it stopped.

  python scripts/download_seas5_sst.py --month 5 --years 1993 2026      (four requests: three hindcast chunks, the forecasts)
Output: data/raw/ecmwf_sst/init<MM>/sst_<YYYY>.nc  (lead_month 1-6 x lat x lon, kelvin; land is missing)
"""
import argparse
from pathlib import Path

import numpy as np
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
AREA = [20, 30, -20, 280]                 # north, west, south, east: 20S-20N, 30E-80W (Indian and Pacific Oceans)
MEMBERS = 25
LEADS = [str(i) for i in range(1, 7)]


CHUNKS = [(1993, 2000), (2001, 2008), (2009, 2016), (2017, 2026)]   # hindcasts (25 members) and forecasts (51) apart


def request(years, month):
    return {'originating_centre': 'ecmwf', 'system': '51', 'variable': ['sea_surface_temperature'],
            'product_type': ['monthly_mean'], 'year': [str(y) for y in years], 'month': [f'{month:02d}'],
            'leadtime_month': LEADS, 'data_format': 'netcdf', 'area': AREA}


def reduce(path):
    """{year: ensemble mean of the first 25 members per lead month} of a downloaded file (one or more years)."""
    out = {}
    with xr.open_dataset(path) as d:
        v = d['sst']
        member = next(k for k in v.dims if 'number' in k or 'member' in k)
        lead = next(k for k in v.dims if 'forecastMonth' in k or 'lead' in k or 'step' in k)
        time = next((k for k in v.dims if 'time' in k or 'reference' in k), None)
        v = v.isel({member: slice(0, MEMBERS)}).mean(member)
        for i in range(v.sizes[time] if time else 1):
            x = v.isel({time: i}) if time else v
            year = int(str(x[time].values)[:4]) if time else None
            drop = [k for k in x.dims if k not in (lead, 'latitude', 'longitude')]
            x = x.squeeze(drop, drop=True) if drop else x
            x = x.drop_vars([c for c in x.coords if c not in (lead, 'latitude', 'longitude')])
            x = x.rename({lead: 'lead_month', 'latitude': 'lat', 'longitude': 'lon'}).astype('float32')
            x['lead_month'] = np.arange(1, x.sizes['lead_month'] + 1)
            out[year] = x.load()
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--month', type=int, required=True)
    p.add_argument('--years', type=int, nargs=2, required=True)
    a = p.parse_args()
    import cdsapi
    client = cdsapi.Client(quiet=True)
    out = ROOT / f'data/raw/ecmwf_sst/init{a.month:02d}'
    out.mkdir(parents=True, exist_ok=True)
    wanted = range(a.years[0], a.years[1] + 1)
    for lo, hi in CHUNKS:
        years = [y for y in wanted if lo <= y <= hi and not (out / f'sst_{y}.nc').is_file()]
        if not years:
            continue
        tmp = out.parent / '_download'                      # inside the project: the system temp folder can be cleaned mid-download
        tmp.mkdir(exist_ok=True)
        raw = tmp / f'init{a.month:02d}_{years[0]}_{years[-1]}.nc'
        for attempt in range(1, 4):
            try:
                client.retrieve('seasonal-monthly-single-levels', request(years, a.month), str(raw))
                break
            except Exception as exc:                        # network errors: retry the chunk (the CDS caches the result)
                print(f'init {a.month:02d} {years[0]}-{years[-1]}: attempt {attempt} failed: {exc!r}', flush=True)
                if attempt == 3:
                    raise
        try:
            fields = reduce(raw)
        finally:
            raw.unlink(missing_ok=True)
        if len(years) == 1 and None in fields:
            fields = {years[0]: fields[None]}
        for y in years:
            if y not in fields:
                raise RuntimeError(f'{y} missing from the download for init {a.month:02d}')
            fields[y].to_dataset(name='sst').to_netcdf(out / f'sst_{y}.nc')
        print(a.month, years[0], '-', years[-1], dict(fields[years[0]].sizes), flush=True)


if __name__ == '__main__':
    main()
