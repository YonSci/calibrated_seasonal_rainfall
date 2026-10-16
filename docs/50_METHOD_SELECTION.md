# Method selection: the approach for each season, target and product

`scripts/method_selection.py` selects, for every forecast season (cycle), target and product, the approach the evidence
supports, from all benchmarks together, by a rule fixed in advance (`config/method_selection_rule.json`). It writes
`outputs/method_selection/selection.json`; the site shows it on *Research › Method selection* and on every outlook page
("Approach for this target"). **A selection is advice for a decision: the published forecasts keep the published approach
(Mean-Variance Scaling and the climatology blend) until a change is decided.**

## Products and references

| Product | Score | Reference (published approach) | Families considered |
| --- | --- | --- | --- |
| Tercile probabilities | RPS | MVS + climatology blend | amount corrections (docs/47), probability-stage methods of Phases 1 and 2, distribution models of Phases 2 and 3 (docs/48), Leung–Dirichlet calibration (docs/51) |
| Rainfall amounts | CRPS (mm) | MVS-corrected ensemble | amount corrections, distribution models of Phases 2 and 3, the Leung–Dirichlet calibration (its corrected amounts; docs/51) |

## Rule

1. **Historical evidence (candidate).** A method is a candidate for a target and product only if its benchmark confirms it
   better than the published reference: outer leave-one-year-out over 1993–2016, Holm-adjusted p < 0.05 across every method
   and target of its family, and not worse over the test years (2017 onward).
2. **Choice.** A recommended candidate first; then the candidate with the largest improvement over the training years.
   **One change at a time:** each family was tested against the published approach, not combined with another family, so the
   selection changes one stage (the amount correction, the probability stage or the whole distribution); the other candidates
   are listed as alternatives.
3. **Validation (status).** Every candidate is scored on the independent seasons after the benchmark: every amount correction
   by the bias-correction validation runs (`bias_validation.py --methods all`, run by the daily scoring), every
   distribution-model candidate by its own shadow forecast (`dist_shadow.py` runs, besides EMOS, every distribution model the
   selection lists). After at least three seasons a candidate is **recommended** if its mean score over them is not worse
   than the reference, **not supported** if worse; before that it stays a **candidate**. Without a confirmed candidate the
   status is **keep** (the published approach).

The bias-correction part uses the suggestions of `bias_recommend.py` (same historical rule, same validation rule;
`config/bias_correction/recommendation_rule.json`).

## Automation

The daily scoring (`scripts/watch_observations.py`) runs, after each newly scored season, `bias_recommend.py` and then
`method_selection.py`; the next site build publishes the updated selection. A status reaches *recommended* only through new
validation seasons, so changes come no faster than seasons are observed.

## Current selection (2026-10-15)

No target–product combination is recommended yet. Six have a candidate:

| Season | Target | Product | Selected | Validation seasons |
| --- | --- | --- | --- | --- |
| FMAM, January initialization | FMAM | amounts | EMOS (distribution model) | 1 of 3 |
| FMAM, February initialization | Feb | probabilities | square-root MVS (amount correction) | 1 of 3 |
| JJAS, May initialization | Jul | amounts | Variance Scaling, unbounded (amount correction) | 1 of 3 |
| JJAS, May initialization | Aug | amounts | Variance Scaling, unbounded (amount correction) | 1 of 3 |
| JJAS, May initialization | Sep | amounts | quantile regression (distribution model; EMOS also confirmed) | 0 of 3 |
| ONDJ, September initialization | Jan | amounts | square-root MVS (amount correction; Leung–Dirichlet and gamma QM also confirmed) | 0 of 3 |

The numbers behind each are on the site and in `selection.json` (training and test differences, Holm p, years better,
validation seasons).

## Summary across seasons: every method against the published approach

`scripts/method_summary.py` counts, for each of the 27 methods (12 bias corrections, 8 probability calibrations, 6
rainfall-distribution models and 1 two-stage calibration, Leung–Dirichlet, counted once: the whole calibration for
probabilities, its corrected amounts for amounts) and each product over the 20 targets of the four seasons, the targets
where its benchmark confirms it better, where it is better on average over 1993–2016 and over the test years, and the
targets of the independent seasons (2026 so far) where it scored better (`outputs/method_selection/summary.md`; on the
site under *Research › Method selection*; refreshed by the daily scoring). As of 2026-10-15:

- **Tercile probabilities:** only one method is confirmed better anywhere: square-root MVS (FMAM from February, February).
  It is also the most consistent amount correction overall (better on average for 14 of 20 targets over 1993–2016, 16 of
  20 over the test years, 11 of 15 validation targets), with Variance Scaling and gamma quantile mapping close. No
  probability calibration, rainfall-distribution model or two-stage calibration is confirmed better than the
  climatology blend for any target; the best of them are better for at most 9 of 20 targets.
- **Rainfall amounts:** square-root MVS, gamma QM, EMOS and Variance Scaling are each confirmed for two targets; square-root
  MVS and gamma QM are better on average for all 20 targets over 1993–2016. Quantile regression, the Leung–Dirichlet
  calibration and power transformation are confirmed for one target each.

## More statistical power (2026-10-17)

`scripts/method_summary.py` also reads the same out-of-sample scores three further ways (no refitting):

- **33 years.** Each target's 1993–2016 leave-one-year-out years are joined with its test years (2017 onward, fitted on
  1993–2016), so every year 1993–2025 counts, scored by a model that did not see it. This gives a paired whole-year
  sign-flip test per target over 33 years (32 for ONDJ).
- **Pooled.** For each method and year, its skill difference from the published approach is averaged over all its targets of
  all seasons, as a share of the climatology score, so targets of different rainfall add up. This gives one test per method
  over the years.
- **Holm and Benjamini–Hochberg** across every method of a product, for the pooled tests and for the 33-year target tests.

**Results:**
- **Tercile probabilities:** no method is significantly better when pooled, under either correction. Square-root MVS comes
  closest: better in 25 of 33 years, p 0.004 before adjustment, Holm 0.12, BH 0.08 (across all 29 methods).
- **Rainfall amounts, pooled:**
  - Holm: Variance Scaling, square-root MVS, gamma QM and quantile regression are significantly better than the MVS-corrected
    ensemble.
  - Benjamini–Hochberg: the same four, plus EMOS.
- **Rainfall amounts, per target over 33 years:** square-root MVS is confirmed for 3 targets under Holm and 12 under BH;
  gamma QM for 2 and 8.
- **Statistical downscaling** (CCA, PCR, docs/53) is worse than the published approach when pooled.

The selection rule stays as fixed in advance: Holm within each benchmark family. These results are sensitivity analyses on
the Research overview. Switching to Benjamini–Hochberg or to pooled evidence would be a decision. It would most likely make
square-root MVS a candidate for amounts in more targets.

