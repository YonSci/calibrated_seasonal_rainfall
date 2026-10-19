# Statistical downscaling by model output statistics (MOS): CCA and PCR against the published pipeline

Model output statistics as in CPT / PyCPT, the tools ICPAC and IRI use for regional seasonal outlooks. The large-scale pattern
of the SEAS5 forecast is related statistically to the observed CHIRPS pattern over the training years, and the relation is
applied to the new forecast. Two methods are tested in every cycle against the published pipeline, with the same data,
cross-validation and tests as the other benchmarks (docs/47, docs/48):
- canonical correlation analysis (CCA);
- principal component regression (PCR).

Script: `scripts/mos_benchmark.py`; configurations `config/mos/<cycle>.json`; results `outputs/mos/<cycle>/`; site:
*Research › Statistical downscaling*. **Nothing here changes the published forecast.**

## 1. Method in brief

- **Predictor:** SEAS5 ensemble-mean rainfall over the whole model box (3–15° N, 33–48° E), averaged to its 1° cells: 180
  predictors.
- **Predictand:** CHIRPS at every 0.25° cell of Ethiopia.
- **Transform:** both are square-root rainfall, standardized per cell (or predictor) with the training years.
- **CCA:** EOF pre-filtering of the predictor (up to 6 modes) and of the predictand (up to 6 modes), then up to 3 canonical
  modes between their leading principal components. The predicted predictand PCs are mapped back through the EOF patterns.
- **PCR:** every CHIRPS cell regressed on the leading predictor principal components (up to 6).
- **Choice of modes:** inner leave-one-year-out cross-validation inside each fold. The choice minimizes the mean normalized
  squared error over the cells with year-to-year variation.
- **Predictive distribution:** Gaussian in square-root space, with the cross-validated error of the chosen modes. Tercile
  probabilities come from it; amounts, the median and 10–90% ranges from 51 of its quantiles, squared back.

**Differences from operational CPT setups.** The predictor here is SEAS5 rainfall over the model box only: sea-surface
temperature and larger domains are not available in the project. The predictive distribution is Gaussian in square-root
space, not CPT's transformed-gamma option.

## 2. Implementation

Each step below names the function in `scripts/mos_benchmark.py` that does it. Notation: n training years, p predictors,
q predictand cells; for a matrix, rows are years.

### 2.1 Data (`predictor`, `run_target`)

- **Forecast:** for each year, the SEAS5 ensemble mean of the target's rainfall on the 0.25° model grid, square-rooted, then
  averaged over blocks of 4 × 4 cells (`settings.block`), ignoring missing cells: one value per 1° cell, p = 180.
  The mean is over the members the archive holds for that year: 25 for 1993–2016, 51 from 2017 (the test years and the
  2026 forecast). From 2027 the cycles use the first 25 members (docs/52).
- **Observation:** CHIRPS v3.0 for the same target at every 0.25° cell of the national mask
  (`data/masks/ethiopia_common.nc`), square-rooted. Dry cells are kept in the fit (see 2.4 and 2.6 for how they are kept out
  of the mode choice and the scores).
- **Targets:** the four months and the season of each cycle, each fitted separately.

### 2.2 Standardization and EOFs (`MOS._standardize`, `MOS._fit_core`)

With the training years only:

```
mean and standard deviation per column:   mx, sx (predictor),  my, sy (predictand); a standard deviation ≤ 1e-6 is set to 1
standardized fields:                       Xz = (X − mx) / sx,   Yz = (Y − my) / sy
singular value decompositions:             Xz = Ux Sx Vxᵀ,       Yz = Uy Sy Vyᵀ
principal components (unit variance):      Xpc = √n Ux,          Ypc = √n Uy
predictand loadings:                       Yload = Sy Vyᵀ / √n,  so that Yz = Ypc Yload
```

For a new year x, its first m predictor PCs are `xpc = (x − mx)/sx · Vx[:m]ᵀ / Sx[:m] · √n`. The decompositions are computed
once per fit and shared by every combination of modes.

### 2.3 Principal component regression (`MOS._predict_core`, PCR branch)

With m predictor PCs, every predictand cell is regressed on them by least squares. Because the PCs are centred, uncorrelated
and of unit variance over the training years, the coefficients are simply their covariances with the cells:

```
B = Xpc[:, :m]ᵀ Yz / n            (m × q)
ŷz = xpc B
```

The standardized prediction is returned to square-root rainfall: `μ = my + sy · ŷz`. One choice: m (1–6).

### 2.4 Canonical correlation analysis (`MOS._predict_core`, CCA branch)

With m predictor PCs, l predictand PCs and k canonical modes (k ≤ min(m, l, 3)):

```
cross-covariance of the two PC sets:   C = Xpc[:, :m]ᵀ Ypc[:, :l] / n            (m × l)
its singular value decomposition:       C = A diag(r) Bᵀ
predicted predictand PCs:               ŷpc = xpc A[:, :k] diag(r[:k]) B[:, :k]ᵀ
back to the cells:                      ŷz = ŷpc Yload[:l],   μ = my + sy · ŷz
```

