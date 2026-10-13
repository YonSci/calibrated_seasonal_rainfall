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
| 2 | `platt_ovr` | Platt (sigmoid), one-vs-rest + normalization | binary calibration | terciles | planned |
| 2 | `beta_ovr` | Beta calibration, one-vs-rest + normalization | binary calibration | terciles | planned |
| 2 | `isotonic_ovr` | Isotonic regression, one-vs-rest + normalization | binary calibration | terciles | planned |
| 2 | `emos_csg` | EMOS, censored shifted gamma | rainfall distribution | CDF, quantiles, terciles | planned |
| 2 | `extended_logistic` | Extended logistic regression | rainfall distribution | CDF, terciles | planned |
| 2 | `quantile_regression` | Regularized quantile regression | rainfall quantiles | quantiles, terciles | planned |
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

DOI and proceedings links checked on 2026-10-13.
