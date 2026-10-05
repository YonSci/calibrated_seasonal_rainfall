# Step 15 — Compare probability calibration using training years only

## Purpose

Your Ethiopia verification showed a large improvement over raw ECMWF rainfall, but only small gains over climatology. The Dirichlet probabilities were concentrated near one-third. This stage tests a small, fixed set of alternatives. Improvement is possible, not guaranteed.

The rainfall correction remains the existing pooled, equal-year mean–variance bias correction, including its scale bounds and clipping at zero. We isolate probability calibration first so that the cause of any change is identifiable. This stage produces a comparison, not a replacement operational forecast.

## 1. Install the update

Extract `seasonal_comparison_update.zip` directly into:

```text
D:\calibrated_seasonal_rainfall
```

The archive contains these new files:

```text
scripts\compare_calibration.py
tests\test_comparison.py
docs\15_TRAINING_ONLY_COMPARISON.md
```

Keep the existing `scripts\common.py`, `scripts\calibration_core.py`, and `scripts\run_calibration.py`. The new script imports them. Your existing environment already has the required NumPy, SciPy, xarray and NetCDF packages. No GIS package is required to use the prepared mask.

In VS Code select a Command Prompt terminal. Run:

```bat
cd /d D:\calibrated_seasonal_rainfall
.venv\Scripts\activate
python -m unittest discover -s tests -p test_comparison.py -v
python scripts\compare_calibration.py --config config\project.json --region-mask data\masks\ethiopia_common.nc
```

These are CMD commands, not PowerShell commands. If `.venv` is already active, activation can be omitted.

The script reads only ECMWF and CHIRPS common-grid files for 1993–2016. All 25 members in those years are used. It does not open the 2017–2026 files. There is no change to the recommendation to retain all 51 operational members in the later application stage.

## 2. Fixed candidate methods

| Output name | Calculation | Purpose |
|---|---|---|
| `climatology` | Observed category frequencies in the applicable training years | Establish whether ECMWF adds value |
| `base` | Corrected ensemble category counts / member count | Reference without probability calibration |
| `smooth` | Add 0.5 to each of three category counts, then normalize | Avoid treating zero ensemble counts as zero event probability |
| `temperature` | Apply one fitted temperature to log smoothed probabilities | Test a much simpler calibration model |
| `blend` | Fit one weight mixing smoothed forecast and training climatology | Limit forecast influence when it does not help RPS |
| `dirichlet_original` | Existing regularized Dirichlet map on base probabilities | Reproduce the current method under stricter validation |
| `dirichlet_smooth` | Same regularized Dirichlet map on smoothed probabilities | Test whether extreme log inputs from zero counts cause problems |

The two Dirichlet methods retain the existing fixed penalties: off-diagonal 0.01, diagonal deviation from identity 0.001, intercept 0.001. This project-specific identity regularization is not a claim to reproduce the paper's exact regularization setup.

### Count smoothing example

Suppose 25 members give category counts `[0, 10, 15]`.

Base probabilities are `[0%, 40%, 60%]`.

With alpha = 0.5 per category:

```text
p[k] = (count[k] + 0.5) / (M + 1.5)
```

The result is approximately `[1.89%, 39.62%, 58.49%]`.

This is symmetric additive pseudocount smoothing, interpretable as a multinomial probability estimate under a symmetric Dirichlet prior. It is distinct from the fitted Dirichlet calibration map. The alpha is fixed in advance, not selected using 2017–2025. At 51 members the denominator is 52.5, so the smoothing has less influence. Finite-ensemble smoothing does not remove a model-system change between reforecasts and real-time forecasts.

### Temperature example

```text
q = softmax(log(p_smoothed) / T)
```

T = 1 leaves probabilities unchanged. T > 1 moves them toward equal probabilities; T < 1 sharpens them. For illustration, `[0.2, 0.3, 0.5]` with T = 2 becomes approximately `[0.263, 0.322, 0.415]`.

A single global T is fitted by weighted log loss, with predeclared bounds 0.25–4. This is temperature scaling applied to log probabilities. It cannot independently correct every category's bias. Check `fold_parameters.json` for repeated boundary values, which indicate the chosen bounds are active.

### Climatology blend example

```text
q = (1 - lambda) * p_smoothed + lambda * p_climatology
```

If lambda = 0.5, forecast `[0.2, 0.3, 0.5]` and climatology `[1/3, 1/3, 1/3]` give `[0.267, 0.317, 0.417]`. Actual climatology is calculated from training observations; it is not forced to exact thirds.

The single global lambda is fitted to minimize weighted RPS, constrained to 0–1. Lambda = 0 retains the smoothed forecast; lambda = 1 uses climatology. Temperature and Dirichlet use log loss for fitting; the blend uses RPS. All candidates are ranked by the same out-of-sample RPS.

## 3. Two-level cross-fitting, step by step

Example: the outer validation year is 2000.

1. Remove 2000 completely from all fitting. The outer training set contains the other 23 years from 1993–2016.
2. Inside those 23 years, hold out another year, for example 1999.
3. Fit rainfall correction, observational eligibility, and tercile thresholds on the remaining 22 years. Neither 1999 nor 2000 contributes.
4. Use that fit to correct the 1999 members and calculate category probabilities. Label the 1999 observation with those same thresholds. Calculate climatology from the 22 training years.
5. Repeat steps 2–4 for all 23 inner years. These records train the probability-calibration maps and blend weight.
6. Refit rainfall correction and thresholds using all 23 outer training years. Apply them to ECMWF 2000 and apply each fitted probability method.
7. Only now use CHIRPS 2000 to score the forecasts. The verification label uses the thresholds from step 6.
8. Repeat for every outer year from 1993 through 2016.

