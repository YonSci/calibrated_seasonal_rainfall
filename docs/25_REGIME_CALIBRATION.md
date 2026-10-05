# Step 25 — Rainfall regimes and a regularized probability-blend experiment

This update adds corrected CHIRPS climatology, explicit rainfall regimes, separate mask layers, regime-stratified verification, and a small regime-specific probability-calibration experiment. It uses the existing location-specific rainfall-amount correction as the baseline. It does not replace your 2026 forecast, change existing calibrated rainfall amounts, modify the GitHub repository, or turn display smoothing into downscaling.

## 1. Install into the existing project

Extract this ZIP into `D:\calibrated_seasonal_rainfall`, merging its `scripts`, `tests`, and `docs` folders with your existing folders. These are new script names. The update depends on the existing `common.py`, `output_runs.py`, `calibration_core.py`, `compare_calibration.py`, `run_calibration.py`, `verification_core.py`, and (for one unit test) `local_blend.py` from earlier updates.

In VS Code's **CMD** terminal:

```bat
cd /d D:\calibrated_seasonal_rainfall
.venv\Scripts\activate
python -m pip install numpy scipy xarray netCDF4 matplotlib
python -m unittest discover -s tests -p test_regime_core.py -v
```

You do not need to rerun seasonal preparation, regridding, or the previous 2026 forecast. Existing outputs stay in place. Run one experiment at a time; avoid simultaneous runs targeting the same output directory.

## 2. Prepare observed climatology and masks once

```bat
python scripts\prepare_regimes.py --config config\project.json --region-mask data\masks\ethiopia_common.nc
```

The script reads the daily file identified by `chirps_file` and the variable named by `chirps_variable` in your configuration. It expects daily CHIRPS in mm/day (or mm amounts per daily time step), complete timestamps for 1993–2025, and the existing common grid. It sorts latitude/longitude; it does not silently interpolate mismatched coordinates. Coordinate names `latitude`/`longitude` are accepted and renamed. Other dimensions, calendars, or unit conventions need explicit inspection rather than guessed conversion.

It reads one calendar year at a time, checks dates and nonnegative finite values, and retains missing cells as missing. On your 48 × 60 grid the daily cache has about 35 million values; expect several hundred MB of working memory, potentially around 1 GB while preparing or evaluating. Runtime depends on disk and CPU. Progress messages identify completed years.

Outputs:

```text
data\processed\regime_climatology\
    chirps_calendar_cache.nc
    training_1993_2016.nc
    descriptive_1993_2025.nc
    preparation_report.json
    regime_diagnostics.png
```

The PNG uses the full 1993–2025 descriptive baseline and intentionally shows grid-cell classifications. It is a scientific diagnostic, not a newly smoothed forecast map. Your existing smooth forecast plotting scripts continue separately.

**Leap-day policy:** the 365-day harmonic cycle removes February 29 by calendar month/day. March 1 stays aligned with March 1; December 31 stays included. Actual monthly totals retain February 29. Consequently, the sum of the twelve actual-calendar monthly climatologies exactly defines `annual_mean_mm`; it can differ from `annual_noleap_mean_mm` by mean leap-day rainfall. This difference is expected, not a reconstruction error.

Strict training-subset completeness is used: a cell with a missing daily value in a training year cannot receive a valid annual climatology/regime for that fit. A missing value in an excluded year does not invalidate the training subset. Seasonal rainfall and probability eligibility remain separately available, so missing annual-regime information does not automatically remove an otherwise valid JJAS forecast.

If you change the daily source, the country mask, or the preparation code, rebuild with:

```bat
python scripts\prepare_regimes.py --config config\project.json --region-mask data\masks\ethiopia_common.nc --regenerate
```

`--regenerate` stages the new output and preserves the previous directory as a dated backup after success. Backups use disk space; review them manually before deleting anything.

## 3. What the regimes mean

For the training-only mean daily cycle Q(d), d = 0,…,364:

```text
A_k = (2 / 365) sum Q(d) cos(2 pi k d / 365)
B_k = (2 / 365) sum Q(d) sin(2 pi k d / 365)
C_k = sqrt(A_k² + B_k²)
rH  = C2 / C1
```