Because both PC sets are uncorrelated with unit variance, the singular values r are the canonical correlations and the
columns of A and B the canonical weights. The forecast's canonical variates `xpc A[:, :k]` are multiplied by their
correlations (the regression of each predictand variate on its predictor variate) and mapped back through B and the
predictand EOFs. This is the CPT formulation.

### 2.5 Choice of modes and the forecast error (`MOS.combos`, `MOS.fit`)

- **Combinations searched:** PCR m = 1–6 (6 combinations); CCA m = 1–6, l = 1–6, k = 1–min(m, l, 3) (77 combinations). The
  number of EOFs never exceeds n − 3, which only matters for very short records.
- **Inner leave-one-year-out:** each of the n training years j is left out in turn; the standardization and the SVDs are
  refitted on the other n − 1 years, and year j is predicted with every combination. This gives, per combination and cell,
  the out-of-sample errors e_j (square-root mm).
- **Score of a combination:** the normalized squared error

  ```
  score = mean over live cells of  Σ_j e_j² / (n · var)
  ```

  where var is the cell's variance of square-root rainfall over the training years and the live cells are those with
  var > 0.01. Without this restriction the many nearly dry cells, whose tiny errors divide by tiny variances, dominated the
  choice. A score of 1 is the error of the training mean; the smallest score wins.
- **Forecast error:** per cell, `σ = √(mean_j e_j²)` of the chosen combination (at least 0.001), the cross-validated
  root-mean-square error. It does not change from year to year.
- **Final model:** the chosen combination refitted on all n training years.

### 2.6 Probabilities, amounts and ranges (`products`)

The forecast for a cell is Gaussian in square-root space, N(μ, σ²). With the tercile limits q1, q2 of the training years'
CHIRPS (the 1/3 and 2/3 quantiles per cell, the same limits as the published forecast and the scoring):

```
P(below)  = Φ((√q1 − μ) / σ)
P(above)  = 1 − Φ((√q2 − μ) / σ)
P(normal) = 1 − P(below) − P(above)    (clipped at 0; the three renormalized to sum to 1)
```

- **Amounts:** 51 quantile members `max(μ + σ Φ⁻¹((i + 0.5)/51), 0)²`, i = 0…50. Square-root values below zero become zero
  rainfall, so the distribution can put mass on no rain.
- **Median and 10–90% range:** `max(μ + σ Φ⁻¹(τ), 0)²` for τ = 0.5, 0.1, 0.9.
- No smoothing and no climatology blend are applied, unlike the published probabilities.

### 2.7 Cross-validation and references (`run_target`, `evaluate`)

- **Training years (1993–2016), outer leave-one-year-out:** for each year y, everything — the terciles, the standardization,
  the SVDs, the mode choice (its own inner leave-one-year-out over the other 23 years) and σ — is fitted without y, then y
  is forecast. The mode choice is therefore nested: it never sees the year it is scored on.
- **Test years (2017 onward; ONDJ to 2024):** the model is fitted once on all 24 training years and each test year forecast.
- **References in the same folds and on the same cells:** the published probabilities (MVS, smoothed tercile counts and the
  climatology blend, with the blend weight fitted inside the fold) and the MVS-corrected ensemble.
- **Scores per year**, area-weighted over the region:
  - RPS of the tercile probabilities, over cells whose training CHIRPS has a standard deviation of at least 1 mm, a lower
    tercile above 0 and distinct terciles, and whose training-mean CHIRPS and SEAS5 are at least 1 mm;
  - CRPS of the 51 members over the cells with those means at least 1 mm, plus pinball losses of the 10%, 50% and 90%
    quantiles and the coverage of the 10–90% range;
  - the same scores of climatology (the training years' observations), for the skill scores.
- The modes chosen in every fold are kept (`modes` in `benchmark.json`).

### 2.8 The forecast year (`forecast_validation`, `validate_target`)

Each method is fitted on the cycle's reference years (for example 1993–2025 for JJAS 2026; the mode choice by inner
leave-one-year-out over them) and forecasts the forecast year. Once its CHIRPS is in the cycle's verification observations,
the forecast is scored with the published probabilities (recomputed by the same code) and the MVS-corrected ensemble, on the
same cells. These forecasts are never published.

### 2.9 Tests and decisions (`tests_of`; `scripts/selection_tests.py`)

- Per method, target and score: the per-year score differences from the reference, a one-sided paired sign-flip test over
  whole years (training years), and the mean differences over the training and the test years.
- **The benchmark's own decision (as run):** Holm across the two methods and five targets of the cycle (10 tests per score);
  confirmed = better over the training years, adjusted p < 0.05 and not worse over the test years.
- **The method selection (docs/50):** the same test with Benjamini–Hochberg in place of Holm, within the same 10 tests,
  since 2026-10-17.

### 2.10 Modes chosen in practice

The most frequent choice over the 24 training folds (m predictor EOFs / l predictand EOFs / k canonical modes):

