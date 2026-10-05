# Comparison with EMI and ICPAC — 2026

Review date: 3 October 2026. This is a qualitative forecast comparison, not verification against 2026 observations.

## Your completed final refit

Source: uploaded `final_reports_2026.json`; spatial interpretation of JJAS uses the uploaded probability and rainfall PNGs. Monthly grid files were not supplied, so monthly spatial agreement cannot yet be measured.

All five targets used 1993–2025 training and all 51 members for 2026. Maximum probability-sum error is at most 2.22e-16. This confirms a basic numerical check, not forecast accuracy.

| Period | Below % | Near % | Above % | Climatology weight % | Eligible Ethiopia probability cells |
|---|---:|---:|---:|---:|---:|
| JJAS | 50.48 | 25.08 | 24.44 | 49.74 | 1455 |
| June | 42.78 | 30.16 | 27.06 | 73.77 | 1201 |
| July | 45.32 | 28.59 | 26.09 | 60.09 | 1193 |
| August | 50.71 | 25.79 | 23.50 | 48.06 | 1264 |
| September | 36.41 | 30.91 | 32.67 | 79.22 | 1422 |

These are area-weighted means of local grid-cell probabilities. They are not probabilities of country-total or country-average rainfall categories. Coverage differs by month. September is close to climatology, although below-normal has the largest spatially averaged probability; this is not a confident nationwide dry forecast.

JJAS PNGs show a broad dry signal over much of western, central and northern Ethiopia, with less dry or locally wetter tendencies toward the southeast. Local probability magnitudes and anomaly totals should be taken from NetCDF, not estimated from screenshot colors.

## Period-by-period comparison

| Period | ICPAC evidence | EMI evidence | Interpretation relative to your product |
|---|---|---|---|
| JJAS | GHACOF73, 18–19 May 2026: dry-favored over much of Ethiopia; elevated probabilities in central/northeastern/northwestern areas [1]. | Kiremt 2026: near/below in several northern/eastern and central/southern Oromia areas; near/above in Benishangul-Gumuz, western Oromia, Gambella and southwest [2]. | Broad agreement with ICPAC dryness. Partial agreement with EMI, with a clear qualitative difference in the west/southwest. |
| June | The dedicated June page forecasts wetter tendencies in parts of eastern/western Ethiopia, drier central/northern areas [3]. | June summary describes stronger rainfall activity and occasional heavy rain in several regions [5]. | Your area mean leans dry. Whether it captures ICPAC's regional contrasts needs your June grid/map. EMI rain-activity statements alone do not establish a tercile disagreement. |
| July | Dedicated July page favors drier-than-usual conditions over most of Ethiopia [4]. | July summary anticipates stronger rain-bearing systems, particularly early in the month, and rain in west/northwest/central/southwest [6]. | Your dry tendency agrees broadly with ICPAC. Heavy-rain episodes and a below-normal monthly total can coexist; do not interpret EMI's episode forecast as necessarily above-normal monthly rainfall. |
| August | The user-supplied August 2026 ICPAC-branded map favors below-normal rainfall over much of Ethiopia. Issue date and original online product were not independently verified. | EMI August summary discusses improving rainfall activity and moderate/heavy episodes [7]. | Broad directional consistency between your dry-leaning August summary and the supplied ICPAC map; no quantitative spatial match established. EMI summary is not sufficient to assign a competing tercile. |
| September | A dedicated monthly September 2026 product was not verified in the accessible search results. | EMI expects continuing western rains, generally near-normal amounts with localized below-normal amounts across named western/central areas [8]. | Your weak signal is not inconsistent at broad scale, but it does not establish local agreement. No claim of an ICPAC monthly match is made. |

EMI summaries above are English paraphrases of the Amharic source text, not official English translations. June–August full bulletins contain additional maps; the table avoids inferring tercile probabilities from unverified image legends. Forecast sections must also be distinguished from the previous-month observations included in the same bulletins.

## Why the products differ

