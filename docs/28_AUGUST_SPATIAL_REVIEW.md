# Step 28 — August spatial review and method decision

## Decision

Retain the shared probability blend as the default August product. Keep the GitHub-refined regularized regime blend as an experimental candidate. Its small national RPS gain masks substantial spatial deterioration. Do not select a different method cell by cell using these already-inspected operational years.

This review changes no source forecast, calibration coefficient, rainfall amount or mask. It completes the geographic check requested after the two August diagnostic reports.

## Inputs and consistency

- Uploaded `diagnostic_fields.nc`: 48 latitude × 60 longitude cells; RPS, category Brier and category probability differences; valid-year counts.
- Previously supplied operational `diagnostic_report.json`: 2017–2025; comparison of regularized regime versus shared blend.
- Existing project country mask from `regime_comparison_and_masks.nc`: used only to calculate country-grid coverage, not to impose full-period regime classes on historical evaluation.
- Existing `eth_admin0` boundary: display outline only.

The diagnostic NetCDF itself has no explicit target/year/mode attributes. Its nine-year support and national RPS difference reproduce the accompanying August operational report. This is the basis for interpreting it as the operational August result. Future diagnostic exports should carry this metadata directly.

Checks passed:

1. All 1,208 evaluated cells have exactly nine valid years; 10,872 grid-cell/year cases in total.
2. Every evaluated cell lies inside the existing 1,484-cell project country mask.
3. The evaluated cells occupy 81.2978% of the country-grid area. The other 276 country cells have no results for this common-support comparison; they cannot be classified as improved or worsened.
4. The area-weighted mean RPS difference is −0.001119317360, matching the operational report's −0.001119317390 within numerical precision.
5. Category probability changes sum to zero, within numerical precision.
6. RPS differences equal below-normal plus above-normal Brier differences, within numerical precision, as expected for this three-category unnormalized RPS implementation.

Area weights are proportional to cosine(latitude), which gives the exact relative spherical cell areas for this regular latitude–longitude grid. With all evaluated cells present in all nine years, averaging the per-cell means with these weights reproduces the equal-year national mean.

## National and category results

All differences are **regularized regime blend minus shared blend**. Negative score differences favor the regime blend. Area fractions below refer to evaluated area, not the whole country.

| Score | Mean difference | Area improved | Area worsened |
|---|---:|---:|---:|
| RPS | −0.00111932 | 50.83% | 49.17% |
| Below-normal Brier | −0.00040796 | 50.80% | 49.20% |
| Near-normal Brier | +0.00031336 | 47.08% | 52.92% |
| Above-normal Brier | −0.00071135 | 46.01% | 53.99% |

Above-normal Brier improves on average even though more than half of the evaluated area worsens: the improvements in other cells are large enough to outweigh those losses. Area fraction and score magnitude answer different questions.

The regime blend's mean probability changes are +0.1491 percentage points for below normal, +0.1479 for near normal, and −0.2970 for above normal. These shifts do not resolve the overall underprediction of above-normal occurrence identified in the operational reliability report. Probability changes are not themselves measures of skill.

For three ordered categories, the two cumulative RPS terms correspond to below-normal and above-normal event losses. Near-normal Brier is therefore useful as a separate diagnostic; a lower RPS does not guarantee a better near-normal Brier score.

## Geographic pattern

The following quadrants are transparent descriptive coordinate partitions at 10°N and 39°E. They are not Ethiopian administrative regions, not R0–R4 rainfall regimes and not proposed calibration boundaries. Their averages describe this evaluation only.

| Evaluated quadrant | Cell-center definition | Cells | Mean RPS difference | Area improved |
|---|---|---:|---:|---:|
| Northwest | latitude ≥10°N; longitude <39°E | 251 | −0.002474 | 67.34% |
| Northeast | latitude ≥10°N; longitude ≥39°E | 202 | −0.017178 | 89.10% |
| Southwest | latitude <10°N; longitude <39°E | 422 | +0.007482 | 21.75% |
| Southeast | latitude <10°N; longitude ≥39°E | 333 | −0.001402 | 52.49% |

The northeast shows the clearest spatial gains. Deterioration is widespread in the southwest, affecting 78.25% of its evaluated area. The southeast is mixed. The map retains native cells and does not smooth away local losses or imply statistical significance.

## What this establishes—and what it does not

The spatial results agree with the earlier national assessment: some locations benefit, but the improvement is not spatially uniform. Uniform nine-year support rules out differing sample lengths as the explanation for the spatial pattern.

The existing whole-year operational bootstrap interval (−0.004193 to +0.002350) still includes zero. The time-averaged NetCDF cannot establish year-by-year consistency or bootstrap confidence intervals for individual cells or these descriptive quadrants. A spatially coherent mean difference is not by itself proof of statistical significance, and neighboring grid cells are not independent trials.

The evidence does not establish why operational above-normal outcomes are more frequent than the forecasts imply. Climate variability, baseline effects and changes in model/ensemble behavior require separate controlled investigation; none is diagnosed causally here.

## Next step

Keep the existing shared-blend final forecasts and complete their product documentation. Archive the August regime maps and this evaluation as experimental evidence. No calibration rerun or further upload is required to retain the default.

If developing another candidate, define its method, domains and selection rules using training data and nested or rolling-origin evaluation. Use later unexamined seasons as prospective evidence. Do not choose only the winning geographic cells from this same operational comparison and then claim those same scores as independent validation.

This review concerns probability calibration. It does not assess or modify rainfall amount correction, CRPS or rainfall-volume forecasts.
