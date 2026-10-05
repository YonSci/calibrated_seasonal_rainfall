# Ethiopia boundary mask and national verification

## Completed checks

Your supplied `eth_admin0` shapefile contains one valid polygon labelled Ethiopia (ISO3 ETH). Its coordinate system is geographic WGS84, so no reprojection was needed. Its attributes record version v04 and valid_on 2025-01-01; those are supplied metadata, not an independent assessment of boundary authority.

The supplied polygon was used without geometry repair. SHA-256 hashes of the shapefile components are in `outputs/inspection/ethiopia_mask_report.json` and the mask metadata.

The ready-made `data/masks/ethiopia_common.nc` contains:

- `region_mask(lat, lon)`, shape 48 x 60.
- 1 = cell centre inside or on the supplied polygon; 0 = outside.
- 1,484 selected cells and 1,396 outside cells.
- Latitude 3.125–14.875 and longitude 33.125–47.875, at 0.25-degree spacing.
- Exact coordinate equality checked against the uploaded CHIRPS grid and spatial verification grid.
- 1,478 selected cells have finite 1993 CHIRPS totals and finite corrected MSE in the supplied spatial-verification file. The six others remain excluded by observation eligibility; their missing-data cause is not inferred from geography.

This is binary cell-centre selection. Border cells are included or excluded by their centre, not fractionally weighted by their area inside Ethiopia. The grid-cell rectangles will consequently form steps along the national boundary. Existing verification uses whole-cell spherical area weights among selected valid cells.

A small western part of the polygon extends to longitude 32.9918, beyond the grid's western cell edge of 33.0. The out-of-grid polygon area is approximately 3.56 km² (WGS84 geodesic calculation). No values are extrapolated into that sliver. The original forecast domain remains unchanged.

## 1. Install the ready-made mask

Extract `ethiopia_mask_update.zip` into the existing project, merging `data`, `scripts`, `docs` and `outputs` folders. The critical file must be:

```text
D:\calibrated_seasonal_rainfall\data\masks\ethiopia_common.nc
```

No new dependencies are required to USE this mask. Regridding and calibration do not need to be rerun for Ethiopia-only evaluation. Original data and fitted models stay intact.

## 2. Run Ethiopia-only verification

```bat
cd /d D:\calibrated_seasonal_rainfall
.venv\Scripts\activate
python scripts\verify_calibration.py --config config\project.json --region-mask data\masks\ethiopia_common.nc --region-name Ethiopia
```

This uses the already installed Stage-4 verification script. It restricts evaluation to Ethiopia while retaining training-observation and category eligibility. It computes the scores, year-bootstrap intervals, member-count sensitivity and regional plots on that selection.

Outputs:

```text
outputs\verification\init05_JJAS\Ethiopia\
```

The previous `full_domain` folder is preserved. The verification plots will show region-masked grid values; the existing plotting code does not add the shapefile outline. The included `ethiopia_mask_preview.png` separately shows the boundary overlay and selected cell centres.

## 3. Return these results

```text
outputs\verification\init05_JJAS\Ethiopia\verification_summary.json
outputs\verification\init05_JJAS\Ethiopia\member_count_sensitivity.json
outputs\verification\init05_JJAS\Ethiopia\roc_auc.json
outputs\verification\init05_JJAS\Ethiopia\training_compression_diagnostics.json
outputs\verification\init05_JJAS\Ethiopia\figures\spatial_diagnostics.png
outputs\verification\init05_JJAS\Ethiopia\figures\reliability_and_histograms.png
```

These support comparison with the full-domain baseline. Full regional verification must run on your computer because the complete member forecasts and observation series are not uploaded here.

## 4. Geographic mask versus land–ocean mask

This file is a national geographic mask. It does not independently distinguish land from lakes or other water bodies. It follows whatever holes the supplied polygon contains and adds no water exclusions.

Use it with `--region-mask` in verification. Do not pass it as `--land-mask` to the calibration script: that option expects a different variable (`land_mask`) and has a different meaning.

Applying the mask for verification does not change the domain on which the global Dirichlet mapping was fitted. A future Ethiopia-only calibration would require an explicit training-region option and refitting; it is not achieved by plotting/evaluating only Ethiopia. Preserve the current full-domain fit as a baseline.

## 5. Optional: rebuild the mask yourself

This is unnecessary if you use the supplied NetCDF. To rebuild for another grid or a revised boundary, keep the shapefile components together:

```text
data\boundaries\eth_admin0.shp
data\boundaries\eth_admin0.shx
data\boundaries\eth_admin0.dbf
data\boundaries\eth_admin0.prj
data\boundaries\eth_admin0.cpg
```

Install geometry libraries in the active virtual environment:

```bat
python -m pip install pyshp==2.3.1 shapely==2.0.6 pyproj==3.7.0
```

Build on the existing common grid:

```bat
python scripts\build_region_mask.py --shapefile data\boundaries\eth_admin0.shp --grid data\processed\init05_JJAS\ecmwf_1993_common.nc --output data\masks\ethiopia_common.nc
```

The script reads the CRS from `.prj`, unions all supplied polygon features, transforms to WGS84 if necessary, rejects invalid geometries, and tests every cell centre. It writes the binary mask, metadata report and boundary-overlay preview. It needs the existing `scripts/common.py`. It does not change input shapefiles or NetCDF files.

The delivered mask was built from the uploaded CHIRPS latitude/longitude coordinates, which are exactly the coordinates used by the common-grid forecasts. Rebuilding from `ecmwf_1993_common.nc` should produce the same selection.

## Validation performed

- All five shapefile components read successfully.
- Geometry was valid before processing.
- WGS84 CRS inspected and recognized.
- Saved mask reopened successfully and contains only 0/1.
- Coordinates exactly match both supplied CHIRPS and spatial-verification files.
- Preview visually checked against the supplied outline.
- GIS generation ran on Linux; the ready-made NetCDF requires only your existing xarray/NetCDF environment on Windows.
