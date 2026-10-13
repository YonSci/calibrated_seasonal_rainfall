# 48 — Probability and rainfall-distribution calibration

Purpose: test whether a different *probability* method improves the tercile probabilities users receive, and — in later phases —
whether full rainfall-distribution models do better than the corrected ensemble. docs/47 answered a different question (which
*amount* correction); this work holds the amount correction fixed.

The implementation order below is a plan, not a ranking of performance on these data.

## 1. Plan

| Phase | Identifier | Method | Family | Output | Status |
| --- | --- | --- | --- | --- | --- |
| 1 | `pseudocount` | Pseudocount smoothing | baseline / stabilization | terciles | implemented |
| 1 | `climatology_blend` | Climatology blending (**incumbent**) | baseline / shrinkage | terciles | implemented |
| 1 | `temperature` | Temperature scaling | tercile calibration | terciles | implemented |
| 1 | `dirichlet` | Regularized Dirichlet calibration | tercile calibration | terciles | implemented |
| 1 | `multinomial_logistic` | Regularized multinomial logistic regression | tercile prediction | terciles | implemented |
| 1 | `ordinal_logistic` | Ordinal (cumulative-logit) logistic regression | tercile prediction | terciles | implemented |
| 2 | `platt_ovr` | Platt (sigmoid), one-vs-rest + normalization | binary calibration | terciles | implemented |
| 2 | `beta_ovr` | Beta calibration, one-vs-rest + normalization | binary calibration | terciles | implemented |
| 2 | `isotonic_ovr` | Isotonic regression, one-vs-rest + normalization | binary calibration | terciles | implemented |
| 2 | `emos_csg` | EMOS, censored shifted gamma | rainfall distribution | CDF, quantiles, terciles | implemented |
| 2 | `extended_logistic` | Extended logistic regression | rainfall distribution | CDF, terciles | implemented |
| 2 | `quantile_regression` | Regularized quantile regression | rainfall quantiles | quantiles, terciles | implemented |
| 3 | `bjp` | Bayesian joint probability | rainfall distribution | CDF, quantiles, terciles | implemented |
| 3 | `bma_precipitation` | Bayesian model averaging | rainfall distribution | CDF, quantiles, terciles | implemented |
| 3 | `quantile_regression_forest` | Quantile regression forest | rainfall quantiles | distribution, terciles | implemented |

Two pathways: **A** — fixed amount correction (MVS), replaced probability calibration (Phase 1 and the binary extensions);
**B** — raw ensemble or declared predictors → a predictive rainfall distribution → terciles, quantiles and intervals (the
distribution models). Applying a new calibrator after the blend would be a separately named composition; none is used here.

## 2. Phase 1 methods (`scripts/prob_calibration.py`)

Common interface: `fit(records, area)` → model; `predict(record, model)` → (cell, 3) probabilities, non-negative, summing to
one. A record is one training year over all cells: smoothed unblended probabilities `s` = (n<sub>k</sub> + α)/(M + 3α)
(α = 0.5), the training-year category frequencies `clim`, the observed category, and two ensemble predictors —
standardized ensemble mean z = (x̄ − μ<sub>obs</sub>)/σ<sub>obs</sub> and log spread ratio log(s<sub>ens</sub>/σ<sub>obs</sub>), with
μ<sub>obs</sub>, σ<sub>obs</sub> from the training CHIRPS. Every method is pooled over the cells of a target (one set of parameters per
target), with equal weight per year and area weight within a year.

| Identifier | Inputs | Multiclass strategy | Parameters (fitted by) | Output |
| --- | --- | --- | --- | --- |
| `pseudocount` | member counts | joint (counts) | α = 0.5 (fixed) | terciles; no CDF |
| `climatology_blend` | smoothed probabilities, climatology | joint | one λ per target (minimum RPS) | terciles; no CDF |
| `temperature` | log smoothed probabilities | joint (softmax) | one T in 0.25–4 (log loss) | terciles; preserves the leading category |
| `dirichlet` | log smoothed probabilities only | joint (softmax of a linear map) | 3×3 map + bias, identity-regularized (log loss) | terciles |
| `multinomial_logistic` | standardized mean, log spread ratio | joint (softmax; near = reference) | 6 coefficients, L2 = 0.001 on slopes (log loss) | terciles |
| `ordinal_logistic` | standardized mean, log spread ratio | ordinal: P(Y ≤ k) = logistic(θ<sub>k</sub> − x·β), θ<sub>1</sub> < θ<sub>2</sub> | 2 cutpoints + 2 slopes, L2 = 0.001 (log loss) | terciles |

Fallback: a method that cannot be fitted (no valid pairs, a missing category, optimizer failure) uses the incumbent for that
fold, and the fallback is counted in the results. Dirichlet calibration is not pseudocount smoothing; Dirichlet (log
probabilities only) and multinomial logistic (ensemble predictors only) are kept as distinct models.

## 3. Design (`scripts/prob_benchmark.py`, `config/probability_calibration/<cycle>.json`)

* **Pathway A, amount correction fixed:** the operational MVS (configurable, `amount_method`).
* **Outer leave-one-year-out over 1993–2016.** For the left-out year y, the amount correction and the terciles of each inner year
  z are fitted without y and z; every calibrator is fitted on these 23 inner out-of-fold records; the calibrated probabilities of
  year y are scored. Test years 2017–2024/2025: everything fitted on the training years (calibrators on their leave-one-year-out
  records), exploratory.
* **SEL (selection-aware):** for each outer year, the calibrator with the lowest inner cross-validated RPS (6 blocks of consecutive
  inner years; training years only) is used, so SEL's score includes the choice among the six methods.
* **Scores** (area-weighted per year over a region, equal years): tercile RPS/RPSS (primary), Brier scores and skill for below and
  above normal, log loss and its skill against climatology, reliability tables.
* **Tests:** each method against the incumbent, paired whole-year sign-flip, Holm across every method and target; SEL against the
  incumbent, Holm across the targets; "confirmed" also requires no harm over the test years.
