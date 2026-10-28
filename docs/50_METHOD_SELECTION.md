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
   better than the published reference: outer leave-one-year-out over 1993–2016, Benjamini–Hochberg-adjusted p < 0.05
   (false discovery rate) across every method and target of its family, and not worse over the test years (2017 onward).
   The adjusted p-values are recomputed (`scripts/selection_tests.py`) from the unadjusted p-values each benchmark stored,
   within the same families as the benchmark (its methods × targets, per score; the selection-aware SEL procedures are their
   own family); nothing is refitted. `selection_tests.holm_check` reproduces every benchmark's own Holm decision exactly, so
   the families are rebuilt correctly. The correction is `multiple_testing` in `config/method_selection_rule.json`.
2. **Choice.** A recommended candidate first; then the candidate with the largest improvement over the training years.
   **Practical tie rule** (`tie_rule`, decided 2026-10-20): candidates of the same status whose improvement is within 1% of the
   published approach's own training-period score (MVS-ensemble CRPS for amounts, published RPS for probabilities, All
   Ethiopia) of the largest improvement are tied, and the simplest is selected: amount corrections and probability-stage
   calibrations, then EMOS, then quantile and extended logistic regression, then the Phase 3 models, Leung–Dirichlet and
   statistical downscaling, then the neural networks, and last what extends a network: the pooled network with an EMOS
   base or neighbourhood inputs, the networks over all cycles or the FMAM and ONDJ cycles, and the combination of models
   (docs/54, 3g and 3h; it contains a network), so an extension never displaces the network it extends on a negligible difference. The tie is recorded in
   `selection.json`. 1% is above the largest error of
   the earlier numerical CRPS (0.7%, `scripts/crps_precision.py`) and well below the typical confirmed improvements (3–8%). It
   was decided before the second stage re-scores the close JJAS September comparison with the corrected CRPS (docs/54, 3f).
   **One change at a time:** each family was tested against the published approach, not combined with another family, so the
   selection changes one stage (the amount correction, the probability stage or the whole distribution); the other candidates
   are listed as alternatives.
3. **Validation (status).** Every candidate is scored on the independent seasons after the benchmark: every amount correction
   by the bias-correction validation runs (`bias_validation.py --methods all`, run by the daily scoring), every
   distribution-model candidate by its own shadow forecast (`dist_shadow.py` runs, besides EMOS, every distribution model the
   selection lists, the neural network included; amounts by its CRPS against the MVS ensemble's, tercile probabilities by
   the RPS of its probabilities against the published ones), the statistical-downscaling methods by their benchmark's forecast year
   (2026) and, from 2027, their own frozen shadow forecasts (`mos_shadow.py`, made when the cycle is run). From 2027 every
   shadow is made when the cycle is run, before its season (docs/52), and scored by the daily scoring once CHIRPS is
   available. After at least three seasons a candidate is **recommended** if its mean score over them is not worse
   than the reference, **not supported** if worse; before that it stays a **candidate**. Without a confirmed candidate the
   status is **keep** (the published approach).

The bias-correction part uses the suggestions of `bias_recommend.py` (same historical rule, same validation rule;
`config/bias_correction/recommendation_rule.json`).

## Automation

The daily scoring (`scripts/watch_observations.py`) runs, after each newly scored season, `bias_recommend.py` and then
`method_selection.py`; the next site build publishes the updated selection. A status reaches *recommended* only through new
validation seasons, so changes come no faster than seasons are observed.

## Change of the multiple-testing correction (2026-10-17)

Until 2026-10-17 the rule used Holm (family-wise error) within each benchmark family. After the sensitivity analyses below
(33-year and pooled evidence, Holm and Benjamini–Hochberg) the project lead decided to use Benjamini–Hochberg, which controls
the expected share of false findings among the confirmed methods and is less strict. The benchmarks keep their own Holm
decisions as run (their pages say so); the selection, the bias-correction suggestions and the summary across seasons apply
Benjamini–Hochberg to the same p-values. The change is recorded in both rule files (`changes`). Effect: six targets had a
candidate under Holm, eight under Benjamini–Hochberg (new: JJAS Jun amounts, gamma QM; JJAS season amounts, PCR), and for
JJAS Aug amounts PCR (larger training improvement) replaces Variance Scaling, which stays an alternative. No status is
*recommended* under either correction: that still needs three validation seasons.

