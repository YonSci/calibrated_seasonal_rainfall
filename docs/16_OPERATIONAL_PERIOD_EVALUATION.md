# Step 16 — Evaluate the frozen candidate on 2017–2025

## Purpose and scope

Step 15 ranked the climatology blend first on 1993–2016 cross-validation. Smoothed Dirichlet and temperature scaling were very close. This stage fits those procedures on 1993–2016 and applies them to the 2017–2025 operational-member period. The primary candidate is fixed as `blend`; the script does not select another winner or tune parameters using 2017–2025.

Those years have already been inspected in this project. Call this exploratory evaluation, not an untouched independent test. All fitting still excludes their observations and forecasts. Actual improvement must be assessed from the outputs; none is assumed.

## 1. Install

Extract `seasonal_holdout_update.zip` into:

```text
D:\calibrated_seasonal_rainfall
```

It adds three files:

```text
scripts\evaluate_candidates.py
tests\test_operational_candidates.py
docs\16_OPERATIONAL_PERIOD_EVALUATION.md
```

Keep these existing scripts from earlier updates in `scripts`:

```text
common.py
calibration_core.py
run_calibration.py
compare_calibration.py
verification_core.py
```

Keep the existing Python environment. Required packages are NumPy, SciPy, xarray, NetCDF4 and Matplotlib, already used in previous stages. No new GIS packages are required.

## 2. Run in Windows CMD / VS Code

```bat
cd /d D:\calibrated_seasonal_rainfall
.venv\Scripts\activate
python -m unittest discover -s tests -p test_operational_candidates.py -v
python scripts\evaluate_candidates.py --config config\project.json --region-mask data\masks\ethiopia_common.nc
```

If the environment is already active, omit the activation command. The test uses a small synthetic dataset, not your real data; its printed scores must not be interpreted as forecast skill.

The evaluation reads the common-grid ECMWF and CHIRPS files for 1993–2025. The existing input loader checks coordinates, rainfall units and member counts: 25 before 2017, 51 from 2017 onward. It does not read 2026 and does not rerun preparation or regridding.

Progress prints `Training OOF: 1993` through `Training OOF: 2016`, then scores and the output path. Fitting the probability maps and producing plots can take time after the final OOF message.

## 3. What happens, and why

### A. Generate training probabilities without using their own year in preprocessing

For each year in 1993–2016:

1. Hold out that year.
2. Fit rainfall mean–variance correction, observational eligibility and category thresholds on the other 23 years.
3. Apply the correction to all 25 members of the held-out year.
4. Calculate its tercile member counts and probabilities.
5. Calculate its observed category using the same fold-specific thresholds.
6. Calculate climatological category frequencies using the 23 fitting years.

Purpose: probability calibration learns from forecasts whose rainfall preprocessing did not use their own verification year.

### B. Fit probability calibration once on the 24 training records

Fit the blend weight to area-weighted RPS using all 24 OOF training records. Also fit the original Dirichlet map, smoothed Dirichlet map and temperature scaling for secondary comparison. Fits retain the existing common-domain geographical scope; the Ethiopia country mask is for evaluation only.

The blend is:

```text
p_final = (1 - lambda) * p_smoothed + lambda * p_training_climatology
```

Do not hard-code the previously reported average fold weight of 0.4745. That was a descriptive average from Step 15. This script estimates the full-training weight and saves it in `fitted_probability_models.json`.

Smoothing remains fixed at 0.5 added to each category count. Temperature remains bounded to 0.25–4. Dirichlet retains the previous fixed regularization. No parameter search is performed.

### C. Fit rainfall correction and thresholds on all 24 training years

Fit the rainfall correction and tercile thresholds on 1993–2016. Calculate climatology from those observations. These values remain fixed for every target year.

Purpose: represent a method fitted before the evaluation period, with a consistent rainfall/category reference throughout that period.

### D. Apply to 2017–2025 using all 51 members

Correct each member's seasonal total using the frozen rainfall correction. Count the members in each category. Smooth using the actual ensemble size:

```text
p_smoothed[k] = (count[k] + 0.5) / (51 + 1.5)
```

Apply the frozen probability maps and blend. There is no random member subsampling and no discarded operational member.

### E. Verify against the target-year CHIRPS observations

Only after producing probabilities, label the 2017–2025 observations using the frozen training thresholds and compute the scores. All methods are scored on common valid cells inside the supplied Ethiopia mask, with area weights within each year and equal weights across years.

## 4. Mask placement

Seasonal totals and regridding are already complete. This stage reads the mask on the common grid, validates its coordinates, then applies the country mask during evaluation and spatial-diagnostic generation.

