# Step 26 — GitHub rainfall-regime reconciliation and evaluation

## What is complete

1. A separately named GitHub-derived classification is implemented: `github_refined_corrected_calendar_v1`.
2. Correct calendar alignment, explicit missingness, and all departures from the original are retained and documented.
3. Both definitions have been compared on your actual uploaded 1993–2025 climatology, identical grid and country mask. Maps, representative rainfall cycles, a transition table, and a changed-cell ledger are included.
4. R1 + R2 JJAS rainfall masks and R2 onset-candidate/eligibility layers are exported separately. Missing onset evidence remains unknown.
5. A runner is implemented and synthetically tested for nested historical re-evaluation using the GitHub classification. **The real historical calibration comparison must run on your PC**, where the year-wise CHIRPS cache and prepared ECMWF/CHIRPS files are stored. The uploaded mean climatology cannot reconstruct year-to-year observations or model ensembles.

No 2026 forecasts have been replaced. No changes have been pushed to GitHub. The full-period descriptive map is never used as a fixed mask inside historical validation.

## Install and inspect the already computed outputs

Extract the ZIP into `D:\calibrated_seasonal_rainfall`, merging the folders. This adds four new scripts and tests; it does not replace earlier calibration scripts. It depends on the previous Step 25 update and earlier calibration helpers.

The folder `example_1993_2025` contains actual results from your uploaded file, not synthetic illustrations:

- `classification_comparison.png`: current, GitHub-derived, and changed cells.
- `representative_rainfall_cycles.png`: four typical class profiles and four changed-class examples.
- `JJAS_separate_domains.png`: three distinct domain definitions.
- `regime_comparison_and_masks.nc`: classes, criteria, ratio/peaks, cleanup flags, separate masks.
- `regime_reconciliation_report.json`: areas, rainfall-volume contributions, transitions, settings/provenance.
- `changed_cell_ledger.json`: coordinates and class changes, including cleanup changes.

Representative locations are selected as grid cells nearest the median normalized monthly profile within a class or transition. They are illustrative locations, not independent station validation. Raw daily climatology and a 10-day-sigma smoothed display are shown; the GitHub classifier itself uses its monthly peak calculation.

Run the unit tests:

```bat
cd /d D:\calibrated_seasonal_rainfall
.venv\Scripts\activate
python -m unittest discover -s tests -p test_github_regimes.py -v
```

To reproduce the actual comparison in the normal output directory:

```bat
python scripts\compare_regime_definitions.py --climatology data\processed\regime_climatology\descriptive_1993_2025.nc --regenerate
```

Output: `outputs\regime_reconciliation\descriptive_1993_2025`.

The uploaded country grid contains 1,484 cells. This update deliberately preserves that grid/mask instead of silently rebuilding the source project's stated 1,485-cell country mask. It does not add a physical land–ocean/lake mask.

## Source and exact classification rules

Source: https://github.com/YonSci/-Operational-Multi-Model-Seasonal-Forecasting-System/blob/07879e42290dd5efd1d75f137961378ca7e39ea2/scripts/compute_seasonal_masks.py

Source SHA-256: `2b3da9ffbc98120651f6e79639ba29a18556596edd5363fa76b2d02319879d09`.

The implementation reproduces the inspected **code**, not all statements in its walkthrough. In particular, it does not add a 60-day peak-separation condition that is absent from the source code. The framework's EMI attribution is retained as source context; official EMI endorsement, thresholds and claimed station validation have not been independently established.

The class tests are applied in this order:

1. **R0 arid/marginal:** annual rainfall <200 mm OR (annual rainfall <300 mm AND OND <30 mm).
2. **R3 lowland rule:** OND >=30 mm AND OND share >=8% AND JJA <1.3 × OND AND (rH >=0.70 OR primary/secondary monthly peak is October/November), excluding R0.
3. **R2 highland rule:** FMAM >=50 mm AND FMAM share >=10% AND JJAS >=120 mm AND JJAS share >=25%, with longitude >=38° OR (longitude >=37.5° AND latitude >=10°), AND (rH >=0.38 OR secondary monthly peak is March/April/May), excluding R0/R3.
4. **R1 western/unimodal residual:** remaining observationally valid inside-country cells. This name follows the source rule; it does not guarantee that every residual pixel is geographically western or has one distinct peak.

Monthly peak detection uses 0.25 × previous month + 0.50 × current month + 0.25 × next month, with circular month indexing. The primary month is the maximum smoothed monthly total. Strict local maxima are ranked by value to obtain the secondary month. A single local maximum is reused as secondary, exactly as in the source; do not interpret this as evidence for two distinct peaks.

The source's four-neighbor connected-component cleanup is reproduced: minimum two pixels for R0, minimum three for R2/R3. Removed pixels become residual R1. Both pre-cleanup and post-cleanup maps are exported, and three cells are changed by cleanup in this uploaded dataset.