* **Provenance:** commit, uncommitted-changes check on the dependency files, and the dependency fingerprint (also the checkpoint
  key per target).

## 4. Phase 1 results (national aggregate, all Ethiopia)

Full numbers: `outputs/probability_calibration/<cycle>/benchmark.json`; site section "Probability calibration". Run at commit 0849f44 (clean). Cells show RPSS over the outer leave-one-year-out 1993–2016 / over the test years (exploratory). No method or SEL is confirmed better than the incumbent in any cycle or target (Holm across 5 methods × 5 targets; SEL across the targets).


**January · FMAM**

| Method | Feb | Mar | Apr | May | FMAM |
| --- | --- | --- | --- | --- | --- |
| **Climatology blend (incumbent)** | +0.027 / +0.022 | +0.002 / +0.008 | +0.001 / +0.002 | +0.028 / +0.004 | +0.032 / +0.017 |
| Pseudocount smoothing | -0.093 / -0.116 | -0.111 / -0.067 | -0.027 / -0.029 | +0.026 / -0.025 | +0.034 / +0.009 |
| Temperature scaling | +0.009 / +0.027 | -0.012 / -0.002 | +0.003 / +0.001 | +0.022 / +0.008 | +0.032 / +0.017 |
| Dirichlet | +0.093 / -0.002 | -0.002 / +0.013 | +0.001 / +0.007 | +0.029 / -0.009 | +0.030 / +0.020 |
| Multinomial logistic | +0.076 / +0.012 | -0.017 / -0.002 | -0.009 / -0.001 | +0.014 / +0.000 | +0.022 / +0.009 |
| Ordinal logistic | +0.078 / +0.015 | -0.016 / -0.002 | -0.009 / -0.000 | +0.015 / +0.001 | +0.022 / +0.006 |
| SEL (chosen per year) | +0.081 / -0.002 | +0.002 / +0.008 | +0.003 / +0.001 | +0.019 / +0.004 | +0.029 / +0.009 |

SEL choices (most frequent, of 24): Feb: Dirichlet (23), Mar: Climatology blend (incumbent) (24), Apr: Temperature scaling (24), May: Climatology blend (incumbent) (15), FMAM: Pseudocount smoothing (23). Fitted temperature (1993–2016): Feb 4.00, Mar 4.00, Apr 4.00, May 3.40, FMAM 1.76.


**February · FMAM**

| Method | Feb | Mar | Apr | May | FMAM |
| --- | --- | --- | --- | --- | --- |
| **Climatology blend (incumbent)** | +0.126 / +0.056 | +0.011 / +0.029 | +0.009 / +0.012 | +0.008 / +0.026 | +0.021 / +0.059 |
| Pseudocount smoothing | +0.054 / -0.071 | -0.058 / +0.005 | -0.001 / +0.007 | -0.002 / +0.023 | +0.005 / +0.096 |
| Temperature scaling | +0.104 / +0.068 | +0.005 / +0.019 | +0.012 / +0.008 | +0.010 / +0.023 | +0.023 / +0.051 |
| Dirichlet | +0.164 / +0.049 | +0.013 / +0.046 | +0.007 / +0.012 | +0.003 / +0.021 | +0.015 / +0.050 |
| Multinomial logistic | +0.178 / +0.081 | -0.005 / +0.037 | -0.017 / +0.001 | -0.010 / +0.022 | +0.012 / +0.046 |
| Ordinal logistic | +0.178 / +0.076 | -0.006 / +0.036 | -0.016 / +0.004 | -0.008 / +0.022 | +0.013 / +0.044 |
| SEL (chosen per year) | +0.178 / +0.076 | +0.004 / +0.029 | +0.005 / +0.008 | -0.018 / +0.026 | +0.020 / +0.051 |

SEL choices (most frequent, of 24): Feb: Ordinal logistic (23), Mar: Temperature scaling (11), Apr: Temperature scaling (23), May: Temperature scaling (19), FMAM: Temperature scaling (22). Fitted temperature (1993–2016): Feb 3.48, Mar 4.00, Apr 4.00, May 4.00, FMAM 2.59.


**May · JJAS**

| Method | Jun | Jul | Aug | Sep | JJAS |
| --- | --- | --- | --- | --- | --- |
| **Climatology blend (incumbent)** | -0.000 / +0.010 | +0.014 / +0.042 | +0.012 / +0.041 | +0.003 / +0.008 | +0.027 / +0.039 |
| Pseudocount smoothing | -0.113 / -0.056 | -0.029 / +0.022 | -0.031 / +0.066 | -0.064 / -0.041 | -0.017 / +0.003 |
| Temperature scaling | -0.001 / +0.009 | +0.014 / +0.034 | +0.012 / +0.042 | +0.006 / +0.009 | +0.027 / +0.037 |
| Dirichlet | -0.007 / +0.012 | +0.008 / +0.042 | +0.009 / +0.040 | +0.001 / +0.010 | +0.024 / +0.035 |
| Multinomial logistic | -0.008 / +0.016 | +0.004 / +0.040 | +0.008 / +0.037 | -0.003 / +0.005 | +0.021 / +0.028 |
| Ordinal logistic | -0.008 / +0.016 | +0.004 / +0.040 | +0.007 / +0.038 | -0.003 / +0.005 | +0.020 / +0.029 |
| SEL (chosen per year) | -0.001 / +0.009 | +0.009 / +0.042 | +0.011 / +0.042 | +0.006 / +0.009 | +0.025 / +0.039 |

SEL choices (most frequent, of 24): Jun: Temperature scaling (24), Jul: Temperature scaling (15), Aug: Temperature scaling (22), Sep: Temperature scaling (24), JJAS: Temperature scaling (22). Fitted temperature (1993–2016): Jun 4.00, Jul 3.85, Aug 4.00, Sep 4.00, JJAS 3.36.


