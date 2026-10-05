# Step 29 — Final shared-blend forecast delivery

## Purpose

Complete the May-initialized 2026 JJAS and June–September research forecast package using the final forecasts already produced. The selected probability method is the **shared climatology blend** for every target. The August regime blend remains experimental. This step performs no training, regridding, rainfall correction or recalibration; it verifies and packages existing results.

Products are **retrospective reconstructions**, generated after initialization, with no 2026 observation-based verification in the supplied archive. Package creation time is recorded separately from forecast initialization. Do not describe this package as a forecast issued in May 2026 or as an official EMI/ICPAC bulletin.

## 1. Install the update

Extract `forecast_delivery_update.zip` into `D:\calibrated_seasonal_rainfall`, merging the folders. Keep `scripts`, `docs` and `evidence` at the project root, not inside an additional nested directory. The update uses new `delivery_*` helper names and does not replace the working calibration or review scripts.

The `evidence` folder contains the complete uploaded 20-experiment comparison and the reviewed August diagnostics. The optional `example_delivery_JJAS` folder is the actual uploaded JJAS result packaged during validation, not the full five-target deliverable.

In Windows CMD:

```bat
cd /d D:\calibrated_seasonal_rainfall
.venv\Scripts\activate
```

Use the existing project environment. If a dependency is missing:

```bat
python -m pip install numpy scipy xarray netCDF4 matplotlib pyshp pyproj
```

## 2. Check inputs before any plotting

```bat
python scripts\finalize_forecast_delivery.py --check-only
```

The command checks all five targets by default and produces no delivery files. Required inputs:

| Input | Default location |
|---|---|
| Final forecast, one per target | `outputs\final_shared_blend\init05_TARGET\2026\forecast_2026.nc` |
| JJAS descriptive domain | `outputs\regime_reconciliation\descriptive_1993_2025\regime_comparison_and_masks.nc` |
| Country outline and CRS | `data\boundaries\ethiopia\eth_admin0.shp`, `.shx`, `.dbf`, `.prj` |
| Experiment evidence | `evidence\all_regime_experiments.json` |

A missing-file message lists required missing paths together, before plotting begins. It does not silently skip a target or replace the requested domain with another mask.

If your regime mask exists elsewhere:

```bat
python scripts\finalize_forecast_delivery.py --mask "D:\actual\folder\regime_comparison_and_masks.nc" --check-only
```

Use the same `--mask` argument in the build command. Other supported overrides are `--boundary`, `--evidence`, `--input-root`, and `--output`.

If the mask has never been generated, use the existing reconciliation script:

```bat
python scripts\compare_regime_definitions.py --climatology data\processed\regime_climatology\descriptive_1993_2025.nc --regenerate
```

This reconstructs a mask from the existing climatology; it does not refit calibration.

## 3. Build the complete package

```bat
python scripts\finalize_forecast_delivery.py --regenerate
```

The script repeats validation, renders the requested maps, copies original forecast NetCDFs unchanged, creates the documentation and offline viewer, and builds `bundle.zip`. It uses a temporary sibling directory and commits the whole delivery folder only after success. Existing delivery output is retained in a timestamped backup when `--regenerate` is supplied. Without that flag, an existing destination is protected.

Final location:

```text
outputs/forecast_delivery/init05_2026/
    index.html
    BULLETIN.md
    WORKFLOW.md
    forecast_summary.json
    historical_verification.json
    method_decision.json
    manifest.json
    completion_report.json
    bundle.zip
    forecasts/init05_TARGET/forecast_2026.nc
    maps/init05_TARGET/2026/all_ethiopia/...
    maps/init05_JJAS/2026/jjas_r12_rainfall_domain/...
    evidence/...
```

For all five targets, the package contains six map views: five national views and one additional JJAS rainfall-domain view. Each view has tercile, millimetre anomaly and percentage anomaly maps in PNG/PDF, native map fields, and metadata. This is 18 PNG figures and 18 PDF versions.

Open the offline viewer in CMD:

```bat
start "" "outputs\forecast_delivery\init05_2026\index.html"
```

No web server, external account, internet connection, deployment or public publication is required. HTML and all maps remain local. Keep the HTML together with its subfolders; share `bundle.zip` to preserve the links.

## 4. What the validation checks

