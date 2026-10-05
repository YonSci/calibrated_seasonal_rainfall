# Step 31 — Historical blend review and verification by rainfall regime

This update adds three commands to the existing Windows project. It reviews evidence and scores existing forecasts; it does not fit new coefficients or change the selected forecast method.

## 1. Install into the existing project

Extract the ZIP and copy its `scripts`, `docs`, `tests`, and `evidence` folders into:

```text
D:\calibrated_seasonal_rainfall
```

Merge the folders. The Step 31 scripts have new names. Keep the existing Step 30 scripts installed, including `verify2026_common.py`, `verify2026_outputs.py`, `verify2026_math.py`, `prepare_verification_2026.py`, and `verify_frozen_2026.py`.

Open VS Code's **Command Prompt / CMD** terminal:

```bat
cd /d D:\calibrated_seasonal_rainfall
.venv\Scripts\activate
python -c "import numpy, xarray, matplotlib, netCDF4; print('Required packages available')"
```

No additional packages are required beyond the working Step 30 environment.

The archive contains:

| File/folder | Purpose |
|---|---|
| `scripts/review_historical_blending.py` | Review annual historical scores, below-/above-mean years, and fold-specific regimes |
| `scripts/followup_reliability.py` | Optional checks of historical probability NetCDF files and reliability plots |
| `scripts/verify_2026_regimes.py` | Summarize existing 2026 verification by the predefined climate regimes |
| `scripts/complete_verification_2026.py` | Check official monthly availability and, when explicitly requested, run the complete-season workflow |
| `scripts/followup_common.py` | Shared paths, hashing, score summaries and guards |
| `evidence/followup_all_regime_experiments.json` | Copy of your uploaded 20-experiment evidence; the review selects the 10 corrected GitHub experiments |
| `evidence/followup_regime_comparison_and_masks.nc` | Previously generated corrected GitHub classification on your 1993–2025 CHIRPS climatology and country grid |
| `evidence/followup_regime_reconciliation_report.json` | Provenance and reconciliation details for that mask |
| `example_historical_review/` | Results already generated from your actual uploaded historical evidence |

These bundled evidence files have distinct names, so installing the update does not replace your earlier evidence files. The regime NetCDF is approximately 335 kB uncompressed in memory; no large rainfall archive is duplicated.

## 2. Protect the frozen 2026 forecasts

Each command checks the existing Step 30 manifest and all five frozen forecasts:

```text
outputs\verification_2026\frozen_forecasts\freeze_manifest.json
outputs\verification_2026\frozen_forecasts\init05_JJAS\forecast_2026.nc
outputs\verification_2026\frozen_forecasts\init05_Jun\forecast_2026.nc
outputs\verification_2026\frozen_forecasts\init05_Jul\forecast_2026.nc
outputs\verification_2026\frozen_forecasts\init05_Aug\forecast_2026.nc
outputs\verification_2026\frozen_forecasts\init05_Sep\forecast_2026.nc
```

It also compares original forecast bytes when the original paths recorded in the manifest remain available. A second check verifies that the frozen files did not change during execution.

`--regenerate` rebuilds **derived review results**, preserving the previous result folder in a timestamped backup. It does not unlock or replace frozen forecasts. Do not delete the freeze manifest to bypass a mismatch: investigate the changed file and retain the original archive.

## 3. Review the historical evidence

Run:

```bat
python scripts\review_historical_blending.py --targets JJAS Jun Jul Aug Sep --regenerate
```

This uses the evidence included in the update, so it does not require you to upload or regenerate the historical probability files.

### What it does and why

