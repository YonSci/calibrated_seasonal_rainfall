# Leung–Dirichlet calibration: the uploaded pipeline as methods, tested for FMAM (January), JJAS (May) and ONDJ (September)

**Leung–Dirichlet calibration**: a modified-Leung member-wise affine bias correction followed by an identity-anchored
Dirichlet (IAD) recalibration of the tercile probabilities, from `process_calib.py`.

`process_calib.py` (Á. G. Muñoz and T. Demissie, ILRI / Alisios Corporation; written for a forage outlook) calibrates
SEAS5 seasonal rainfall for East Africa and turns it into tercile probabilities and a pasture index. Its rainfall
calibration has **two methods**, one per stage, which are implemented here unchanged as separate methods and tested with
the same data, cross-validation and tests as the other benchmarks (docs/47, docs/48):

| Stage | Method (uploaded code) | Here |
| --- | --- | --- |
| Bias correction (amounts) | modified-Leung member-wise affine calibration | `leung_affine` in `scripts/bias_methods.py` (`fit_leung`, `apply_leung`) |
| Probabilities | raw member counts against the CHIRPS terciles | `member_probabilities()` in `scripts/leung_dirichlet.py` |
| Probability calibration | Identity-Anchored Dirichlet (IAD) recalibration | `IADDirichlet` in `scripts/leung_dirichlet.py` |

The benchmark is `scripts/leung_dirichlet_benchmark.py` with one configuration per season (`config/leung_dirichlet/jan_fmam.json`,
`may_jjas.json`, `sep_ondj.json`); results in `outputs/leung_dirichlet/<cycle>/` and on the site (*Research › Leung–Dirichlet
calibration*). Sections 1–4 were written for ONDJ; section 4b adds FMAM and JJAS. **Nothing here changes the published
forecast.**

## 1. What the uploaded code does

1. **Regridding.** SEAS5 monthly totals summed to the season and put on the CHIRPS grid by nearest neighbour. Here the
   project's own SEAS5 seasonal and monthly totals on the 0.25° CHIRPS v3 grid are used, so the comparison isolates the
   calibration.
2. **Modified-Leung member-wise affine calibration** (total space, per cell). Over the training years, every member index
   *m* has its own climatology, mean μ<sub>m</sub> and standard deviation σ<sub>m</sub> (population SD), and the
   observations have μ<sub>obs</sub>, σ<sub>obs</sub>:
   - pooled model SD σ<sub>pool</sub> = √(mean<sub>m</sub> σ<sub>m</sub>²); effective SD
     σ<sub>eff,m</sub> = (1 − β) σ<sub>m</sub> + β σ<sub>pool</sub>, β = 0.3;
   - ratio r<sub>m</sub> = clip((σ<sub>obs</sub> + 10⁻⁶) / (σ<sub>eff,m</sub> + 10⁻⁶), 0.5, 2), and r<sub>m</sub> = 1 where
     σ<sub>obs</sub> and σ<sub>eff,m</sub> are both below σ<sub>min</sub> = 1 mm;
   - corrected member x′<sub>m</sub> = μ<sub>obs</sub> + r<sub>m</sub> (x<sub>m</sub> − μ<sub>m</sub>), clipped at 0.

   The difference from the published Mean-Variance Scaling (MVS) is that each member is corrected against **its own**
   climatology rather than the ensemble's, with the spread ratio partly pooled across members.
3. **Tercile probabilities.** The fraction of corrected members below the lower CHIRPS tercile, between the terciles
   (inclusive) and above the upper tercile. No smoothing and no climatology blend.
4. **Identity-Anchored Dirichlet (IAD) recalibration** (a regularised Dirichlet calibration, Kull et al. 2019):
   p′ = softmax(A log p + b), with A (3 × 3) and b (3) fitted by mean negative log-likelihood of the observed categories
   plus the penalties ½ λ<sub>off</sub> Σ<sub>i≠j</sub> A<sub>ij</sub>² + ½ λ<sub>diag</sub> Σ (A<sub>ii</sub> − 1)² +
   ½ λ<sub>b</sub> ‖b‖², so that with little evidence it stays at the identity (probabilities unchanged). Defaults of
   the script: λ<sub>off</sub> = 0.01, λ<sub>diag</sub> = λ<sub>b</sub> = 0.001; probabilities clipped at 10⁻¹²;
   L-BFGS-B from A = I, b = 0, 400 iterations. It is fitted once on the hindcast probabilities and observed categories
   pooled over all cells, every cell-year with equal weight, and applied to the forecast.
