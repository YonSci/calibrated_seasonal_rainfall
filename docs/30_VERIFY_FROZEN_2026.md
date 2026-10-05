# Step 30 — Verify the frozen 2026 forecasts against CHIRPS v2

## Confirmed observation product

The supplied historical file identifies itself as **CHIRPS Version 2.0**, with daily rainfall units `mm/day`. Its `date_created: 2015-10-07` describes file/product metadata; it does not establish the last observation date in the merged archive. The script checks actual time coordinates.

Use matching CHIRPS v2 observations. This update uses the official **daily 0.25° (p25) product distributed in monthly files**:

https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/netcdf/p25/by_month/

As checked on 4 October 2026, June, July and August 2026 are listed; September is not listed. Availability is checked again when downloading. No preliminary CHIRPS or CHIRPS v3 product is substituted. A filename containing a year does not imply complete coverage of that year.

Matching version and coordinates alone is insufficient. Before downloading target-year observations, the preparation script compares the requested months of **2025** from the official product against the corresponding daily values in your existing historical archive. A mismatch stops preparation. This identifies an incompatible historical resampling or a changed source product before new observations are scored.

## 1. Install

Extract `verification_2026_update.zip` into `D:\calibrated_seasonal_rainfall`, merging `scripts`, `docs` and `tests`. It uses distinct `verify2026_*` helper names and does not replace your working calibration scripts.

```bat
cd /d D:\calibrated_seasonal_rainfall
.venv\Scripts\activate
```

The existing environment should contain all dependencies. If needed:

```bat
python -m pip install numpy pandas xarray netCDF4 matplotlib
```

No download credentials are required for the official CHIRPS archive. Internet access is required only for preparation downloads. Downloads are streamed to temporary files, validated, then cached with source URL and SHA-256. Existing cache files are reused only if their provenance record and hash match.

## 2. Freeze forecasts and prepare available observations

```bat
python scripts\prepare_verification_2026.py --config config\project.json --months Jun Jul Aug --regenerate
```

The command performs these steps in order:

1. Validates all five existing final shared-blend forecast files and their 51-member ensembles.
2. Saves a frozen copy of each forecast and a hash manifest under `outputs\verification_2026\frozen_forecasts`. This happens before the script downloads 2026 observations. It is a retrospective snapshot, not proof of real-time May issuance or proof that nobody previously saw 2026 outcomes.
3. Downloads the 2025 June–August p25 daily files for the historical overlap check. It subsets the project grid and compares all daily values and missing-data patterns against your existing historical CHIRPS archive. The absolute daily tolerance is 0.0001 mm, for numerical equivalence rather than scientific bias tolerance.
4. Downloads the 2026 June–August p25 daily files after all overlap checks pass. Official files are roughly 5–10 MB each; the regional arrays are much smaller.
5. Requires every daily timestamp for each complete month, with unique increasing midnight date labels. Matches cell centers to the existing common grid within 0.000001 degrees; it does not interpolate or change resolution.
6. Sums daily values with float64 precision. A daily `mm/day` value integrated over one day contributes that many millimetres; do not multiply by 86,400. Any missing daily value makes that cell's monthly total unavailable; missing days are never silently treated as zero.
7. Saves observations and preparation reports separately from existing calibration inputs.

Primary inputs:

| Input | Location |
|---|---|
| Historical CHIRPS archive | `chirps_file` in `config\project.json` |
| Five final forecasts | `outputs\final_shared_blend\init05_TARGET\2026\forecast_2026.nc` |
| Official download cache | `data\raw\chirps\verification_p25` |

Outputs:

```text
outputs/verification_2026/frozen_forecasts/freeze_manifest.json
outputs/verification_2026/frozen_forecasts/init05_TARGET/forecast_2026.nc
outputs/verification_2026/observations/Jun/chirps_2026_common.nc
outputs/verification_2026/observations/Jun/preparation_report.json
```

Equivalent observation folders are created for July and August. The original 1993–2025 CHIRPS file, project configuration, model coefficients and original forecasts remain unchanged.

If the historical overlap fails, retain the message and stop. Do not increase the tolerance, switch versions or interpolate until the data agree. The original 0.25° archive may have been generated with a different resampling method, or the provider may have revised historical values. Resolve the processing provenance first.

## 3. Evaluate the frozen forecasts

```bat
python scripts\verify_frozen_2026.py --targets Jun Jul Aug --regenerate
```

Additional existing inputs, per requested target:

```text
 data/processed/init05_TARGET/ecmwf_2026_common.nc
 data/processed/init05_TARGET/chirps_1993_common.nc
 ...
 data/processed/init05_TARGET/chirps_2025_common.nc
```

The 33 historical observed totals supply the empirical climatology distribution for CRPS. The script checks that their mean, tercile thresholds and category frequencies reproduce the saved forecast reference fields. It does not fit new calibration coefficients or include 2026 in the reference period.