This is a climatological classification, not rainfall bias correction, probability calibration, downscaling, or an onset-detection algorithm. The harmonic baseline is motivated by Dunning et al. (2016), https://doi.org/10.1002/2016JD025428 ; the geographic thresholds and refinements above are source-specific additions.

## Deliberate corrections and limitations

- February 29 is removed by month/day for the 365-day harmonic cycle. March dates remain aligned and December 31 is retained. We do not reproduce the source's `dayofyear <= 365` bug.
- For source-rule comparability, classification totals and monthly peaks are calculated from the corrected **365-day/no-leap cycle**, just as the source rule expects a 365-element cycle. Actual-calendar monthly climatologies remain separate and are used for rainfall-volume statistics. The two annual totals can differ by mean leap-day rainfall.
- Missing observations are code -1, outside country -2. They cannot enter residual R1 or be reassigned by cleanup.
- If C1 <=0.0001 mm/day, rH is NaN, not zero. Ratio-threshold clauses fail, while independently satisfied peak clauses may still pass. Complete data can still receive residual R1; undefined ratio alone is not a new regime.
- Scientific comparison uses the same current 1,484-cell binary country mask for both methods. No partial-cell boundary fractions are inferred.
- Rainfall-total domains do not require onset-detection rates. Such rates are separate evidence, never manufactured as 100% when absent.
- No map smoothing or cosmetic reassignment is added beyond the explicitly exported source cleanup. The rectangular diagnostic cells preserve the classifications used for calculations.

A reference check executed the pinned source's inspected arithmetic/classification block on the same corrected climatology and country-validity mask. The new cleaned map differed at **zero cells**. This verifies the rule port under the documented input corrections; it does not claim pixel-for-pixel agreement with an old map generated using the original calendar bug, another baseline or another boundary.

## What changed in your actual climatology

The GitHub-derived cleaned classification differs from the previous peak refinement at **304 cells**, covering **20.4000%** of the country-mask area. The largest transition is current R1 → GitHub R2: **173 cells**. Other changes include 46 R2 → R1, 35 R2 → R0, and 15 R2 → R3. Former uncertain cells become R1 or R2 under the source's residual/refinement rules.

The comparison figure explains where changes occur. The geographic restriction and the broader harmonic/seasonal tests, rather than a different harmonic equation, account for major boundary shifts. Some changed examples have weak spring shoulders that satisfy source thresholds but do not pass the previous distinct-peak criteria. Inspect the cycles before interpreting all R2 labels as verified double peaks.

## Which regions dominate JJAS rainfall?

These are estimates from the uploaded CHIRPS climatology using the **cleaned GitHub-derived classification**:

| Class | Cells | Country-mask area | Share of observed JJAS rainfall volume | Mean JJAS rain within class |
|---|---:|---:|---:|---:|
| R0 arid/marginal | 64 | 4.27% | 1.16% | 118.8 mm |
| R1 western/unimodal residual | 421 | 28.30% | 57.46% | 892.3 mm |
| R2 Belg–Kiremt highland rule | 418 | 28.04% | 33.60% | 526.5 mm |
| R3 Gu–Deyr lowland rule | 575 | 39.00% | 7.78% | 87.7 mm |
| Missing observations | 6 | 0.40% | Not estimated | Not estimated |

R1 + R2 cover **56.33%** of the country-mask area and contribute **91.06%** of the estimated observed JJAS rainfall volume. R3 covers a larger area than R1, but contributes much less JJAS rain. This distinguishes geographic extent from rainfall contribution.

Computation: each cell's actual-calendar mean JJAS rainfall in mm × spherical cell area in km² × 10^-6 gives km³ of precipitation. The sum over observationally valid country cells is approximately **497.60 km³ per JJAS season**. This is precipitation falling on the grid area, not runoff, available water, or a gauge-only national estimate. Observations cover 99.60% of the binary-country area; missing rainfall is excluded, not assumed zero. Group volume shares use the observed total as their denominator.

## Separate rainfall and onset layers

Exported in `regime_comparison_and_masks.nc`:

| Variable | Meaning |
|---|---|
| `github_regime_raw` | Classification before source cleanup |
| `github_regime_cleaned` | Classification after source cleanup |
| `github_jjas_r12_rainfall_raw` | Raw R1/R2 AND JJAS >=120 mm AND annual share >=20% |
| `github_jjas_r12_rainfall` | Cleaned R1/R2 AND the same rainfall thresholds; main rainfall-domain export |
| `github_jjas_r12_rainfall_cleaned` | Optional further three-cell cleanup of the rainfall domain |
| `github_onset_candidate_r2` | Cleaned R2 AND rainfall thresholds; a candidate domain, not evidence of successful onset detection |
| `onset_detection_rate` | Supplied detection rate, otherwise NaN |
| `onset_evidence_available` | Whether a finite supplied rate exists inside the country |
| `onset_eligibility_r2` | -1 unknown, 0 excluded/fails, 1 passes candidate and rate >=0.60 |

