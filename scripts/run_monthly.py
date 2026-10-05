"""Separate June/July/August/September totals and fits from May-initialized data."""
import argparse
import calendar
import copy
import json
import subprocess
import sys
import numpy as np
import xarray as xr
from common import ROOT, load_config, save_json
from cycle import CYCLE

MONTHS={6:'Jun',7:'Jul',8:'Aug',9:'Sep'}


def monthly_config(cfg, month):
    if cfg['initialization_month']!=5 or cfg['season']!={'name':'JJAS','start':'06-01','end':'09-30'}:
        raise ValueError('This wrapper requires the established May-initialized JJAS project configuration.')
    out=copy.deepcopy(cfg)
    out['season']=dict(name=MONTHS[month],start=f'{month:02d}-01',end=f'{month:02d}-{calendar.monthrange(2000,month)[1]:02d}')
    return out


# Comparison tolerance only: this does not modify input rainfall or daily QC.
RECON_ATOL_MM = 0.001
RECON_RTOL = 1e-6


def compare_totals(total, reference):
    total=np.asarray(total,dtype=np.float64)
    reference=np.asarray(reference,dtype=np.float64)
    if total.shape!=reference.shape:raise ValueError('Monthly/seasonal shapes differ.')
    if np.isinf(total).any() or np.isinf(reference).any():raise ValueError('Infinite rainfall totals.')
    if not np.array_equal(np.isfinite(total),np.isfinite(reference)):
        raise ValueError('Monthly and seasonal completeness differ.')
    valid=np.isfinite(reference)
    if not valid.any():raise ValueError('No complete rainfall cells to compare.')
    delta=np.abs(total[valid]-reference[valid])
    allowed=RECON_ATOL_MM+RECON_RTOL*np.abs(reference[valid])
    return dict(maximum_absolute_difference_mm=float(delta.max()),
                absolute_tolerance_mm=RECON_ATOL_MM,relative_tolerance=RECON_RTOL,
                cells_exceeding_tolerance=int((delta>allowed).sum()),passed=bool((delta<=allowed).all()))


def reconstruction_check():
    report=[]
    # Model years through the cycle's forecast year; observations through its reference end.
    for year in range(CYCLE.ref_first,CYCLE.year+1):
        for kind in (['ecmwf','chirps'] if year<=CYCLE.ref_last else ['ecmwf']):
            seasonal=ROOT/f'data/processed/init05_JJAS/{kind}_{year}_common.nc'
            if not seasonal.exists():raise FileNotFoundError(f'Seasonal reference required: {seasonal}')
            with xr.open_dataset(seasonal) as d:
                source_dtype=str(d.precip_season.dtype)
                ref=d.precip_season.load().astype('float64')
            total=None
            for month in MONTHS:
                path=ROOT/f'data/processed/init05_{MONTHS[month]}/{kind}_{year}_common.nc'
                with xr.open_dataset(path) as d:a=d.precip_season.load().astype('float64')
                xr.align(ref,a,join='exact')
                a=a.transpose(*ref.dims)
                total=a if total is None else total+a
            result=compare_totals(total.values,ref.values)
            report.append(dict(kind=kind,year=year,reference_dtype=source_dtype,**result))
    path=ROOT/'outputs/qc/monthly_reconstruction.json'
    save_json(path,report)
    failed=[r for r in report if not r['passed']]
    if failed:
        first=failed[0]
        raise ValueError(f"{len(failed)} reconstruction checks failed; first {first['kind']} {first['year']}, "
                         f"max {first['maximum_absolute_difference_mm']} mm. Full report: {path}")
    worst=max(report,key=lambda r:r['maximum_absolute_difference_mm'])
    print('Passed: monthly totals reproduce JJAS within numerical comparison tolerance.',flush=True)
    print(f"Largest difference: {worst['maximum_absolute_difference_mm']:.9f} mm ({worst['kind']} {worst['year']}).",flush=True)
    print('Report:',path,flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',default='config/project.json')
    p.add_argument('--stage',choices=['configs','prepare','training','operational','check'],required=True)
    p.add_argument('--months',type=int,nargs='+',choices=list(MONTHS),default=list(MONTHS))
    p.add_argument('--region-mask',default='data/masks/ethiopia_common.nc');p.add_argument('--land-mask')
    p.add_argument('--regenerate',action='store_true',help='Rebuild training/operational outputs with backups; not raw monthly preparation.')
    args=p.parse_args();cfg=load_config(args.config)
    if args.regenerate and args.stage not in ['training','operational']:
        p.error('--regenerate applies only to training or operational stages.')
    if args.stage=='check':reconstruction_check();return
    for month in args.months:
        mc=monthly_config(cfg,month);config=ROOT/f'config/monthly_{MONTHS[month]}.json'
        if config.exists():
            if json.loads(config.read_text(encoding='utf-8-sig'))!=mc:raise ValueError(f'Existing monthly configuration differs: {config}')
        else:save_json(config,mc)
        print(f'Month: {MONTHS[month]}, config: {config}',flush=True)
        if args.stage=='prepare':
            if cfg['archive_years'][0]!=cfg['observation_years'][0] or cfg['archive_years'][1]<cfg['observation_years'][1]:
                raise ValueError('archive_years must start with observation_years and cover them.')
            for folder in ['data/interim','data/processed']:
                path=ROOT/f'{folder}/init05_{MONTHS[month]}'
                if path.exists():raise FileExistsError(f'{path} exists. Rename partial/old monthly folder before preparation.')
            subprocess.run([sys.executable,str(ROOT/'scripts/prepare_seasonal.py'),'--config',str(config),'--years',*[str(y) for y in range(cfg['archive_years'][0],cfg['archive_years'][1]+1)]],cwd=ROOT,check=True)
            subprocess.run([sys.executable,str(ROOT/'scripts/regrid_seasonal.py'),'--config',str(config)],cwd=ROOT,check=True)
        elif args.stage in ['training','operational']:
            command=[sys.executable,str(ROOT/'scripts/local_blend.py'),'--config',str(config),'--mode',args.stage,'--region-mask',args.region_mask]
            if args.land_mask:command+=['--land-mask',args.land_mask]
            if args.regenerate:command+=['--regenerate']
            subprocess.run(command,cwd=ROOT,check=True)
    if args.stage=='prepare' and set(args.months)==set(MONTHS):reconstruction_check()


if __name__=='__main__':main()