All probability methods are evaluated on the same probability support; all rainfall methods use the same amount support. Support is the fixed forecast eligibility/country mask intersected with complete observations and available comparison values. Coverage is reported. No new regime boundary or post-outcome geographic selection is used.

## 4. Metrics and comparisons

| Component | Compared predictions | Metrics |
|---|---|---|
| Rainfall amount | Raw ECMWF, corrected ensemble, historical observed climatology | Bias, MAE, RMSE, empirical CRPS; CRPSS against climatology |
| Tercile probabilities | Raw counts against observed thresholds; corrected counts; corrected smoothed counts; selected shared blend; climatology | Brier score per category, RPS, log loss, BSS and RPSS against climatology |

Observed category thresholds are the **saved 1993–2025 q1/q2** in each frozen forecast. Below: observed rainfall <q1; near: q1≤rainfall≤q2; above: rainfall >q2. New-year observations never redefine those categories.

Raw probabilities use raw rainfall members against the frozen **observed** thresholds. They are not probabilities against a separate model climatology. This makes the effect of amount correction visible while keeping the event definition fixed.

Probability blending does not modify corrected member rainfall. It therefore has no separate rainfall CRPS: raw versus corrected CRPS evaluates amount correction, while corrected/smoothed/shared probability scores evaluate probability processing.

CRPS uses the finite empirical predictive distributions: 51 members for raw/corrected ECMWF and 33 historical observed years for climatology. No iid-based fair-CRPS correction is imposed. Log loss uses natural logarithms and floors probabilities at 1e-12; the count of observed events assigned exactly zero probability is also reported.

Bias is forecast minus observed: positive means too wet. Lower MAE, RMSE, CRPS, Brier score, RPS and log loss are better. Positive BSS/RPSS/CRPSS means improvement over the specified climatology on this year's common spatial support; it does not establish long-term skill.

## 5. Results to inspect

Per target:

```text
outputs/verification_2026/results/Jun/verification_report.json
outputs/verification_2026/results/Jun/verification_fields.nc
outputs/verification_2026/results/Jun/verification_maps.png
```

The six-panel native-grid figure shows observed anomaly, forecast mean anomaly, rainfall error, observed tercile, shared-minus-climatology RPS, and corrected ensemble CRPS. Negative shared-minus-climatology RPS favors the shared forecast. The country outline is the existing raster-mask contour; no new administrative boundary or smoothing is introduced for verification.

Combined files:

```text
outputs/verification_2026/reports/Jun_Jul_Aug/verification_summary.json
outputs/verification_2026/reports/Jun_Jul_Aug/VERIFICATION.md
```

Share `verification_summary.json` first. It contains the metrics, coverage and provenance for all three months. The maps can be shared separately if geographic interpretation is needed.

## 6. September and JJAS when observations are complete

When the official September daily p25 file becomes available:

```bat
python scripts\prepare_verification_2026.py --config config\project.json --months Jun Jul Aug Sep --regenerate
python scripts\verify_frozen_2026.py --targets Jun Jul Aug Sep JJAS --regenerate
```

The preparation script builds JJAS only when all four months are explicitly requested and complete in the run. It sums those observed monthly totals to obtain all 122 days. If September is unavailable, the command gives a clear error and does not create a partial JJAS total. Individual earlier months may already have completed; their outputs are valid and remain separately labeled.

Do not compare a June–August observed total with the JJAS forecast. The observed monthly totals reconstruct the observed JJAS total; separately calibrated forecast monthly totals need not reconstruct the calibrated JJAS forecast.

## 7. Limits and archive rules

- No 2026 observations enter fitting or method selection in these scripts.
- This is a retrospective held-out-year assessment conditional on earlier decisions not having used 2026 outcomes; it is not real-time issuance verification.
- One new year cannot establish long-term reliability. Neighboring cells are not independent samples, and June–September plus JJAS are not five independent seasons. No confidence interval is manufactured by bootstrapping grid cells, and no combined score across overlapping targets is reported.
- CHIRPS is an observation-based reference with uncertainty, not error-free ground truth.
- Do not tune the selected model to the 2026 errors and continue to describe the resulting scores as independent evaluation.
- `--regenerate` preserves previous observation/score directories in timestamped backups. Frozen forecasts are never overwritten by that flag. If current source forecasts differ from the frozen snapshot, the preparation command stops; investigate the change rather than replacing the assessment archive.
- Cached monthly files are reused with their hashes. A provider revision should be handled as a documented new observation version, not silently substituted into the existing assessment.

## Tests

```bat
python tests\test_verification_2026.py
```

The tests use explicitly synthetic temporary data to check scoring, missing support, incomplete dates, grid/overlap rejection and an offline preparation-to-report run. Synthetic scores are not real 2026 verification results. Real-source download/calendar/grid checks were performed separately; full user-archive overlap and actual forecast scoring occur on your computer.
