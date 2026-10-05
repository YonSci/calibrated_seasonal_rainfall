# Step 17 — Local probability calibration and separate month-year evaluation

## What this update implements

We now compare three blend procedures:

1. Shared blend: one fitted climatology weight across the common calibration domain.
2. Independent local blend: one fitted climatology weight per eligible grid cell.
3. Regularized local blend: local weights pulled toward the shared weight.

Climatology and the smoothed corrected ensemble remain references. Rainfall mean–variance correction and observed tercile thresholds were already grid-cell specific. This update changes the blend weight, not the rainfall-correction formula. It does not fit a full independent Dirichlet matrix at every cell.

Two temporal scales are supported:

- Season-year: one JJAS total and verification outcome per grid cell per year.
- Month-year: separate June, July, August and September totals and verification outcomes, all from the same May-initialized forecasts.

Each month has its own correction, thresholds, climatology, blend parameters and verification. This is monthly-target verification of a seasonal forecast, not verification of forecasts reinitialized every month.

## 1. Install

Extract `seasonal_local_monthly_update.zip` into:

```text
D:\calibrated_seasonal_rainfall
```

New files:

```text
scripts\local_blend.py
scripts\run_monthly.py
tests\test_local_monthly.py
docs\17_LOCAL_AND_MONTHLY_CALIBRATION.md
```

Keep existing `common.py`, `calibration_core.py`, `run_calibration.py`, `compare_calibration.py`, `verification_core.py`, `prepare_seasonal.py` and `regrid_seasonal.py` in `scripts`. These are dependencies from previous updates. No new Python packages are needed.

Run in a Windows CMD terminal:

```bat
cd /d D:\calibrated_seasonal_rainfall
.venv\Scripts\activate
python -m unittest discover -s tests -p test_local_monthly.py -v
```

Tests use synthetic data; their values are not estimates of real forecast skill.

## 2. First run the seasonal training comparison

```bat
python scripts\local_blend.py --config config\project.json --mode training --region-mask data\masks\ethiopia_common.nc
```

Only 1993–2016 files are read in this mode. Output:

```text
outputs\local_calibration\init05_JJAS\training
```

The three procedures and regularization strength are fixed before seeing these results. Nothing is automatically selected or promoted to an operational model.

## 3. Statistical definition and purpose

At grid cell g:

```text
q_g = (1 - lambda_g) * p_smoothed_g + lambda_g * climatology_g
```

The observed climatology is local. The member-count smoothing is:

```text
p_smoothed[k] = (M * p_base[k] + 0.5) / (M + 1.5)
```

M is the actual member count, so all 25 reforecast or all 51 operational members are used.

For independent local fitting, minimize mean RPS over the available training-year probability/observation pairs at that cell, with lambda bounded to 0–1.

For regularized fitting, minimize:

```text
mean_local_RPS(lambda_g) + gamma * (lambda_g - lambda_shared)^2
```

The implementation uses **gamma = 0.05**, fixed for this first experiment. This is a project-specific experimental choice, not an empirically optimal or universally recommended value. It is not tuned against either period. RPS is the unnormalized sum over two cumulative category boundaries, and the loss is averaged over years; this normalization defines the meaning of gamma.

Why fix gamma? It keeps this first comparison limited and avoids adding another hyperparameter-selection layer. If we later tune gamma, tuning must occur within the outer training folds; selecting it from the displayed outer scores and treating the winning score as unbiased would be incorrect.

The global shared weight is fitted with equal total weight per year and spherical cell-area weights within each year. Local loss uses equal valid-year weights at each cell. A constant cell-area factor would cancel from the unpenalized local fit; the chosen mean-loss penalty has the same strength definition across cells.

### Analytic fit

Let F be the first two cumulative forecast probabilities, C the cumulative climatology probabilities, and O the cumulative observed one-hot vector. Define:

```text
A_g = mean_year sum_boundary (C - F)^2
B_g = -mean_year sum_boundary (F - O) * (C - F)
```

Then:

```text
lambda_local = clip(B_g / A_g, 0, 1)
lambda_regularized = clip((B_g + gamma * lambda_shared) / (A_g + gamma), 0, 1)
```

The shared weight uses the corresponding equal-year/area-weighted sums of A and B before taking the ratio. No iterative local optimizer is needed.

Cells with fewer than 20 valid training pairs, or with indistinguishable forecast and climatology probabilities, fall back to the shared weight. `training_pairs` and `local_supported` document this. The fallback does not bypass the original rainfall/probability eligibility checks.