5. **SPBI** (Standardized Pasture Biomass Index from NDVI and the calibrated seasonal mean): a product built on the
   calibrated rainfall, not a rainfall calibration; not implemented.

## 2. Implementation choices

The code is reproduced as it is; three points needed a decision because the project's data differ from the script's:

- **Members beyond the hindcast's.** SEAS5 has 25 members for 1993–2016 and 51 from 2017. The member-wise climatology
  exists only for the first 25; members 26–51 are corrected with the pooled climatology (mean of μ<sub>m</sub>,
  σ<sub>pool</sub>). The script assumes equal member counts and does not cover this.
- **The Dirichlet inside the folds.** The script fits the IAD on the hindcast probabilities in sample. To score honestly,
  every fold repeats that procedure on its own training years only: the Leung affine is fitted on the training years and
  applied to each of them, the IAD is fitted on those probabilities, and the pair is applied to the left-out year.
- **Cells.** The IAD is pooled over the national cells with finite probabilities and a decided observed category, as the
  script pools over its domain.

## 3. Methods compared

| Key | Pipeline | Tests |
| --- | --- | --- |
| `ld_full` | Leung affine → member counts → IAD (the uploaded code) | the whole calibration |
| `ld_no_dirichlet` | Leung affine → member counts (the script with `--no_dirichlet`) | the bias correction with raw counts |
| `iad_on_mvs` | published MVS → member counts → IAD | the probability calibration alone |
| `leung_blend` | Leung affine → the published probability stage (smoothed counts, climatology blend with its weight from inner years) | the bias correction alone |
| `leung_affine` | Leung-corrected ensemble (amounts) | the bias correction for amounts |

References in the same folds: the published probabilities (MVS → smoothed counts → climatology blend) for the tercile
RPS, and the MVS-corrected ensemble for the amount CRPS (plus 80% coverage and pinball losses).

Design, as in Phase 2 (docs/48): outer leave-one-year-out over 1993–2016 (every fitted quantity, including the IAD and
the blend weight, from the remaining years); the test years 2017–2024 fitted on all of 1993–2016. Ethiopia, cell-area
weights, equal year weights. **Confirmed better**: better over the training years with Holm-adjusted p < 0.05 (paired
whole-year sign-flip) across the four probability methods and five targets (RPS), or across the five targets (CRPS),
and not worse over the test years.

## 4. Results (Ethiopia), ONDJ from September

Skill against the observed climatology (RPSS for probabilities, CRPSS for amounts); training = leave-one-year-out
1993–2016, test = fitted on 1993–2016 and scored 2017–2024.

| Target | Published probabilities | Leung–Dirichlet (as uploaded) | Leung + member counts | MVS + Dirichlet | Leung + published blend | MVS ensemble (CRPSS) | Leung ensemble (CRPSS) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Oct | +0.013 / +0.027 | +0.004 / +0.001 | −0.021 / +0.004 | +0.003 / +0.006 | +0.009 / +0.024 | −0.002 / +0.059 | −0.006 / +0.055 |
| Nov | +0.040 / +0.053 | +0.035 / +0.014 | +0.046 / +0.041 | +0.035 / +0.015 | +0.041 / +0.053 | +0.084 / +0.158 | +0.088 / +0.162 |
| Dec | +0.003 / +0.016 | +0.008 / +0.008 | −0.064 / −0.040 | +0.008 / +0.001 | +0.002 / +0.017 | +0.029 / −0.033 | +0.032 / −0.040 |
| Jan | +0.001 / −0.004 | −0.004 / +0.021 | −0.132 / −0.213 | +0.000 / +0.006 | +0.002 / −0.005 | −0.040 / −0.066 | **−0.022 / −0.050** |
| ONDJ | +0.039 / +0.075 | +0.026 / +0.041 | +0.025 / +0.058 | +0.031 / +0.049 | +0.034 / +0.071 | +0.070 / +0.178 | +0.070 / +0.175 |

