"""Freeze all five cycle forecasts, verify historical CHIRPS overlap, prepare cycle-year totals (cycle.py)."""
import argparse,shutil,sys,urllib.request,urllib.error,uuid
import numpy as np
import xarray as xr
from verify2026_common import *
from verify2026_outputs import staged_output
from cycle import CYCLE, YEAR, REF, REF_DASH, REF_YEARS, MEMBERS, REGIME, REGIME_YEARS, OVERLAP_YEAR, EVALUATION_STUDY

def freeze(input_root,output):
    sources={t:input_root/f'{TAG}_{t}/{YEAR}/forecast_{YEAR}.nc' for t in TARGETS}
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
            dest=output/f'{TAG}_{t}/forecast_{YEAR}.nc'
            if sha(p)!=manifest['targets'][t]['sha256'] or sha(dest)!=manifest['targets'][t]['sha256']:raise ValueError('Frozen forecast differs: '+t+'. Keep the existing assessment archive; do not overwrite it.')
        print('Existing frozen forecasts verified.',flush=True)
    else:
        with staged_output(output,False) as stage:
            records={}
            for t,p in sources.items():
                out=stage/f'{TAG}_{t}';out.mkdir();shutil.copy2(p,out/f'forecast_{YEAR}.nc')
                digest=sha(out/f'forecast_{YEAR}.nc')
                if digest!=sha(p):raise ValueError('Source changed during freeze')
                records[t]={'source':str(p),'sha256':digest}
            write(stage/'freeze_manifest.json',{'created_utc':now(),'targets':records,'training_years':f'{REF}','evaluation_year':YEAR,'selected_probability_method':'shared climatology blend','note':f'Snapshot precedes this script downloading {YEAR} observations. This does not establish that nobody previously inspected {YEAR} outcomes.'})
        print('Saved frozen forecasts:',output,flush=True)
    return reference

def fetch(year,month,cache):
    name=f'chirps-v2.0.{year}.{month:02d}.days_p25.nc';dest=cache/name
    if dest.exists():
        receipt=dest.with_suffix('.download.json')
        if not receipt.is_file():raise ValueError('Cached file has no download provenance: '+str(dest)+'. Move it out of this cache and rerun to download from the official archive.')
        record=read(receipt)
        if record.get('derived_from'):
            if record.get('sha256')!=sha(dest) or record['derived_from'].get('url')!=ANNUAL_BASE+record['derived_from']['file']:
                raise ValueError('Cached month subset differs from its recorded derivation: '+str(dest))
            print('Using cached',name,'(month subset of the official annual p25 file)',flush=True);return dest
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
        if exc.code==404:
            if part.exists():part.unlink()
            return from_annual(year,month,cache)
        raise
    finally:
        if part.exists():part.unlink()
    return dest

def download_annual(year,cache,need):
    """Official annual p25 file (cached with a receipt); refreshed when it lacks the needed month."""
    name=f'chirps-v2.0.{year}.days_p25.nc';dest=cache/name;url=ANNUAL_BASE+name
    def covers(p):
        with xr.open_dataset(p) as d:
            days=set(np.asarray(d.time.values).astype('datetime64[D]'))
        return need<=days
    if dest.is_file():
        rec=read(dest.with_suffix('.download.json'))
        if rec.get('url')!=url or rec.get('sha256')!=sha(dest):raise ValueError('Cached annual file differs from its recorded official download: '+str(dest))
        if covers(dest):return dest,rec
    cache.mkdir(parents=True,exist_ok=True);part=cache/(name+'.'+uuid.uuid4().hex+'.part')
    print('Downloading',name,'(official annual p25 file)',flush=True)
    for attempt in range(1,4):   # a large file: retry a stalled or truncated transfer before giving up
        try:
            with urllib.request.urlopen(url,timeout=120) as response,part.open('wb') as out:
                shutil.copyfileobj(response,out,length=1024*1024)
                expected=response.headers.get('Content-Length');modified=response.headers.get('Last-Modified')
            if expected and part.stat().st_size!=int(expected):raise ValueError('Incomplete download')
            part.replace(dest);break
        except (OSError,ValueError) as exc:
            if attempt==3 or isinstance(exc,urllib.error.HTTPError):raise
            print(f'Download attempt {attempt} failed ({exc}); retrying',flush=True)
        finally:
            if part.exists():part.unlink()
    rec={'url':url,'retrieved_utc':now(),'sha256':sha(dest),'http_last_modified':modified,
         'product':'CHIRPS v2.0 official daily p25 archive, annual file'}
    write(dest.with_suffix('.download.json'),rec)
    if not covers(dest):raise ValueError(f'{name} does not yet contain every day of the requested month; no incomplete total will be created.')
    return dest,rec