This requires 24 outer folds, 552 inner preprocessing fits and 48 Dirichlet fits. It prints progress after each outer fold. Runtime depends on your machine; the first progress line can take time. No cached OOF file from the earlier development fit is reused because those rows can contain information from the outer validation year in their preprocessing.

The workflow is nested cross-fitting for each fixed candidate. It does NOT add a third validation layer around selection of the winning method. Consequently, the winner's reported score is an optimistic estimate of the selected procedure's performance. Do not call it an unbiased final skill estimate.

## 4. Where masking belongs

The processing order remains:

1. Form native-grid seasonal rainfall totals.
2. Regrid onto the common grid.
3. Align/apply any separately supplied physical land–ocean mask on that grid.
4. Fit rainfall and probability calibration using training-only observation eligibility.
5. Restrict the verification scores to Ethiopia using `region_mask`.

`ethiopia_common.nc` is a country mask, not a physical land–ocean or lake mask. Here it restricts evaluation only. Global probability calibration retains the same geographical training domain as your existing model so this experiment isolates calibration-method changes.

If you previously supplied a real common-grid land mask during calibration, pass that same mask here:

```bat
python scripts\compare_calibration.py --config config\project.json --region-mask data\masks\ethiopia_common.nc --land-mask data\masks\land_common.nc
```

Use that command only if this separate file actually exists and contains binary `land_mask(lat,lon)`. It is not provided in this update. Do not pass the Ethiopia country mask as `--land-mask`.

## 5. Outputs

Results are saved under:

```text
outputs\model_comparison\init05_JJAS\training_only\
```

| File | Contents |
|---|---|
| `comparison_summary.json` | Ranked methods, mean scores, annual scores, region provenance, member counts and uncertainty caveats |
| `comparison_table.csv` | Compact ranking readable in Excel or VS Code |
| `fold_parameters.json` | T, lambda and both Dirichlet maps for each outer fold |
| `cross_validated_probabilities.nc` | Seven probability fields, observed categories, fold-specific thresholds, and region mask |

Probability fields in the NetCDF cover the eligible common domain; use its `region_mask` when mapping Ethiopia. Observed category codes are -1 missing, 0 below, 1 near, 2 above. Thresholds are in mm. The existing development and final output folders are not modified.

If the output folder already exists, the script stops to avoid overwriting it. To rerun, rename the old `training_only` folder first. There is no resume feature; an interrupted run must restart.

## 6. How to interpret the comparison

- RPS and log loss: lower is better. RPS uses the unnormalized sum over the two cumulative category boundaries.
- RPSS: above zero beats the matching training-climatology reference.
- Brier scores and Brier skill scores are reported in below/near/above order.
- `rps_difference_vs_original`: negative favors that alternative over the original Dirichlet method.
- `mean_max_probability`: larger means more confident forecasts, not necessarily better forecasts. Judge confidence alongside proper scores.
- Within each year, scores are area-weighted across common valid Ethiopia cells. Years receive equal weight.
- The paired-year bootstrap resamples the 24 outer-year scores 2,000 times with a fixed seed. Its range is descriptive: it does not refit models, account for temporal dependence, or fully capture uncertainty from overlapping training sets. It is not a selection-adjusted significance test.

Do not replace the current model solely because one candidate wins by a tiny margin. Check whether gains recur across years and categories, whether log loss worsens, and whether the difference range overlaps zero. If climatology wins, report that result rather than forcing an ECMWF-based winner.

CRPS and rainfall-error metrics are not repeated here: all seven candidates use the same underlying rainfall correction, and categorical calibration does not define a newly corrected continuous rainfall ensemble. Existing CRPS results remain the relevant continuous assessment. ROC and reliability can be recomputed from the saved probability fields after choosing which candidates warrant closer review.

## 7. What to send back and what follows

Upload:

```text
comparison_summary.json
comparison_table.csv
fold_parameters.json
```

The large NetCDF is optional unless we need maps or reliability diagnostics. We will examine the method ranking and annual consistency, then freeze one candidate for an exploratory 2017–2025 comparison with the existing baseline. Those years have already informed our discussion, so they are no longer a pristine, untouched test set for this revised workflow.

Only after that review should we refit the chosen method on 1993–2025 and generate its 2026 probabilities using all 51 members. The final fit must reproduce the selected smoothing and calibration procedure exactly. Because JJAS 2026 has elapsed, this is a reconstruction of the May-initialized forecast unless it was issued earlier. No 2026 observations are available in your current CHIRPS archive.

## Scientific references

- Kull et al. (2019), *Beyond temperature scaling: Obtaining well-calibrated multi-class probabilities with Dirichlet calibration*. https://proceedings.neurips.cc/paper/2019/hash/8ca01ea920679a0fe3728441494041b9-Abstract.html
- Guo et al. (2017), *On Calibration of Modern Neural Networks*. https://proceedings.mlr.press/v70/guo17a.html

These introduce the general calibration approaches. The rainfall preprocessing, fixed penalties, geographical weighting, smoothing strength and validation design above are choices specific to this project, not claims that these papers validate ECMWF seasonal rainfall skill.
