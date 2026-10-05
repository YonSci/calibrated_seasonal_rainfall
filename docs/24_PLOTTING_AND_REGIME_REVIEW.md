# Step 24 — Rounded display masks and rainfall-regime review

## Run the plotting update

Extract the ZIP into D:\calibrated_seasonal_rainfall, merging scripts/data/docs. It contains a replacement plot_smooth_forecasts.py and compatible helpers, plus the existing Ethiopia boundary.

```bat
cd /d D:\calibrated_seasonal_rainfall
.venv\Scripts\activate
python scripts\plot_smooth_forecasts.py --targets JJAS --regenerate
```

All five targets:

```bat
python scripts\plot_smooth_forecasts.py --regenerate
```

New output: outputs\forecast_maps_contours\init05_TARGET\2026\.
The supplied example_JJAS folder contains the actual regenerated JJAS figures from your uploaded NetCDF. No regime mask has been added to the forecast in this update.

### Display method

The previous version preserved nearest-cell binary eligibility boundaries, producing rectangular gray patches. This version draws rounded boundaries from the zero contour of interpolated signed distances to the valid/invalid cells, on a 16x display mesh. It also uses a mild, mask-normalized Gaussian display filter with sigma 0.6 native cells before bilinear interpolation and filled contours. Probabilities are processed together, normalized and then classified; categorical codes are never averaged.

This is cartographic generalization, not improved forecast resolution. It changes the appearance and can move a displayed category boundary, reduce isolated peaks or change which weak signals are visible. Original-grid fields and numerical summaries are unchanged. All original cell-center validity labels were checked to be preserved. The edges between cell centers are only an approximate depiction of the mask, not newly inferred coverage. Excluded cells remain excluded at their centers; small gray areas are not deleted or filled. Some geometric structure can remain because the source data and masks are gridded.

To use rounded masks and interpolation without the Gaussian display filter:

```bat
python scripts\plot_smooth_forecasts.py --display-sigma 0 --regenerate
```

The default is 0.6; permitted range is 0–1 native cells. Do not use rendered images for extracting exact probabilities or calculating skill. Use the original NetCDF. The Gaussian kernel can mix nearby values across narrow excluded areas for display only; it is not a terrain-aware interpolator or a physical spatial model.

Validation: generated all three JJAS PNG/PDF products; checked original-grid probabilities against source-derived values; checked every original mask cell-center label after display resampling; inspected percentage-anomaly output. No calibration parameters changed. Existing pyshp and pyproj installations resolve the prior missing dependency.

## What Fourier regimes can and cannot improve

Dunning et al. (2016), section 2.2.1, uses the relative amplitudes of annual and semiannual harmonics to distinguish annual-dominant and biannual-dominant rainfall cycles. It also warns about misleading ratios in dry areas. This is seasonality analysis, not itself a rainfall bias-correction or probability-calibration algorithm.

For daily climatology Q(d), the first two amplitudes can be calculated as:

A_k = (2/N) sum_d Q(d) cos(2*pi*k*d/N)
B_k = (2/N) sum_d Q(d) sin(2*pi*k*d/N)
C_k = sqrt(A_k^2 + B_k^2)
r_H = C_2 / C_1

When C1 is tiny, the ratio is unstable even if C2 is small. Retain C1 and C2, total rainfall, harmonic phase, cycle strength and peak diagnostics, rather than using the ratio alone. Treat undefined/ambiguous ratios explicitly. A high ratio is not a forecast-skill measure. The exact equality rH=1 needs a documented convention.

| Use | Value | Limitation |
|---|---|---|
| Seasonal relevance mask | Separates a main-rainy-season product from dry-season locations | Does not improve predictions at retained locations by itself |
| Regime-stratified verification | Shows where the current calibration succeeds/fails | Smaller samples and changing coverage require careful comparison |
| Regime-specific probability mapping | Can pool places with related calibration errors | Improvement is a hypothesis; overfitting remains possible |
| Rainfall amount correction | Regimes can guide diagnostics or regularization | Current correction already fits location-specific mean/variance; replacing it with one regime mean loses local detail |
| Onset/cessation domain | Avoids applying a season-timing algorithm where the season is not identifiable | The same exclusion is not automatically appropriate for seasonal rainfall totals |