- Expected May initialization, 2026 target year, exact target dates and 1993–2025 reference metadata.
- The selected shared-blend method is identified in the source.
- All targets have a common regular 0.25° grid and country mask.
- There are 51 unique forecast members. None is removed to imitate the 25-member reforecast years.
- Corrected member rainfall is finite and nonnegative where eligible; the stored mean matches the member mean.
- Stored tercile probabilities reproduce corrected-member category counts using the saved thresholds.
- Count smoothing reproduces `(count + 0.5)/(51 + 1.5)`.
- The final probabilities reproduce `(1 − lambda) × smoothed probability + lambda × climatology probability` and sum to one.
- Stored rainfall anomalies reproduce corrected mean minus observed reference mean.
- The descriptive JJAS mask has the expected method, years, grid and country support.
- Each requested target has the four expected method/mode experiment records, and GitHub baseline-reproduction checks passed.
- Source input hashes are unchanged during packaging, and forecast copies are byte-identical to the originals.

These are implementation and consistency checks. They do not constitute independent verification of 2026 forecast skill or rerun the historical experiments.

## 5. Scientific method statement

### Rainfall amount correction

The existing method is **mean–variance bias correction**, a location-and-scale adjustment applied to each ensemble member at each grid cell:

`corrected = max(0, observed_mean + scale × (model − model_mean))`.

The installed final-fit implementation gives every historical year equal weight when estimating model moments, despite differing ensemble sizes. Its scale is the observed/model standard-deviation ratio capped to [0.5, 2.0]; model standard deviation below 1 mm uses mean-only correction. Clipping negative corrected rainfall to zero can prevent exact moment matching. These coefficients were already fitted; delivery does not alter them.

### Probability calibration

The selected product uses **additive count smoothing followed by linear pooling with climatology**. A shared climatology weight is estimated from out-of-fold historical predictions, separately for each target. The final refit uses 1993–2025. One weight is shared across the fitting domain for that target; it is not one weight shared across all five targets.

The initial project investigated regularized Dirichlet calibration and later local/regime alternatives. **No Dirichlet mapping, local blend or regime blend is used in the selected final shared-blend NetCDFs.** This distinction must be preserved in methods sections and bulletins.

### Masks and rendering

National products use existing country and variable-specific eligibility masks. Country clipping is distinct from a physical land–ocean/lake mask; the original `mask_json` is retained in forecast NetCDFs. The source dataset supplied for JJAS reported no explicit physical land mask.

The separate JJAS view uses the cleaned GitHub-derived R1/R2 rainfall domain with climatological JJAS >=120 mm and annual share >=0.20. It is a full-period descriptive display mask for 2026, not an onset-detection mask, a historical verification mask, or a separate fitted forecast. It does not replace the national view and is not applied universally to June–September.

Maps use display-only Gaussian filtering (sigma 0.6 native cells), 16-fold interpolation and vector boundary clipping. Smoothing does not create meteorological resolution or change native forecast values. A leading tercile is shown only when its probability is at least 40% and not tied. Percent anomalies are hidden where reference rainfall is below 10 mm.

## 6. Reading the summaries

The bulletin reports area averages of local below/near/above probabilities. These are not probabilities of national rainfall totals and not the fraction of Ethiopia expected to be dry/wet. Display-category area fractions are a separate field in `forecast_summary.json`.

Rainfall and anomaly means use amount-eligible country cells. Probability means use probability-eligible country cells. Coverage can differ by variable and target. Monthly and seasonal forecasts were corrected separately; their corrected amounts need not be additive.

Historical verification uses the common-support regime-experiment summaries. It covers nested training evaluation (1993–2016) and operational evaluation (2017–2025, fitted using 1993–2016). Those operational years have been examined repeatedly. Scores are not new independent evidence, not scores of the 1993–2025 final refit against 2026, and not verification of the separately displayed JJAS R1+R2 subset.

## 7. Archive and next use

The method decision retains the shared blend for all requested targets. August's alternative remains experimental because its small national gain is spatially uneven and its operational whole-year uncertainty interval includes zero. Step 28 documents the detailed geographic assessment.

Check `completion_report.json` for `status: completed` and `complete_five_target_package: true`. Retain `bundle.zip` and the completion receipt with your project. The manifest records input/output/script hashes. Source calibration parameters remain in their existing project directories; this is a forecast-product delivery package, not a complete raw-data/calibration reproduction archive.

No further calibration rerun is needed for this decision. The next use is reviewing and communicating the selected products. Additional experimental calibration should have a predefined evaluation design and use later unexamined cases for prospective assessment.

## Optional single-target build

```bat
python scripts\finalize_forecast_delivery.py --targets JJAS --output outputs\forecast_delivery\JJAS_only --regenerate
```

A partial package is explicitly labeled partial in its viewer, bulletin and completion report. It must not be presented as the completed five-target package.
