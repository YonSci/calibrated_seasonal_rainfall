# Ethiopia rainfall forecast package — May initialization, 2026

Retrospective reconstruction of May-initialized 2026 forecasts; no verification against 2026 observations in this package.

All five targets. Generated 2026-10-04T16:50:53.362812+00:00.

## Selected methods

Rainfall amounts: existing equal-year mean–variance bias correction at each grid cell. Probabilities: alpha=0.5 additive count smoothing followed by the existing shared climatology blend. No Dirichlet mapping, grid-cell blend or regime blend is applied in these selected final products. All 51 members are retained.

## Forecast summary

Probabilities below are area averages of local probabilities, not probabilities for country-total rainfall. Rainfall means use amount-eligible cells; probability summaries use probability-eligible cells. Their support can differ.

| Target | Below % | Near % | Above % | Corrected mean mm | Reference mean mm | Anomaly mm | Probability coverage % |
|---|---:|---:|---:|---:|---:|---:|---:|
| JJAS | 50.5 | 25.1 | 24.4 | 375.1 | 441.1 | -66.0 | 98.0 |
| Jun | 42.8 | 30.2 | 27.1 | 65.6 | 80.7 | -15.1 | 80.9 |
| Jul | 45.3 | 28.6 | 26.1 | 112.8 | 129.7 | -16.9 | 80.3 |
| Aug | 50.7 | 25.8 | 23.5 | 117.5 | 136.4 | -18.9 | 85.1 |
| Sep | 36.4 | 30.9 | 32.7 | 82.6 | 94.3 | -11.7 | 95.8 |

Reference period: CHIRPS 1993–2025. Monthly and JJAS products were corrected separately; corrected monthly totals need not sum to corrected JJAS totals. Percent-anomaly maps hide reference rainfall below 10 mm.

## Historical probability verification

Lower RPS and log loss are better. RPSS uses the fold-specific climatology benchmark. Historical scores do not establish the skill of the final 1993–2025 refit on 2026.

| Target | Evaluation | Shared RPS | Shared RPSS | Shared log loss |
|---|---|---:|---:|---:|
| JJAS | training | 0.432298 | 0.0463 | 1.062577 |
| JJAS | operational | 0.428397 | 0.0505 | 1.056390 |
| Jun | training | 0.448727 | 0.0104 | 1.086764 |
| Jun | operational | 0.459003 | 0.0243 | 1.076147 |
| Jul | training | 0.446008 | 0.0172 | 1.081424 |
| Jul | operational | 0.450595 | 0.0364 | 1.066709 |
| Aug | training | 0.443382 | 0.0214 | 1.078216 |
| Aug | operational | 0.426368 | 0.0664 | 1.046967 |
| Sep | training | 0.451226 | 0.0037 | 1.092390 |
| Sep | operational | 0.454776 | 0.0096 | 1.084685 |

Training evaluation: nested cross-validation over 1993–2016. Operational evaluation: 2017–2025 with fits based on 1993–2016; these years have been inspected repeatedly and are exploratory evidence. Detailed Brier/BSS category scores are in historical_verification.json. These figures come from the supplied regime-comparison common support, which can differ from other earlier verification stages.

## Maps and domains

Nationwide maps preserve the country mask and variable-specific eligibility. JJAS also includes a separately labeled R1+R2 rainfall-domain view: cleaned GitHub-derived refinement, climatological JJAS >=120 mm and >=20% of annual rainfall. This is a descriptive display domain, not an onset mask or a separately calibrated forecast. No official EMI endorsement is implied.

Smooth contours are for display only; native NetCDF values and statistics remain unchanged. The 0.25-degree common grid is not evidence of new forecast resolution. Country clipping is distinct from a physical land–ocean/lake mask. Source mask metadata is preserved in each forecast NetCDF.

## Decision and next use

Retain the shared blend. The August regime candidate remains experimental; do not select winning cells using these same operational years. Use this package for review and communication of the retrospective reconstruction. It is not an official EMI/ICPAC product, an observation of 2026 rainfall, or a validation of rainfall-driven impact forecasts.

## Files

Open index.html locally for maps and download links. forecasts/ contains unchanged copies of the source NetCDFs. maps/ contains PNG/PDF products, native map fields and product metadata. evidence/ contains the experiment summary and any available August review evidence. manifest.json records input, script and output hashes. bundle.zip contains the delivery files except itself and the completion receipt. completion_report.json records the final archive hash.