1. Selects only `github_refined_corrected_calendar_v1` experiments. This keeps the rainfall-regime definition consistent with the corrected GitHub implementation previously reconciled with your project.
2. Checks evaluation years and recorded training years. Each 1993–2016 evaluation year must be absent from its training set. All 2017–2025 evaluations must use 1993–2016 fitting data.
3. Reproduces the old equal-year summary from annual scores. It also checks the three-category RPS identity, `RPS = BS_below + BS_above`, and common method support.
4. Compares `smooth`, `shared_blend`, and `climatology` on the same annual/domain support. Here `smooth` means **amount-corrected ensemble probabilities with alpha = 0.5 count smoothing**.
5. Splits years by observed area-mean rainfall anomaly within each domain. This tests whether the blend behaved differently in relatively dry and wet years.
6. Repeats the review for each saved regime and seasonal relevance domain. Historical regime maps were estimated from each training fold; a full 1993–2025 mask is never imposed on past evaluation years.
7. Writes annual score tables, an annual-difference plot, JSON and Markdown reports. No winner is automatically adopted.

The dry/wet split is precisely:

```text
observed area-mean anomaly = - climatology bias
below_mean: anomaly < -0.000001 mm
above_mean: anomaly > +0.000001 mm
at_mean: numerical equality within that tolerance
```

The climatology bias is the training-climatology mean minus observed rainfall, calculated on the amount-evaluation support. Therefore its negative recovers the observed anomaly without refitting.

**These groups are not tercile labels, official drought classifications, or categories available at forecast issuance.** They are retrospective diagnostic groups. The amount and probability supports differ; the report records both. The grouping must never be used to select a forecast after observing its outcome.

### How to read the main comparison

```text
blend_minus_smooth_rps = shared_blend RPS - smooth RPS
negative: blending improves the score
positive: smoothing alone performs better
```

Years receive equal weight. Within each year and domain, the existing area weighting is retained. The bootstrap resamples whole annual score pairs, not individual grid cells. Its intervals are descriptive: they do not account for serial dependence, overlapping model fits, repeated model selection or multiple comparisons. No interval is reported for fewer than five years.

The 2017–2025 results have already been inspected repeatedly and are exploratory. The historical models were trained on 1993–2016, while the frozen 2026 forecast was refitted on 1993–2025. Consequently, these comparisons do not test one identical fitted weight across all years.

### Outputs

```text
outputs\verification_followup\historical\historical_blend_review.json
outputs\verification_followup\historical\HISTORICAL_BLEND_REVIEW.md
outputs\verification_followup\historical\annual_blend_scores.csv
outputs\verification_followup\historical\annual_blend_difference.png
```

Open the report in VS Code:

```bat
code outputs\verification_followup\historical\HISTORICAL_BLEND_REVIEW.md
```

If you have subsequently regenerated the historical experiments, collect the current results and explicitly review those instead of the bundled snapshot:

```bat
python scripts\collect_regime_experiments.py
python scripts\review_historical_blending.py --evidence outputs\all_regime_experiments.json --targets JJAS Jun Jul Aug Sep --regenerate
```

### Optional: probability-file checks and reliability plots

```bat
python scripts\review_historical_blending.py --targets JJAS Jun Jul Aug Sep --with-fields --regenerate
```

This additionally reads, for each target and mode:

```text
outputs\regime_calibration_github\init05_TARGET\MODE\regime_probabilities_and_weights.nc
```

It checks that annual RPS, category Brier scores and log loss reproduce the selected JSON evidence before producing reliability curves and probability histograms. It records the number of contributing years in each probability bin. Cell-year counts are not independent sample sizes, and the curves have no independence-based confidence bands.

