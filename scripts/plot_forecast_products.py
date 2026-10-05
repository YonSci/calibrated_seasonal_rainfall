"""Plot final_shared_blend NetCDFs; no fitting, regridding or probability changes."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import xarray as xr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.cm import ScalarMappable
from matplotlib.patches import Patch
from output_runs import staged_output, check_destination

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ['JJAS', 'Jun', 'Jul', 'Aug', 'Sep']
CATEGORIES = ['below', 'near', 'above']
COLORS = [
    ['#fff3a1','#ffe100','#ffbd00','#ff9400','#ff7100','#ff4300','#ef0000'],
    ['#e3ffff','#b4ffff','#80ffff','#49f5f5','#1adede','#00bebe','#009595'],
    ['#c1ffc1','#83f76b','#50d425','#30ab00','#218500','#106000','#004000']]
PROB_BOUNDS = [100/3,40,50,60,70,80,90,100]
ANOM_COLORS = ['#d60000','#f52a00','#ff5400','#ff8500','#ffb800','#ffe000',
               '#ffffff','#b6f88b','#75df36','#42c300','#279c00','#147000','#004800']
ANOM_STEPS = np.array([-1,-.8,-.6,-.4,-.2,-.1,-.02,.02,.1,.2,.4,.6,.8,1.])


def resolve(path):
    path = Path(path)
    return path if path.is_absolute() else ROOT/path


def classify(p, valid, minimum=0.40, tie_tolerance=1e-8):
    """Codes: -2 ineligible/outside, -1 weak/tied, 0 below, 1 near, 2 above."""
    p = np.asarray(p, dtype=float)
    valid = np.asarray(valid, dtype=bool)
    if p.shape != valid.shape+(3,):
        raise ValueError('Expected probabilities (...,3) aligned with valid mask.')
    if not np.isfinite(p[valid]).all():
        raise ValueError('Missing probability in an eligible cell.')
    if np.any(p[valid] < 0) or np.any(p[valid] > 1) or not np.allclose(p[valid].sum(-1),1,rtol=0,atol=1e-6):
        raise ValueError('Eligible probabilities must be within [0,1] and sum to one.')
    safe = np.where(valid[...,None],p,0.)
    peak = safe.max(-1)
    tied = (np.abs(safe-peak[...,None]) <= tie_tolerance).sum(-1) > 1
    dominant = np.full(valid.shape,-2,dtype='int8')
    dominant[valid & ~tied] = safe.argmax(-1)[valid & ~tied]
    dominant[valid & tied] = -1
    display = dominant.copy()
    display[valid & (peak < minimum)] = -1
    peak = np.where(valid,peak,np.nan)
    return dominant, display, peak, tied & valid


def derive(d, minimum=.40, percent_floor=10.):
    if int(d.attrs.get('initialization_month',-1)) != 5 or int(d.attrs.get('target_year',-1)) != 2026:
        raise ValueError('Expected May-initialized 2026 final_shared_blend file.')
    for coordinate in ['lat','lon']:
        a=d[coordinate].values
        if a.ndim!=1 or len(a)<2 or not np.isfinite(a).all() or not np.all(np.diff(a)>0):
            raise ValueError('Expected ascending finite latitude/longitude coordinates.')
    if set(map(str,d.category.values)) != set(CATEGORIES) or d.sizes['category']!=3:
        raise ValueError('Expected below, near, above categories.')
    p=d.blend_probability.sel(category=CATEGORIES).transpose('lat','lon','category').values
    def field(name):return d[name].transpose('lat','lon').values
    for name in ['region_mask','amount_eligible','probability_eligible']:
        if not np.isin(field(name),[0,1]).all():raise ValueError(f'{name} must be binary.')
    region=field('region_mask')==1
    pv=region & (field('probability_eligible')==1)
    av=region & (field('amount_eligible')==1)
    if not pv.any() or not av.any():raise ValueError('No eligible cells within region.')
    mean=field('corrected_ensemble_mean').astype(float)
    clim=field('observed_training_mean').astype(float)
    for name in ['corrected_ensemble_mean','observed_training_mean','corrected_mean_anomaly']:
        if d[name].attrs.get('units')!='mm':raise ValueError(f'{name} must have units mm.')
    if not np.isfinite(mean[av]).all() or not np.isfinite(clim[av]).all() or (clim[av]<0).any():
        raise ValueError('Invalid rainfall means in amount-eligible cells.')
    anomaly=mean-clim
    if not np.allclose(anomaly[av],field('corrected_mean_anomaly')[av],atol=.001,rtol=1e-6):
        raise ValueError('Stored anomaly disagrees with forecast mean minus observed mean.')
    dominant,display,peak,ties=classify(p,pv,minimum)
    percentage=np.full(av.shape,np.nan)
    pct_valid=av & (clim>=percent_floor) & (clim>0)
    np.divide(100*anomaly,clim,out=percentage,where=pct_valid)
    out=xr.Dataset(coords={'lat':d.lat,'lon':d.lon,'category':CATEGORIES},attrs={
        'target_period':d.attrs.get('target_period',''), 'target_year':2026,
        'initialization_month':5,'reference_period':d.attrs.get('training_years','1993-2025'),
        'probability_source':'blend_probability; unchanged',
        'display_minimum_probability':minimum,'tie_tolerance':1e-8,
        'percent_anomaly_minimum_climatology_mm':percent_floor,
        'status':'Research reconstruction; not an EMI or ICPAC product',
        'mask_note':'Existing region and eligibility masks only; no new land-ocean or dry-season mask'})
    def add(name,values,attrs=None):
        out[name]=(('lat','lon'),values)
        out[name].attrs.update(attrs or {})
    codes={'flag_values':np.array([-2,-1,0,1,2],dtype='int8'),
           'flag_meanings':'ineligible_or_outside unresolved below near above'}
    add('dominant_tercile',dominant,{**codes,'note':'Unresolved means a tied maximum; no probability threshold applied.'})
    add('display_tercile',display,{**codes,'note':'Unresolved means tied maximum or maximum below display threshold.'})
    add('maximum_probability',peak,{'units':'1'})
    add('probability_tie',ties.astype('int8'))
    add('region_mask',region.astype('int8'))
    add('probability_valid',pv.astype('int8'))
    add('amount_valid',av.astype('int8'))
    add('rainfall_anomaly_mm',np.where(av,anomaly,np.nan),{'units':'mm'})
    add('rainfall_anomaly_percent',percentage,{'units':'%','formula':'100*(corrected_ensemble_mean-observed_training_mean)/observed_training_mean'})
    out['blend_probability']=(('lat','lon','category'),np.where(pv[...,None],p,np.nan))
    return out


def boundary_lines(path):
    if path is None:return None
    import shapefile
    from pyproj import CRS, Transformer
    path=resolve(path)
    prj=path.with_suffix('.prj')
    if not prj.exists():raise FileNotFoundError(f'Boundary needs its .prj CRS file: {prj}')
    transform=Transformer.from_crs(CRS.from_wkt(prj.read_text()),'EPSG:4326',always_xy=True)
    lines=[]
    with shapefile.Reader(str(path)) as reader:
        for shape in reader.iterShapes():
            pts=np.asarray(shape.points)
            starts=list(shape.parts)+[len(pts)]
            for a,b in zip(starts[:-1],starts[1:]):
                x,y=transform.transform(pts[a:b,0],pts[a:b,1]);lines.append((x,y))
    return lines


def decorate(ax,g,lines):
    if lines is not None:
        for x,y in lines:ax.plot(x,y,color='#222222',lw=.7,zorder=5)
    else:
        # This is a raster footprint outline, not a political boundary dataset.
        mask=g.region_mask.values
        ax.contour(g.lon,g.lat,mask,levels=[.5],colors='#333333',linewidths=.65)
    dx=float(np.diff(g.lon).mean());dy=float(np.diff(g.lat).mean())
    ax.set(xlim=(float(g.lon.min())-dx/2,float(g.lon.max())+dx/2),
           ylim=(float(g.lat.min())-dy/2,float(g.lat.max())+dy/2),
           xlabel='Longitude (degrees E)',ylabel='Latitude (degrees N)',aspect='equal')
    ax.set_axisbelow(True);ax.grid(alpha=.15)


def background(ax,g):
    ax.pcolormesh(g.lon,g.lat,np.where(g.region_mask,1,np.nan),
                  cmap=ListedColormap(['#bdbdbd']),vmin=0,vmax=1,shading='auto')


def save(fig,path):
    fig.savefig(path.with_suffix('.png'),dpi=220,facecolor='white')
    fig.savefig(path.with_suffix('.pdf'),facecolor='white')
    plt.close(fig)


def probability_map(g,target,path,lines):
    fig=plt.figure(figsize=(10.5,8.1))
    grid=fig.add_gridspec(3,2,width_ratios=[17,1],left=.08,right=.88,bottom=.19,top=.85,wspace=.12,hspace=.40)
    ax=fig.add_subplot(grid[:,0]);background(ax,g)
    display=g.display_tercile.values
    ax.pcolormesh(g.lon,g.lat,np.where(display==-1,1,np.nan),cmap=ListedColormap(['#ffffff']),vmin=0,vmax=1,shading='auto')
    norm=BoundaryNorm(PROB_BOUNDS,7)
    for row,k in enumerate([2,1,0]):
        cmap=ListedColormap(COLORS[k])
        ax.pcolormesh(g.lon,g.lat,np.where(display==k,100*g.maximum_probability,np.nan),cmap=cmap,norm=norm,shading='auto')
        cax=fig.add_subplot(grid[row,1]);cb=fig.colorbar(ScalarMappable(norm=norm,cmap=cmap),cax=cax,ticks=[40,50,60,70,80,90,100])
        cb.set_label(['Below normal (%)','Near normal (%)','Above normal (%)'][k])
    decorate(ax,g,lines)
    fig.suptitle(f'Ethiopia | {target} 2026 rainfall tercile outlook',fontsize=16,y=.965)
    fig.text(.5,.92,'May initialization | shared probability blend | CHIRPS reference 1993–2025',ha='center',fontsize=10)
    threshold=100*g.attrs['display_minimum_probability']
    fig.legend(handles=[Patch(facecolor='white',edgecolor='gray',label=f'Weak (<{threshold:g}%) or tied maximum'),
                        Patch(facecolor='#bdbdbd',label='Inside region, probability ineligible')],loc='lower center',bbox_to_anchor=(.47,.08),ncol=1,frameon=False)
    fig.text(.5,.035,'Color shows the leading category and its probability, not certainty or rainfall amount.\nResearch reconstruction; not an official EMI/ICPAC forecast. Outside region is blank.',ha='center',fontsize=9)
    save(fig,path)


def anomaly_map(g,target,path,lines,percent=False,limit=300.):
    name='rainfall_anomaly_percent' if percent else 'rainfall_anomaly_mm'
    unit='%' if percent else 'mm'
    fig,ax=plt.subplots(figsize=(9.2,7.6));fig.subplots_adjust(left=.09,right=.85,bottom=.19,top=.86)
    background(ax,g)
    cmap=ListedColormap(ANOM_COLORS);norm=BoundaryNorm(ANOM_STEPS*limit,13,clip=True)
    im=ax.pcolormesh(g.lon,g.lat,g[name],cmap=cmap,norm=norm,shading='auto')
    fig.colorbar(im,ax=ax,extend='both',shrink=.87,label=f'Rainfall anomaly ({unit})',ticks=np.array([-1,-.6,-.2,0,.2,.6,1])*limit)
    decorate(ax,g,lines)
    fig.suptitle(f'Ethiopia | {target} 2026 rainfall anomaly',fontsize=16,y=.96)
    fig.text(.5,.915,'May initialization | corrected ensemble mean minus CHIRPS 1993–2025 mean',ha='center',fontsize=10)
    masknote=(f'Percentages hidden where climatological total < {g.attrs["percent_anomaly_minimum_climatology_mm"]:g} mm.' if percent else 'Gray: amount-ineligible cells within the region.')
    fig.text(.5,.09,'Red/orange: drier mean; green: wetter mean. White is a small interval around zero.\n'+masknote+'\nAmount correction only; separate from probability blending. Not an EMI/ICPAC product.',ha='center',fontsize=9)
    save(fig,path)


def process(source,out,target,args,lines):
    with xr.open_dataset(source) as dataset:
        d=dataset.load()
    try:period=json.loads(d.attrs['target_period'])['name']
    except (KeyError,TypeError,ValueError):raise ValueError(f'Missing target_period metadata: {source}')
    if period!=target:raise ValueError(f'Target mismatch: {period} versus {target}')
    g=derive(d,args.min_probability,args.percent_min_climatology_mm)
    g.attrs['source_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
    g.attrs['source_file']=str(source)
    g.attrs['boundary_source']=str(resolve(args.boundary)) if args.boundary else 'Existing region-mask contour'
    limit=args.jjas_anomaly_limit_mm if target=='JJAS' else args.monthly_anomaly_limit_mm
    g.attrs['anomaly_color_limit_mm']=limit
    g.attrs['anomaly_color_limit_percent']=args.percent_anomaly_limit
    with staged_output(out,args.regenerate) as stage:
        g.to_netcdf(stage/'map_fields_2026.nc',engine='netcdf4',encoding={n:{'zlib':True,'complevel':4} for n in g.data_vars})
        probability_map(g,target,stage/'dominant_tercile_2026',lines)
        anomaly_map(g,target,stage/'rainfall_anomaly_mm_2026',lines,limit=limit)
        anomaly_map(g,target,stage/'rainfall_anomaly_percent_2026',lines,percent=True,limit=args.percent_anomaly_limit)
        valid=g.probability_valid.values.astype(bool)
        # Exact relative area weights for this regular latitude-longitude grid.
        area=np.broadcast_to(np.cos(np.deg2rad(g.lat.values))[:,None],valid.shape)
        weights=area[valid]/area[valid].sum()
        codes=g.display_tercile.values
        report={'target':target,'source':str(source),'source_sha256':g.attrs['source_sha256'],
                'valid_probability_cells':int(valid.sum()),'minimum_display_probability':args.min_probability,
                'area_mean_gridcell_probabilities':(weights@g.blend_probability.values[valid]).tolist(),
                'probability_note':'Area average of local probabilities, not probability of country-total rainfall.',
                'area_fraction_display_categories':{label:float(weights@(codes[valid]==code)) for code,label in [(-1,'weak_or_tied'),(0,'below'),(1,'near'),(2,'above')]},
                'probability_ineligible_region_cells':int(((g.region_mask==1)&(g.probability_valid==0)).sum()),
                'anomaly_color_limit_mm':limit,'anomaly_color_limit_percent':args.percent_anomaly_limit,
                'amount_cells_beyond_color_range':int((np.abs(g.rainfall_anomaly_mm)>limit).sum()),
                'percent_cells_beyond_color_range':int((np.abs(g.rainfall_anomaly_percent)>args.percent_anomaly_limit).sum()),
                'percent_anomaly_hidden_amount_cells':int(((g.amount_valid==1)&g.rainfall_anomaly_percent.isnull()).sum()),
                'boundary_source':g.attrs['boundary_source'],
                'mask_note':g.attrs['mask_note']}
        (stage/'plot_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(f'Saved {target}: {out}',flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-root',default='outputs/final_shared_blend')
    p.add_argument('--output-root',default='outputs/forecast_maps')
    p.add_argument('--targets',nargs='+',choices=TARGETS,default=TARGETS)
    p.add_argument('--boundary',help='Optional .shp outline with .shx/.dbf/.prj; display only.')
    p.add_argument('--min-probability',type=float,default=.40)
    p.add_argument('--percent-min-climatology-mm',type=float,default=10.)
    p.add_argument('--jjas-anomaly-limit-mm',type=float,default=300.)
    p.add_argument('--monthly-anomaly-limit-mm',type=float,default=100.)
    p.add_argument('--percent-anomaly-limit',type=float,default=100.)
    p.add_argument('--regenerate',action='store_true')
    args=p.parse_args()
    if not np.isfinite(args.min_probability) or not 1/3<=args.min_probability<=1: p.error('Minimum probability must be in [1/3,1].')
    for name in ['percent_min_climatology_mm','jjas_anomaly_limit_mm','monthly_anomaly_limit_mm','percent_anomaly_limit']:
        if not np.isfinite(getattr(args,name)) or getattr(args,name)<=0:p.error(f'{name} must be finite and positive.')
    jobs=[]
    for target in dict.fromkeys(args.targets):
        source=resolve(args.input_root)/f'init05_{target}/2026/forecast_2026.nc'
        out=resolve(args.output_root)/f'init05_{target}/2026'
        if not source.is_file():raise FileNotFoundError(f'Missing final forecast: {source}')
        if out.resolve()==source.parent.resolve() or source.resolve().is_relative_to(out.resolve()):
            raise ValueError('Plot output must be separate from input forecasts.')
        check_destination(out,args.regenerate);jobs.append((source,out,target))
    lines=boundary_lines(args.boundary)
    for source,out,target in jobs:process(source,out,target,args,lines)


if __name__=='__main__':main()