**September · ONDJ**

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| **Climatology blend (incumbent)** | +0.013 / +0.027 | +0.040 / +0.053 | +0.003 / +0.015 | +0.001 / -0.005 | +0.039 / +0.075 |
| Pseudocount smoothing | -0.009 / +0.012 | +0.044 / +0.041 | -0.068 / -0.049 | -0.213 / -0.300 | +0.035 / +0.065 |
| Temperature scaling | +0.016 / +0.027 | +0.027 / +0.042 | +0.004 / +0.007 | -0.031 / -0.098 | +0.043 / +0.078 |
| Dirichlet | +0.010 / +0.012 | +0.050 / +0.015 | +0.010 / +0.010 | +0.007 / +0.057 | +0.037 / +0.069 |
| Multinomial logistic | -0.003 / -0.005 | +0.062 / +0.060 | +0.008 / +0.027 | -0.016 / +0.031 | +0.034 / +0.064 |
| Ordinal logistic | -0.003 / -0.004 | +0.063 / +0.048 | +0.007 / +0.023 | -0.014 / +0.032 | +0.037 / +0.063 |
| SEL (chosen per year) | +0.016 / +0.027 | +0.051 / +0.060 | +0.002 / +0.015 | +0.001 / -0.005 | +0.043 / +0.078 |

SEL choices (most frequent, of 24): Oct: Temperature scaling (24), Nov: Multinomial logistic (12), Dec: Temperature scaling (12), Jan: Climatology blend (incumbent) (24), ONDJ: Temperature scaling (24). Fitted temperature (1993–2016): Oct 2.32, Nov 2.73, Dec 4.00, Jan 4.00, ONDJ 1.52.


### Findings

1. **The incumbent climatology blend is not beaten.** No Phase 1 method, and not the selection-aware SEL, is confirmed better than
   the blend for the published tercile probabilities in any cycle or target.
2. **The largest point gains are in the first forecast month of the FMAM cycles** (February): for the February initialization,
   multinomial and ordinal logistic regression reach RPSS +0.178 against +0.126 (Δ RPS −0.023, 15 of 24 years better, Holm p 0.31)
   and SEL +0.178 (Holm p 0.066 across the targets); for the January initialization Dirichlet calibration reaches +0.093 against
   +0.027 (Holm p 0.22). These are candidates worth revisiting as more years accumulate, not demonstrated improvements.
3. **Smoothed counts alone are much worse than the blend** (e.g. ONDJ January −0.213 against +0.001): the blend's shrinkage toward
   climatology is the part of the pipeline doing most of the work.
4. **Temperature scaling reaches its upper bound (T = 4) in most monthly targets**: the count probabilities are strongly
   over-confident, and a fixed bound limits how far temperature scaling can flatten them; the blend can move all the way to
   climatology.
5. **No fallbacks** occurred in any fold: every method could be fitted for every target.

### What this means

Keep the climatology blend as the probability stage. Phase 2 adds the one-vs-rest binary calibrators (Pathway A) and the first
full rainfall-distribution models (Pathway B), which change what is modelled rather than only how the counts are calibrated.


## 5. Phase 2 methods and design

### Pathway A: one-vs-rest binary calibrators (`prob_calibration.py`)

Each category k is calibrated as a binary event (category k against the rest) from the same smoothed, unblended probability
p<sub>k</sub>; the three calibrated values are then divided by their sum. The normalized vector is the forecast that is fitted, checked
(non-negative, sums to one) and scored — the normalization is part of the method, inside the validation. Inputs are floored at
10⁻⁴ before logs and normalization.

| Identifier | Binary map per category | Parameters |
| --- | --- | --- |
| `platt_ovr` | q<sub>k</sub> = logistic(c + a·logit p<sub>k</sub>) | 2 per category, L2 10⁻⁴ on a, log loss |
| `beta_ovr` | logit q<sub>k</sub> = c + a·ln p<sub>k</sub> − b·ln(1 − p<sub>k</sub>), a, b ≥ 0 | 3 per category, log loss |
| `isotonic_ovr` | monotone step map (weighted pool-adjacent-violators), constant beyond the data | pooled over cells and years (no cell-by-cell fitting) |

Design: as Phase 1 (`config/probability_calibration/<cycle>_phase2.json`), with the incumbent and the three calibrators as their
own family (Holm across 3 methods × 5 targets) and SEL among the four.

### Pathway B: rainfall-distribution models (`dist_calibration.py`, `dist_benchmark.py`)