`C1` and `C2` are in mm/day. The raw harmonic class distinguishes annual-dominant C1 > C2, semiannual-dominant C2 > C1, near equality, and weak/unavailable cycles. A ratio is exported only when C1 > 0.0001 mm/day. A strong semiannual cycle with negligible C1 can still be recognized from C2 directly; its undefined ratio is not set to zero.

The Dunning et al. (2016) harmonic approach motivates this diagnostic. The additional classifications and thresholds below are **fixed experimental project rules**, not the unmodified Dunning method, official EMI zones, or verified station-based classes.

| Regime code | Meaning | Fixed classification rule |
|---|---|---|
| -2 | Outside country | Existing country mask is zero |
| -1 | Missing observations | Incomplete training climatology |
| 0 | Arid | Actual-calendar annual mean below 200 mm |
| 1 | Annual summer | Annual-dominant cycle; primary peak in June–September; not assigned code 2 |
| 2 | Spring and summer | Strong cycle with two accepted peaks, one March–May and one June–September |
| 3 | Spring and autumn | Semiannual-dominant cycle with accepted peaks in March–May and October–November |
| 4 | Other or uncertain | Complete observations but other timing, weak seasonality, unresolved peaks, or near-equal harmonics not satisfying a refinement rule |

The peak finder uses a circular Gaussian-smoothed climatological cycle, sigma 10 days, to suppress daily sampling noise. Accepted peaks require prominence at least 15% of the smoothed cycle's range, minimum circular separation 60 days, and secondary peak height at least 30% of the primary. A strong cycle requires max(C1,C2) > max(0.0001 mm/day, 5% of mean daily rain). Harmonic amplitudes are computed from the **unsmoothed** climatological cycle.

Priority is: missing/outside first; aridity overrides supported timing classes; spring–summer before spring–autumn; annual summer next; otherwise uncertain. No longitude/latitude boundary forces an Ethiopian region label. No isolated cluster is reassigned for appearance. Code 2 does not assert a known highland region or station validation. Diagnostics export amplitudes, ratio validity, phase, peak days, prominence, separation, and class flags for inspection. `refinement_reason` mirrors the final class, except reason 5 identifies weak cycles within uncertain regime 4; reason 4 identifies other timing or unresolved peaks.

Before adopting these labels, inspect representative climatological cycles, stability between training folds, and independent station information where available. Strong harmonic ratios alone do not prove two agriculturally meaningful seasons.

## 4. Separate masks and the correct place to apply them

**All analysis masks are aligned to the common grid, after regridding.** A physical source-grid mask used by a regridding method is a separate issue; this update does not reconstruct or change past remapping.

| Layer | Purpose | Effect in this update |
|---|---|---|
| `region_mask` | Ethiopia study boundary | Restricts regime-specific weight fitting and evaluation |
| Optional `land_mask` | Physical land/water distinction | Passed to existing amount/probability preprocessing if supplied |
| `observation_valid` | Complete training annual cycle | Permits regime diagnosis; failure falls back to shared calibration |
| `amount_eligible` | Existing rainfall correction requirements | Keeps existing local amount eligibility |
| `probability_eligible` | Existing tercile thresholds/variability requirements | Keeps existing probability eligibility |
| `JJAS_relevant`, monthly equivalents | Candidate rainy-season view | Additional verification subset only; does not remove cells from main fit or main score |
| Onset-detection evidence | Validity of onset/cessation estimates | **Not computed or assumed.** No invented 100% detection rate; not required for rainfall totals |

A country mask is not a physical land–ocean/lake mask. If you have a separate verified common-grid binary `land_mask`, pass `--land-mask data\masks\land_common.nc` to the evaluation commands. Without it, the report records that no physical land mask was supplied. In the evaluation NetCDF a scalar physical-land value of -1 means unavailable, not all-water.

Candidate seasonal relevance: JJAS mean >=120 mm AND annual share >=20%. Each single month uses >=30 mm AND >=5%, rather than incorrectly applying the four-month threshold to every month. These are transparent initial project choices, not established universal thresholds. They do not use onset-detection rates and do not force an arid/regime class to pass or fail. Review threshold sensitivity before operational use. All-country and complementary valid non-relevant scores remain visible, preventing a restricted-domain score from being mistaken for a calibration improvement.

## 5. Run JJAS training evaluation first

```bat
python scripts\run_regime_calibration.py --config config\project.json --targets JJAS --mode training --region-mask data\masks\ethiopia_common.nc
```

