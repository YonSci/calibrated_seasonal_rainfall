# Where to apply the land–ocean mask

## Correct position in this project

1. Prepare native-grid seasonal totals.
2. Regrid ECMWF to the CHIRPS coordinate grid and verify conservation.
3. Load an independent static land–ocean mask ON THAT COMMON GRID.
4. Within each training fit, combine the static mask with training-only observation eligibility.
5. Fit amount correction and probability calibration using eligible cells.
6. Apply the same fitted eligibility to target forecasts.
7. For Ethiopia-only presentation, apply a separate Ethiopia boundary mask.

The regridding stage is already complete and need not be repeated. Conservation was checked on the whole rectangular grid before removing any cells. The calibration script applies its optional land mask before fitting. The input common-grid files remain intact; excluded cells in corrected amounts/probabilities are NaN.

## Three distinct masks

| Mask | Meaning | How used |
|---|---|---|
| Static land–ocean mask | Independent geography: land vs water | Optional input; applied before fitting, unchanged across years/folds |
| Observation eligibility | Complete training-year CHIRPS observations | Rebuilt within every training fold; combined with static land if supplied |
| Ethiopia boundary mask | Inside vs outside Ethiopia | Separate geographic selection for final national maps or a deliberately defined analysis region |

A country mask is not a global land–ocean mask. An observation mask is not independent evidence of geography. The 223 missing CHIRPS cells must not simply be renamed ocean. They could reflect source coverage or other missing-data causes.

No explicit geographic mask has been provided in this conversation. The update therefore does NOT automatically create or claim to apply a physical land mask. It supports one via `--land-mask` and records whether it was applied.

## Required land-mask file

Suggested location:

```text
data\masks\land_mask_common.nc
```

Required contents:

```text
Variable: land_mask
Dimensions: lat, lon
Shape: 48, 60
Values: 1 = land; 0 = water
Missing values: none
Latitude: 3.125, 3.375, ..., 14.875 (ascending)
Longitude: 33.125, 33.375, ..., 47.875 (ascending)
```

Coordinates must exactly equal those in `ecmwf_1993_common.nc`. The script rejects mismatches, missing values and non-binary values rather than silently resampling a mask. Record its provider, version, resolution, water/lake treatment and coastal-cell decision in the NetCDF `source` attribute or accompanying documentation.

If starting from a fractional land-cover raster, a deliberate rule is needed for coastal cells (for example, land fraction >= 0.5). Use appropriate area aggregation to obtain target-cell land fraction before thresholding. If starting from land polygons, use a documented cell-centre or area-overlap rule. These methods differ near coasts. Do not use precipitation values to infer the physical mask. A supplied binary mask should not be smoothed with bilinear interpolation.

This update does not fetch a coastline dataset, choose a provider for you, or rasterize polygons. A suitable existing land-mask raster/NetCDF or land polygon dataset can be used to build that input in a separate, traceable step. Until then, the default observation-based eligibility is operational, with `land_mask.applied=false` clearly recorded.

## Commands

Without an explicit physical land mask:

```bat
python scripts\run_calibration.py --config config\project.json --mode development
```

With the mask:

```bat
python scripts\run_calibration.py --config config\project.json --mode development --land-mask data\masks\land_mask_common.nc
```

Then use the identical mask for final fitting:

```bat
python scripts\run_calibration.py --config config\project.json --mode final --land-mask data\masks\land_mask_common.nc
```

If adding/changing the mask after a previous calibration run, rerun calibration: it can change the cells and weights used to train the global Dirichlet map. Regridding does not need to be repeated.

## When to apply Ethiopia's boundary

For presentation-only clipping, apply the boundary to final products. If the intended statistical fitting domain is strictly Ethiopia, define that domain before fitting the pooled Dirichlet map; otherwise the map learns from all eligible cells in the rectangular domain, including neighbouring countries. This update defaults to the full eligible rectangular domain. Do not assume final map clipping retroactively changes the fitting domain.

A future extension may add a separately named geographic analysis-region mask. Keep that concept distinct from the land–ocean input described here.
