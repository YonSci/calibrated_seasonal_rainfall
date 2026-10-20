# Statistical downscaling by model output statistics (MOS): CCA and PCR against the published pipeline

Model output statistics as in CPT / PyCPT, the tools ICPAC and IRI use for regional seasonal outlooks. The large-scale pattern
of the SEAS5 forecast is related statistically to the observed CHIRPS pattern over the training years, and the relation is
applied to the new forecast. Two methods are tested in every cycle against the published pipeline, with the same data,
cross-validation and tests as the other benchmarks (docs/47, docs/48):
- canonical correlation analysis (CCA);
- principal component regression (PCR).

Script: `scripts/mos_benchmark.py`; configurations `config/mos/<cycle>.json`; results `outputs/mos/<cycle>/`; SST
download `scripts/download_seas5_sst.py`; site: *Research › Statistical downscaling*. **Nothing here changes the published
forecast.**

**Version 2 (2026-10-19)** addresses the four limitations of the first version (section 2.12): the same ensemble size in
every year, sea-surface temperature as a candidate predictor, a forecast-dependent spread and a climatology blend of the
probabilities. Section 4 compares the two versions; the first version's results are kept in `outputs/mos_v1/`. The
changes were made after the first version's results had been seen, which section 4 takes into account.

## 1. Method in brief

- **Predictor**, chosen inside each fold from three fields, all ensemble means of the first 25 SEAS5 members of every year:
  - SEAS5 rainfall over the whole model box (3–15° N, 33–48° E), square-rooted and averaged to its 1° cells: 180 values;
  - SEAS5 sea-surface temperature over the tropical Indian and Pacific Oceans (20° S–20° N, 30° E–80° W), averaged over
    the target months, in 2° cells (about 2,200 ocean values);
  - both, each part weighted to the same total variance.
- **Predictand:** CHIRPS at every 0.25° cell of Ethiopia, square-root rainfall.
- **Transform:** every field standardized per cell (or predictor) with the training years.
- **CCA:** EOF pre-filtering of the predictor (up to 6 modes) and of the predictand (up to 6 modes), then up to 3 canonical
  modes between their leading principal components. The predicted predictand PCs are mapped back through the EOF patterns.
- **PCR:** every CHIRPS cell regressed on the leading predictor principal components (up to 6).
- **Choice of field and modes:** inner leave-one-year-out cross-validation inside each fold. The choice minimizes the mean
  normalized squared error over the cells with year-to-year variation.
- **Predictive distribution:** Gaussian in square-root space. Its variance is the cross-validated error variance scaled by
  (1 + leverage) of the forecast, so it is wider when the forecast is unusual (the CPT prediction-error formula). Tercile
  probabilities come from it and are blended with climatology, with a weight chosen by the same inner cross-validation;
  amounts, the median and 10–90% ranges come from 51 of its quantiles, squared back.

**Differences from operational CPT setups.** The SST predictor is the SEAS5 forecast SST (what is available at issue time),
not observed SST; no other fields or larger domains. The predictive distribution is Gaussian in square-root space, not CPT's
transformed-gamma option.

## 2. Implementation

Each step below names the function in `scripts/mos_benchmark.py` that does it. Notation: n training years, p predictors,
q predictand cells; for a matrix, rows are years.

### 2.1 Data (`predictor`, `sst_predictor`, `predictors`)

- **Rainfall field:** for each year, the mean of the first 25 SEAS5 members (`settings.members`) of the target's rainfall on
  the 0.25° model grid, square-rooted, then averaged over blocks of 4 × 4 cells (`settings.block`), ignoring missing cells:
  one value per 1° cell, p = 180. Hindcasts have 25 members and forecasts 51 from 2017; using the first 25 every year keeps
  the noise of the ensemble mean the same in the years fitted and the years forecast (the 2027 policy, docs/52).
- **SST field:** SEAS5 monthly-mean sea-surface temperature (CDS `seasonal-monthly-single-levels`, system 51) over
  20° S–20° N, 30° E–80° W, downloaded by `scripts/download_seas5_sst.py` and reduced at once to the mean of the first 25
  members per lead month (`data/raw/ecmwf_sst/init<MM>/sst_<YYYY>.nc`). For a target, the lead months of its calendar months
  are averaged (lead 1 = the initialization month), then 2 × 2 blocks of 1° cells (`settings.sst_block`); cells missing in
  any year (land) are dropped.