(training / test). Tests against the reference:

- **Tercile probabilities: no Leung–Dirichlet pipeline is confirmed better than the published probabilities** for any target
  (Holm p = 1 for all 20). The uploaded pipeline (`ld_full`) is slightly worse than the published probabilities over the
  training years for Oct, Nov, Jan and ONDJ (ΔRPS +0.002 to +0.006) and over the test years for all targets but Jan.
- **The raw member counts are overconfident**, most of all for the drier months (Jan RPSS −0.13 training, −0.21 test):
  without the Dirichlet the uploaded pipeline is the worst method.
- **The IAD repairs that overconfidence, but by flattening.** Fitted on all training years, A has diagonal elements of
  0.05–0.35 (identity: 1) for most targets; with ~35 000 pooled cell-years the identity penalty is weak, so the
  probabilities are pulled most of the way towards equal thirds plus a fixed shift b. Only the upper tercile of Nov (A₃₃
  ≈ 1.18) and Dec (≈ 0.65) keeps much of the ensemble's signal. The result is close to, but not better than, the
  published climatology blend, which weights the ensemble per target with a weight fitted in inner years.
- **The bias correction alone changes little for probabilities**: the Leung affine through the published probability
  stage (`leung_blend`) is within ±0.003 RPS of the published probabilities everywhere.
- **Amounts: the Leung ensemble is confirmed better than the MVS ensemble for January** (CRPS −0.15 mm, 21 of 24 years
  better, Holm p < 0.001; test years −0.09 mm, 80% coverage 0.54 against 0.46). It is not confirmed for Oct, Nov, Dec
  or ONDJ (worse for Oct). Jan amounts already have a candidate from the bias-correction benchmark (square-root MVS).

The forecast year 2026 (`forecast/`; not published): the published and Leung + counts maps favour the same terciles
(below normal in the west, above normal elsewhere); after the IAD most of the central and northern highlands no longer
reach 40% in any tercile.

**Conclusion.** For ONDJ the uploaded calibration does not improve the published tercile probabilities; its probability
stage (IAD) mostly reproduces what the climatology blend already does, slightly less well. Its bias correction gives a
confirmed amount improvement for January, which enters the method selection as an alternative: square-root MVS stays
selected for January amounts because its confirmed improvement is larger (−0.48 mm against −0.15 mm over the training years).

### Tercile-probability plots

- **Reliability diagrams** (`figures/leung_dirichlet_reliability_training.png`, `_test.png`): for every pipeline, below and
  above normal, the observed frequency against the forecast probability in bins of 10% (area-weighted, each year equal;
  bins with under 1% of the forecasts not drawn; marker area = share of forecasts). The member counts without the
  Dirichlet spread their probabilities from 0 to 80% but verify close to 33% for Oct, Dec and Jan (a line much flatter
  than the diagonal): overconfident, which is why their RPS is the worst. The pipelines with the IAD and the published
  blend keep almost all probabilities between 25% and 45%; where they go further (Nov, ONDJ) the outcomes roughly follow
  the diagonal. The IAD gains reliability by giving up sharpness, as the published blend does.
- **Forecast-year maps** (`forecast/ld_<year>_<target>_probabilities.png`): the below-, near- and above-normal
  probabilities of every pipeline for each 2026 target, next to the published ones (rows: published, Leung–Dirichlet
  (as uploaded), Leung + member counts, MVS + Dirichlet, Leung + published blend), and the favoured tercile (`ld_<year>_<target>.png`).
  The published probability stage recomputed by the benchmark matches the published files (largest difference below
  10⁻⁸), so the panels are directly comparable. ONDJ 2026, national means below / near / above: published 27 / 27 / 46%,
  Leung–Dirichlet (as uploaded) 32 / 30 / 38%, Leung + member counts 25 / 26 / 50%, MVS + Dirichlet 31 / 30 / 39%, Leung + published
  blend 27 / 27 / 46%: the uploaded pipeline keeps the published pattern (below normal in the west, above normal in the
  south and east) with weaker probabilities. Where the published maps are blank the cells are too dry for terciles
  (mostly January: 1 029 of 1 484 cells are scored); the Leung–Dirichlet pipelines give values there, but every pipeline is
  scored on the same cells.