### What a local weight means

- Lambda near zero: retain more of the corrected, smoothed ensemble probabilities.
- Lambda near one: rely more heavily on local climatology.
- Regularization: discourage large local departures unsupported by the small seasonal sample.

A weight is not a probability that ECMWF is correct. A large weight does not identify the physical cause of poor skill. Local blending cannot independently remove every category-specific probability bias.

## 4. Leakage control in training mode

For an outer validation year, such as 2000:

1. Exclude 2000 from all fitting.
2. For each of the other 23 years, exclude that inner target year as well.
3. Fit rainfall correction and thresholds on the remaining 22 years and create the inner held-out probability/observation pair.
4. Fit the shared and local weights using those 23 inner records.
5. Fit rainfall correction and thresholds on the full 23-year outer training set.
6. Predict and score 2000.
7. Repeat for all 24 years.

This prevents an outer validation year's data entering either preprocessing or local-weight estimation. Existing Step 15 OOF records are not reused for inner fits, because their preprocessing can include the current outer held-out year.

The shared-blend JJAS training RPS should closely reproduce Step 15's value around 0.432298 if inputs and core scripts are unchanged. This is a useful baseline consistency check.

## 5. Monthly preparation

Monthly calibration needs monthly amounts, not the JJAS total divided by four. The wrapper creates separate configurations without editing `config/project.json`:

```text
config\monthly_Jun.json
config\monthly_Jul.json
config\monthly_Aug.json
config\monthly_Sep.json
```

These copy source paths, variable names and the configured 0.2 mm negative-increment tolerance from your project. Only the target period changes. This wrapper is deliberately limited to the established May-initialized JJAS project.

Prepare all months:

```bat
python scripts\run_monthly.py --config config\project.json --stage prepare
```

For each month it runs the existing preparation and regridding scripts over 1993–2026. CHIRPS preparation stops at 2025, as configured. The raw model files are read again for each month, so this stage requires extra disk space and I/O time. Existing seasonal files remain unchanged.

New directories:

```text
data\interim\init05_Jun
data\interim\init05_Jul
data\interim\init05_Aug
data\interim\init05_Sep

data\processed\init05_Jun
data\processed\init05_Jul
data\processed\init05_Aug
data\processed\init05_Sep
```

Each processed folder should contain 34 ECMWF files and 33 CHIRPS files. For compatibility, the rainfall variable remains named `precip_season` even in the monthly files; the configuration metadata and directory identify its actual time period. Values are monthly totals in mm, not mm/day.

Month lengths are June 30, July 31, August 31, September 30 days. Daily ECMWF accumulations are handled exactly as before: endpoint minus preceding endpoint, labelled to the preceding day, with configured tiny negative increments clipped. Conservative regridding uses the existing common grid.

After all four months are prepared, the wrapper checks:

```text
Jun + Jul + Aug + Sep = JJAS
```

This check covers every ECMWF member/cell for all 34 years and complete CHIRPS cells for all 33 years, also requiring identical missingness. Floating-point tolerance is 1e-5 mm plus a small relative tolerance. This reconstruction tolerance is distinct from the 0.2 mm daily negative-increment tolerance.

Results are saved to:

```text
outputs\qc\monthly_reconstruction.json
```

You can repeat only the reconstruction check:

```bat
python scripts\run_monthly.py --config config\project.json --stage check
```

For a staged preparation, use `--months 6`, then 7, 8, 9 in separate commands. After all four are prepared, run `--stage check`. If preparation fails, rename the affected month's partial interim/processed folders before rerunning that month. Completed months do not need to be prepared again.

## 6. Run separate monthly training comparisons

After monthly preparation and its reconstruction check pass:

```bat
python scripts\run_monthly.py --config config\project.json --stage training --region-mask data\masks\ethiopia_common.nc
```

This runs four independent training comparisons. To start with June only:

```bat
python scripts\run_monthly.py --config config\project.json --stage training --months 6 --region-mask data\masks\ethiopia_common.nc
```

Then use `--months 7 8 9` for the remaining months. Do not run June again without renaming its previous result folder.

Output locations:

```text
outputs\local_calibration\init05_Jun\training
outputs\local_calibration\init05_Jul\training
outputs\local_calibration\init05_Aug\training
outputs\local_calibration\init05_Sep\training
```

Each month still has only 24 historical seasonal-year cases per cell. We do not pool June, July, August and September into 96 supposedly independent observations. Their climatologies and forecast lead times differ, and they share within-year dependence.