For each outer test year in 1993–2016:

1. Exclude that year. Its rainfall never enters its climatology, regime classification, amount correction, tercile thresholds, or blend fit.
2. Within the remaining 23 years, leave out each inner target in turn. Compute amount correction, thresholds, probabilities, and regimes using the other 22 years.
3. Fit probability-blend weights to these inner out-of-fold predictions and observed categories.
4. Refit preprocessing and regime diagnosis on the outer 23 training years; predict the outer excluded year.
5. Compare all probability methods on exactly the same valid cells for that year. Repeat for all 24 outer years.

The daily cache contains all years for convenience, but each diagnostic explicitly selects its training subset. The full-baseline descriptive map is **never** used to define evaluation regimes. Cross-fitting the regime labels as well as the probabilities prevents target rainfall from deciding its own group.

This is a substantial nested computation: 24 outer folds × 23 inner records, plus outer fits. It can take longer than plotting. Progress appears after each outer year. Regime diagnostics are cached within the process and reused across requested targets.

## 6. The probability method being tested

This candidate is a **regularized regime-specific linear probability pool**, not a new Dirichlet calibration model:

```text
p_calibrated = (1 - lambda_g) p_smoothed + lambda_g p_climatology
```

A larger lambda means more weight on the training climatology. Existing member-count smoothing remains `(M p + 0.5)/(M + 1.5)` with the actual M; 51-member operational ensembles are retained in full.

Five methods are compared:

1. Training climatological probabilities.
2. Corrected-ensemble probabilities with count smoothing.
3. Existing shared probability blend.
4. Independent blend weight per supported regime (0–3).
5. Regime blend weight regularized toward the shared weight.

The shared fit retains the original full common-domain fitting policy, so the baseline procedure is reproduced. Regime adjustments use only cells inside the Ethiopia mask. Missing, uncertain, outside-country, or unsupported groups use the shared weight. This preserves predictions rather than deleting difficult cells.

With d = first two cumulative values of (p_climatology - p_smoothed), and e = first two cumulative values of (p_smoothed - observed one-hot category), define A = mean(||d||²) and B = mean(-e·d). Means are area weighted within each contributing year, then equally weighted across years.

```text
lambda_independent = clip(B/A, 0, 1)
lambda_regularized = clip((B + gamma lambda_shared)/(A + gamma), 0, 1)
```

The second expression minimizes mean RPS plus `gamma * (lambda - lambda_shared)²`. Gamma is fixed at 0.05; it is not selected on evaluation results. At least 20 inner years with at least 10 eligible cells each are required for a group. Otherwise it falls back to shared. Grid cells are correlated; this cell threshold is only a coverage gate, not a claim of 10 independent samples.

Example: shared lambda = 0.60, group A = 0.02 and B = 0.016 gives independent lambda = 0.80, and regularized lambda = (0.016 + 0.05×0.60)/(0.02 + 0.05) ≈ 0.657. Regularization permits a group adjustment but limits an unstable move from 0.60 to 0.80.

No new Dirichlet matrices are fitted in this update. This tests a small, interpretable change before considering many additional parameters. Existing location-specific mean/variance rainfall correction remains unchanged; its regime diagnostics determine whether a future amount-method change is warranted.

## 7. Monthly and operational-period evaluations

Once JJAS succeeds, run the months using your already prepared common-grid monthly files:

```bat
python scripts\run_regime_calibration.py --config config\project.json --targets Jun Jul Aug Sep --mode training --region-mask data\masks\ethiopia_common.nc
```

The runner derives each monthly season definition from the main configuration. It does not rerun monthly preparation or require overwriting `monthly_*.json`.

Then run 2017–2025 evaluations with fits frozen on 1993–2016:

```bat
python scripts\run_regime_calibration.py --config config\project.json --targets JJAS Jun Jul Aug Sep --mode operational --region-mask data\masks\ethiopia_common.nc
```

These operational years have already been inspected during earlier comparisons, so this is an **exploratory operational-period test**, not a pristine holdout. The training archive has 25 members; the operational archive has 51. The current code preserves all members and count smoothing, but that alone does not eliminate distribution shifts between archives. Retain the earlier member-count sensitivity evidence when interpreting results.

To repeat a completed evaluation, add `--regenerate`:

```bat
python scripts\run_regime_calibration.py --config config\project.json --targets JJAS --mode training --region-mask data\masks\ethiopia_common.nc --regenerate
```

## 8. Outputs and interpretation

For each target/mode:

```text
outputs\regime_calibration\init05_JJAS\training\
    regime_comparison_summary.json
    regime_probabilities_and_weights.nc
    regime_spatial_scores.nc
    annual_regime_rps.png
```

The summary contains all-country, seasonal-relevance, complementary non-relevance, and individual-regime results. Empty domains are recorded with no scores, rather than zeros. Each domain lists evaluated years; never compare averages for different sets of years without checking support.

Probability scores: RPS (sum of the two cumulative squared errors), RPSS, category Brier scores and BSS, and log loss. Amount scores: empirical ensemble CRPS/CRPSS, ensemble-mean bias and RMSE, for raw, corrected, and observed-climatology ensembles. Amount methods share their own identical evaluation support, which can differ from tercile support. RMSE is calculated from aggregated MSE; skill scores use ratios of aggregated losses, not averages of annual skill ratios.

Each annual spatial average uses spherical grid-cell areas, followed by equal weighting of years. Coverage is reported as cell count and fraction of the existing binary-country-mask area. Boundary fractions are not estimated. Regime membership can change across folds; stratified results describe the classification procedure, not permanently fixed polygons.

`rps_difference_vs_shared < 0` favors the candidate. The 95% range uses 5,000 paired whole-year score resamples. It describes uncertainty in these fixed-fit scores, without correcting for serial dependence, overlapping training sets, repeated model selection, or multiple targets. It is not a guarantee of future improvement.

The NetCDF includes annual probabilities, weights, observed categories, tercile thresholds, fold-specific regimes, and each support/eligibility mask. This allows the earlier reliability, ROC and histogram workflows to be extended later if the candidate is competitive; this update does not claim to have regenerated those diagnostics. Diagnostic plots are not used to estimate numerical skill.

## 9. Adoption decision after reviewing results

Keep the current shared 2026 forecast as the operational product until real-data evidence is reviewed. Look for:

- lower all-country RPS on identical support, with useful paired-year evidence;
- no unacceptable Brier/log-loss degradation or reliance on one anomalous year;
- adequate group support, sensible weights, and stable physical classifications;
- broadly consistent training and exploratory operational-period behavior;
- no claimed gain that comes only from a smaller seasonal mask.

Do not choose gamma or thresholds by repeatedly optimizing these same reports and still call the result an independent test. Any new tuning requires another selection layer or fresh evaluation data. Sparse unsupported groups should retain the shared weight. Keep the simpler shared method when gains are small or uncertain.

This release intentionally has no automatic final-refit command. Once results justify a candidate, a separate reviewed update can fit 1993–2025 and generate a parallel 2026 candidate with complete provenance. Your current forecast is not overwritten just because a more complicated method is available.

## 10. Tests and provenance

Run the optional complete isolated synthetic test:

```bat
python tests\smoke_regime_pipeline.py
```

It builds tiny artificial CHIRPS/model files in a temporary directory, exercises preparation, nested training, the 25-to-51 member transition, operational evaluation, NetCDF/report/figure writing, and regeneration backups. It never accesses your real data or output directories. Five unit tests check leap-day alignment, missingness, harmonic amplitudes and circular peaks, regularization/fallback/probability sums, exact shared-baseline weight agreement, and excluded-year cache behavior.

The developer ran these tests with synthetic data. Your complete daily CHIRPS archive and all historical prepared files were not available in this execution environment, so no real Ethiopian regime skill improvement is asserted here. Source hashes and fixed settings are written to the reports.

References:

- Dunning, C. M., Black, E. C. L., and Allan, R. P. (2016), *The onset and cessation of seasonal rainfall over Africa*, JGR Atmospheres, https://doi.org/10.1002/2016JD025428 . Harmonic seasonality diagnosis is distinct from forecast probability calibration.
- Your previously reviewed implementation: https://github.com/YonSci/-Operational-Multi-Model-Seasonal-Forecasting-System/blob/07879e42290dd5efd1d75f137961378ca7e39ea2/scripts/compute_seasonal_masks.py . This update implements the safeguards in Step 24 rather than copying its geographic thresholds or onset-detection fallback.
