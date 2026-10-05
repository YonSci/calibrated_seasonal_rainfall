# 04 — Full scientific workflow after preparation

> **Status update (2026-10-05):** stages 1–8 are implemented. The final 2026 product uses a shared climatology blend, not Dirichlet. See [36_PROJECT_STATUS_REVIEW.md](36_PROJECT_STATUS_REVIEW.md). The original design text below is kept for reference.

**Status: design specification.** These calibration stages are not implemented in version 0.1.0. Do not expect a fit or forecast command until this stage is developed against the verified data. Never treat native-grid preparation outputs as calibrated forecasts.

## 1. Align grids and define support

ECMWF is 1 degree; CHIRPS is 0.25 degree. Verify source/target cell bounds. Their centre-coordinate extents differ, but inferred outer cell edges may agree. Do not extrapolate implicitly or trim valid edge coverage solely from centre extents. Select and document conservative remapping where feasible, or a documented simpler alternative. Establish a common Ethiopia/domain mask and maintain NaNs. Remapping to 0.25 degrees does not create independent 0.25-degree dynamical forecast information.

## 2. Freeze development/test roles

- Development: 1993–2016 (24 seasons).
- Independent test: 2017–2025 (9 seasons).
- Forecast application: 2026.

This design assumes the stated model-system compatibility is confirmed. Tune only inside development data. After independent evaluation, lock the design before refitting through 2025. Changes made after examining test results require acknowledging that the test was used for development.

## 3. Fit the shared rainfall correction

Member indices are exchangeable; do not pair 25 historical members with 51 operational members. This project proposes a shared correction at each pixel, applied to each member, explicitly adapting the original member-specific code.

With equal weight per year:

`mu_H = mean_over_years(mean_over_members(H))`

`var_H = mean_over_years(mean_over_members(H**2)) - mu_H**2`

`r = clip(sigma_O / sigma_H, 0.5, 2.0)`

`corrected = max(0, mu_O + r * (raw - mu_H))`

Implement finite-value handling, minimum year/member coverage, cancellation protection in variance, and a documented small-variance policy. Historical observations have one value per year. Pooled model moments include member variation. Do not mistake these for variance of the ensemble mean. No beta member-stabilization term is needed in this shared-parameter adaptation. Validate the chosen method; bounds and zero clipping prevent exact moment matching.

## 4. Estimate observed terciles inside the training fold

Calculate q1 and q2 from training CHIRPS seasonal totals only. Categories are below `<q1`, near `>=q1 and <=q2`, and above `>q2`. Flag degenerate thresholds and insufficient sample support. Do not classify missing rainfall as near normal.

## 5. Generate out-of-fold training probabilities

For each development year, exclude that year from all moment estimation and tercile estimation; transform its model ensemble and categorize its observed outcome using those training-fold thresholds. Count valid members only. Save fold/year IDs, probabilities, labels, masks, and training-year provenance. Each development-year probability used to train Dirichlet must be produced without its own observations influencing the upstream fit.

## 6. Fit regularized Dirichlet

Use `softmax(A @ log(p) + b)` with identity initialization. Penalize off-diagonal entries toward zero, diagonal entries toward one, and biases toward zero. Candidate baseline penalties are 0.01, 0.001, and 0.001. These are candidates, not validated optimal settings. Clip zeros with a documented numerical epsilon and retain the distinction between numerical clipping and finite-ensemble probability smoothing.

Sample/weight years fairly and account for spatial duplication. One shared domain mapping is the initial design. Region-specific mappings require enough data and validation. Save A, b, regularization, class order, training years, season, initialization, domain, sample weighting, member-count information, and numerical settings.

### Prevent tuning leakage

For each validation split used to tune penalties, construct the Dirichlet training examples entirely within that split's training years. This may require inner cross-fitting of rainfall corrections. Do not reuse a global out-of-fold table if its rows were generated with moments or thresholds that included the current validation years. Whole-year splits are required; random pixel splits cannot establish future-season performance.

## 7. Evaluate on 2017–2025

Compare climatology, raw probabilities, amount-corrected probabilities, and two-stage probabilities. Report mean-rainfall bias/MAE/RMSE, category Brier scores, RPS, log loss, reliability and sharpness. Estimate uncertainty by resampling entire years; neighbouring pixels are correlated. Evaluate regional performance. A dominant-category map alone is not validation.

Test actual 51-member probabilities and repeated 25-member subsamples as an ensemble-size diagnostic. These repeated subsamples are not independent seasons. Use the member count actually present, and make any smoothing strategy part of the frozen validation design.

## 8. Refit and apply to 2026

After fixing the design, rebuild out-of-fold probabilities over eligible 1993–2025 seasons, fit the final Dirichlet map, fit the final amount correction and thresholds on all eligible history, and transform the 2026 ensemble. Weight historical years equally despite 25/51-member differences. Consider ensemble-size sensitivity when transferring the mixed-size probability mapping to 51-member forecasts.

Save both corrected rainfall members/mean and recalibrated probabilities. Dirichlet does not modify corrected rainfall amounts again. Use 1993–2025 reference labels if that is the final baseline, and retain the separate reference used during independent testing. CHIRPS through 2025 cannot verify 2026.

## 9. Final products

- Corrected seasonal ensemble and mean in mm.
- Observed q1/q2 and valid-support mask.
- Probabilities before/after Dirichlet, summing to one where valid.
- Dominant category and maximum probability.
- Validation tables, reliability figures, regional reports.
- Reproducible model/configuration artifacts.
- Map metadata generated from actual inputs, not fixed year/member/resolution labels.

## 10. Future extension

Daily onset/cessation, daily rainfall bias correction, SPBI/NDVI blending, region-specific models, and cross-year seasons are separate tasks. Seasonal-total affine correction does not by itself correct the daily rainfall sequence needed for onset/cessation.