Each model predicts a full distribution of the target's rainfall for every cell from the **raw** ensemble (the MVS correction is
not part of this pathway). One interface: `cdf(x)`, `quantile(u)`, `terciles(q1, q2)` at the training CHIRPS boundaries
(p<sub>below</sub> = F(q1), p<sub>near</sub> = F(q2) − F(q1), p<sub>above</sub> = 1 − F(q2); with q1 > 0 there is no atom at a boundary) and
`crps(y)` by numerical integration of (F(x) − 1{x ≥ y})². Pooling over cells: rainfall in units of the cell's training CHIRPS mean
(y' = y/μ<sub>obs</sub>); predictors relative to the raw ensemble's climatological mean μ<sub>model</sub> (equal-year weights): ensemble
mean m', standard deviation s', mean absolute difference md'. Cells with μ<sub>obs</sub> or μ<sub>model</sub> below 1 mm are not modelled.

| Identifier | Distribution | Parameters (fitting) | Zeros, tails, monotonicity |
| --- | --- | --- | --- |
| `emos_csg` | Y' = max(0, X + δ), X ~ Gamma with mean softplus(a₀ + a₁m') and sd softplus(b₀ + b₁md'), δ = −softplus(d) ≤ 0 | 5, weighted maximum likelihood | probability of 0 = G(−δ); gamma tail |
| `extended_logistic` | P(Y' ≤ q') = logistic((√q' − (b₀ + b₁√m'))/exp(g₀ + g₁ ln s')) | 4, log loss over each cell's 9 training CHIRPS deciles | coherent, monotone CDF in q by construction; closed-form quantiles |
| `quantile_regression` | q'<sub>τ</sub> = b₀τ + b₁τ m' + b₂τ s' at τ = 0.05…0.95 | 3 per level, pinball loss (Huber-smoothed, 10⁻³), L2 10⁻⁴ | non-crossing by rearrangement (share of crossing cells reported), clipped at 0; F linear from 0 below q<sub>0.05</sub> and to 1 at q<sub>0.95</sub> + (q<sub>0.95</sub> − q<sub>0.5</sub>) |

Design (`config/probability_calibration/<cycle>_distribution.json`): outer leave-one-year-out over the training years (each model
fitted on the other training years only, pooled, equal weight per year), test years from a fit on all training years. In the same
folds: the published probabilities (incumbent, blend weight from the inner out-of-fold years) and the MVS-corrected ensemble.
Scores: tercile RPS/RPSS (against the incumbent), CRPS/CRPSS (against the MVS-corrected ensemble), pinball loss at 10/50/90 %,
coverage of the 10–90 % interval. Tests: Holm across the 3 models × 5 targets, separately for RPS and CRPS; no harm over the test
years.

## 6. Phase 2 results (national aggregate, all Ethiopia)

Full numbers: `outputs/probability_calibration/<cycle>/phase2_binary/benchmark.json` and `.../distribution/benchmark.json`; site section "Probability calibration". Run at commit 6d8236d (clean). ✓ = confirmed better than the reference (Holm-adjusted p < 0.05 across the family, and not worse over the test years).

### Pathway A — binary calibrators: tercile RPSS, outer leave-one-year-out 1993–2016

**January · FMAM**

| Method | Feb | Mar | Apr | May | FMAM |
| --- | --- | --- | --- | --- | --- |
| Climatology blend (incumbent) | +0.027 | +0.002 | +0.001 | +0.028 | +0.032 |
| Platt OvR | +0.032 | +0.001 | +0.003 | +0.026 | +0.032 |
| Beta OvR | +0.064 | +0.001 | -0.000 | +0.031 | +0.029 |
| Isotonic OvR | -0.032 | -0.033 | -0.004 | +0.033 | +0.028 |
| SEL (chosen each year) | +0.064 | +0.005 | +0.001 | +0.028 | +0.032 |

**February · FMAM**

| Method | Feb | Mar | Apr | May | FMAM |
| --- | --- | --- | --- | --- | --- |
| Climatology blend (incumbent) | +0.126 | +0.011 | +0.009 | +0.008 | +0.021 |
| Platt OvR | +0.135 | +0.008 | +0.011 | +0.007 | +0.020 |
| Beta OvR | +0.143 | +0.015 | +0.008 | +0.007 | +0.017 |
| Isotonic OvR | +0.061 | +0.017 | +0.002 | +0.010 | +0.018 |
| SEL (chosen each year) | +0.137 | +0.014 | +0.009 | +0.008 | +0.021 |

**May · JJAS**

| Method | Jun | Jul | Aug | Sep | JJAS |
| --- | --- | --- | --- | --- | --- |
| Climatology blend (incumbent) | -0.000 | +0.014 | +0.012 | +0.003 | +0.027 |
| Platt OvR | -0.001 | +0.012 | +0.009 | +0.003 | +0.026 |
| Beta OvR | -0.004 | +0.010 | +0.009 | +0.001 | +0.024 |
| Isotonic OvR | -0.014 | +0.006 | +0.008 | +0.000 | +0.022 |
| SEL (chosen each year) | -0.000 | +0.014 | +0.012 | +0.003 | +0.027 |

**September · ONDJ**

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| Climatology blend (incumbent) | +0.013 | +0.040 | +0.003 | +0.001 | +0.039 |
| Platt OvR | +0.015 | +0.049 | +0.013 | +0.006 | +0.042 |
| Beta OvR | +0.013 | +0.050 | +0.010 | +0.008 | +0.039 |
| Isotonic OvR | +0.009 | +0.049 | +0.008 | -0.039 | +0.039 |
| SEL (chosen each year) | +0.013 | +0.044 | +0.002 | +0.002 | +0.039 |

### Pathway B — rainfall-distribution models, outer leave-one-year-out 1993–2016

Cells: tercile RPSS / amount CRPSS / share of observations inside the 10–90 % interval (80 % is calibrated). The first row gives the published probabilities' RPSS and the MVS-corrected ensemble's CRPSS and coverage. Pathway B is scored on the cells where the distribution models are defined (non-zero training climatology), so the incumbent's RPSS differs slightly from the Pathway A table.

**January · FMAM**

| Method | Feb | Mar | Apr | May | FMAM |
| --- | --- | --- | --- | --- | --- |
| Published pipeline (incumbent / MVS ensemble) | +0.033 / +0.074 / 56% | +0.002 / -0.044 / 54% | +0.001 / -0.016 / 68% | +0.028 / +0.007 / 69% | +0.032 / +0.025 / 72% |
| EMOS (CSG) | +0.043 / +0.074 / 82% | -0.065 / -0.026 / 81% | -0.001 / +0.005 / 77% | +0.026 / +0.014 / 78% | +0.037 / +0.039 ✓ / 78% |
| Extended logistic | +0.065 / +0.072 / 89% | -0.065 / -0.076 / 92% | -0.000 / -0.005 / 84% | +0.027 / -0.004 / 85% | +0.031 / +0.032 / 83% |
| Quantile regression | +0.039 / +0.104 / 78% | -0.052 / -0.018 / 77% | -0.001 / +0.004 / 77% | +0.028 / +0.012 / 77% | +0.030 / +0.033 / 77% |

**February · FMAM**

| Method | Feb | Mar | Apr | May | FMAM |
| --- | --- | --- | --- | --- | --- |
| Published pipeline (incumbent / MVS ensemble) | +0.137 / +0.250 / 55% | +0.011 / -0.034 / 59% | +0.009 / -0.001 / 68% | +0.008 / -0.005 / 67% | +0.021 / -0.007 / 70% |
| EMOS (CSG) | +0.103 / +0.248 / 83% | -0.043 / -0.013 / 81% | -0.003 / +0.003 / 76% | -0.008 / -0.003 / 78% | +0.028 / +0.026 / 79% |
| Extended logistic | +0.168 / +0.234 / 90% | -0.038 / -0.067 / 91% | +0.004 / -0.008 / 84% | -0.007 / -0.023 / 84% | +0.021 / +0.017 / 84% |
| Quantile regression | +0.099 / +0.259 / 78% | -0.021 / -0.010 / 77% | -0.006 / +0.000 / 77% | -0.008 / -0.004 / 77% | +0.023 / +0.020 / 77% |

**May · JJAS**

| Method | Jun | Jul | Aug | Sep | JJAS |
| --- | --- | --- | --- | --- | --- |
| Published pipeline (incumbent / MVS ensemble) | -0.000 / -0.096 / 65% | +0.015 / -0.005 / 73% | +0.012 / -0.027 / 75% | +0.003 / -0.060 / 71% | +0.027 / -0.028 / 70% |
| EMOS (CSG) | -0.045 / -0.031 / 84% | -0.004 / +0.018 / 81% | -0.014 / -0.004 / 83% | -0.013 / -0.006 ✓ / 82% | +0.003 / +0.017 / 81% |
| Extended logistic | -0.052 / -0.054 / 90% | -0.003 / +0.013 / 86% | -0.008 / -0.010 / 88% | -0.018 / -0.017 / 87% | +0.005 / +0.007 / 87% |
| Quantile regression | -0.052 / -0.015 / 78% | -0.013 / +0.014 / 78% | -0.030 / -0.004 / 78% | -0.020 / -0.001 ✓ / 78% | +0.001 / +0.014 / 78% |

**September · ONDJ**

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| Published pipeline (incumbent / MVS ensemble) | +0.013 / -0.002 / 72% | +0.040 / +0.084 / 75% | +0.003 / +0.029 / 76% | +0.001 / -0.040 / 46% | +0.039 / +0.070 / 75% |
| EMOS (CSG) | +0.003 / +0.016 / 77% | +0.037 / +0.071 / 78% | -0.113 / +0.015 / 84% | -0.060 / -0.029 / 80% | +0.029 / +0.049 / 79% |
| Extended logistic | -0.000 / -0.011 / 90% | +0.032 / +0.058 / 89% | -0.076 / -0.017 / 92% | -0.040 / -0.023 / 89% | +0.030 / +0.062 / 83% |
| Quantile regression | -0.010 / -0.010 / 77% | +0.017 / +0.056 / 77% | -0.143 / +0.033 / 79% | -0.064 / -0.036 / 77% | +0.019 / +0.032 / 76% |

### Findings

1. **Pathway A: no binary calibrator is confirmed better than the incumbent blend** in any cycle or target (Holm across 3 methods
   × 5 targets; SEL across the targets). The largest point gains are again in February of the FMAM cycles (beta calibration:
   January-initialized +0.064 against +0.027, February-initialized +0.143 against +0.126) and in ONDJ November and December
   (Platt +0.049 and +0.013 against +0.040 and +0.003); none is significant. In JJAS no calibrator improves on the blend.
   Isotonic regression is the weakest (January-initialized February −0.032, ONDJ January −0.039): the step map overfits in the
   short pooled record, as the plan anticipated.
2. **Pathway B, tercile probabilities: no distribution model is confirmed better than the published probabilities.** Extended
   logistic regression comes closest in February (+0.168 against +0.137 February-initialized; +0.065 against +0.033
   January-initialized), not significant. Elsewhere the models are usually worse for terciles, clearly so in March, JJAS June
   and ONDJ December (down to −0.14).
3. **Pathway B, rainfall amounts: three confirmed improvements in CRPS over the MVS-corrected ensemble** — EMOS for the
   January-initialized FMAM season (+0.039 against +0.025), and EMOS and quantile regression for JJAS September (−0.006 and
   −0.001 against −0.060). Larger but unconfirmed gains: JJAS June (quantile regression −0.015 against −0.096), the
   February-initialized FMAM season (EMOS +0.026 against −0.007). The MVS ensemble stays better in ONDJ November and the ONDJ season.
4. **The distribution models' intervals are close to calibrated; the MVS ensemble's are too narrow.** The 10–90 % interval of the
   MVS-corrected ensemble contains 46–76 % of observations (80 % is calibrated; lowest in ONDJ January and FMAM February/March);
   EMOS 76–84 %, quantile regression 76–79 %, extended logistic 83–92 % (somewhat wide).
5. **Fits are coherent:** every model converged in every fold, and quantile regression needed rearrangement for at most 2.2 % of
   cells (mean share per target).

### What this means

* Keep the incumbent climatology blend for the published tercile probabilities: neither Phase 1 nor Phase 2 beats it.
* For **rainfall amounts and ranges**, the distribution models (EMOS in particular) give near-calibrated intervals where the MVS
  ensemble's are too narrow, and are confirmed better in CRPS for some targets. This makes them candidates for a separate
  amount/interval product, with the published probabilities unchanged; any such product is a separate decision.
* Phase 3 (Bayesian joint probability, precipitation BMA, quantile regression forests) reuses this distribution interface and
  benchmark (sections 7–8); the shadow amount and range forecast (section 9) collects independent seasons for EMOS.

## 7. Phase 3 methods and design (`dist_calibration.py`)

Same interface, pooling and benchmark as Phase 2 (`config/probability_calibration/<cycle>_phase3.json`, Holm across these three
models × 5 targets, separately for RPS and CRPS). Predictors are computed from the training years of each fold only.

| Identifier | Model | Parameters (fitting) | Notes |
| --- | --- | --- | --- |
| `bjp` | Bayesian joint probability: m' and y' each log-sinh transformed, z = log(sinh(a + b·x))/b; in transformed space z<sub>y</sub> = c<sub>0</sub> + c<sub>1</sub>·d + e, d the standardized transformed ensemble mean, e ~ N(0, s²); y' = 0 left-censored at the transform of zero | 4 (predictor) + 5 (observation), weighted censored maximum likelihood with the Jacobian (posterior mode under flat priors) | parameter uncertainty of the normal model integrated analytically under the reference prior with the number of training years as the effective sample (cells of one year are not independent): Student-t predictive, ν = years − 2, scale s·√(1 + 1/years + d²/years). b is bounded below at e⁻⁵, where the log-sinh approaches a shifted log transform |
| `bma_precipitation` | BMA for precipitation, exchangeable members with equal weights: per member f', P(Y' = 0) = logistic(a<sub>0</sub> + a<sub>1</sub>f'<sup>1/3</sup> + a<sub>2</sub>·1{f' = 0}); given Y' > 0, Y'<sup>1/3</sup> ~ Gamma with mean softplus(b<sub>0</sub> + b<sub>1</sub>f'<sup>1/3</sup>) and variance softplus(c<sub>0</sub>) + softplus(c<sub>1</sub>)·f' | 7, joint weighted maximum likelihood of the mixture (analytic gradient, checked numerically in the tests) | equal weights because SEAS5 members are exchangeable (Fraley et al. 2010); 25 members in training, 51 in the test years (the mixture takes whatever members a year has); quantiles by bisection |
| `quantile_regression_forest` | Quantile regression forest: 200 trees, ≥ 40 samples per leaf, half the predictors per split, sample weights = equal-year area weights | predictors m', s', md', the ensemble's relative 10 % and 90 % quantiles, log climatological mean, CHIRPS coefficient of variation | predictive distribution = all training amounts weighted by leaf co-membership (Meinshausen 2006), at 39 levels (2.5–97.5 %); piecewise-linear CDF as for quantile regression. scikit-learn 1.5.2 (random seed 0) |

## 8. Phase 3 results (national aggregate, all Ethiopia)

Full numbers: `outputs/probability_calibration/<cycle>/phase3/benchmark.json`; site section "Probability calibration". The runs
started from commit 56a067d and were saved at 583cc4c (FMAM cycles) and 03feb0f (JJAS, ONDJ), all clean; the benchmark's code
and configuration files are identical in the three commits. Cells: tercile RPSS / amount CRPSS / share of observations inside
the 10–90 % interval (80 % is calibrated), outer leave-one-year-out 1993–2016; the first row gives the published probabilities'
RPSS and the MVS-corrected ensemble's CRPSS and coverage, as in Phase 2. ✓ = confirmed better than that reference (Holm across
3 models × 5 targets, separately for RPS and CRPS; not worse over the test years).

