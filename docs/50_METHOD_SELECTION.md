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
| Rainfall amounts | CRPS (mm) | MVS-corrected ensemble | amount corrections, distribution models of Phases 2 and 3, the Leung affine of the Leung–Dirichlet calibration (docs/51) |

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
| ONDJ, September initialization | Jan | amounts | square-root MVS (amount correction; Leung affine and gamma QM also confirmed) | 0 of 3 |

The numbers behind each are on the site and in `selection.json` (training and test differences, Holm p, years better,
validation seasons).

## Summary across seasons: every method against the published approach

`scripts/method_summary.py` counts, for every method and product over the 20 targets of the four seasons, the targets
where its benchmark confirms it better, where it is better on average over 1993–2016 and over the test years, and the
targets of the independent seasons (2026 so far) where it scored better (`outputs/method_selection/summary.md`; on the
site under *Research › Method selection*; refreshed by the daily scoring). As of 2026-10-15:

- **Tercile probabilities:** only one method is confirmed better anywhere: square-root MVS (FMAM from February, February).
  It is also the most consistent amount correction overall (better on average for 14 of 20 targets over 1993–2016, 16 of
  20 over the test years, 11 of 15 validation targets), with Variance Scaling and gamma quantile mapping close. No
  probability-stage method (Phases 1 and 2), distribution model or Leung–Dirichlet pipeline is confirmed better than the
  climatology blend for any target; the best of them are better for at most 9 of 20 targets.
- **Rainfall amounts:** square-root MVS, gamma QM, EMOS and Variance Scaling are each confirmed for two targets; square-root
  MVS and gamma QM are better on average for all 20 targets over 1993–2016. Quantile regression, the Leung
  affine and power transformation are confirmed for one target each.
