# Step 23 — Smooth forecast maps and next steps

## What caused the boxes?

The final JJAS file is 48 × 60 at 0.25-degree spacing, with 51 members. The earlier plot used pcolormesh, showing each grid cell as a rectangle. Its boundary followed the raster mask. This is a display issue, not evidence of failed calibration. The original ECMWF grid was coarser still; regridding and display interpolation do not create additional forecast resolution.

## What changed

- Mask-aware bilinear interpolation onto an eight-times-denser display mesh.
- Filled contours instead of rectangular cells.
- Your supplied Ethiopia shapefile is bundled and used to clip and outline the maps.
- Probability fields are interpolated together and normalized; the leading category is then recalculated for display. Category codes themselves are never interpolated.
- Original excluded cells and the percentage-anomaly low-climatology safeguard remain excluded, using nearest-cell validity on the display mesh. Small gray areas can therefore remain rectangular intentionally.
- No Gaussian filtering, calibration refitting, or invented high-resolution information.
- Original-grid probabilities, anomalies and statistics are retained in map_fields_2026.nc and plot_report.json. Smooth color boundaries can differ slightly from the original cell boundaries. Use original-grid fields for extraction and verification.
- Linear interpolation is bounded by contributing values. At valid/invalid boundaries interpolation is normalized over available valid corners, then restricted to the nearest original valid cell; it does not fill excluded cells. At the outer half-cell edge the nearest boundary value is used.

## Install and run in Windows CMD

Extract this package into `D:\calibrated_seasonal_rainfall`. Merge scripts, data and docs. It includes compatible plotting helpers and the Ethiopia boundary under `data\boundaries\ethiopia`.

```bat
cd /d D:\calibrated_seasonal_rainfall
.venv\Scripts\activate
python scripts\plot_smooth_forecasts.py --targets JJAS --regenerate
```

For all five existing final products:

```bat
python scripts\plot_smooth_forecasts.py --regenerate
```

Dependencies: existing numpy, scipy, xarray, matplotlib, netCDF4, pyshp and pyproj. If the last two are missing:

```bat
python -m pip install pyshp pyproj
```

Inputs remain `outputs\final_shared_blend\init05_TARGET\2026\forecast_2026.nc`.
New output: `outputs\forecast_maps_smooth\init05_TARGET\2026\`.
PNG/PDF outputs, original-grid derived NetCDF and report are produced. Previous smooth outputs get timestamped backups with --regenerate. The original raster maps and forecast files remain available.

The supplied JJAS example images were generated from your uploaded NetCDF, not synthetic data. Reference period, 40% weak-signal cutoff, anomaly scales and all calibration choices are unchanged. Maps are labeled display-only interpolation.

## JJAS report interpretation

Across eligible original-grid Ethiopia cells, area fractions are:

| Display class | Area fraction |
|---|---:|
| Below normal with maximum probability at least 40% | 77.80% |
| Above normal with maximum probability at least 40% | 13.01% |
| Near normal with maximum probability at least 40% | 0.34% |
| Weak or tied maximum | 8.85% |

These are fractions of eligible area assigned a display category, not forecast probabilities. The average local below-normal probability is 50.48%, a different statistic. There are 1455 probability-eligible cells and 29 ineligible cells inside the region mask. Percent anomalies are hidden at 99 amount-eligible cells with very low reference rainfall; three cells exceed the ±100% plotting range. Saturated colors retain their full numeric values in NetCDF.

The region mask is not an explicit land–ocean mask. Vector clipping is a visual boundary treatment, not a new calibration mask.

## Next steps, in order

1. Generate smooth maps for Jun, Jul, Aug and Sep with the same command. Retain common monthly color scales to support comparison. Keep the weak-signal legend, especially for September.
2. Inspect the monthly NetCDFs and maps, including probability eligibility, very dry areas and the June–August amount-clipping pattern. Avoid changing the selected method solely to resemble an agency map.
3. Preserve the final model parameters and May-initialized predictions as a frozen version. Document training years, forecast initialization, reference climatology, member counts, masks and code version together.
4. Add observed 2026 CHIRPS rainfall when a complete, quality-controlled product is available. Aggregate exact JJAS/monthly periods and use the same grid and masks. Classify observations with the frozen 1993–2025 q1/q2 thresholds. Do not include 2026 observations in fitting this forecast.
5. Verify against those observations: category Brier scores/BSS, RPS/RPSS and log loss for calibrated probabilities; CRPS and mean-error diagnostics for the corrected ensemble. Use frozen training climatology as reference. Treat 2026 as a case study; robust reliability/ROC assessment still needs multiple independent years, rather than treating correlated grid cells as independent years.
6. Complete the agency comparison using matching valid periods and documented initialization/reference periods. Numerical agreement requires official grids or forecast-zone probabilities. Smooth graphics do not resolve reference-period or lead-time differences and do not establish skill.

This step changes visualization only. Amount-method improvements, physical land masking or a revised climatological reference require separate, cross-validated experiments.