**January · FMAM**

| Method | Feb | Mar | Apr | May | FMAM |
| --- | --- | --- | --- | --- | --- |
| Published pipeline (incumbent / MVS ensemble) | +0.033 / +0.074 / 56% | +0.002 / -0.044 / 54% | +0.001 / -0.016 / 68% | +0.028 / +0.007 / 69% | +0.032 / +0.025 / 72% |
| Bayesian joint probability | +0.026 / +0.085 / 83% | -0.088 / -0.048 / 82% | -0.005 / -0.018 / 81% | +0.019 / -0.016 / 81% | +0.030 / +0.019 / 82% |
| BMA (precipitation) | +0.014 / +0.084 / 82% | -0.037 / -0.014 / 81% | -0.010 / -0.011 / 82% | +0.030 / +0.008 / 84% | +0.044 / +0.044 / 80% |
| Quantile regression forest | +0.028 / +0.018 / 74% | -0.107 / -0.100 / 71% | -0.087 / -0.071 / 72% | -0.027 / -0.033 / 73% | -0.025 / -0.022 / 72% |

**February · FMAM**

| Method | Feb | Mar | Apr | May | FMAM |
| --- | --- | --- | --- | --- | --- |
| Published pipeline (incumbent / MVS ensemble) | +0.137 / +0.250 / 55% | +0.011 / -0.034 / 59% | +0.009 / -0.001 / 68% | +0.008 / -0.005 / 67% | +0.021 / -0.007 / 70% |
| Bayesian joint probability | +0.124 / +0.222 / 85% | -0.071 / -0.041 / 82% | -0.008 / -0.021 / 80% | -0.011 / -0.029 / 81% | +0.019 / +0.007 / 82% |
| BMA (precipitation) | +0.123 / +0.237 / 84% | -0.011 / +0.001 / 81% | +0.006 / +0.001 / 82% | +0.015 / -0.003 / 83% | +0.034 / +0.030 / 79% |
| Quantile regression forest | +0.154 / +0.261 / 76% | -0.120 / -0.121 / 71% | -0.047 / -0.034 / 72% | -0.081 / -0.067 / 71% | -0.050 / -0.051 / 71% |