def from_annual(year,month,cache):
    """Month subset of the official annual p25 file when the by_month file is not published.

    Accepted only after at least one other month of the same year is bit-identical in the annual file and
    in its published by_month file (same values, grid and days), i.e. the two are the same product.
    """
    import calendar as cal
    name=f'chirps-v2.0.{year}.{month:02d}.days_p25.nc';dest=cache/name
    days=np.arange(np.datetime64(f'{year}-{month:02d}-01'),np.datetime64(f'{year}-{month:02d}-01')+np.timedelta64(cal.monthrange(year,month)[1],'D'))
    print(f'{name} is not published; checking the official annual p25 file',flush=True)
    annual,arec=download_annual(year,cache,set(days))
    checks=[]
    for other in sorted((m for m in range(1,13) if m!=month),key=lambda m:abs(m-month)):
        ref=f'chirps-v2.0.{year}.{other:02d}.days_p25.nc'
        try:
            with urllib.request.urlopen(urllib.request.Request(BASE+ref,method='HEAD'),timeout=30):pass
        except urllib.error.HTTPError:
            continue
        p=fetch(year,other,cache)
        with xr.open_dataset(p) as a,xr.open_dataset(annual) as b:
            sub=b.precip.sel(time=a.time)
            # CHIRPS names its axes latitude/longitude; compare every axis whatever its name
            same=(a.precip.dims==sub.dims and all(np.array_equal(a[k].values,sub[k].values) for k in a.precip.dims)
                  and np.array_equal(a.precip.values,sub.values,equal_nan=True))
        checks.append({'month':f'{year}-{other:02d}','by_month_url':BASE+ref,'by_month_sha256':sha(p),'identical':bool(same)})
        if not same:raise ValueError(f'The annual p25 file differs from the published {ref}; it is not used as a substitute.')
        if len(checks)==2:break
    if not checks:raise ValueError(f'No published by_month file of {year} to check the annual file against; {name} not created.')
    with xr.open_dataset(annual) as b:
        sub=b.sel(time=slice(str(days[0]),str(days[-1]))).load()
    t=np.asarray(sub.time.values).astype('datetime64[D]')
    if not np.array_equal(t,days):raise ValueError(f'The annual file does not hold every day of {year}-{month:02d} exactly once')
    sub.attrs.update(history_subset=f'{year}-{month:02d} extracted unchanged from {annual.name} (official annual p25 file); the by_month file was not published')
    part=cache/(name+'.'+uuid.uuid4().hex+'.part.nc')
    try:
        sub.to_netcdf(part);part.replace(dest)
    finally:
        if part.exists():part.unlink()
    write(dest.with_suffix('.download.json'),{'url':arec['url'],'retrieved_utc':now(),'sha256':sha(dest),
        'derived_from':{'file':annual.name,'url':arec['url'],'sha256':arec['sha256'],'http_last_modified':arec.get('http_last_modified')},
        'month':f'{year}-{month:02d}','equivalence_check':checks,
        'product':'CHIRPS v2.0 official daily p25 archive: month subset of the annual p25 file (by_month file not published when checked); values unchanged'})
    print(f'Created {name} from the annual file (identical to the published by_month files for '+', '.join(c['month'] for c in checks)+')',flush=True)
    return dest

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config',default='config/project.json')
    ap.add_argument('--months',nargs='+',choices=list(MONTHS),default=list(MONTHS))
    ap.add_argument('--input-root',default='outputs/final_shared_blend')
    ap.add_argument('--root',default=f'outputs/verification_{YEAR}')
    ap.add_argument('--cache',default='data/raw/chirps/verification_p25')
    ap.add_argument('--regenerate',action='store_true')
    ap.add_argument('--freeze-only',action='store_true',help='Only create (or check) the SHA-256 freeze of the cycle forecasts; no observations')
    a=ap.parse_args()
    try:
        cfg=read(path(a.config));historical=path(cfg['chirps_file']);variable=cfg.get('chirps_variable','precip')
        if not historical.is_file():raise ValueError('Historical archive missing: '+str(historical))
        root=path(a.root);cache=path(a.cache)
        if historical.resolve().is_relative_to(root.resolve()):raise ValueError('Assessment output must not contain historical input')
        grid=freeze(path(a.input_root),root/'frozen_forecasts')
        if a.freeze_only:
            print('Freeze ready:',root/'frozen_forecasts'/'freeze_manifest.json');return
        names=[n for n in MONTHS if n in a.months]
        # Complete all overlap checks before downloading target-year observations.
        overlaps={}
        with xr.open_dataset(historical) as old:
            for name in names:
                month=MONTHS[name];p=fetch(OVERLAP_YEAR,month,cache)
                with xr.open_dataset(p) as new:b=daily_block(new,OVERLAP_YEAR,month,grid.lat,grid.lon)
                h=daily_block(old,OVERLAP_YEAR,month,grid.lat,grid.lon,variable)
                overlaps[name]={**overlap_check(b.values,h.values),'overlap_file_sha256':sha(p),'historical_source':str(historical),'historical_file_bytes':historical.stat().st_size,'historical_file_mtime_ns':historical.stat().st_mtime_ns}
                print('Overlap passed:',name,OVERLAP_YEAR,flush=True)
        for name in names:
            month=MONTHS[name];my=month_year(name);p=fetch(my,month,cache)
            with xr.open_dataset(p) as new:b=daily_block(new,my,month,grid.lat,grid.lon)
            z,count=total(b);expected=b.sizes['time']
            ds=xr.Dataset({'precip_season':(('lat','lon'),z),'valid_day_count':(('lat','lon'),count.astype('int16'))},coords={'lat':grid.lat,'lon':grid.lon},attrs={'year':YEAR,'target':name,'season_start':str(b.time.values[0])[:10],'season_end':str(b.time.values[-1])[:10],'expected_days':expected,'product':'CHIRPS Version 2.0 daily p25','source_url':read(p.with_suffix('.download.json')).get('url',BASE+p.name),'source_sha256':sha(p),'processing_utc':now(),'grid_method':'native coordinate match; no interpolation','forecast_freeze_sha256':sha(root/'frozen_forecasts/freeze_manifest.json')})
            ds.precip_season.attrs['units']='mm'
            with staged_output(root/'observations'/name,a.regenerate) as stage:
                ds.to_netcdf(stage/f'chirps_{YEAR}_common.nc',encoding={k:{'zlib':True,'complevel':4} for k in ds.data_vars})
                write(stage/'preparation_report.json',{'target':name,'overlap':overlaps[name],'expected_days':expected,'complete_cells':int((count==expected).sum()),'missing_cells':int((count!=expected).sum()),'source_sha256':sha(p),'forecast_freeze_sha256':ds.attrs['forecast_freeze_sha256'],'prepared_total_sha256':sha(stage/f'chirps_{YEAR}_common.nc')})
            print('Prepared',name,expected,'days',flush=True)
        # Build the season only when all its months are requested and complete in this run.
        if set(names)==set(MONTHS):
            datasets=[]
            for name in MONTHS:
                with xr.open_dataset(root/'observations'/name/f'chirps_{YEAR}_common.nc') as f:datasets.append(f.load())
            z=sum(d.precip_season.values.astype(float) for d in datasets);count=sum(d.valid_day_count.values.astype('int16') for d in datasets)
            ds=xr.Dataset({'precip_season':(('lat','lon'),z),'valid_day_count':(('lat','lon'),count)},coords={'lat':grid.lat,'lon':grid.lon},attrs={'year':YEAR,'target':SEASON,'season_start':window_iso(SEASON)[0],'season_end':window_iso(SEASON)[1],'expected_days':window_days(SEASON),'product':'CHIRPS Version 2.0 daily p25','processing_utc':now(),'forecast_freeze_sha256':sha(root/'frozen_forecasts/freeze_manifest.json')})
            ds.precip_season.attrs['units']='mm'
            with staged_output(root/'observations'/SEASON,a.regenerate) as stage:
                ds.to_netcdf(stage/f'chirps_{YEAR}_common.nc')
                write(stage/'preparation_report.json',{'target':SEASON,'month_sha256':{n:sha(root/'observations'/n/f'chirps_{YEAR}_common.nc') for n in MONTHS},'prepared_total_sha256':sha(stage/f'chirps_{YEAR}_common.nc'),'expected_days':window_days(SEASON),'reconstruction':f'Sum of {len(MONTHS)} complete calendar-month totals; missing cells remain NaN'})
            print(f'Prepared {SEASON}: {window_days(SEASON)} days; monthly reconstruction exact.',flush=True)
        print('Prepared targets:',', '.join(names)+(', '+SEASON if set(names)==set(MONTHS) else '')+'. Forecasts unchanged.')
    except (ValueError,KeyError,OSError,urllib.error.URLError) as exc:print('ERROR:',exc,file=sys.stderr);sys.exit(2)
if __name__=='__main__':main()