The existing probability-eligibility rules are retained: adequate observed variation and distinct, nonzero lower tercile threshold. Some dry month/cell combinations may therefore be excluded even where JJAS is eligible. An all-ineligible target fails explicitly. Do not force artificial three-category forecasts at dry/degenerate cells just to obtain a complete map.

## 7. Optional subsequent operational-period evaluation

Review training-period results first. To apply the same fixed procedures, without tuning, to 2017–2025:

```bat
python scripts\local_blend.py --config config\project.json --mode operational --region-mask data\masks\ethiopia_common.nc
python scripts\run_monthly.py --config config\project.json --stage operational --region-mask data\masks\ethiopia_common.nc
```

Operational mode fits weights on 24 LOYO training records from 1993–2016, fits amount correction and thresholds on all 24 years, and applies them to 2017–2025 with all 51 members. It reads the target observations only for scoring, not fitting. Parameters are fixed across the nine target years.

The JJAS shared-blend operational RPS should be around 0.428397 if all inputs and core scripts are unchanged. Monthly scores need not resemble the seasonal score.

Treat evaluation on 2017–2025 as exploratory, since these years have already been inspected. Repeatedly trying variants on them does not create independent validation. There is no automatic final refit or 2026 product in this update.

## 8. Outputs for each target and mode

| File | Contents |
|---|---|
| `local_comparison_summary.json` | Annual and mean RPS/log loss/Brier scores, RPSS/BSS, differences and descriptive uncertainty |
| `local_probabilities_and_weights.nc` | Probabilities, observed labels, thresholds, local weights, training-pair counts and mask |
| `local_spatial_scores.nc` | Cellwise mean RPS and valid-year counts inside the evaluation region |
| `annual_local_rps.png` | Separate year-by-year scores for the selected season or month |
| `local_weights.png` | Independent and regularized climatology weights |
| `local_skill_difference.png` | Local-method RPS minus shared-blend RPS |

Probabilities and parameter fields cover the eligible common domain. Apply the saved `region_mask` for Ethiopia-only use. Spatial scores already exclude cells outside the region. In training mode the weight map is the mean across outer-fold fits, not a single operational parameter map. The NetCDF retains each fold separately. In operational mode the same fitted weights are repeated for all target years.

Country masking occurs after common-grid preparation and restricts evaluation. It is not a physical land–ocean mask. If you used a separate physical land mask before, pass the same file via `--land-mask` to either calibration script/wrapper. Do not pass the Ethiopia region mask as the land mask.

No output folder is overwritten. Rename existing result folders before rerunning. Monthly configurations are reused only if their contents exactly match the requested configuration.

## 9. How to interpret success

Compare regularized local blending with shared blending on the same valid cells in each year. Lower RPS/log loss is better. Positive skill beats the matching training climatology. Negative RPS difference favors the local method.

Look for consistent gains across years, not only a lower grand mean. Inspect whether independent local weights saturate at 0/1 and whether regularization reduces unstable patterns. A smoother map alone is not evidence of forecast skill.

The bootstrap resamples whole years, not cells or members, 5,000 times. Its ranges are descriptive and do not account fully for serial dependence, model-fitting uncertainty, or candidate selection. Use caution interpreting hundreds of cellwise differences, especially with only nine operational evaluation years.

Monthly RPSS uses that month's own climatology and eligibility. Report each month separately; do not label their simple average as JJAS skill. Calibrated monthly category probabilities cannot be summed or averaged to obtain seasonal probabilities. Seasonal and monthly amount corrections can also produce totals that are not additive after correction; the reconstruction check applies to the uncalibrated input totals only. A coherent joint monthly/seasonal calibrated rainfall product would require another modeling step.

Continuous CRPS/RMSE and categorical ROC/reliability are not recalculated in this focused local-weight comparison. Saved probability fields support later ROC/reliability diagnostics. Categorical blends do not define new continuous rainfall ensembles.

## 10. Send back

First send the JJAS training summary and three PNGs. For monthly comparisons, send each month's `local_comparison_summary.json`, naming uploads clearly, for example `Jun_local_comparison_summary.json`. Also send `monthly_reconstruction.json` to confirm input consistency. The large NetCDF files are optional for deeper diagnostics.

Review the training comparisons before promoting a local model. The scripts provide the subsequent operational evaluation commands, but do not select or replace any existing forecast method automatically.