- **Forecast-year maps on the grid cells** (`scripts/leung_dirichlet_maps.py`, `forecast/maps/<view>/`): for each target
  and for two views, the season's rainfall domain (the seasonal mask; for ONDJ the R3 Deyr domain) and All Ethiopia,
  drawn on the 0.25° cells as computed (no interpolation or smoothing), as the published grid-cell outlook map
  (`presentation_layers.tercile_cells`: same classes, colours, background and legend):
  `<pipeline>/<target>.png`, the rainfall tercile outlook of each pipeline, shown on the site next to the published
  grid-cell map of the same target and view; and `probabilities/<target>.png`, the below-, near- and above-normal
  probabilities of the published forecast and every pipeline, with area means over the view. On the ONDJ rainfall
  domain for ONDJ 2026/27 the uploaded pipeline gives above normal 40–50% almost everywhere (50–60% in the far south)
  where the published forecast gives 50–70%: area means below / near / above 27 / 28 / 45% against the published
  16 / 26 / 58%.

## 4b. Results for FMAM (January initialization) and JJAS (May initialization)

Same design (outer leave-one-year-out 1993–2016, test years 2017–2025, Holm across the four probability pipelines and five
targets, and across the five targets for amounts). RPSS / CRPSS, training / test:

| Season | Target | Published | Leung–Dirichlet (as uploaded) | Leung + member counts | MVS + Dirichlet | Leung + published blend | MVS ensemble (CRPSS) | Leung ensemble (CRPSS) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FMAM | Feb | +0.033 / +0.020 | +0.079 / −0.017 | +0.027 / −0.068 | +0.076 / +0.033 | +0.050 / +0.017 | +0.074 / +0.002 | +0.091 / +0.010 |
| FMAM | Mar | +0.002 / +0.008 | −0.003 / −0.002 | −0.080 / −0.045 | −0.005 / +0.001 | +0.002 / +0.010 | −0.044 / +0.005 | −0.040 / +0.015 |
| FMAM | Apr | +0.001 / +0.002 | −0.002 / +0.003 | −0.027 / −0.033 | −0.004 / +0.005 | +0.001 / +0.001 | −0.016 / −0.006 | −0.016 / −0.004 |
| FMAM | May | +0.028 / +0.004 | +0.021 / −0.007 | +0.026 / −0.026 | +0.022 / −0.007 | +0.028 / +0.002 | +0.007 / −0.007 | +0.007 / −0.009 |
| FMAM | FMAM | +0.032 / +0.017 | +0.019 / +0.018 | +0.026 / +0.014 | +0.021 / +0.016 | +0.028 / +0.021 | +0.025 / +0.016 | +0.022 / +0.021 |
| JJAS | Jun | −0.000 / +0.010 | −0.009 / +0.000 | −0.121 / −0.056 | −0.014 / +0.001 | −0.001 / +0.011 | −0.096 / −0.030 | −0.094 / −0.030 |
| JJAS | Jul | +0.015 / +0.042 | −0.010 / +0.004 | −0.033 / +0.019 | −0.017 / +0.003 | +0.015 / +0.043 | −0.005 / +0.002 | −0.003 / −0.001 |
| JJAS | Aug | +0.012 / +0.041 | −0.001 / +0.012 | −0.039 / +0.065 | −0.003 / +0.008 | +0.011 / +0.042 | −0.027 / +0.055 | −0.028 / +0.057 |
| JJAS | Sep | +0.003 / +0.008 | +0.002 / +0.004 | −0.068 / −0.042 | +0.004 / +0.004 | +0.003 / +0.009 | −0.060 / −0.034 | −0.060 / −0.033 |
| JJAS | JJAS | +0.027 / +0.039 | +0.003 / +0.013 | −0.024 / −0.002 | +0.007 / +0.012 | +0.027 / +0.040 | −0.028 / −0.018 | −0.028 / −0.019 |

