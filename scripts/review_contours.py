"""Display-only bilinear interpolation and contour maps of existing final forecasts."""
import sys
from pathlib import Path
import numpy as np
from scipy.ndimage import map_coordinates, gaussian_filter, distance_transform_edt
from matplotlib.path import Path as MplPath
from matplotlib.patches import PathPatch
import review_map_base as base

_original_probability = base.probability_map
_original_anomaly = base.anomaly_map
_original_decorate = base.decorate
_original_process = base.process
FACTOR = 16
DISPLAY_SIGMA = 0.6


def display_grid(g):
    """Interpolate continuous fields, never numeric category codes. Retain native eligibility."""
    lat=g.lat.values;lon=g.lon.values
    yi=np.linspace(-.5,len(lat)-.5,len(lat)*FACTOR+1)
    xi=np.linspace(-.5,len(lon)-.5,len(lon)*FACTOR+1)
    yy,xx=np.meshgrid(yi,xi,indexing='ij');points=np.array([yy,xx])
    def nearest(a):return map_coordinates(np.asarray(a,float),points,order=0,mode='nearest')
    def rounded(valid):
        valid=np.asarray(valid,bool)
        if valid.all():return np.ones(xx.shape,bool)
        if not valid.any():return np.zeros(xx.shape,bool)
        signed=distance_transform_edt(valid)-distance_transform_edt(~valid)
        return map_coordinates(signed,points,order=1,mode='nearest')>0
    def interpolate(a,valid):
        a=np.asarray(a,float);valid=np.asarray(valid,bool)&np.isfinite(a)
        weight=valid.astype(float);value=np.where(valid,a,0.)
        if DISPLAY_SIGMA>0:
            weight=gaussian_filter(weight,DISPLAY_SIGMA,mode='nearest')
            value=gaussian_filter(value,DISPLAY_SIGMA,mode='nearest')
        denominator=map_coordinates(weight,points,order=1,mode='nearest')
        numerator=map_coordinates(value,points,order=1,mode='nearest')
        return np.divide(numerator,denominator,out=np.full(xx.shape,np.nan),where=denominator>1e-12)
    import xarray as xr
    h=xr.Dataset(coords={'lat':lat[0]+yi*(lat[1]-lat[0]),'lon':lon[0]+xi*(lon[1]-lon[0]),'category':base.CATEGORIES},attrs=dict(g.attrs))
    for key in ['region_mask','probability_valid','amount_valid']:
        h[key]=(('lat','lon'),rounded(g[key].values).astype('int8'))
    valid=g.probability_valid.values==1
    p=np.stack([interpolate(g.blend_probability.values[...,k],valid) for k in range(3)],-1)
    support=(h.probability_valid.values==1)&np.isfinite(p).all(-1)
    p=np.clip(p,0,1);s=p.sum(-1,keepdims=True)
    p=np.divide(p,s,out=np.full_like(p,np.nan),where=s>0)
    raw,shown,peak,ties=base.classify(p,support,g.attrs['display_minimum_probability'])
    for key,a in [('dominant_tercile',raw),('display_tercile',shown),('maximum_probability',peak)]:h[key]=(('lat','lon'),a)
    for key in ['rainfall_anomaly_mm','rainfall_anomaly_percent']:
        v=np.isfinite(g[key].values)&(g.amount_valid.values==1)
        a=interpolate(g[key].values,v)
        # Do not fill cells excluded by the original validity/low-climatology mask.
        a[~rounded(v)]=np.nan
        h[key]=(('lat','lon'),a)
    return h


class ContourAxes:
    """Use existing layout/legends, replacing only the raster drawing operation."""
    def __init__(self,ax):self.ax=ax;self.original=ax.pcolormesh
    def pcolormesh(self,x,y,z,**kwargs):
        if np.ndim(x)!=1 or np.ndim(y)!=1:
            return self.original(x,y,z,**kwargs)
        kwargs.pop('shading',None)
        norm=kwargs.get('norm')
        if norm is not None:
            levels=norm.boundaries
            kwargs['extend']='both'
            kwargs.pop('vmin',None);kwargs.pop('vmax',None)
        else:
            levels=[.5,1.5]
            kwargs.pop('vmin',None);kwargs.pop('vmax',None)
        return self.ax.contourf(x,y,np.ma.masked_invalid(z),levels=levels,corner_mask=False,**kwargs)
    def __getattr__(self,key):return getattr(self.ax,key)