**May · JJAS**

| Method | Jun | Jul | Aug | Sep | JJAS |
| --- | --- | --- | --- | --- | --- |
| Published pipeline (incumbent / MVS ensemble) | -0.000 / -0.096 / 65% | +0.015 / -0.005 / 73% | +0.012 / -0.027 / 75% | +0.003 / -0.060 / 71% | +0.027 / -0.028 / 70% |
| Bayesian joint probability | -0.061 / -0.121 / 86% | -0.016 / -0.034 / 85% | -0.033 / -0.075 / 85% | -0.033 / -0.066 / 85% | -0.020 / -0.101 / 86% |
| BMA (precipitation) | -0.062 / -0.083 / 85% | -0.024 / -0.046 / 83% | -0.050 / -0.055 / 81% | -0.038 / -0.063 / 82% | +0.001 / -0.002 / 82% |
| Quantile regression forest | -0.088 / -0.065 / 74% | -0.050 / -0.013 / 74% | -0.042 / -0.021 / 76% | -0.067 / -0.045 / 74% | -0.045 / -0.021 / 73% |

**September · ONDJ**

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| Published pipeline (incumbent / MVS ensemble) | +0.013 / -0.002 / 72% | +0.040 / +0.084 / 75% | +0.003 / +0.029 / 76% | +0.001 / -0.040 / 46% | +0.039 / +0.070 / 75% |
| Bayesian joint probability | -0.030 / -0.041 / 81% | +0.013 / +0.048 / 81% | -0.126 / +0.014 / 83% | -0.058 / -0.010 / 81% | +0.017 / +0.042 / 79% |
| BMA (precipitation) | -0.004 / +0.010 / 80% | +0.036 / +0.073 / 80% | -0.152 / +0.021 / 79% | -0.033 / -0.002 / 78% | +0.042 / +0.069 / 80% |
| Quantile regression forest | -0.046 / -0.056 / 73% | +0.010 / +0.015 / 72% | -0.129 / -0.054 / 75% | -0.119 / -0.085 / 72% | -0.008 / -0.052 / 69% |

