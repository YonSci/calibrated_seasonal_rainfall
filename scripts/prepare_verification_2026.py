"""Freeze all five forecasts, verify historical CHIRPS overlap, prepare 2026 totals."""
import argparse,shutil,sys,urllib.request,urllib.error,uuid
import numpy as np
import xarray as xr
from verify2026_common import *
from verify2026_outputs import staged_output
TARGETS=['JJAS','Jun','Jul','Aug','Sep']

def freeze(input_root,output):
    sources={t:input_root/f'init05_{t}/2026/forecast_2026.nc' for t in TARGETS}
    missing=[str(p) for p in sources.values() if not p.is_file()]
    if missing:raise ValueError('Missing final forecasts:\n'+'\n'.join(missing))
    reference=None
    for t,p in sources.items():
        with xr.open_dataset(p) as d:
            check_forecast(d,t)
            if reference is None:reference=d[['region_mask']].load()
            else:
                same_grid(d,reference)
                if not np.array_equal(d.region_mask,reference.region_mask):raise ValueError('Forecast country masks differ')
    if output.exists():
        manifest=read(output/'freeze_manifest.json')
        for t,p in sources.items():
            dest=output/f'init05_{t}/forecast_2026.nc'
            if sha(p)!=manifest['targets'][t]['sha256'] or sha(dest)!=manifest['targets'][t]['sha256']:raise ValueError('Frozen forecast differs: '+t+'. Keep the existing assessment archive; do not overwrite it.')
        print('Existing frozen forecasts verified.',flush=True)
    else:
        with staged_output(output,False) as stage:
            records={}
            for t,p in sources.items():
                out=stage/f'init05_{t}';out.mkdir();shutil.copy2(p,out/'forecast_2026.nc')
                digest=sha(out/'forecast_2026.nc')
                if digest!=sha(p):raise ValueError('Source changed during freeze')
                records[t]={'source':str(p),'sha256':digest}
            write(stage/'freeze_manifest.json',{'created_utc':now(),'targets':records,'training_years':'1993-2025','evaluation_year':2026,'selected_probability_method':'shared climatology blend','note':'Snapshot precedes this script downloading 2026 observations. This does not establish that nobody previously inspected 2026 outcomes.'})
        print('Saved frozen forecasts:',output,flush=True)
    return reference