| Cycle | Season target: CCA | Season target: PCR | Range over the month targets |
| --- | --- | --- | --- |
| FMAM, January | 2/1/1 and 5/1/1 (4 folds each) | 1 PC (23 folds) | CCA 1–6 predictor EOFs; PCR 1 PC |
| FMAM, February | 4/1/1 (8 folds) | 1 PC (14), 3 PCs (9) | CCA 1–6 predictor EOFs; PCR 1–2 PCs |
| JJAS, May | 1/2/1 (21 folds) | 1 PC (24) | CCA 1 predictor EOF; PCR 1 PC |
| ONDJ, September | 1/1/1 (11 folds) | 1 PC (24) | CCA 1–6 predictor EOFs; PCR 1 PC |

CCA keeps one canonical mode in almost every fold, and PCR one or two PCs. With 23 training years the cross-validation
rarely supports more than one large-scale pattern: in effect both methods scale the forecast's leading pattern into the
observed pattern it correlates with.

### 2.11 Settings, checkpoints and provenance

- `config/mos/<cycle>.json`: the benchmark configuration it shares with the bias-correction benchmark (years, cells,
  regions), and `settings` (block 4, at most 6 predictor EOFs, 6 predictand EOFs and 3 canonical modes, square-root
  transform).
- Each target is checkpointed in `outputs/mos/<cycle>/parts/<target>.pkl` with a key from the dependency fingerprint of the
  inputs and configurations and the SHA-256 of the code; a changed input or script reruns the target.
- `benchmark.json` records the commit, the input fingerprints, the configuration and the protocol.

### 2.12 Known limitations of this implementation

- The ensemble mean averages 25 members in 1993–2016 and 51 from 2017, so the predictor is a little less noisy in the test
  years and the forecast year than in the years it was fitted on. From 2027 the cycles use 25 members.
- One predictor field (SEAS5 rainfall over the model box). CPT setups often use sea-surface temperature or a larger domain.
- σ is the same every year: the forecast's spread does not depend on the forecast itself.
- No climatology blend: a method with weak signal can be over-confident where the published probabilities are not.

## 3. Design

As for the Leung–Dirichlet comparison (docs/51):
- outer leave-one-year-out over 1993–2016, with every fitted quantity inside the folds;
- test years from 2017, fitted on 1993–2016;
- references: the published probabilities (RPS) and the MVS-corrected ensemble (CRPS);
- confirmed: better over 1993–2016 with adjusted p < 0.05 across both methods and the five targets, and not worse over the
  test years (the benchmark's own decision uses Holm; the method selection uses Benjamini–Hochberg since 2026-10-17);
- the forecast year is scored as an independent season once observed.

## 4. Results (All Ethiopia, four cycles)

- **Confirmed better:** only for JJAS rainfall amounts.
  - Under the selection rule (Benjamini–Hochberg): August (PCR, adjusted p 0.025), September (CCA 0.020, PCR 0.020) and
    the JJAS season (PCR 0.044).
  - In the benchmark as run (Holm): September only (CCA 0.036, PCR 0.023).
  - In the method selection, PCR is the selected candidate for JJAS August and season amounts (the largest improvement over
    1993–2016 among the candidates). For September, quantile regression stays selected, and CCA and PCR are alternatives.
- **Over 1993–2016:**
  - **Tercile probabilities:** both methods are mostly below the published probabilities.
  - **Amounts:** mixed.
- **Over the test years they are often better than over the training years.** CCA RPSS: ONDJ October +0.130 (published
  +0.027), November +0.157 (+0.053), the ONDJ season +0.124 (+0.075), the JJAS season +0.081 (+0.039). This is not
  confirmed: 8–9 test years, and worse for other targets.
- **Pooled over all 20 targets and 1993–2025:** both methods are worse than the published approach for both products. The
  skill gain is about −3% of the climatology score for probabilities and −2% for amounts.
- **The 2026 independent seasons:**
  - **Probabilities:** CCA beats the published probabilities for every JJAS target (JJAS RPSS +0.52 against +0.35) and for
    9 of the 15 observed targets; PCR for 11 of 15.
  - **Amounts, the confirmed JJAS targets:** worse than the MVS-corrected ensemble. CRPS: PCR August 18.7 mm against 15.5,
    September 16.6 against 15.3, the season 59.7 against 47.2; CCA September 17.2 against 15.3.
  - One season is one validation season, not a verdict: a candidate needs three (docs/50).

**Reading.** With 23 training years, CCA and PCR estimate many parameters (patterns and modes). The published scaling
estimates two per cell and is more stable. The test-year and 2026 results suggest the large-scale relation carries signal in
some seasons. The 1993–2016 record does not confirm that it beats the published approach, except for JJAS amounts, where
the first validation season goes the other way.

## 5. Running

    python scripts/mos_benchmark.py --config config/mos/<cycle>.json --workers 2

Checkpoints per target are kept in `outputs/mos/<cycle>/parts/`. Tests: `tests/test_mos.py` (the model recovers a shared
signal; probabilities, quantile members and quantiles are coherent).