### Findings

1. **No Phase 3 model is confirmed better** than the published probabilities (tercile RPS) or the MVS-corrected ensemble
   (amount CRPS), in any cycle or target.
2. **BMA for precipitation is the strongest of the three.** Its CRPSS is above the MVS ensemble's in 13 of 20 targets (largest:
   January-initialized FMAM season +0.044 against +0.025, Holm p 0.12; February-initialized FMAM season +0.030 against −0.007), and
   its RPSS above the published probabilities' in 5 of 20, but none of these differences is significant, and over the test years
   its CRPSS is higher in only 7 of 20. In Phase 2, EMOS was confirmed better in CRPS for two targets; BMA is not.
3. **Bayesian joint probability gives calibrated ranges (79–86 % inside the 10–90 % interval) but not better forecasts**: its RPSS
   is below the published probabilities' in all 20 targets and its CRPSS above the MVS ensemble's in 3. A likely reason is that it
   uses only the ensemble mean, so the predicted spread does not follow the forecast's own spread.
4. **The quantile regression forest is the weakest**: CRPSS above the MVS ensemble's in 5 of 20 targets, RPSS above the published
   probabilities' in 1, and its ranges are too narrow (69–76 %). Its flexibility does not pay off with 23 training years per
   fold: its best result (February-initialized February, +0.261 against +0.250) falls below the MVS ensemble over the test years.
5. **Intervals:** BJP 79–86 %, BMA 78–85 %, the forest 69–76 %, against 46–76 % for the MVS ensemble.
6. **Fits:** BMA and the forest converged in every fold. BJP's optimizer reached its iteration limit in some folds, on a flat
   ridge of the log-sinh parameters (where the transform tends to a shifted log); a much more thorough refit of one such case
   (January-initialized March, fit 1993–2016) improves the objective only in the seventh significant digit, changes the predicted
   quantiles by less than 0.02 % and leaves the CRPS of 2017–2020 unchanged.

### What this means

* Across Phases 1–3 (15 methods), nothing is confirmed better than the incumbent climatology blend for the published tercile
  probabilities: keep it.
* For rainfall amounts and ranges, EMOS (Phase 2) remains the best-supported distribution model and the one in the shadow
  forecast (section 9); BMA is a close, unconfirmed alternative. Any amount or range product remains a separate decision after
  the shadow has several scored seasons.

## 9. Shadow rainfall-amount and range forecast (`scripts/dist_shadow.py`)

**Not a published forecast.** Phase 2 showed that the distribution models' 10–90 % ranges are close to calibrated where the
MVS-corrected ensemble's are too narrow. To build independent evidence before any amount or range product is considered, every
cycle also runs EMOS (configured in `config/probability_calibration/amount_shadow.json`; automatic stage `amount_shadow` in
`run_operational.py`):

* EMOS is fitted on the cycle's reference years (as the published forecast), pooled over the national cells exactly as in the
  benchmark, and predicts each target's 10 %, 50 % and 90 % quantiles (mm) and tercile probabilities for the forecast year; the
  MVS-corrected ensemble's quantiles are stored next to them.
* Once CHIRPS is prepared for a target, both are scored (CRPS, coverage of the 10–90 % range, pinball losses), and the shadow's
  tercile probabilities are scored against the published probabilities (RPS). These seasons were not used to build or select
  anything.
* Files: `outputs/probability_calibration/<cycle>/amount_shadow/<year>/` — `emos_csg__<target>.json` (scores, fitted parameters,
  provenance; reused while the dependency fingerprint is unchanged), `shadow_emos_csg_<year>_<target>.nc` and `.png`.

### Results so far: 2026 forecasts (national area-weighted means over the modelled cells)

Forecast: median (10–90 % range) in mm, shadow EMOS / MVS-corrected ensemble. Scored targets: share of observations inside the 10–90 % range (80 % is calibrated) and amount CRPSS against the CHIRPS climatology, shadow / MVS. One season each.

| Cycle | Target | Shadow (EMOS) | MVS ensemble | Coverage | CRPSS |
| --- | --- | --- | --- | --- | --- |
| January · FMAM | Feb | 18 (6–40) | 15 (10–39) | 89 % / 63 % | -0.319 / -0.207 |
| January · FMAM | Mar | 50 (13–131) | 47 (26–116) | 78 % / 60 % | +0.164 / +0.101 |
| January · FMAM | Apr | 86 (33–176) | 85 (38–171) | 82 % / 81 % | +0.010 / +0.014 |
| January · FMAM | May | 98 (47–170) | 98 (57–158) | 94 % / 87 % | +0.017 / +0.032 |
| January · FMAM | FMAM | 266 (165–402) | 267 (170–396) | 88 % / 84 % | -0.027 / -0.066 |
| February · FMAM | Feb | 14 (5–31) | 14 (10–27) | 92 % / 58 % | -0.002 / +0.018 |
| February · FMAM | Mar | 45 (12–118) | 48 (22–106) | 64 % / 52 % | +0.078 / +0.067 |
| February · FMAM | Apr | 101 (44–197) | 119 (59–197) | 76 % / 65 % | -0.185 / -0.486 |
| February · FMAM | May | 100 (45–182) | 99 (52–172) | 95 % / 89 % | -0.051 / -0.032 |
| February · FMAM | FMAM | 286 (186–420) | 301 (206–413) | 88 % / 72 % | -0.017 / -0.091 |
| May · JJAS | Jun | 81 (45–132) | 71 (49–100) | 70 % / 68 % | +0.225 / +0.404 |
| May · JJAS | Jul | 151 (101–212) | 138 (96–184) | 63 % / 62 % | +0.151 / +0.228 |
| May · JJAS | Aug | 149 (104–206) | 137 (102–180) | 75 % / 73 % | +0.269 / +0.431 |
| May · JJAS | Sep | 103 (61–161) | 93 (58–141) | awaiting CHIRPS | awaiting CHIRPS |
| May · JJAS | JJAS | 473 (373–593) | 430 (345–515) | awaiting CHIRPS | awaiting CHIRPS |
| September · ONDJ | Oct | 78 (30–170) | 87 (38–160) | awaiting CHIRPS | awaiting CHIRPS |
| September · ONDJ | Nov | 55 (18–127) | 55 (17–133) | awaiting CHIRPS | awaiting CHIRPS |
| September · ONDJ | Dec | 12 (3–37) | 12 (5–39) | awaiting CHIRPS | awaiting CHIRPS |
| September · ONDJ | Jan | 17 (6–41) | 15 (9–40) | awaiting CHIRPS | awaiting CHIRPS |
| September · ONDJ | ONDJ | 176 (90–306) | 181 (94–313) | awaiting CHIRPS | awaiting CHIRPS |

