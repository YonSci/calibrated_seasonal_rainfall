# Stage 3: Rainfall correction, probabilities and Dirichlet calibration

> **Status update (2026-10-05):** `--mode final` (Dirichlet) is not the 2026 product. The final forecast comes from `final_shared_blend.py` (doc 20). See [36_PROJECT_STATUS_REVIEW.md](36_PROJECT_STATUS_REVIEW.md).

## What this update implements

- Training-only observation eligibility masks, plus optional explicit static land–ocean mask.
- Pooled, equal-year-weight mean–variance seasonal rainfall bias correction.
- Leave-one-year-out (LOYO) base probabilities for training a probability calibrator.
- One spatially pooled, identity-regularized Dirichlet calibrator for the three categories.
- Independent 2017–2025 evaluation, including raw and corrected rainfall, probability scores, and reliability bins.
- Separate final refit on 1993–2025 and application to the May-initialized JJAS 2026 forecast.

This is an extension of the previous starter, using its environment and `scripts/common.py`. No new Python packages are required. This is seasonal-total calibration: it does not create corrected daily rainfall or onset dates.

## 1. Install

Extract `seasonal_calibration_update.zip`. Copy its `scripts`, `tests`, and `docs` folders into `D:\calibrated_seasonal_rainfall`, merging them with existing folders. The ZIP adds these files:

```text
scripts/calibration_core.py
scripts/run_calibration.py
tests/test_calibration.py
docs/10_RUN_CALIBRATION.md
docs/11_CALIBRATION_METHODS.md
docs/12_LAND_OCEAN_MASK.md
```

It does not replace your project configuration, preparation script or regridding script.

## 2. Activate and verify

In the VS Code CMD terminal:

```bat
cd /d D:\calibrated_seasonal_rainfall
.venv\Scripts\activate
python -m unittest discover -s tests -p test_calibration.py -v
```

Expected result: five tests pass. Tests use temporary synthetic datasets and do not modify your scientific data.

## 3. Decide whether to supply a physical land mask

Read `docs/12_LAND_OCEAN_MASK.md` before running. The correct position is after regridding and before estimating any calibration parameters.

No physical mask was supplied with your data. The default run therefore uses training-observation eligibility only and reports `land_mask.applied: false`. It never calls this eligibility a land–ocean mask. This run can proceed without a geographic mask because cells without training observations are excluded from fitting and predictions.

If you have an independently sourced, aligned binary land mask, use the alternative command below. Use the same mask for development and final fitting. Do not run both variants into the same output directories if you need to retain them for comparison: each mode overwrites its own derived outputs.

## 4. Run development and independent evaluation FIRST

Without an explicit physical land mask:

```bat
python scripts\run_calibration.py --config config\project.json --mode development
```

OR, with the static land mask described in guide 12:

```bat
python scripts\run_calibration.py --config config\project.json --mode development --land-mask data\masks\land_mask_common.nc
```

This command:

1. Reads regridded ECMWF and CHIRPS 1993–2025.
2. Builds 24 year-withheld base-probability records from 1993–2016. Each withheld year is excluded from fitting the amount statistics, observation eligibility, thresholds and variance checks.
3. Fits the Dirichlet mapping using those out-of-fold probabilities and their observed categories.
4. Refits amount correction and terciles on all 24 development years.
5. Applies both corrections to the nine 2017–2025 forecasts.
6. Uses 2017–2025 observations only for evaluation. They never enter either fitted correction.

There is no automatic hyperparameter tuning. Regularization and amount-correction safeguards are fixed in the supplied implementation. This avoids selecting settings against the heldout test period. Tuning, if later required, must use nested year-based validation inside 1993–2016.

### Outputs

| File under project root | Purpose |
|---|---|
| `models/init05_JJAS/development/amount_parameters.nc` | Grid-cell means, SDs, scales, terciles and eligibility flags |
| `models/init05_JJAS/development/dirichlet_parameters.json` | Global 3 x 3 matrix, three intercepts, penalties and optimizer status |
| `outputs/calibration/init05_JJAS/development/base_probabilities_oof.nc` | 24 withheld-year base probabilities, fold thresholds and labels |
| `outputs/calibration/init05_JJAS/development/corrected_2017.nc` through `corrected_2025.nc` | Corrected seasonal member amounts for evaluation |
| `outputs/calibration/init05_JJAS/development/probabilities.nc` | Raw, amount-corrected, Dirichlet and training-climatology probabilities for nine test years |
| `outputs/calibration/init05_JJAS/development/calibration_report.json` | Fold definitions, eligible cell counts, clipping fractions and mask status |
| `outputs/calibration/init05_JJAS/development/validation_metrics.json` | Annual and equally weighted across-year scores |
| `outputs/calibration/init05_JJAS/development/reliability.json` | Ten-bin reliability/sharpness summaries for each category |