The ICPAC JJAS technical statement [1] uses May-initialized outputs from eight global producing centres and combines three calibration approaches: canonical correlation analysis, linear regression and a Kharin et al. method. It uses 1991–2020 observed climatology. Your selected product uses ECMWF with mean–variance amount correction, count smoothing and a fitted shared climatology blend, referenced to CHIRPS 1993–2025. The current final product is not Dirichlet calibration: that was a tested candidate, while shared blend was retained from the comparisons.

Consequently, neither the leading category nor its probability must match ICPAC cell by cell. Do not increase your probabilities merely to resemble its colors.

All your monthly products use the May initialization. Monthly agency outlooks can incorporate later information; the exact model initialization and issue date must be established for each before making a fair skill comparison. Website crawl dates are not forecast issue dates. The matching ICPAC May-initialized JJAS statement is a stronger timing match than a later monthly outlook.

The uploaded weekly anomaly example is titled 29 September–6 October 2026. It is a visual-style reference only, not a JJAS or full-September forecast comparison. Its image alone does not establish the anomaly units or climatological reference.

## Recommended next work

1. Generate the new maps using Step 21, without refitting the selected calibration.
2. Compare each month's actual spatial field, using the same Ethiopia area and preserving ineligible cells. Keep unknown agency metadata explicitly unknown.
3. For numerical inter-agency comparison obtain original probability grids (or documented forecast zones), not just PNGs. Align valid period, initialization, reference climatology, grid and dry-season masks. Compare probability differences and area-weighted category agreement on common valid support. Agreement measures similarity, not skill.
4. To compare forecast accuracy, obtain quality-controlled 2026 rainfall observations and apply frozen historical thresholds to those observations. Evaluate archived predictions with the same metrics and masks. Do not use 2026 outcomes to select or tune the 2026 forecast retrospectively.
5. If a 1991–2020 standard reference is desired, obtain the missing CHIRPS 1991–1992 observations and implement a separately documented reference-period experiment. Changing tercile thresholds requires rebuilding labels and calibration; do not simply relabel the existing 1993–2025 probabilities.
6. Inspect June–August amount-clipping locations before any proposed amount-method revision. Current report clipping fractions (22–24%) are member/cell fractions across the common domain, not Ethiopia land-area fractions. Assess this with held-out continuous scores; it is separate from the plotting task.

## Sources and retrieval limitations

[1] ICPAC GHACOF73 technical statement, hosted by IGAD ICPALD, 18–19 May 2026:
https://icpald.org/wp-content/uploads/2026/05/Technical-Statement.pdf

[2] EMI Kiremt 2026 seasonal outlook:
https://www.ethiomet.gov.et/products/seasonal-forecast/kiremt-2026-seasonal-climate-forecast/

[3] ICPAC June 2026, dedicated product page:
https://www.icpac.net/monthly-forecast/june-2026/

[4] ICPAC July 2026, dedicated product page:
https://www.icpac.net/monthly-forecast/july-2026/

[5] EMI June 2026:
https://www.ethiomet.gov.et/products/monthly-forecast/1-30-june-2026/
PDF: https://www.ethiomet.gov.et/documents/692/1-30_June_2026.pdf

[6] EMI July 2026:
https://www.ethiomet.gov.et/products/monthly-forecast/1-31-july-2026/
PDF link discovered; PDF retrieval unsuccessful in this review:
https://www.ethiomet.gov.et/documents/729/1-31_July_2026.pdf

[7] EMI August 2026:
https://www.ethiomet.gov.et/products/monthly-forecast/1-31-august-2026/
PDF: https://www.ethiomet.gov.et/documents/752/1-31_August_2026.pdf

[8] EMI September 2026:
https://www.ethiomet.gov.et/products/monthly-forecast/1-30-september-2026/
PDF: https://www.ethiomet.gov.et/documents/765/1-31_September_2026.pdf
The PDF filename contains "1-31"; September has 30 days and the official product page explicitly identifies 1–30 September.

ICPAC's generic monthly listing returned inconsistent month labels in the retrieved content, so the dedicated June/July pages were used. Guessed August/September product URLs returned 404; this does not demonstrate that the agency did not issue those forecasts. The provided August image remains useful as user-supplied evidence with unverified issue metadata. No weekly, JJA, JAS or OND outlook has been substituted for a missing monthly or JJAS product.