def decorate(ax,g,lines):
    real=ax.ax if isinstance(ax,ContourAxes) else ax
    # Clip every filled contour to the original vector rings (including holes).
    if lines:
        paths=[]
        for x,y in lines:
            vertices=np.column_stack([x,y])
            if not np.array_equal(vertices[0],vertices[-1]):vertices=np.vstack([vertices,vertices[0]])
            codes=np.full(len(vertices),MplPath.LINETO,dtype=np.uint8)
            codes[0]=MplPath.MOVETO;codes[-1]=MplPath.CLOSEPOLY
            paths.append(MplPath(vertices,codes))
        patch=PathPatch(MplPath.make_compound_path(*paths),transform=real.transData)
        for collection in real.collections:collection.set_clip_path(patch)
    _original_decorate(real,g,lines)


def render(function,g,*args,**kwargs):
    """Temporarily wrap map axes; original source dataset is never modified."""
    h=display_grid(g)
    h.attrs["render_field"]=("rainfall_anomaly_percent" if kwargs.get("percent",False) else "rainfall_anomaly_mm") if function is _original_anomaly else "maximum_probability"
    original_add=base.plt.Figure.add_subplot
    def add(fig,*a,**kw):
        ax=original_add(fig,*a,**kw)
        # pyplot internals need a genuine Axes; intercept its pcolormesh only.
        proxy=ContourAxes(ax)
        ax.pcolormesh=proxy.pcolormesh
        return ax
    original_save=base.save
    def save(fig,path):
        fig.text(.5,.006,f'Display only: 16x contours, Gaussian sigma={DISPLAY_SIGMA:g} cells; rounded masks. Original data unchanged.',ha='center',fontsize=8)
        original_save(fig,path)
    base.plt.Figure.add_subplot=add;base.save=save
    try:return function(h,*args,**kwargs)
    finally:base.plt.Figure.add_subplot=original_add;base.save=original_save


def background(ax,g):
    ax.pcolormesh(g.lon,g.lat,np.where(g.region_mask,1,np.nan),cmap=base.ListedColormap(['#bdbdbd']),vmin=0,vmax=1,shading='auto')
    # White under valid contours prevents tiny contour seams looking like missing data.
    valid=np.isfinite(g[g.attrs['render_field']])
    ax.pcolormesh(g.lon,g.lat,np.where(valid,1,np.nan),cmap=base.ListedColormap(['#ffffff']),vmin=0,vmax=1,shading='auto')


def process(source,out,target,args,lines):
    _original_process(source,out,target,args,lines)
    import json
    report_path=out/'plot_report.json'
    report=json.loads(report_path.read_text())
    report['display_rendering']={'method':'normalized Gaussian display filter plus bilinear contours and signed-distance mask boundaries', 'gaussian_sigma_native_cells':DISPLAY_SIGMA, 'mask_boundary':'zero contour of bilinearly interpolated signed distance; native cell-center labels preserved',
      'factor':FACTOR,'native_grid_degrees':0.25,'statistics_grid':'original grid',
      'note':'Display interpolation is not downscaling. Category boundaries can shift visually; original probabilities and statistics are unchanged.'}
    report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')


def probability(g,*args,**kwargs):return render(_original_probability,g,*args,**kwargs)
def anomaly(g,*args,**kwargs):return render(_original_anomaly,g,*args,**kwargs)


def main():
    global DISPLAY_SIGMA
    # Consume display-specific option before passing existing options to the base CLI.
    import argparse
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--display-sigma',type=float,default=0.6)
    extra,rest=parser.parse_known_args()
    if not np.isfinite(extra.display_sigma) or not 0<=extra.display_sigma<=1:
        parser.error('--display-sigma must be between 0 and 1 native cells')
    DISPLAY_SIGMA=extra.display_sigma
    sys.argv=[sys.argv[0]]+rest
    # Reuse the validated input checks, original-grid reports and atomic backups.
    base.probability_map=probability;base.anomaly_map=anomaly;base.decorate=decorate;base.background=background;base.process=process
    if '--output-root' not in sys.argv:sys.argv.extend(['--output-root','outputs/forecast_maps_contours'])
    if '--boundary' not in sys.argv:
        path=base.ROOT/'data/boundaries/ethiopia/eth_admin0.shp'
        if not path.exists():raise FileNotFoundError(f'Extract bundled boundary files first: {path}')
        sys.argv.extend(['--boundary',str(path)])
    base.main()

if __name__=='__main__':main()