- **Combined field:** both concatenated; after standardization each column is multiplied by 1/√(columns of its part), so
  the two parts have the same total variance whatever their sizes (`MOS.column_weights`).
- **Observation:** CHIRPS v3.0 for the same target at every 0.25° cell of the national mask
  (`data/masks/ethiopia_common.nc`), square-rooted. Dry cells are kept in the fit (see 2.5 and 2.7 for how they are kept out
  of the mode choice and the scores).
- **Targets:** the four months and the season of each cycle, each fitted separately.

### 2.2 Standardization and EOFs (`MOS._standardize`, `MOS._fit_core`)

With the training years only:

```
mean and standard deviation per column:   mx, sx (predictor),  my, sy (predictand); a standard deviation ≤ 1e-6 is set to 1
standardized fields:                       Xz = (X − mx) / sx · w,   Yz = (Y − my) / sy      (w: column weights, 1 for one field)
singular value decompositions:             Xz = Ux Sx Vxᵀ,       Yz = Uy Sy Vyᵀ
principal components (unit variance):      Xpc = √n Ux,          Ypc = √n Uy
predictand loadings:                       Yload = Sy Vyᵀ / √n,  so that Yz = Ypc Yload
```

For a new year x, its first m predictor PCs are `xpc = (x − mx)/sx · w · Vx[:m]ᵀ / Sx[:m] · √n`. The decompositions are
computed once per fit and field and shared by every combination of modes.

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

### 2.5 Choice of field and modes, and the forecast error (`MOS.combos`, `MOS.fit`, `MOS.leverage`)

- **Combinations searched, for each of the three fields:** PCR m = 1–6 (6 combinations); CCA m = 1–6, l = 1–6,
  k = 1–min(m, l, 3) (77 combinations). The number of EOFs never exceeds n − 3, which only matters for very short records.
- **Inner leave-one-year-out:** each of the n training years j is left out in turn; the standardization and the SVDs are
  refitted on the other n − 1 years, and year j is predicted with every field and combination. This gives, per field,
  combination and cell, the out-of-sample errors e_j (square-root mm), and the leverage of year j (below).
- **Score of a field and combination:** the normalized squared error

  ```
  score = mean over live cells of  Σ_j e_j² / (n · var)
  ```

  where var is the cell's variance of square-root rainfall over the training years and the live cells are those with
  var > 0.01. Without this restriction the many nearly dry cells, whose tiny errors divide by tiny variances, dominated the
  choice. A score of 1 is the error of the training mean; the smallest score over fields and combinations wins.
- **Leverage:** the forecast's regressors v (its m predictor PCs for PCR, its k canonical variates for CCA) have unit
  variance and are uncorrelated over the training years, so the leverage of a forecast, with the intercept, is
  `h = (1 + |v|²) / n`: about 1/n for a typical year, larger for a forecast far from the training years.
- **Forecast error:** per cell, the error variance net of leverage, `s² = mean_j e_j² / (1 + h_j)` (at least 10⁻⁶), with
  h_j the leverage of the left-out year in its inner fit; for a forecast, `σ² = s² (1 + h)`. This is the regression
  prediction-error formula CPT uses, calibrated on the cross-validated errors: the spread changes from year to year with how
  unusual the forecast is.
- **Final model:** the chosen field and combination refitted on all n training years.

### 2.6 Probabilities, amounts and ranges (`gaussian_terciles`, `products`, `MOS._blend`)

The forecast for a cell is Gaussian in square-root space, N(μ, σ²). With the tercile limits q1, q2 of the training years'
CHIRPS (the 1/3 and 2/3 quantiles per cell, the same limits as the published forecast and the scoring):

```
P(below)  = Φ((√q1 − μ) / σ)
P(above)  = 1 − Φ((√q2 − μ) / σ)
P(normal) = 1 − P(below) − P(above)    (clipped at 0; the three renormalized to sum to 1)
blended:    w · P + (1 − w) / 3
```

- **Climatology blend:** the weight w (0 to 1 in steps of 0.05) minimizes the RPS of the inner leave-one-year-out forecasts
  of the chosen model. For each left-out year j: the probabilities from its inner prediction, with the terciles of the other
  years and an error variance computed without year j, scored against year j, area-weighted over the probability cells. As
  for the published probabilities, the blend pulls a weak forecast toward climatology.
- **Amounts:** 51 quantile members `max(μ + σ Φ⁻¹((i + 0.5)/51), 0)²`, i = 0…50. Square-root values below zero become zero
  rainfall, so the distribution can put mass on no rain. The amounts are not blended: their spread already reflects the
  cross-validated error.