`ethiopia_common.nc` is a geographic region mask. It is not a land–ocean or lake mask. Probability fitting retains the existing domain. Training-observation eligibility is calculated from training years only.

If you used a separate physical land mask in previous stages, supply the same file with `--land-mask`. Otherwise use the command above. Do not substitute the Ethiopia mask for a physical land mask.

## 5. Output location and files

```text
outputs\model_comparison\init05_JJAS\operational_period\
```

| File | Purpose |
|---|---|
| `operational_comparison_summary.json` | Aggregate and annual scores, primary candidate, member counts, mask provenance and code hashes |
| `fitted_probability_models.json` | Fitted blend weight, temperature, Dirichlet maps and smoothing strength |
| `amount_parameters.nc` | Frozen 1993–2016 rainfall correction and tercile thresholds |
| `operational_probabilities.nc` | Seven probability methods for 2017–2025, observed categories and region mask |
| `reliability_bins.json` | Area/equal-year weighted reliability bins, sample counts and probability histograms |
| `roc_curves.json` | Category-wise weighted ROC curves and AUC values; null when undefined |
| `spatial_scores.nc` | Cellwise mean RPS by method and valid-year counts, restricted to the region |
| `annual_rps.png` | Year-by-year probability-score comparison |
| `reliability_and_histograms.png` | Reliability and the frequency of issued probabilities |
| `roc_curves.png` | Below/near/above discrimination |
| `spatial_rps.png` | Original and blend RPSS maps, plus their RPS difference |

The full probability NetCDF retains eligible cells across the common domain. Apply its `region_mask` for Ethiopia maps. Spatial scores already exclude cells outside the region. No shapefile outline is drawn; the map title explicitly states that.

The output folder must not already exist. If it exists, rename it before rerunning. An interrupted run may leave a partial folder; rename that folder and rerun. There is no resume mode. Existing calibration, verification and Step 15 outputs are not overwritten.

## 6. Metrics and interpretation

The summary includes RPS, RPSS, log loss, Brier scores and Brier skill scores by category, mean maximum probability, and differences from the original Dirichlet RPS. Category order is below, near, above.

- Lower RPS/log loss/Brier score is better.
- Positive RPSS/BSS means improvement over the matching training climatology.
- Negative `rps_difference_vs_original` favors that method over original Dirichlet.
- Reliability close to the diagonal is desirable, but inspect probability-bin weights before interpreting points based on very little data.
- AUC measures discrimination, not probability reliability.
- Greater maximum probability indicates greater confidence, not automatically greater skill.

The bootstrap range uses 5,000 paired resamples of the nine whole-year score records, preserving spatial dependence within each year. It does not refit the models, account for serial dependence or capture all training uncertainty. Treat it as descriptive. Nine seasons are a short sample.

In the spatial figure, blue RPSS means positive skill; red means negative skill. In the difference panel, blue/negative values favor the blend. Colors saturate outside the displayed ranges; the NetCDF contains the actual values. Spatial estimates based on nine years can be noisy.

The earlier Ethiopia original-Dirichlet evaluation gave RPS around 0.441260 and log loss around 1.083075. The recomputed `dirichlet_original` should agree closely if your data, masks and existing core scripts are unchanged. A substantial discrepancy should be investigated before interpreting the alternative-method differences.

CRPS, rainfall bias and RMSE are not repeated: these categorical probability alternatives share the same rainfall correction and do not produce different continuous rainfall ensembles. Reuse the earlier continuous verification when describing that part of the system.

## 7. What to send back

Upload:

```text
operational_comparison_summary.json
fitted_probability_models.json
annual_rps.png
reliability_and_histograms.png
roc_curves.png
spatial_rps.png
```

The NetCDFs and detailed reliability/ROC JSON files are optional unless deeper diagnostics are needed.

We will check whether the blend improves both RPS and log loss, whether gains persist across years and categories, and where spatial performance is poor. Secondary comparisons remain exploratory; repeatedly switching methods based on these nine years would overstate validation evidence.

## 8. Later final refit

This stage does not generate the 2026 forecast or replace the operational model. After reviewing results, the selected procedure can be refitted on 1993–2025 and applied to the 51 members of the 2026 forecast. That later implementation must retain the selected smoothing and calibration procedure, including equal-year fitting when training years have unequal member counts.

JJAS 2026 has already elapsed, so a forecast generated now is a retrospective reconstruction of the May-initialized product. Your current CHIRPS archive ends in 2025 and cannot verify 2026.