## Current selection (2026-10-20)

No target–product combination is recommended yet. Eight have a candidate:

| Season | Target | Product | Selected | Validation seasons |
| --- | --- | --- | --- | --- |
| FMAM, January initialization | FMAM | amounts | EMOS (distribution model) | 1 of 3 |
| FMAM, February initialization | Feb | probabilities | square-root MVS (amount correction) | 1 of 3 |
| JJAS, May initialization | Jun | amounts | gamma QM (amount correction; square-root MVS also confirmed) | 1 of 3 |
| JJAS, May initialization | Jul | amounts | Variance Scaling, unbounded (amount correction) | 1 of 3 |
| JJAS, May initialization | Aug | amounts | PCR (statistical downscaling; VS, square-root MVS, PT and gamma QM also confirmed) | 1 of 3 |
| JJAS, May initialization | Sep | amounts | EMOS (distribution model; tied within 1% with the DRN and quantile regression, practical tie rule; gamma QM, VS, square-root MVS also confirmed) | 1 of 3 |
| JJAS, May initialization | JJAS | amounts | PCR (statistical downscaling) | 1 of 3 |
| ONDJ, September initialization | Jan | amounts | square-root MVS (amount correction; Leung–Dirichlet and gamma QM also confirmed) | 0 of 3 |

Changes on 2026-10-20: statistical downscaling version 2 (docs/53) keeps PCR confirmed for JJAS August and season amounts
but no longer confirms CCA and PCR for September; the neural network (DRN, docs/54) is confirmed for JJAS September amounts
and was selected there (improvement −1.10 mm over 1993–2016 against −1.08 mm for quantile regression). Under the practical tie
rule adopted the same day, the DRN (−1.10 mm), quantile regression (−1.08 mm) and EMOS (−0.98 mm) are within 1% of the
published CRPS (19.34 mm, tolerance 0.19 mm), so EMOS, the simplest, is selected; the DRN and quantile regression remain
confirmed alternatives with their own shadow forecasts.

The numbers behind each are on the site and in `selection.json` (training and test differences, Benjamini–Hochberg p and the benchmark's Holm p, years better,
validation seasons).

## Summary across seasons: every method against the published approach

`scripts/method_summary.py` counts, for each of the 30 methods (12 bias corrections, 8 probability calibrations, 6
rainfall-distribution models, 1 two-stage calibration, Leung–Dirichlet, counted once: the whole calibration for
probabilities, its corrected amounts for amounts, 2 statistical downscaling methods, CCA and PCR, and 1 neural network, the
DRN of docs/54) and each product over
the 20 targets of the four seasons, the targets where it is confirmed better under the selection rule (Benjamini–Hochberg
within its benchmark family since 2026-10-17), where it is better on average over 1993–2016 and over the test years, and the
targets of the independent seasons (2026 so far) where it scored better (`outputs/method_selection/summary.md`; on the
site under *Research › Method selection*; refreshed by the daily scoring). As of 2026-10-20 (Benjamini–Hochberg; statistical
downscaling version 2):

- **Tercile probabilities:** only one method is confirmed better anywhere: square-root MVS (FMAM from February, February).
  It is also the most consistent amount correction overall (better on average for 14 of 20 targets over 1993–2016, 16 of
  20 over the test years, 11 of 15 validation targets), with Variance Scaling and gamma quantile mapping close. No
  probability calibration, rainfall-distribution model or two-stage calibration is confirmed better than the
  climatology blend for any target; the best of them are better for at most 9 of 20 targets.
- **Rainfall amounts:** square-root MVS is confirmed for 5 targets, Variance Scaling and gamma QM for 4, PCR, EMOS and
  power transformation for 2; quantile regression, the Leung–Dirichlet calibration and the DRN for one each. Square-root
  MVS and gamma QM are better on average for all 20 targets over 1993–2016.

