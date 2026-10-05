# Step 20 — Final shared-blend refit and 2026 products

## Decision

Retain separately fitted shared blends for JJAS, June, July, August and September. The local-blend experiments did not establish an improvement sufficient to replace the shared method. August's smoothed-only operational result is recorded as exploratory evidence, not used to select a new method after inspecting the evaluation period.

This stage refits on 1993–2025 and applies the selected procedure to all 51 members of the May-initialized 2026 forecast. It does not estimate new validation skill from the final fitting sample. JJAS 2026 has already elapsed: label these outputs retrospective reconstructions of the May-initialized product, not newly issued forecasts with advance lead time.

## Install and run

Extract `final_shared_blend_update.zip` into:

```text
D:\calibrated_seasonal_rainfall
```

The package adds `scripts\final_shared_blend.py`, `tests\test_final_shared_blend.py` and this guide. Keep existing `common.py`, `calibration_core.py`, `run_calibration.py`, `compare_calibration.py`, `local_blend.py`, `verification_core.py`, `run_monthly.py`, and `output_runs.py` in `scripts`. No new dependencies are required.

In CMD:

```bat
cd /d D:\calibrated_seasonal_rainfall
.venv\Scripts\activate
python -m unittest discover -s tests -p test_final_shared_blend.py -v
python scripts\final_shared_blend.py --config config\project.json --region-mask data\masks\ethiopia_common.nc --regenerate
```

By default the script runs all five targets, using the existing regridded data. It generates monthly configurations in memory from the main project settings; it does not alter `config/project.json` or repeat preparation.

To run JJAS first:

```bat
python scripts\final_shared_blend.py --config config\project.json --targets JJAS --region-mask data\masks\ethiopia_common.nc --regenerate
```

For individual months, use `--targets Jun Jul Aug Sep`, or a subset. The combined report contains only targets completed in the current invocation; running a subset refreshes that combined report with the subset. Per-target results remain available in their respective folders.

If a separate physical land mask was used during evaluation, pass the same file via `--land-mask`. Your current evaluated workflow has no separately supplied physical land mask. Do not substitute the Ethiopia country mask for one.

## How the final fit works

For each target independently:

1. Read ECMWF totals for 1993–2026 and CHIRPS totals for 1993–2025. The loader checks units, coordinates, period configuration, year and member count.
2. Build 33 leave-one-year-out records. For each historical target year, fit rainfall correction, thresholds and eligibility using the other 32 years, then generate its corrected ensemble probabilities and observed category.
3. Smooth counts using `(count + 0.5)/(M + 1.5)`, with that year's actual 25 or 51 members.
4. Fit one shared climatology-blend weight by minimizing equal-year, area-weighted RPS over those 33 records. The shared-weight calculation is reused from the tested local-comparison code; local weights are not applied to the final forecast.
5. Refit grid-cell rainfall mean–variance correction and tercile thresholds using all 33 years. Compute the grid-cell observed category climatology from those observations.
6. Apply that correction to all 51 members of 2026. Calculate base probabilities, apply count smoothing with denominator 52.5, then apply the fitted shared blend.
7. Verify probability bounds and sums, write parameters and forecast files, and generate maps masked to Ethiopia.

Each training year has equal weight. Rainfall-model moments are averaged within each year's ensemble before averaging years; probability-calibration sample weights also give each year equal total weight. Operational training years therefore do not get double weight just because they have 51 members. Unequal ensemble sampling uncertainty and possible model-system differences are not eliminated by this weighting.

The full-training blend weights are newly estimated. Do not copy the earlier 1993–2016 weights or the average cross-validation-fold weights into this fit.

No CHIRPS 2026 file is read. No forecast from 2026 contributes to parameter estimation. The available observational archive cannot verify 2026.

## Outputs

For example:

```text
outputs\final_shared_blend\init05_JJAS\2026
outputs\final_shared_blend\init05_Jun\2026
outputs\final_shared_blend\init05_Jul\2026
outputs\final_shared_blend\init05_Aug\2026
outputs\final_shared_blend\init05_Sep\2026
```

Each target contains:

| File | Contents |
|---|---|
| `forecast_2026.nc` | Corrected 51-member rainfall, ensemble mean/anomaly, four probability fields, thresholds and masks |
| `amount_parameters.nc` | Full-training local mean–variance parameters, tercile thresholds and eligibility |
| `blend_parameters.json` | Shared climatology/forecast weights, smoothing strength and training years |
| `final_report.json` | QC, member counts, eligible-cell coverage, regional summaries and provenance |
| `probabilities_2026.png` | Below/near/above category probabilities on the same 0–100% color scale |
| `rainfall_2026.png` | Amount-corrected ensemble mean and anomaly from the 1993–2025 observed mean |

The combined report is:

```text
outputs\final_shared_blend\final_reports_2026.json
```

It is small enough to upload as one file. It contains only targets processed in that invocation. The `area_mean_gridcell_probabilities` values summarize grid-cell probabilities over the region. They are not the probabilities that national-average rainfall falls into national-average terciles.

## Interpreting the products

- `blend_probability` is the selected final categorical product. Category order is below, near, above; units are fractions, not percentages.
- `base_probability` is the direct corrected-member fraction.
- `smoothed_probability` includes the 0.5 pseudocount per category.
- `climatology_probability` is based on observed training categories and is not forced to exactly one-third where ties affect category counts.
- Thresholds are local: below is rainfall less than q1; near includes q1 and q2; above is greater than q2.
- `precip_corrected` and its mean/anomaly reflect amount correction only. They are not a continuous distribution adjusted to reproduce the blended category probabilities.
- Maps are masked to Ethiopia but do not draw a shapefile outline. The full NetCDF retains the eligible common domain and includes `region_mask` for regional use.
- Dry/degenerate cells may have valid rainfall amounts but unavailable category probabilities. Respect the `amount_eligible` and `probability_eligible` masks.
- Probabilities for different months cannot be added or averaged to obtain JJAS probabilities. Independently corrected monthly amounts are also not guaranteed to sum to the separately corrected JJAS total. This stage does not impose temporal coherence.
- Final refitting can change thresholds, weights and coverage relative to development-period fits. Preserve the earlier cross-validation and 2017–2025 evaluation reports as the evidence of skill; final-fit products are not new validation evidence.

## Reruns and preservation

`--regenerate` generates new outputs in a staging folder and moves existing per-target outputs to a dated backup after successful generation. Existing comparison and verification folders remain unchanged. Without the flag, the script protects an existing destination. Do not run two jobs for the same target simultaneously. Backups consume disk space and are not automatically deleted.

## Tests and review

The synthetic tests check that changing the 2026 forecast cannot alter fitted parameters, replicating members within one year does not change equal-year rainfall fitting, and the final NetCDF retains 51 members with correct smoothing/blending and probability sums. Synthetic test output is not evidence of actual forecast skill.

Upload `final_reports_2026.json` after running all targets. Optionally include the JJAS probability and rainfall PNGs. We will check the new weights, probability sums, coverage and clipping diagnostics before interpreting the reconstructed 2026 signal.
