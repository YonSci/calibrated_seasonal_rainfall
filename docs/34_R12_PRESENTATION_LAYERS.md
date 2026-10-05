# Step 34 — R1+R2 rainfall domain as a presentation layer

## 1. Yes: use this view for all five targets

The existing JJAS R1+R2 rainfall domain can be used consistently to present June,
July, August, September and JJAS forecasts and their verification. This gives a
focused view of the area selected by your established JJAS climatological rules.

Its label remains **JJAS R1+R2 rainfall domain** on monthly products. The label does
not imply a newly derived June/July/August/September regime classification, that
every included cell is equally wet in each month, or that rainfall outside the
domain is unimportant. The national view is retained beside it.

## 2. Exact mask used

The source is the existing Step 31 reconciliation mask:

```text
evidence/followup_regime_comparison_and_masks.nc
```

The field is:

```text
github_jjas_r12_rainfall_cleaned
```

It combines:

1. The existing Ethiopia country mask.
2. Cleaned R1 or R2 classification from the corrected GitHub refinement.
3. JJAS climatological rainfall of at least 120 mm.
4. JJAS rainfall accounting for at least 20% of annual climatological rainfall.

The classification baseline is CHIRPS 1993–2025. No onset-detection condition is
added. This is a descriptive rainfall-domain mask, not the earlier R2 onset gate.

The stored method must be `github_refined_corrected_calendar_v1`. The runner
checks the grid, country mask, class consistency and baseline. Where the stored
rainfall/share diagnostics are present, it also checks the threshold conditions.

The mask remains an implementation of the previously reviewed Dunning-inspired
harmonic baseline plus your Ethiopia-specific refinement. This update does not
claim that the R1/R2 boundary is an independently validated official EMI boundary,
or that Dunning et al. prescribed these exact local refinement thresholds.

## 3. Where the mask enters the workflow

The order is:

1. Existing common-grid rainfall data and existing amount/probability calibration.
2. Existing final forecast and its eligibility masks.
3. Existing verification on its declared common support, where observations exist.
4. National and fixed-domain presentation views and separate domain summaries.

For a forecast amount field:

```python
display_support = country_mask & amount_eligible & jjas_r12_domain
```

For forecast probabilities:

```python
display_support = country_mask & probability_eligible & jjas_r12_domain
```

For verification, the domain intersects the existing `amount_support` or
`probability_support`, which also accounts for valid observations and the compared
forecast/reference data. Missing or ineligible cells are not turned into zeros.

## 4. What stays fixed and what changes

| Quantity | Effect of selecting the domain view |
|---|---|
| Corrected ensemble members and mean rainfall | No change |
| Shared-blend probabilities and weights | No change |
| Observed tercile thresholds and reference mean | No change |
| Native grid and country mask | No change |
| Verification score at an individual grid cell | No change |
| National summary score | Retained and checked against the original report |
| Map area emphasized | Restricted to the selected presentation domain |
| Domain-average forecast or score | Calculated over the selected eligible area and labeled separately |

The selected final probability method remains additive member-count smoothing
followed by the shared climatology blend. This update does not introduce a
Dirichlet mapping, separate grid-cell calibration or a new regime blend.

## 5. Monthly and seasonal reference values remain distinct

Each monthly map uses its own target-specific forecast, climatological rainfall
mean, tercile thresholds, eligibility and verification fields. For example,
August anomaly uses August rainfall minus the August 1993–2025 reference mean,
displayed within the same fixed R1+R2 footprint.

JJAS is evaluated directly against complete JJAS observations and its own saved
forecast. Separately corrected monthly forecasts need not sum to the separately
corrected JJAS forecast. Monthly and seasonal verification scores overlap and must
not be pooled as five independent forecast seasons.

## 6. Area weighting and interpretation

All summaries use the original regular latitude–longitude grid with weights
proportional to `cos(latitude)`. Amount and probability products can have different
eligible supports. Both cell counts and area coverage are reported **within the
selected domain**, plus the domain's share of country-grid area.

Mean local probabilities are:

```text
sum(cell_area * local_probability) / sum(eligible_cell_area)
```

They are not probabilities for the total or mean rainfall over the entire domain.

Domain RPSS is calculated from area-mean losses on the same support:

```text
RPSS = 1 - mean_domain_RPS_forecast / mean_domain_RPS_climatology
```

It is not the area average of unstable grid-cell skill ratios. CRPSS and
category-specific Brier Skill Scores follow the same ratio-of-mean-losses logic.
The existing Step 31 aggregation functions are reused. A zero reference loss
produces an undefined skill score, not an invented zero or infinite skill.

The domain can have better or worse scores than the country because the area
being summarized differs. A better focused score does not by itself prove better
calibration. Keep both views visible and retain excluded-area evidence.

## 7. Smoothing and colors

Continuous forecast and verification fields are interpolated for map display.
Defaults are normalized Gaussian filtering with sigma 0.6 native cells and
12-times bilinear display sampling. This is not downscaling and does not add
forecast resolution.

Each continuous field is filtered once using the original country/eligibility
support. The national and R1+R2 views then clip that same display field. Thus,
selecting the domain does not introduce a second smoothing operation or change
values near its edge. National and domain panels share color scales within each
target/product.

Forecast category colors are derived from the interpolated probability vectors,
renormalized to sum to one, then classified. Numeric category codes are never
averaged. Observed verification categories use nearest-cell sampling of the
original codes and retain their discrete support. Their edges can therefore look
more angular than continuous anomaly contours.

The exact vector country rings clip filled contours. The raster domain boundary
is shown using an interpolated signed-distance contour; native cell membership
remains the authority for all statistics. A smooth display boundary is not a new
analytical mask. Missing-data eligibility is retained on the native grid; rounded
display edges do not add missing cells to the verification or its summaries.

Legend distinctions:

- Light gray: outside the selected focus, inside the country footprint.
- Dark gray: ineligible or excluded by a display rule within the selected view.
- White on tercile maps: weak leading probability (default below 40%) or a tie.
- White on anomaly maps: a small interval around zero, as shown by the color scale.

Percent anomalies are hidden where the target-specific climatological mean is
below 10 mm. This is a display rule only, not a new fitting or verification mask.

## 8. Native exports and reproducibility

`presentation_fields.nc` stores the original-grid forecast-derived fields or the
unchanged verification fields, plus `jjas_r12_rainfall_domain`. It does not store
the display-interpolated arrays as if they were higher-resolution predictions.

To select the domain for a separate analysis:

```python
import xarray as xr

with xr.open_dataset(
    r"outputs\operational_2026\presentation\forecast\JJAS\presentation_fields.nc"
) as ds:
    anomaly = ds.rainfall_anomaly_mm.where(ds.jjas_r12_rainfall_domain == 1)
```

Keep the eligibility and missing-data masks when calculating statistics. The
provided JSON summaries already use the correct target-specific support.

## 9. Actual JJAS example supplied with this update

The example was rendered from the uploaded `forecast_2026.nc` without changing it:

| Summary | All Ethiopia | JJAS R1+R2 domain |
|---|---:|---:|
| Domain cells | 1,484 | 833 |
| Domain share of country-grid area | 100.0% | 55.9% |
| Mean corrected rainfall | 375.1 mm | 614.1 mm |
| Mean reference rainfall | 441.1 mm | 714.7 mm |
| Mean anomaly | −66.0 mm | −100.6 mm |
| Area-mean local below-normal probability | 50.5% | 55.0% |
| Area-mean local near-normal probability | 25.1% | 25.4% |
| Area-mean local above-normal probability | 24.4% | 19.6% |

Amount coverage is 99.6% of the national domain and 100% of the focused domain;
probability coverage is 98.0% and 100%, respectively. The different domain means
are expected: they summarize different areas, not different calibrated forecasts.

These are forecast summaries, not observed JJAS outcomes or JJAS verification.
Actual monthly and verification maps are generated on your computer from their
own NetCDF inputs. They are not reconstructed here from screenshots or summary
statistics.
