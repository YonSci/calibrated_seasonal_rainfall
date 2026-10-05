"""Build a binary cell-centre region mask from polygons on an existing grid.
Requires pyshp, shapely and pyproj ONLY when rebuilding, not to use a saved mask.
"""
import argparse
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import xarray as xr
import shapefile
from shapely.geometry import shape,Point,box
from shapely.ops import unary_union,transform
from shapely.prepared import prep
from pyproj import CRS,Transformer,Geod
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from common import source_path,save_netcdf,save_json


def edges(a):
    a=np.asarray(a,float);d=np.diff(a)
    if len(a)<2 or not np.isfinite(a).all() or not (d>0).all() or not np.allclose(d,d[0]):
        raise ValueError('Grid must have regular ascending one-dimensional coordinates.')
    return np.r_[a[0]-d[0]/2,(a[:-1]+a[1:])/2,a[-1]+d[-1]/2]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--shapefile',required=True)
    p.add_argument('--grid',default='data/processed/init05_JJAS/ecmwf_1993_common.nc')
    p.add_argument('--output',default='data/masks/ethiopia_common.nc')
    p.add_argument('--report',default='outputs/inspection/ethiopia_mask_report.json')
    p.add_argument('--preview',default='outputs/inspection/ethiopia_mask_preview.png')
    args=p.parse_args();src=source_path(args.shapefile);grid=source_path(args.grid)
    for suffix in ('.shp','.shx','.dbf','.prj'):
        if not src.with_suffix(suffix).is_file():raise FileNotFoundError(src.with_suffix(suffix))
    crs=CRS.from_wkt(src.with_suffix('.prj').read_text())
    cpg=src.with_suffix('.cpg')
    encoding=cpg.read_text().strip() if cpg.exists() else 'utf-8'
    if encoding in ('65001','UTF8'):encoding='utf-8'
    geometries=[];records=[]
    with shapefile.Reader(str(src),encoding=encoding) as reader:
        for record in reader.iterShapeRecords():
            g=shape(record.shape.__geo_interface__)
            if g.is_empty or not g.is_valid or g.geom_type not in ('Polygon','MultiPolygon'):
                raise ValueError('Each feature must be a valid nonempty polygon; no automatic geometry repair.')
            geometries.append(g);records.append(record.record.as_dict())
    if not geometries:raise ValueError('Shapefile has no features.')
    g=unary_union(geometries)
    if not crs.equals(CRS.from_epsg(4326),ignore_axis_order=True):
        tr=Transformer.from_crs(crs,'EPSG:4326',always_xy=True)
        g=transform(tr.transform,g)
    if not g.is_valid or g.is_empty:raise ValueError('Invalid geometry after transformation.')
    with xr.open_dataset(grid) as d:
        lat=d.lat.values.copy();lon=d.lon.values.copy()
    la,lo=edges(lat),edges(lon);xx,yy=np.meshgrid(lon,lat)
    prepared=prep(g)
    mask=np.array([prepared.covers(Point(float(x),float(y))) for x,y in zip(xx.ravel(),yy.ravel())],dtype='int8').reshape(xx.shape)
    if not mask.any():raise ValueError('No cell centres lie inside boundary.')
    hashes={s:hashlib.sha256(src.with_suffix(s).read_bytes()).hexdigest() for s in ('.shp','.shx','.dbf','.prj','.cpg') if src.with_suffix(s).exists()}
    attrs=dict(source='User-supplied '+src.name,region='union of supplied polygon features',
        source_crs_wkt=crs.to_wkt(),output_crs='EPSG:4326',
        mask_rule='1 if polygon covers grid-cell centre (boundary included); otherwise 0',
        purpose='Geographic evaluation mask; not an independently derived land-ocean mask',
        source_hashes_json=json.dumps(hashes),created_utc=datetime.now(timezone.utc).isoformat())
    d=xr.Dataset({'region_mask':(('lat','lon'),mask)},coords={'lat':lat,'lon':lon},attrs=attrs)
    d.region_mask.attrs.update(long_name='Region membership by cell centre',flag_values=np.array([0,1],dtype='int8'),flag_meanings='outside inside')
    d.lat.attrs['units']='degrees_north';d.lon.attrs['units']='degrees_east'
    save_netcdf(d,source_path(args.output))
    outside=g.difference(box(lo[0],la[0],lo[-1],la[-1]))
    geod=Geod(ellps='WGS84')
    def area(geom):
        if geom.is_empty:return 0.
        if geom.geom_type in ('MultiPolygon','GeometryCollection'):return sum(area(x) for x in geom.geoms)
        return abs(geod.geometry_area_perimeter(geom)[0])/1e6 if geom.geom_type=='Polygon' else 0.
    report=dict(features=len(geometries),records=records,geometry_valid=g.is_valid,boundary_bounds_lonlat=list(g.bounds),
        grid_bounds_lonlat=[float(lo[0]),float(la[0]),float(lo[-1]),float(la[-1])],
        shape=list(mask.shape),inside_cells=int(mask.sum()),outside_cells=int((mask==0).sum()),
        boundary_area_outside_grid_km2=area(outside),source_hashes=hashes,mask_rule=attrs['mask_rule'],
        note='Binary centre selection, not fractional area weighting. Boundary slivers outside the available grid are not extrapolated.')
    save_json(source_path(args.report),report)
    fig,ax=plt.subplots(figsize=(9,7),constrained_layout=True)
    from matplotlib.colors import ListedColormap
    ax.pcolormesh(lo,la,mask,cmap=ListedColormap(['#f3f4f6','#b6d9b5']),vmin=0,vmax=1,shading='flat')
    polygons=[g] if g.geom_type=='Polygon' else list(g.geoms)
    for polygon in polygons:
        x,y=polygon.exterior.xy;ax.plot(x,y,color='#222222',lw=1)
        for ring in polygon.interiors:
            x,y=ring.xy;ax.plot(x,y,color='#222222',lw=.6)
    ax.scatter(xx[mask==1],yy[mask==1],s=2,color='#237338',alpha=.4)
    ax.set(xlabel='Longitude',ylabel='Latitude',title=f'Ethiopia evaluation mask: {mask.sum()} selected cell centres\n0.25-degree grid; supplied boundary in black')
    ax.set_aspect(1/np.cos(np.deg2rad(np.mean(lat))))
    preview=source_path(args.preview);preview.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(preview,dpi=160);plt.close(fig)
    print(json.dumps(report,default=str,indent=2))


if __name__=='__main__':main()