def fetch(year,month,cache):
    name=f'chirps-v2.0.{year}.{month:02d}.days_p25.nc';dest=cache/name
    if dest.exists():
        receipt=dest.with_suffix('.download.json')
        if not receipt.is_file():raise ValueError('Cached file has no download provenance: '+str(dest)+'. Move it out of this cache and rerun to download from the official archive.')
        record=read(receipt)
        if record.get('url')!=BASE+name or record.get('sha256')!=sha(dest):raise ValueError('Cached data differ from their recorded official download: '+str(dest))
        print('Using cached',name,flush=True);return dest
    cache.mkdir(parents=True,exist_ok=True);part=cache/(name+'.'+uuid.uuid4().hex+'.part')
    url=BASE+name;print('Downloading',name,flush=True)
    try:
        with urllib.request.urlopen(url,timeout=45) as response,part.open('wb') as out:
            shutil.copyfileobj(response,out,length=1024*1024)
            expected=response.headers.get('Content-Length')
        if expected and part.stat().st_size!=int(expected):raise ValueError('Incomplete download')
        with xr.open_dataset(part) as ds:
            if 'precip' not in ds:raise ValueError('Downloaded content is not a precipitation NetCDF')
        part.replace(dest)
        write(dest.with_suffix('.download.json'),{'url':url,'retrieved_utc':now(),'sha256':sha(dest),'product':'CHIRPS v2.0 official daily p25 archive; no preliminary-product substitution'})
    except urllib.error.HTTPError as exc:
        if exc.code==404:raise ValueError(f'{name} is not available at the official archive. Exclude this month for now; no incomplete total will be created.') from exc
        raise
    finally:
        if part.exists():part.unlink()
    return dest

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config',default='config/project.json')
    ap.add_argument('--months',nargs='+',choices=list(MONTHS),default=['Jun','Jul','Aug'])
    ap.add_argument('--input-root',default='outputs/final_shared_blend')
    ap.add_argument('--root',default='outputs/verification_2026')
    ap.add_argument('--cache',default='data/raw/chirps/verification_p25')
    ap.add_argument('--regenerate',action='store_true');a=ap.parse_args()
    try:
        cfg=read(path(a.config));historical=path(cfg['chirps_file']);variable=cfg.get('chirps_variable','precip')
        if not historical.is_file():raise ValueError('Historical archive missing: '+str(historical))
        root=path(a.root);cache=path(a.cache)
        if historical.resolve().is_relative_to(root.resolve()):raise ValueError('Assessment output must not contain historical input')
        grid=freeze(path(a.input_root),root/'frozen_forecasts')
        names=[n for n in MONTHS if n in a.months]
        # Complete all overlap checks before downloading target-year observations.
        overlaps={}
        with xr.open_dataset(historical) as old:
            for name in names:
                month=MONTHS[name];p=fetch(2025,month,cache)
                with xr.open_dataset(p) as new:b=daily_block(new,2025,month,grid.lat,grid.lon)
                h=daily_block(old,2025,month,grid.lat,grid.lon,variable)
                overlaps[name]={**overlap_check(b.values,h.values),'overlap_file_sha256':sha(p),'historical_source':str(historical),'historical_file_bytes':historical.stat().st_size,'historical_file_mtime_ns':historical.stat().st_mtime_ns}
                print('Overlap passed:',name,'2025',flush=True)
        for name in names:
            month=MONTHS[name];p=fetch(2026,month,cache)
            with xr.open_dataset(p) as new:b=daily_block(new,2026,month,grid.lat,grid.lon)
            z,count=total(b);expected=b.sizes['time']
            ds=xr.Dataset({'precip_season':(('lat','lon'),z),'valid_day_count':(('lat','lon'),count.astype('int16'))},coords={'lat':grid.lat,'lon':grid.lon},attrs={'year':2026,'target':name,'season_start':str(b.time.values[0])[:10],'season_end':str(b.time.values[-1])[:10],'expected_days':expected,'product':'CHIRPS Version 2.0 daily p25','source_url':BASE+p.name,'source_sha256':sha(p),'processing_utc':now(),'grid_method':'native coordinate match; no interpolation','forecast_freeze_sha256':sha(root/'frozen_forecasts/freeze_manifest.json')})
            ds.precip_season.attrs['units']='mm'
            with staged_output(root/'observations'/name,a.regenerate) as stage:
                ds.to_netcdf(stage/'chirps_2026_common.nc',encoding={k:{'zlib':True,'complevel':4} for k in ds.data_vars})
                write(stage/'preparation_report.json',{'target':name,'overlap':overlaps[name],'expected_days':expected,'complete_cells':int((count==expected).sum()),'missing_cells':int((count!=expected).sum()),'source_sha256':sha(p),'forecast_freeze_sha256':ds.attrs['forecast_freeze_sha256'],'prepared_total_sha256':sha(stage/'chirps_2026_common.nc')})
            print('Prepared',name,expected,'days',flush=True)
        # Build JJAS only when all four months are explicitly requested and complete in this run.
        if set(names)==set(MONTHS):
            datasets=[]
            for name in MONTHS:
                with xr.open_dataset(root/'observations'/name/'chirps_2026_common.nc') as f:datasets.append(f.load())
            z=sum(d.precip_season.values.astype(float) for d in datasets);count=sum(d.valid_day_count.values.astype('int16') for d in datasets)
            ds=xr.Dataset({'precip_season':(('lat','lon'),z),'valid_day_count':(('lat','lon'),count)},coords={'lat':grid.lat,'lon':grid.lon},attrs={'year':2026,'target':'JJAS','season_start':'2026-06-01','season_end':'2026-09-30','expected_days':122,'product':'CHIRPS Version 2.0 daily p25','processing_utc':now(),'forecast_freeze_sha256':sha(root/'frozen_forecasts/freeze_manifest.json')})
            ds.precip_season.attrs['units']='mm'
            with staged_output(root/'observations/JJAS',a.regenerate) as stage:
                ds.to_netcdf(stage/'chirps_2026_common.nc')
                write(stage/'preparation_report.json',{'target':'JJAS','month_sha256':{n:sha(root/'observations'/n/'chirps_2026_common.nc') for n in MONTHS},'prepared_total_sha256':sha(stage/'chirps_2026_common.nc'),'expected_days':122,'reconstruction':'Sum of four complete calendar-month totals; missing cells remain NaN'})
            print('Prepared JJAS: 122 days; monthly reconstruction exact.',flush=True)
        print('Prepared targets:',', '.join(names)+(', JJAS' if len(names)==4 else '')+'. Forecasts unchanged.')
    except (ValueError,KeyError,OSError,urllib.error.URLError) as exc:print('ERROR:',exc,file=sys.stderr);sys.exit(2)
if __name__=='__main__':main()