- **Median and 10–90% range:** `max(μ + σ Φ⁻¹(τ), 0)²` for τ = 0.5, 0.1, 0.9.

### 2.7 Cross-validation and references (`run_target`, `evaluate`)

- **Training years (1993–2016), outer leave-one-year-out:** for each year y, everything — the terciles, the standardization,
  the SVDs, the choice of field and modes (its own inner leave-one-year-out over the other 23 years), the error variance and
  the blend weight — is fitted without y, then y is forecast. The choices are therefore nested: they never see the year they
  are scored on.
- **Test years (2017 onward; ONDJ to 2024):** the model is fitted once on all 24 training years and each test year forecast.
- **References in the same folds and on the same cells:** the published probabilities (MVS, smoothed tercile counts and the
  climatology blend, with the blend weight fitted inside the fold) and the MVS-corrected ensemble.
- **Scores per year**, area-weighted over the region:
  - RPS of the tercile probabilities, over cells whose training CHIRPS has a standard deviation of at least 1 mm, a lower
    tercile above 0 and distinct terciles, and whose training-mean CHIRPS and SEAS5 are at least 1 mm;
  - CRPS of the 51 members over the cells with those means at least 1 mm, plus pinball losses of the 10%, 50% and 90%
    quantiles and the coverage of the 10–90% range;
  - the same scores of climatology (the training years' observations), for the skill scores.
- The modes, field and blend weight chosen in every fold are kept (`modes` and `choices` in `benchmark.json`).

### 2.8 The forecast year (`forecast_validation`, `validate_target`)

Each method is fitted on the cycle's reference years (for example 1993–2025 for JJAS 2026; the choices by inner
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

### 2.10 Choices in practice (version 2)

The most frequent modes over the 24 training folds (m predictor EOFs / l predictand EOFs / k canonical modes):

| Cycle | Season target: CCA | Season target: PCR | Month targets |
| --- | --- | --- | --- |
| FMAM, January | 3/1/1 (6 folds), 6/1/1 (5) | 1 PC (15), 2 PCs (9) | CCA 1 canonical mode in 94 of 96 folds; PCR 1 PC in 95 |
| FMAM, February | 2/1/1 (19 folds) | 2 PCs (14), 1 PC (10) | CCA 1 canonical mode in 77 of 96, 2 in 19; PCR 1 PC in 94 |
| JJAS, May | 4/5/1 (11 folds), 2/2/1 (7) | 1 PC (24) | CCA 1 canonical mode in 95 of 96; PCR 1 PC in 96 |
| ONDJ, September | 6/2/2 (6 folds), 4/5/1 (4) | 1 PC (21) | CCA 1 canonical mode in 92 of 96; PCR 1 PC in 91 |

- **Modes:** as in version 1, one canonical mode and one or two PCs nearly everywhere. With 23 training years the
  cross-validation rarely supports more than one large-scale pattern.
- **Field:** SST alone in 52% of the folds (both methods, all targets), SST with rainfall in 40%, rainfall alone in 9%.
  Rainfall alone is kept mostly by CCA where the local signal dominates (JJAS September, FMAM-January May, ONDJ January).
- **Blend weight:** median 0.75 (interquartile range 0.50–0.85): the probabilities keep about three quarters of the MOS
  forecast. The weight is low (0.1–0.4) where the signal is weak: June and September, FMAM March, ONDJ December and January.

### 2.11 Settings, checkpoints and provenance

- `config/mos/<cycle>.json`: the benchmark configuration it shares with the bias-correction benchmark (years, cells,
  regions), and `settings` (block 4, at most 6 predictor EOFs, 6 predictand EOFs and 3 canonical modes, square-root
  transform, `members` 25, `fields` rain / sst / rain+sst, `sst_block` 2).
- Each target is checkpointed in `outputs/mos/<cycle>/parts/<target>.pkl` with a key from the dependency fingerprint of the
  inputs and configurations, the SHA-256 of the code and of every SST file; a changed input or script reruns the target.
- `benchmark.json` records the commit, the input fingerprints, the SST file fingerprint, the configuration and the protocol.

### 2.12 Limitations of version 1, and what version 2 does

| Version 1 | Version 2 |
| --- | --- |
| The ensemble mean averaged 25 members in 1993–2016 and 51 from 2017: a less noisy predictor in the years forecast than in the years fitted | the first 25 members in every year |
| One predictor field (SEAS5 rainfall over the model box) | SEAS5 SST over the tropical Indian and Pacific Oceans, alone or with rainfall, chosen inside the folds |
| σ the same every year | σ² = s²(1 + leverage): wider for unusual forecasts |
| No climatology blend: over-confident where the signal is weak | probabilities blended with climatology, weight chosen inside the folds |

Remaining limitations: the predictive distribution is Gaussian in square-root space; the choice among three fields is a
search that the 23 training years must support; the spread depends on the forecast only through its leverage, not through
the ensemble spread; amounts are not blended.

## 3. Design

As for the Leung–Dirichlet comparison (docs/51):
- outer leave-one-year-out over 1993–2016, with every fitted quantity inside the folds;
- test years from 2017, fitted on 1993–2016;
- references: the published probabilities (RPS) and the MVS-corrected ensemble (CRPS);
- confirmed: better over 1993–2016 with adjusted p < 0.05 across both methods and the five targets, and not worse over the
  test years (the benchmark's own decision uses Holm; the method selection uses Benjamini–Hochberg since 2026-10-17);
- the forecast year is scored as an independent season once observed.

## 4. Results (All Ethiopia, four cycles, version 2)

**Version 1 against version 2, over the 20 targets** (skill against the observed climatology; published: RPSS of the
published probabilities, CRPSS of the MVS-corrected ensemble):

| | CCA v1 | CCA v2 | PCR v1 | PCR v2 | Published |
| --- | --- | --- | --- | --- | --- |
| Probabilities, mean RPSS 1993–2016 | −0.022 | +0.012 | −0.014 | +0.022 | +0.022 |
| Targets better than published, 1993–2016 | 1 | 6 | 3 | 9 | |
| Probabilities, mean RPSS 2017+ | +0.043 | +0.023 | +0.025 | +0.031 | +0.027 |
| Amounts, mean CRPSS 1993–2016 | −0.017 | −0.010 | −0.006 | −0.001 | +0.009 |
| Amounts, mean CRPSS 2017+ | +0.042 | +0.000 | +0.038 | +0.018 | +0.022 |
| Coverage of the 10–90% range, 1993–2016 | 79% | 78% | 81% | 80% | |

- **Probabilities:** the blend removed the negative skill. Over 1993–2016 RPSS is higher in version 2 for 19 of 20 targets
  (CCA) and 17 of 20 (PCR); PCR now equals the published probabilities on average. Pooled over all targets and 1993–2025,
  PCR's skill difference from the published probabilities is −0.06% of the climatology score (version 1: about −3%), CCA's
  −1.2%. Neither is significantly better, for any target or pooled.
- **Amounts:** about the same over 1993–2016; lower over the test years than version 1. Pooled: CCA −3.2%, PCR −2.3%.
- **Confirmed better (both corrections): PCR for JJAS August and JJAS season amounts.** Version 1 had, under
  Benjamini–Hochberg, PCR for August, September and the season and CCA for September; September is no longer confirmed.
- **The 2026 independent season:** probabilities better than the published ones for JJAS (CCA RPS 0.324, PCR 0.318,
  published 0.338), August (both), July (CCA) and FMAM from January (both 0.419 against 0.443); amounts still worse than the
  MVS ensemble for most JJAS targets (season CRPS: PCR 62.0 mm, CCA 67.4, MVS 47.2), better for FMAM and for July.

**Reading.** The four fixes made MOS a fair competitor for tercile probabilities — the blend in particular — but not a
better one: on average over 1993–2016 PCR matches the published probabilities and CCA stays below. SST is the field the
cross-validation prefers, yet it brings no confirmed gain, and the test-year skill is lower than in version 1, where it had
looked promising. The fixes were made after version 1's results had been seen; version 2's evidence is not weakened by that
(every choice is still made inside the folds), but the comparison between the versions is one more look at the same years.
Both versions point the same way: with 23 training years, a large-scale statistical relation does not clearly beat the
simple published scaling, except for JJAS amounts with PCR.

## 5. Running

    python scripts/download_seas5_sst.py --month <1|2|5|9> --years 1993 2026      (once per initialization month)
    python scripts/mos_benchmark.py --config config/mos/<cycle>.json --workers 2

Checkpoints per target are kept in `outputs/mos/<cycle>/parts/`. Tests: `tests/test_mos.py` (the model recovers a shared
signal; the spread grows with leverage; the blend weight follows the signal; the informative field is chosen and combined
fields are weighted equally; target months across the year; probabilities, quantile members and quantiles are coherent).
