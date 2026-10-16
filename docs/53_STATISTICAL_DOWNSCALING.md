# Statistical downscaling by model output statistics (MOS): CCA and PCR against the published pipeline

Model output statistics as in CPT / PyCPT, the tools ICPAC and IRI use for regional seasonal outlooks. The large-scale pattern
of the SEAS5 forecast is related statistically to the observed CHIRPS pattern over the training years, and the relation is
applied to the new forecast. Two methods are tested in every cycle against the published pipeline, with the same data,
cross-validation and tests as the other benchmarks (docs/47, docs/48):
- canonical correlation analysis (CCA);
- principal component regression (PCR).

Script: `scripts/mos_benchmark.py`; configurations `config/mos/<cycle>.json`; results `outputs/mos/<cycle>/`; site:
*Research › Statistical downscaling*. **Nothing here changes the published forecast.**

## 1. Method

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

## 2. Design

As for the Leung–Dirichlet comparison (docs/51):
- outer leave-one-year-out over 1993–2016, with every fitted quantity inside the folds;
- test years from 2017, fitted on 1993–2016;
- references: the published probabilities (RPS) and the MVS-corrected ensemble (CRPS);
- confirmed: better over 1993–2016 with Holm p < 0.05 across both methods and the five targets, and not worse over the test
  years;
- the forecast year is scored as an independent season once observed.

## 3. Results (All Ethiopia, four cycles)

- **Confirmed better:** only JJAS September rainfall amounts, by both CCA and PCR. They are listed as alternatives in the
  method selection; quantile regression stays selected for that target.
- **Over 1993–2016:**
  - **Tercile probabilities:** both methods are mostly below the published probabilities.
  - **Amounts:** mixed.
- **Over the test years they are often better than over the training years.** CCA RPSS: ONDJ October +0.130 (published
  +0.027), November +0.157 (+0.053), the ONDJ season +0.124 (+0.075), the JJAS season +0.081 (+0.039). This is not
  confirmed: 8–9 test years, and worse for other targets.
- **Pooled over all 20 targets and 1993–2025:** both methods are worse than the published approach for both products. The
  skill gain is about −3% of the climatology score for probabilities and −2% for amounts.
- **The 2026 independent seasons:** CCA beats the published probabilities for every JJAS target (JJAS RPSS +0.52 against
  +0.35) and for 9 of the 15 observed targets; PCR for 11 of 15. One season is one validation season, not a verdict.

**Reading.** With 23 training years, CCA and PCR estimate many parameters (patterns and modes). The published scaling
estimates two per cell and is more stable. The test-year and 2026 results suggest the large-scale relation carries signal in
some seasons. The 1993–2016 record does not confirm that it beats the published approach.

## 4. Running

    python scripts/mos_benchmark.py --config config/mos/<cycle>.json --workers 2

Checkpoints per target are kept in `outputs/mos/<cycle>/parts/`. Tests: `tests/test_mos.py` (the model recovers a shared
signal; probabilities, quantile members and quantiles are coherent).