A climatologically dry season can still have valid rainfall-amount or exceedance forecasts. Do not remove every such location from all products. For terciles, explicitly assess zero/tied thresholds and sample variability. Preserve an all-domain research product alongside any operational rainy-season-only view. Do not use an onset-detection-rate requirement as a mandatory rainfall-total criterion.

## Audit of the supplied repository

Inspected repository commit: 07879e42290dd5efd1d75f137961378ca7e39ea2.
Reviewed docs/scientific_masking/WALKTHROUGH.md and scripts/compute_seasonal_masks.py. This is a targeted source review; the external project's full pipeline and claimed station validation were not executed.

1. **Leap-year bug.** The code uses dayofyear <= 365. In leap years it retains February 29, shifts calendar alignment from March onward, and drops December 31. Build climatology by month-day, explicitly remove February 29 for the 365-day harmonic cycle, and keep actual-calendar seasonal sums separate. Do not merely remove February 29 and continue grouping by the original dayofyear.
2. **Hybrid rules, not ratio-only classification.** The code uses rH >= 0.70 for one lowland criterion and >=0.38 for one highland criterion, plus rainfall totals, ratios, peak timing and explicit longitude/latitude boundaries. That is an Ethiopia-specific heuristic extension. It must not be presented as the unmodified Dunning classification.
3. **Documentation mismatches.** The walkthrough mentions an 80 mm Belg threshold, while the inspected mask code uses 50 mm. Claimed two-peak separation of at least 60 days is not explicitly enforced in that script. Its highland classification can pass from a ratio and geographical test without a verified second spring peak.
4. **Gu window mismatch.** The mask labeled Gu/MAM uses p_fmam (February–May) and dr_fmam. Compute March–May totals and the appropriate diagnostics for a MAM product.
5. **Missingness/undefined ratios.** np.mean is used without a completeness policy. A nonfinite or very small C1 yields rH=0 through np.where. Unclassified inside-country cells then fall into residual Regime 1. Missing or ambiguous data need separate codes and must not silently become Western Unimodal.
6. **Detection-rate fallback.** Missing onset products lead to arrays of ones, which is effectively a 100% detection rate. Missing evidence should remain unavailable, not automatically pass the filter. For rainfall totals, remove this onset-specific requirement rather than manufacturing detection rates.
7. **Morphological cleanup changes classification.** Small clusters removed from other regimes are subsequently absorbed into residual Regime 1. Keep raw and cleaned maps and a changed-cell ledger; do not treat cosmetic cleanup as physical validation.
8. **JJAS mask export omission.** compute_ethiopia_masks returns mask_kiremt_jjas, but the inspected main() exports mask_kiremt (Regime 2 onset mask) and omits mask_kiremt_jjas from both individual NetCDF and the combined NPZ. Check other export scripts before assuming the existing downloadable mask is the intended rainfall domain.
9. **Area and boundary claims.** Pixel fractions are labeled land-area percentages. Use spherical grid-cell areas (and optionally boundary fractions) for geographic area statistics. Country containment is not a physical land–ocean/lake mask. The other project's 1485 cells need alignment against this project's 1484-cell region mask; equal dimensions do not prove matching masks.
10. **Validation traceability.** The walkthrough's station examples have differing values between table and profile sections (e.g. Gambella's ratio), and Gondar appears in different regime descriptions. Its '20/20' statement should be backed by station source, observation period, data-QC method, matching coordinates and independent labels before being treated as demonstrated validation. CHIRPS contains station information, so gauge comparisons also need an independence assessment.

These findings do not invalidate the concept; they mean direct transplantation would import avoidable errors and undocumented choices. No changes were pushed to the external repository.