## Ranking by season (2026-10-28)

`scripts/method_summary.py` also ranks, for each season and product, every method scored for all four months of the
season by its **skill gain** over the published approach. The skill gain is the score difference as a share of the
climatology score (percentage points of CRPSS for amounts, RPSS for probabilities). It is averaged over the four months
and over 1993–2025, each year scored by a model that did not see it (the 33 years of "More statistical power").

- **Published approach:** listed at its rank, with a gain of 0.
- **Season total:** shown but not ranked, because the neural networks forecast the months only.
- **Where to find it:** `ranking` in `outputs/method_selection/summary.json`, the tables in `summary.md`, and on the site
  under *Research › Method selection › Ranking by season*.

The ranking is information, not the selection. The selection is made per month and season total, needs Benjamini–Hochberg
confirmation, and applies the 1% tie rule. So the top-ranked method is not always the one selected; for example, the pooled
DRN is selected for FMAM (Jan) March–May although the all-cycles network ranks above it.

As of 2026-10-28 (38 methods), the published approach ranks as follows. The methods above it are better on average, and
the number in brackets is how many of the four months are confirmed:

| Season | Rainfall amounts: published rank | Top three | Tercile probabilities: published rank | Top three |
| --- | --- | --- | --- | --- |
| FMAM (Jan) | 17 of 31 | all-cycles DRN (4), FMAM+ONDJ DRN (4), pooled DRN (3) | 17 of 39 | PCR, FMAM+ONDJ DRN, all-cycles DRN (none confirmed) |
| FMAM (Feb) | 17 of 30 | all-cycles DRN, FMAM+ONDJ DRN (3), pooled DRN with neighbourhood inputs | 15 of 38 | square-root MVS (1), FMAM+ONDJ DRN (1), pooled DRN with neighbourhood inputs |
| JJAS (May) | 19 of 30 | pooled DRN with neighbourhood inputs (2), pooled DRN (2), pooled neural EMOS correction (2) | 6 of 38 | PCR, Variance Scaling, square-root MVS (gains ≤ 0.4, none confirmed) |
| ONDJ (Sep) | 21 of 31 | all-cycles DRN (1), FMAM+ONDJ DRN (1), square-root MVS (1) | 10 of 39 | square-root MVS, Linear Scaling, Local Intensity Scaling (none confirmed) |

**Rainfall amounts:** the neural networks lead in every season, with gains of 3–7 points.

**Tercile probabilities:**
- No method gains 2 points or more; the largest gain is square-root MVS in FMAM (Feb), +1.7.
- In JJAS and ONDJ every neural network ranks below the published approach.
- In JJAS the published approach is in practice the best.

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
  closest: better in 25 of 33 years, p 0.004 before adjustment, Holm 0.13, BH 0.085 (across all 30 methods).
- **Rainfall amounts, pooled:**
  - Holm: Variance Scaling, square-root MVS, gamma QM, quantile regression and the DRN are significantly better than the
    MVS-corrected ensemble. The largest pooled gains are quantile regression's (+2.4% of the climatology score, 28 of 33
    years) and the DRN's (+2.2%, 27 of 33), both mostly from better-calibrated ranges (docs/54).
  - Benjamini–Hochberg: the same five, plus EMOS.
- **Rainfall amounts, per target over 33 years:** square-root MVS is confirmed for 3 targets under Holm and 12 under BH;
  gamma QM for 2 and 8.
- **Statistical downscaling** (CCA, PCR, docs/53, version 2) is not better than the published approach when pooled: PCR's
  probabilities match it (−0.06%), CCA's are below (−1.2%), and both are below for amounts (−2.3%, −3.2%).

These results are sensitivity analyses on the Research overview. After seeing them the project lead switched the selection
rule to Benjamini–Hochberg within each benchmark family (section "Change of the multiple-testing correction"); the pooled
tests are not part of the rule.