The files retain the full rectangular grid; excluded cells carry NaN probabilities/amounts. Category labels are -1 where unavailable, 0 below, 1 near, 2 above.

## 5. Review evaluation before making a skill claim

Upload these small reports after the development command finishes:

```text
outputs\calibration\init05_JJAS\development\calibration_report.json
outputs\calibration\init05_JJAS\development\validation_metrics.json
outputs\calibration\init05_JJAS\development\reliability.json
```

Checks:

- Optimizer converged and all requested years appear.
- There are usable cells in every fold and test year.
- Predicted probability vectors sum to one (checked by the script).
- Compare raw vs corrected ensemble-mean bias/MAE/RMSE.
- Compare raw, amount-corrected and Dirichlet probability RPS, Brier scores and log loss.
- Check whether Dirichlet improves on both the base probabilities and training climatology. A completed optimizer does not prove improved forecasting.
- Inspect reliability: predicted probability vs observed frequency, along with bin weight. Sparse bins are uncertain.

There are only nine test seasons. Grid cells and members are dependent and are not additional independent years. This update provides descriptive scores, not confidence intervals or statistical significance. Regional diagnostics, year-block bootstrap uncertainty and 25-member subsampling of operational ensembles remain additional evaluation work.

## 6. Final refit for 2026

After reviewing the independent evaluation, this command refits the same fixed procedure using all observed years 1993–2025:

```bat
python scripts\run_calibration.py --config config\project.json --mode final
```

If you used a physical mask in development, use it here too:

```bat
python scripts\run_calibration.py --config config\project.json --mode final --land-mask data\masks\land_mask_common.nc
```

Final mode rebuilds 33 year-withheld training records, refits the global Dirichlet map, fits rainfall parameters on all 33 years with equal year weights, and applies both mappings to 51-member 2026 forecasts. Development outputs are retained in their separate folder.

Results:

```text
models\init05_JJAS\final\amount_parameters.nc
models\init05_JJAS\final\dirichlet_parameters.json
outputs\calibration\init05_JJAS\final\base_probabilities_oof.nc
outputs\calibration\init05_JJAS\final\corrected_2026.nc
outputs\calibration\init05_JJAS\final\probabilities.nc
outputs\calibration\init05_JJAS\final\calibration_report.json
```

Use `dirichlet_probability` in final `probabilities.nc` for the calibrated tercile maps, provided evaluation supports using this method. `base_probability` is available for comparison. These probabilities are fractions (0–1), not percentages. Corrected amounts remain in mm.

As of October 2026, JJAS 2026 has elapsed: this reconstructs the May-initialized forecast. The supplied observations end in 2025, so no 2026 verification is performed.

## 7. Reproducibility and limitations

- The year split is explicit in `run_calibration.py`: development 1993–2016, test 2017–2025, final target 2026. It does not automatically adapt to other archive periods.
- Every derived run records configuration, training years and UTC time. Explicit land-mask inputs also record a SHA-256 hash.
- Data sources and regridded inputs are never changed. Re-running a mode replaces its derived outputs. A failed run may leave outputs from an earlier run, so require the terminal `Complete` message and review the latest report.
- Real checks previously confirmed all regridding years. This calibration update was tested with synthetic multi-year datasets, including both member counts, masks and NetCDF roundtrips. The actual multi-year calibration has not been run here because those common-grid files remain on your computer.
- The five tests cover unequal member weighting, a known affine bias, missing/land masks, tied thresholds, probability sums, optimizer gradients, development/final command-line execution and unchanged fitted parameters when heldout observations change.
- Tests passed with the pinned scientific dependencies on Linux; Windows execution remains your local check. The test environment emitted a NumPy/NetCDF binary-compatibility warning, but all tests and read/write checks completed successfully.

## 8. Troubleshooting

- `No module named common`: install inside the original project's scripts folder.
- `No module named ...`: activate `.venv` and use the starter requirements.
- `Grid mismatch`: do not interpolate inside calibration; resolve the common-grid inputs first.
- `land_mask coordinates must exactly match`: build the static mask on the common grid and in the same coordinate order.
- `No eligible...` or no calibration pairs: inspect training observation completeness, variability, thresholds and mask overlap. Do not replace NaNs with zero.
- Optimizer failure: send the traceback; the script stops instead of silently using a failed fit.
- Permission denied: close software holding an output NetCDF open.