## Proposed integration into this project

### Stage A — Correct and audit observed climatology

Use the complete daily CHIRPS archive, not ECMWF forecasts, JJAS totals alone or 2026 outcomes. Compute a consistent 365-day climatological cycle, actual-calendar monthly/seasonal means, C1/C2/ratio/phase, peak prominence and separation, and explicit missing-data flags. Check that summing climatological months reconstructs the climatological annual total under the chosen leap-day convention. Export both raw harmonic classes and refined classes, all criteria and a refinement reason per cell. Keep uncertain transition cells rather than forcing four labels everywhere.

For final descriptive 2026 products, 1993–2025 is the established available reference. For cross-validation, derive data-dependent masks and regimes only from each training fold, or use a genuinely pre-specified independent baseline. Do not use a full 1993–2025 mask to claim an untouched 2017–2025 holdout test. Those years have already been inspected in model comparisons, so further selection on them is exploratory.

### Stage B — Separate masks

Maintain separate country, observational-validity, physical-land (if available), rainfall-amount eligibility, probability eligibility, seasonal-relevance, and onset-detection masks. A new JJAS rainy-season view may use candidate thresholds such as seasonal total >=120 mm and annual share >=20%, but those are project choices to audit and sensitivity-test, not universal Dunning thresholds. Do not impose the same four-month threshold on June, July, August and September separately.

### Stage C — Diagnose the current baseline by regime

Keep current location-specific amount correction and the selected shared blend. Report CRPS/bias/RMSE for amounts and RPS, category Brier scores and log loss for probabilities within each regime. Use identical valid cell/year support for candidate comparisons and report coverage separately. Removing difficult cells is not a calibration gain.

### Stage D — Test partial pooling of blend weights

The next candidate should be a small number of regime-specific blend weights, shrunk toward the existing shared weight, before fitting a full Dirichlet map per regime or per cell:

p_cal(x) = (1-lambda_g) * p_smoothed(x) + lambda_g * p_climatology(x)

Here g is the observed rainfall regime, while climatology and tercile thresholds remain local to x. Fit lambda_g on out-of-fold training predictions with a penalty such as gamma*(lambda_g-lambda_shared)^2; constrain weights to [0,1]. Use the shared value for insufficient-support or ambiguous regimes. Select gamma within inner training folds, not against the evaluation year. Evaluate amounts separately because changing categorical probabilities does not modify corrected rainfall members.

Example only: if a regime consistently shows excessive confidence, its fitted climatology weight might be higher; if another has reliable signal, it might be lower. These are hypotheses, not estimated results.

### Stage E — Test amount refinements only if diagnostics justify them

Current per-cell mean/variance correction already accounts for local climatology. Regime structure may help stabilize parameters or motivate a nonnegative distributional method in dry areas, but neither Fourier amplitude nor hard masking fixes clipping by itself. Any new method must improve held-out continuous scores, not merely produce attractive maps.

### Stage F — Adoption

Use outer held-out years with inner tuning, year-block uncertainty estimates and coverage reporting. Compare the baseline and candidates on the same support. Keep rainfall-regime calibration experimental until there is reproducible evidence of benefit; retain the frozen current 2026 product as the baseline. Subsequent independent years provide prospective validation.

## Sources

Dunning, Black and Allan (2016), The onset and cessation of seasonal rainfall over Africa, JGR Atmospheres, DOI 10.1002/2016JD025428:
https://agupubs.onlinelibrary.wiley.com/doi/full/10.1002/2016JD025428

User repository walkthrough:
https://github.com/YonSci/-Operational-Multi-Model-Seasonal-Forecasting-System/blob/07879e42290dd5efd1d75f137961378ca7e39ea2/docs/scientific_masking/WALKTHROUGH.md

Inspected implementation:
https://github.com/YonSci/-Operational-Multi-Model-Seasonal-Forecasting-System/blob/07879e42290dd5efd1d75f137961378ca7e39ea2/scripts/compute_seasonal_masks.py
