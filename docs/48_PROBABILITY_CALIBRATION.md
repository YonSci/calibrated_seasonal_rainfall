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
| 3 | `bjp` | Bayesian joint probability | rainfall distribution | CDF, quantiles, terciles | planned |
| 3 | `bma_precipitation` | Bayesian model averaging | rainfall distribution | CDF, quantiles, terciles | planned |
| 3 | `quantile_regression_forest` | Quantile regression forest | rainfall quantiles | distribution, terciles | planned |

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
  amount/interval product, with the published probabilities unchanged; any such product is your decision.
* Phase 3 (Bayesian joint probability, precipitation BMA, quantile regression forests) can reuse this distribution interface and
  benchmark.

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
* Zadrozny, B., & Elkan, C. (2002). Transforming classifier scores into accurate multiclass probability estimates. *Proceedings of
  the 8th ACM SIGKDD*, 694–699. https://doi.org/10.1145/775047.775151

DOI and proceedings links for the Phase 1 references checked on 2026-10-13; the Phase 2 references were added on 2026-10-13 without a separate online check.