The main rainfall domain contains **833 cells / 55.93%** of country-mask area. It is smaller than R1 + R2 because six residual-R1 cells fail the rainfall thresholds. Optional mask cleanup changes no cells for this input. The previous threshold-only JJAS view contains 963 cells / 64.72% and remains separately exported.

There are **418 R2 onset-candidate cells**. With no onset detection file supplied, their eligibility is unknown. Six missing-observation cells are also unknown, producing 424 unknown cells in the eligibility layer. Zero cells are confirmed to pass; this means evidence was not supplied, not that onset detection failed everywhere.

Optional supplied onset rates:

```bat
python scripts\compare_regime_definitions.py --onset-rates data\masks\onset_rates_1993_2025.nc --regenerate
```

That file must have `onset_detection_rate(lat,lon)`, values 0–1 or NaN, exact matching coordinates, and a global `training_years` JSON-list attribute matching the climatology. Derive the rates from validated year-wise onset results; do not put percentage values 0–100 into this variable. The script does not estimate onset itself or use supplied onset evidence to alter rainfall totals.

## Historical re-evaluation after reviewing the maps

The uploaded descriptive file cannot replace `chirps_calendar_cache.nc` for historical testing. Use your existing daily-year cache and prepared common-grid files. No regridding or daily preparation rerun is needed.

Begin with JJAS:

```bat
python scripts\evaluate_github_regimes.py --config config\project.json --targets JJAS --mode training --region-mask data\masks\ethiopia_common.nc

python scripts\evaluate_github_regimes.py --config config\project.json --targets JJAS --mode operational --region-mask data\masks\ethiopia_common.nc
```

Then the four months:

```bat
python scripts\evaluate_github_regimes.py --config config\project.json --targets Jun Jul Aug Sep --mode training --region-mask data\masks\ethiopia_common.nc

python scripts\evaluate_github_regimes.py --config config\project.json --targets Jun Jul Aug Sep --mode operational --region-mask data\masks\ethiopia_common.nc
```

For repeated runs, add `--regenerate`; prior directories are backed up after a successful staged build. If your earlier evaluations used a physical land mask, supply the identical `--land-mask` argument here. The existing reports show none was supplied.

New results go to `outputs\regime_calibration_github\init05_TARGET\MODE`. Current-peak results remain under `outputs\regime_calibration`. Each target/mode has the familiar summary, annual RPS plot, probability/weight NetCDF and spatial score NetCDF.

The runner changes **only the regime definition used to group probability-blend fitting and diagnostics**. It retains the amount correction, actual ensemble sizes, probability smoothing, shared fit, gamma=0.05, minimum support, and evaluation years. Both inner and outer classifications use their own training subsets. Operational mode fits only 1993–2016 and evaluates 2017–2025; this remains exploratory because those years were already inspected.

For comparable scores, the old threshold-only seasonal-relevance subset is retained in the standard report. The new R1/R2 rainfall domain is additionally exported fold by fold in the NetCDF. All-country score comparisons remain on identical support. Do not compare a restricted new R1/R2 score directly with a whole-country old score and call the difference a calibration gain.

Where earlier current-peak summaries exist, the runner verifies agreement of annual climatology, smooth and shared RPS/log-loss/category-Brier scores and probability-cell counts. It stops on a mismatch rather than attributing changed inputs to regime improvement. Report field `baseline_reproduction` records the check. Amount eligibility and corrected rainfall are unchanged by design.

Unknown onset flags are exported separately for each fold; no descriptive full-period onset layer is used in historical evaluation.

Collect all reports without duplicate archive filenames:

```bat
python scripts\collect_regime_experiments.py
```

Upload `outputs\all_regime_experiments.json`. It includes current and GitHub-derived reports, each explicitly keyed by method, target and mode. Missing runs are omitted; the script prints the number collected.

## Validation and decision

Six focused unit tests passed: geographic refinement, arid/lowland priority, missingness and cleanup, connectivity, unknown onset evidence, and rainfall-volume accounting. A full isolated synthetic test passed both classification workflows, 24-year nested training, nine-year operational evaluation with 51 members, exact shared-baseline reproduction, NetCDF/report output and regeneration backups:

```bat
python tests\smoke_github_regime_pipeline.py
```

The real descriptive comparison was run and all three figures inspected. Real historical skill under the new classification is **not yet known**. Keep the current shared 2026 products until those results are reviewed. A map that better matches intended climate regions is useful, but does not by itself demonstrate improved forecast calibration.