- **Nothing is confirmed better than the published approach for FMAM or JJAS**, for probabilities or amounts.
- **FMAM February is the one promising case.** The Dirichlet on the published MVS ensemble (`iad_on_mvs`) is better than
  the published probabilities in 15 of 24 training years (ΔRPS −0.020, p = 0.008 for this target alone) and over the test
  years (−0.006), but not after the Holm adjustment across the 20 tests (p = 0.16); the uploaded pipeline is better over
  the training years (p = 0.011) but worse over the test years. Worth watching, not a candidate.
- **JJAS: the published probabilities are clearly better** than every pipeline with the Dirichlet; the IAD fitted on
  all training years has diagonal elements of 0.04–0.15 for every JJAS target, so it reduces the probabilities almost to
  climatology plus a fixed shift, and gives up the skill the published forecast has in July, August and JJAS. The member
  counts without it are again overconfident (Jun RPSS −0.12).
- **The Leung affine changes amounts very little** in either season (CRPSS within ±0.02 of MVS); the Leung + published
  blend pipeline is within ±0.003 RPSS of the published one except FMAM February (+0.050 against +0.033, not
  significant).

**Independent season 2026** (FMAM and JJAS have been observed; ONDJ not yet), RPSS against the observed climatology:

| Target | Published | Leung–Dirichlet (as uploaded) | Leung + member counts | MVS + Dirichlet | Leung + published blend |
| --- | --- | --- | --- | --- | --- |
| FMAM Feb / Mar / Apr / May / FMAM | −0.037 / +0.049 / +0.010 / +0.028 / −0.026 | −0.070 / +0.011 / −0.006 / +0.016 / −0.023 | −0.260 / +0.238 / −0.002 / +0.039 / −0.066 | −0.071 / +0.017 / −0.005 / +0.014 / −0.022 | −0.053 / +0.059 / +0.010 / +0.031 / −0.032 |
| JJAS Jun / Jul / Aug / Sep / JJAS | +0.125 / +0.198 / +0.277 / +0.107 / +0.352 | +0.015 / +0.060 / +0.077 / +0.036 / +0.210 | +0.433 / +0.269 / +0.439 / +0.318 / +0.610 | +0.024 / +0.063 / +0.056 / +0.037 / +0.220 | +0.130 / +0.200 / +0.278 / +0.111 / +0.352 |

In JJAS 2026, a season with a strong and correct ensemble signal, the sharp raw member counts score best and the
Dirichlet pipelines worst, the reverse of the 1993–2016 evidence: a single season rewards sharpness when the signal is
right, which is why the selection needs several seasons.

## 5. Place in the method selection

The comparison is a family of its own (`leung_dirichlet`) in `scripts/method_selection.py` (docs/50). A method confirmed
here becomes a candidate for that target and product (so far only the Leung affine for ONDJ January amounts, listed as
an alternative to square-root MVS). Its validation seasons are the cycle's forecast years once observed, scored by the
benchmark run itself (section 4b); the published forecast is unchanged.

## 6. Running

    python scripts/leung_dirichlet_benchmark.py --config config/leung_dirichlet/sep_ondj.json --workers 2

The grid-cell maps are drawn afterwards from the forecast files, with the season's cycle configuration
(`config/cycles/jan_2026_fmam.json` for jan_fmam, `config/operational.json` for may_jjas):

    set CALIBRATION_CYCLE=config\cycles\sep_2026_ondj.json
    python scripts/leung_dirichlet_maps.py --name sep_ondj

Checkpoints per target in `outputs/leung_dirichlet/sep_ondj/parts/` (keyed on inputs, code and configuration). Outputs:
`benchmark.json` (scores per year, reliability sums, tests, fitted IAD parameters, provenance), `figures/leung_dirichlet_summary.png`,
`figures/leung_dirichlet_reliability_{training,test}.png`, and for the forecast year `forecast/ld_<year>_<target>.nc` (every
pipeline's probabilities and the published ones; not published) with `ld_<year>_<target>.png` (favoured tercile) and
`ld_<year>_<target>_probabilities.png` (tercile probabilities). Other cycles need only a configuration file pointing at their bias-correction benchmark configuration.

Tests: `tests/test_leung_dirichlet.py` (the IAD stays near the identity on calibrated input and softens overconfident
input; the Leung affine reproduces each member's climatology and handles extra members; counts and categories).