Of the 13 targets observed so far, the EMOS range is closer to calibrated coverage in 9 and EMOS has the higher CRPSS in 5; the MVS ensemble is clearly better in CRPS for JJAS June–August 2026. One season per target is not evidence for a change; the record grows with each cycle.

## References

* Guo, C., Pleiss, G., Sun, Y., & Weinberger, K. Q. (2017). On calibration of modern neural networks. *Proceedings of the 34th
  International Conference on Machine Learning*, PMLR 70, 1321–1330. https://proceedings.mlr.press/v70/guo17a.html
* Kull, M., Perello-Nieto, M., Kängsepp, M., Silva Filho, T., Song, H., & Flach, P. (2019). Beyond temperature scaling:
  obtaining well-calibrated multiclass probabilities with Dirichlet calibration. *NeurIPS 2019*. https://arxiv.org/abs/1910.12656
* McCullagh, P. (1980). Regression models for ordinal data. *Journal of the Royal Statistical Society, Series B*, 42, 109–127.
  https://doi.org/10.1111/j.2517-6161.1980.tb01109.x
* Rajagopalan, B., Lall, U., & Zebiak, S. E. (2002). Categorical climate forecasts through regularization and optimal
  combination of multiple GCM ensembles. *Monthly Weather Review*, 130, 1792–1811.
  https://doi.org/10.1175/1520-0493(2002)130<1792:CCFTRA>2.0.CO;2
* Wilks, D. S. (2019). *Statistical Methods in the Atmospheric Sciences* (4th ed.). Elsevier.
* Kull, M., Silva Filho, T., & Flach, P. (2017). Beta calibration: a well-founded and easily implemented improvement on logistic
  calibration for binary classifiers. *Proceedings of AISTATS 2017*, PMLR 54. https://proceedings.mlr.press/v54/kull17a.html
* Koenker, R., & Bassett, G. (1978). Regression quantiles. *Econometrica*, 46, 33–50. https://doi.org/10.2307/1913643
* Messner, J. W., Mayr, G. J., Zeileis, A., & Wilks, D. S. (2014). Heteroscedastic extended logistic regression for postprocessing of
  ensemble guidance. *Monthly Weather Review*, 142, 448–456. https://doi.org/10.1175/MWR-D-13-00271.1
* Platt, J. C. (1999). Probabilistic outputs for support vector machines and comparisons to regularized likelihood methods. In
  *Advances in Large Margin Classifiers* (pp. 61–74). MIT Press.
* Scheuerer, M., & Hamill, T. M. (2015). Statistical postprocessing of ensemble precipitation forecasts by fitting censored, shifted
  gamma distributions. *Monthly Weather Review*, 143, 4578–4596. https://doi.org/10.1175/MWR-D-15-0061.1
* Wilks, D. S. (2009). Extending logistic regression to provide full-probability-distribution MOS forecasts. *Meteorological
  Applications*, 16, 361–368. https://doi.org/10.1002/met.134
* Fraley, C., Raftery, A. E., & Gneiting, T. (2010). Calibrating multimodel forecast ensembles with exchangeable and missing
  members using Bayesian model averaging. *Monthly Weather Review*, 138, 190–202. https://doi.org/10.1175/2009MWR3046.1
* Meinshausen, N. (2006). Quantile regression forests. *Journal of Machine Learning Research*, 7, 983–999.
  https://jmlr.org/papers/v7/meinshausen06a.html
* Sloughter, J. M., Raftery, A. E., Gneiting, T., & Fraley, C. (2007). Probabilistic quantitative precipitation forecasting using
  Bayesian model averaging. *Monthly Weather Review*, 135, 3209–3220. https://doi.org/10.1175/MWR3441.1
* Wang, Q. J., & Robertson, D. E. (2011). Multisite probabilistic forecasting of seasonal flows for streams with zero value
  occurrences. *Water Resources Research*, 47, W02546. https://doi.org/10.1029/2010WR009333
* Wang, Q. J., Robertson, D. E., & Chiew, F. H. S. (2009). A Bayesian joint probability modeling approach for seasonal forecasting
  of streamflows at multiple sites. *Water Resources Research*, 45, W05407. https://doi.org/10.1029/2008WR007355
* Wang, Q. J., Shrestha, D. L., Robertson, D. E., & Pokhrel, P. (2012). A log-sinh transformation for data normalization and
  variance stabilization. *Water Resources Research*, 48, W05514. https://doi.org/10.1029/2011WR010973
* Zadrozny, B., & Elkan, C. (2002). Transforming classifier scores into accurate multiclass probability estimates. *Proceedings of
  the 8th ACM SIGKDD*, 694–699. https://doi.org/10.1145/775047.775151

DOI and proceedings links for the Phase 1 references checked on 2026-10-13; the Phase 2 and 3 references were added on 2026-10-13 and 2026-10-14 without a separate online check.