Outputs are under `historical\reliability\TARGET\MODE\`. If you regenerated NetCDF predictions, use the newly collected evidence via `--evidence` as well; mismatched generations intentionally fail.

## 4. Verify 2026 performance within the predefined regimes

Run:

```bat
python scripts\verify_2026_regimes.py --targets Jun Jul Aug --regenerate
```

This reads the already completed Step 30 `verification_fields.nc` and `verification_report.json` files. It also checks their forecast and observation hashes, coordinates, masks, observed categories, amount fields and probabilities against the frozen forecasts/prepared observations. Country scores must reproduce the existing Step 30 report before domain results are accepted.

### Domains

| Domain | Meaning |
|---|---|
| `all_country` | Original country evaluation, retained as the reference |
| `regime_0` | Arid / marginal regime |
| `regime_1` | Western unimodal residual class |
| `regime_2` | Belg–Kiremt highland rule |
| `regime_3` | Gu–Deyr lowland rule |
| `regime_-1` | Missing climatological classification, reported explicitly |
| `regime_4` | Unused class in this refinement, normally empty |
| `jjas_r12_rainfall_domain` | Cleaned R1/R2 classification plus the previously defined JJAS rainfall criteria |
| `outside_jjas_r12_rainfall_domain` | Country complement of that rainfall domain |

The domain uses the existing cleaned-class rule with JJAS rainfall at least 120 mm and at least 20% of annual rainfall, as documented by the bundled reconciliation report. No onset-detection gate is applied.

These are **climatological classification rules**, not administrative regions. The GitHub refinement is not presented as independently verified official EMI zoning. Full 1993–2025 classification is appropriate for stratifying the 2026 assessment because its climatological inputs precede 2026; it is not used for historical model fitting.

The script checks the exact country grid and country mask and rejects mismatches; it does not interpolate a mask to force a match. To use your own corresponding reconciliation output explicitly:

```bat
python scripts\verify_2026_regimes.py --targets Jun Jul Aug --mask outputs\regime_reconciliation\descriptive_1993_2025\regime_comparison_and_masks.nc --regenerate
```

### Metrics and coverage

For each domain the report contains:

- Domain area and grid-cell count.
- Amount and probability coverage, both within the domain and relative to country area.
- Raw, corrected and climatological bias, MAE, RMSE, CRPS and CRPSS.
- RPS/RPSS, category Brier/BSS and log loss for the five existing probability products.
- Observed category fractions, final mean probabilities and observed/forecast anomalies.
- Shared-blend minus corrected-smoothed RPS.

Empty domains have empty metric dictionaries and explicit zero coverage, rather than invented zero scores. Low CRPS in a dry region is not by itself evidence of high predictability; use CRPSS and the region's rainfall scale as well. Probability blending does not change the corrected amount ensemble or its CRPS.

Outputs:

```text
outputs\verification_followup\regimes\Jun_Jul_Aug\regime_verification_summary.json
outputs\verification_followup\regimes\Jun_Jul_Aug\REGIME_VERIFICATION.md
outputs\verification_followup\regimes\Jun_Jul_Aug\regime_metrics.csv
outputs\verification_followup\regimes\Jun_Jul_Aug\regime_probability_skill.png
```

These remain single-year diagnostics. No 2026 reliability or statistical-significance claim is made. The original verification maps remain on the native grid; no smoothing is applied to scoring fields.

## 5. Complete September and JJAS when the observations are available

Check availability now:

```bat
python scripts\complete_verification_2026.py --check
```

The script checks this official product directory:

https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/netcdf/p25/by_month/

It accepts only the matching CHIRPS v2 daily 0.25-degree monthly files. HTTP 404 means unavailable; a network/server error means unknown, not ready. Availability does not establish calendar completeness: the existing Step 30 preparation still checks every expected day, daily units, grid alignment, historical overlap and valid-day counts.

At the 4 October 2026 archive check, June, July and August were listed; September was not. The command checks again each time you run it. It is a manual command, not a scheduled task.

When all four months are confirmed available, run:

```bat
python scripts\complete_verification_2026.py --run --regenerate
```

This executes, in order:

1. `prepare_verification_2026.py --months Jun Jul Aug Sep`: verify the original 2025 daily overlap, prepare complete 2026 months, then construct the 122-day observed JJAS total.
2. `verify_frozen_2026.py --targets Jun Jul Aug Sep JJAS`: score each existing forecast against its own target-period observations and frozen thresholds.
3. `verify_2026_regimes.py --targets Jun Jul Aug Sep JJAS`: produce the corresponding regime summaries.

If a monthly file is unavailable, it reports `WAITING` and leaves existing verification results unchanged. If preparation fails a scientific check, subsequent stages do not run. It never substitutes CHIRPS v3, preliminary observations or a three-month total for JJAS.

The JJAS observations are the sum of complete monthly observations. The separately fitted JJAS forecast is scored directly; monthly forecasts, tercile probabilities and skill scores are not added or averaged to manufacture a JJAS product.

The status is written to:

```text
outputs\verification_followup\season_status.json
```

Completed full-season reports will be under:

```text
outputs\verification_2026\reports\Jun_Jul_Aug_Sep_JJAS\verification_summary.json
outputs\verification_followup\regimes\Jun_Jul_Aug_Sep_JJAS\regime_verification_summary.json
```

## 6. Findings already available from your uploaded historical evidence

The included example is computed from the actual uploaded `all_regime_experiments(1).json`, not synthetic data. The table shows shared-blend RPS minus corrected-smoothed RPS, using the same country support in each year.

| Target | Training 1993–2016 | Operational 2017–2025 | Interpretation of historical means |
|---|---:|---:|---|
| JJAS | -0.01059 | -0.01429 | Blending improved both means |
| June | -0.03160 | -0.01421 | Blending improved both means |
| July | -0.01925 | -0.01248 | Blending improved both means |
| August | -0.01216 | +0.01372 | Blending improved training mean but worsened operational mean |
| September | -0.02905 | -0.02106 | Blending improved both means |

For August 2017–2025, smoothing alone scored 0.41265 versus 0.42637 for the shared blend. Blending was worse in six of nine years. The descriptive paired-year interval for the difference is approximately [-0.00939, +0.03642], which spans zero. All five operational-period intervals span zero; the record is short.

This makes August a useful diagnostic priority, but does not justify changing the frozen 2026 forecast. It also shows why the 2026 outcome alone is insufficient to discard climatology blending across all targets. No new blend weight has been fitted in this update. If a new rule is later proposed, its preprocessing, weight estimation and any hyperparameter selection must be nested inside year-based evaluation; the inspected 2026 result remains diagnostic evidence, not an untouched test set.

## 7. Troubleshooting and tests

| Message | Action |
|---|---|
| `No module named verify2026_outputs` or `verify2026_common` | Install/retain the Step 30 scripts in the same project `scripts` folder |
| Step 30 freeze missing | Use the existing Step 30 preparation workflow; keep existing forecasts and do not make a replacement freeze to hide differences |
| Frozen/original forecast differs | Inspect the changed file and preserve the original archive; the new review intentionally stops |
| Missing historical experiment | Re-run `collect_regime_experiments.py` and pass its output with `--evidence`; the bundle contains the previously uploaded complete snapshot |
| Optional field input missing | Run without `--with-fields`, or supply the correct `--input-root` |
| NetCDF/evidence reproduction mismatch | Use matching generations of summaries and predictions; investigate before loosening tolerances |
| Regime mask/grid mismatch | Use the correct mask produced on the project grid and baseline; do not resample categorical masks merely to silence the check |
| September unavailable | Wait for the official file, then rerun the completion command |
| Existing derived output | Add `--regenerate`; previous outputs are preserved in a dated backup |

Optional local test command:

```bat
python tests\test_followup.py
```

The tests use actual historical evidence for the historical comparison and explicitly synthetic fixtures for the 2026 integration checks. Synthetic scores are never included in the real assessment. See `archive/step33_validation/VALIDATION.md` for the executed checks and limits.

## 8. Files to share after running

The most useful new outputs are:

```text
outputs\verification_followup\historical\historical_blend_review.json
outputs\verification_followup\regimes\Jun_Jul_Aug\regime_verification_summary.json
```

If the optional probability-field review is run, include August's `reliability.json` and `reliability.png` for each period. The historical JSON snapshot alone cannot reconstruct probability-bin reliability; those outputs require your saved probability NetCDF files.
