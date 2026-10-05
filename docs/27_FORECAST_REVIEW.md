# Step 27 — Forecast products and focused August review

## Purpose and decision

Keep the existing shared probability blend for JJAS, June, July, August and September. The uploaded 20-experiment comparison does not justify replacing it across Ethiopia. August's GitHub-refined regularized blend is promising, but remains experimental: its mean RPS improvement is about 0.00283 in training cross-validation and 0.00112 in operational evaluation. The operational whole-year bootstrap interval includes zero. Some regimes worsen even when the national score improves. These years have already been inspected repeatedly, so this is exploratory evidence, not a new untouched test.

This update performs no fitting and changes no source forecast. Rainfall anomalies continue to use the existing corrected ensemble mean. Probability maps use the existing shared blend. This stage does not introduce or refit a Dirichlet calibrator.

## 1. Install

Extract the ZIP into `D:\calibrated_seasonal_rainfall`, merging `scripts`, `docs`, and `evidence` with the project folders. The new helper names are distinct from existing plotting scripts. `example_products` contains products generated from the uploaded JJAS forecast; it is optional reference material.

In Windows CMD in VS Code:

```bat
cd /d D:\calibrated_seasonal_rainfall
.venv\Scripts\activate
python -m pip install numpy scipy xarray netCDF4 matplotlib pyshp pyproj
```

## 2. Build the JJAS products first

Expected sources:

- `outputs\final_shared_blend\init05_JJAS\2026\forecast_2026.nc`
- `outputs\regime_reconciliation\descriptive_1993_2025\regime_comparison_and_masks.nc`
- `data\boundaries\ethiopia\eth_admin0.shp` and matching `.shx`, `.dbf`, `.prj`
- `evidence\all_regime_experiments.json` (the supplied 20-experiment results)

```bat
python scripts\build_forecast_review.py --targets JJAS --regenerate
```

If your mask is elsewhere, supply `--mask "full\path\regime_comparison_and_masks.nc"`. Boundary and evidence paths can similarly be overridden with `--boundary` and `--evidence`.

For each target, the script opens the existing forecast, validates its target and probability fields, derives anomalies and dominant categories on the native grid, then renders smooth display contours. Original forecast values are unchanged. Native fields are saved separately from rendered contours.

JJAS generates two clearly labeled views:

| View | Purpose | Mask |
|---|---|---|
| `all_ethiopia` | Preserve nationwide coverage | Existing country mask and variable-specific eligibility |
| `jjas_r12_rainfall_domain` | Focus interpretation on the established JJAS rainfall domain | Cleaned GitHub-refined R1/R2, JJAS climatology ≥120 mm and annual rainfall fraction ≥0.20 |

The second view uses the corrected-calendar 1993–2025 descriptive mask. It is **not an onset mask**, not a new probability calibration, and not an official EMI classification. Country clipping is distinct from a physical land–ocean/lake mask. No physical mask is invented here.

The domain is applied to native-grid fields before display smoothing, then contours are clipped to the country boundary. Gaussian smoothing (sigma 0.6 native cells) and 16-fold interpolation affect appearance only. They add no meteorological resolution; boundaries can move visually. Do not use the displayed contours as analytical data.

Outputs under `outputs\forecast_review\init05_JJAS\2026\VIEW`:

- `dominant_tercile_2026.png` and `.pdf`: leading category probability; white means tied or maximum below 40%.
- `rainfall_anomaly_mm_2026.png` and `.pdf`: corrected mean minus CHIRPS reference mean.
- `rainfall_anomaly_percent_2026.png` and `.pdf`: 100 × anomaly/reference, hidden below 10 mm reference rainfall.
- `map_fields_2026.nc`: native analytical values, domain, country mask and eligibility.
- `product_metadata.json`: source hash, methods, reference years, domain definition, original-grid statistics and historical verification evidence.

Verification in the metadata is explicitly **all-country historical verification**. It is not a verification of the 2026 forecast, and is not recomputed for the R1+R2 view. The mean of grid-cell probabilities is not the probability of country-total rainfall.

## 3. Build all five targets

Once the five final forecast files exist:

```bat
python scripts\build_forecast_review.py --targets JJAS Jun Jul Aug Sep --regenerate
```

The monthly views retain nationwide coverage. Do not reuse the JJAS mask as a universal monthly rainfall mask. Separately corrected monthly mean totals need not reconstruct the separately corrected JJAS forecast.

## 4. Diagnose August before any experimental final refit

Required actual data, for both `training` and `operational`:

```text
outputs/regime_calibration_github/init05_Aug/MODE/regime_probabilities_and_weights.nc
```

```bat
python scripts\diagnose_august.py --regenerate
```

The script:

1. Checks the GitHub-refined classification method, expected years and probability validity.
2. Uses the saved fold-specific common support. It never applies the full-period 2026 descriptive mask to historical scores.
3. Calculates shared and regularized regime RPS, Brier losses and category probabilities on identical cells.
4. Checks mean RPS against the supplied August experiment summary (absolute tolerance 0.000002). A mismatch stops the run so another target or file version cannot silently be analyzed.
5. Gives every year equal weight; within each year, weights cells by their relative area. Reliability bins use those weights, with 1.0 included in the final bin.
6. Produces category reliability curves and weighted probability histograms; exports bin counts, contributing years and weight fractions.
7. Produces native-grid RPS differences, valid-year counts, and category Brier/probability differences. Negative score differences favor the regime candidate. A probability difference alone does not indicate better skill.
8. Bootstraps whole years for the national mean RPS difference, using a fixed random seed. Spatial cells are not treated as independent samples. Curves have no misleading independent-cell confidence intervals.

Outputs: `outputs\august_review\training` and `outputs\august_review\operational`, each with three PNG/PDF figures, `diagnostic_fields.nc`, and `diagnostic_report.json`.

## 5. Interpret and return

Review reliability against the diagonal together with histogram coverage: sparse bins provide weak evidence. Inspect near-normal behavior separately from below/above categories. Check whether improvements occupy a coherent domain and whether enough years support them. The existing training result and operational interval should be considered together, with the repeated-experiment limitation.

Share both `diagnostic_report.json` files and the operational `reliability_and_histograms.png`, `category_differences.png`, and `spatial_rps_and_support.png`. The next decision is whether to keep August experimental or prepare a separately labeled experimental refit. This update does not automatically select regional winners, change defaults, or issue a new operational forecast.

## Regeneration and validation

`--regenerate` builds in a temporary sibling directory and preserves the old output in a timestamped backup when the new run succeeds. Without it, an existing destination is protected. Each target/view/mode commits independently; if a later job fails, earlier successful jobs remain usable.

The package was tested with the actual uploaded JJAS forecast and descriptive mask. A controlled test checks diagnostic score direction, empty support, weighting, bin endpoints (0 and 1) and invalid probability rejection. Actual August diagnostic figures must be generated locally because the yearly August probability NetCDFs were not supplied. Monthly final maps likewise require their local forecast files.

Optional diagnostic check:

```bat
python tests\test_diagnostics.py
```
