# Neural distributional regression (DRN): a neural EMOS against the published pipeline

A compact distributional regression network (Rasp & Lerch 2018) with a censored shifted gamma output, the distribution of the
EMOS model (docs/48). It learns how the SEAS5 ensemble and the local rainfall climate of a cell relate to the distribution of
the observed CHIRPS rainfall. From that distribution come the rainfall amounts, the 10–90% ranges and the tercile
probabilities. The question is whether modest nonlinear flexibility improves on EMOS and on the published approach,
especially for rainfall amounts and their uncertainty.

Code: `scripts/neural_calibration.py` (the model), run by `scripts/dist_benchmark.py` with
`config/probability_calibration/<cycle>_neural.json`; results `outputs/probability_calibration/<cycle>/neural/`; site:
*Research › Neural network (DRN)*; tests `tests/test_neural_calibration.py`. **Nothing here changes the published forecast.**

## 1. What is compared

| Model | Role | Inputs | Fitting |
| --- | --- | --- | --- |
| `drn_csg` — DRN | candidate (the only model tested for adoption) | ensemble mean, median, standard deviation, mean absolute difference, 10% and 90% quantiles (relative); log CHIRPS mean, CHIRPS coefficient of variation; latitude, longitude | shared network, 1 or 2 hidden layers (32, or 32 and 16 units), CRPS |
| `emos_csg` — EMOS | comparator: does the network add anything? | ensemble mean and mean absolute difference | linear, maximum likelihood (docs/48) |
| `drn_linear_csg` — linear control | is a gain due to the hidden layers, or to the extra inputs and the CRPS loss? | as the DRN | no hidden layer, CRPS |
| `drn_climatology` — ablation | does the SEAS5 forecast add anything beyond the cell's normal rainfall? | log CHIRPS mean, coefficient of variation, latitude, longitude | as the DRN |

References in the same folds and on the same cells: the published probabilities (MVS, smoothed tercile counts and the
climatology blend) for the RPS, and the MVS-corrected ensemble for the CRPS. **Every model uses the first 25 SEAS5 members
in every year** (`members: 25`), the operational policy from 2027 (docs/52), so hindcasts and forecasts have the same
ensemble size.

Only the DRN enters the tests for adoption (5 targets per cycle and score): EMOS, the control and the ablation are
diagnostic comparisons, reported without adjustment, and do not dilute the multiple-testing correction.

## 2. Implementation (`scripts/neural_calibration.py`)

### 2.1 Samples and inputs (`dist_benchmark.fold`, `dist_calibration.features`)

As for every distribution model: within each fold, every valid cell (training-mean CHIRPS and SEAS5 at least 1 mm) and
training year is one sample; amounts are relative to the cell's training CHIRPS mean (the observation) or SEAS5 mean (the
ensemble summaries); weights are the cell areas, with equal total weight per year. The DRN adds the ensemble median and the
cell's latitude and longitude. Every input is standardized with the training samples of the fold.

### 2.2 Network and output (`_forward`)

```
h = ELU(x W1 + b1)                    (and h = ELU(h W2 + b2) for two layers)
o = h W + b                           three outputs
μ = softplus(o1) + 0.001,  σ = softplus(o2) + 0.001,  δ = −softplus(o3)
k = (μ/σ)²,  θ = σ²/μ                 Y = max(0, X + δ) · (CHIRPS mean),  X ~ Gamma(k, θ)
```

The same parameterization as EMOS, so the comparison isolates how the parameters depend on the inputs. The output layer
starts near zero weights with biases at the training mean and standard deviation: the network starts from a climatological
distribution.

### 2.3 Loss and gradient (`crps_csg`, `_loss_grad`)

The loss is the area- and year-weighted CRPS of the censored shifted gamma in closed form (Scheuerer & Hamill 2015, eq. 5),
plus weight decay 10⁻⁴ on the weights:

```
CRPS = θ ỹ (2 P_k(ỹ) − 1) − θ c̃ P_k(c̃)² + θ k (1 + 2 P_k(c̃) P_{k+1}(c̃) − P_k(c̃)² − 2 P_{k+1}(ỹ))
       − θ k / π · B(½, k + ½) (1 − P_{2k}(2c̃)),       ỹ = (y − δ)/θ,  c̃ = −δ/θ
```

with P_a the regularized lower incomplete gamma function (P_{a+1} from P_a by recurrence). The test suite checks it
against numerical integration of the CDF. The derivatives of each sample's CRPS with respect to (μ, σ, δ) are taken by
forward differences in double precision (the derivative of the incomplete gamma function with respect to its shape has no
closed form), then back-propagated through the network by hand; the test suite checks the whole gradient against finite
differences. NumPy and SciPy only: no deep-learning library is needed for a network of this size.

### 2.4 Training (`_train`, `fit`)

- **Optimizer:** full-batch Adam, learning rate 0.003, at most 2000 steps.
- **Early stopping:** about 20% of the fold's training years (5 of 23) are held out; their CRPS is checked every 10 steps,
  and training stops after 15 checks without improvement, keeping the best weights.
- **Seeds:** three, each with its own held-out years and initial weights.
- **Architecture:** one hidden layer of 32 units, or two of 32 and 16, chosen by the mean held-out CRPS of the three seeds.
  Everything is chosen inside the outer fold; the left-out year is never seen.
- **Forecast:** the equal mixture of the three seeds' distributions (`CSGMixture`): its CDF is the mean of theirs, its
  quantiles found by bisection.
- **Training cells:** every second cell in each direction of the 0.25° grid (neighbouring cells carry nearly the same
  information), which makes training four times faster; forecasts and scores cover every cell.
- The linear control uses the same procedure without a hidden layer and without weight decay.

### 2.5 Products

Tercile probabilities `P(below) = F(q1)`, `P(near) = F(q2) − F(q1)`, `P(above) = 1 − F(q2)` with the training-year CHIRPS
terciles q1, q2 (the convention of every distribution model); amounts, median and 10–90% range from the quantiles.

### 2.6 Evaluation and decision

As every benchmark: outer leave-one-year-out over 1993–2016, then fitted on all of 1993–2016 for the test years; scores per
year area-weighted over All Ethiopia (RPS, CRPS, pinball losses, 10–90% coverage); one-sided paired sign-flip test over
whole years. The benchmark's own decision uses Holm across the DRN's five targets; the method selection uses
Benjamini–Hochberg on the same p-values (docs/50). A confirmed DRN becomes a candidate, which needs three independent
validation seasons (a shadow forecast) before it can be recommended.

**Caveats on the evidence.** Each fold has 23 seasons: pooling over cells helps estimation, but the evidence for a new year
still comes from those seasons, and the tests use whole years. The years 2017 onward have been looked at during the
development of the other methods; they are a check, not an untouched test set. Real evidence will come from forecasts saved
before their seasons (docs/52).

## 3. Results (All Ethiopia, four cycles, 20 targets)

| Mean over the 20 targets | DRN | EMOS | Linear control | No-forecast ablation | Published |
| --- | --- | --- | --- | --- | --- |
| Amounts, CRPSS 1993–2016 | +0.025 | +0.024 | +0.022 | +0.006 | +0.009 (MVS ensemble) |
| Amounts, CRPSS 2017+ | +0.016 | | | | +0.011 |
| Coverage of the 10–90% range, 1993–2016 (nominal 80%) | 81% (75–90%) | 80% | | | 67% (46–76%) |
| Probabilities, RPSS 1993–2016 | +0.013 | −0.003 | | | +0.022 |

- **Rainfall amounts.** The DRN is better than the published MVS ensemble on average over 1993–2016 for 16 of 20 targets
  and over the test years for 10. **Confirmed better only for JJAS September** (Holm and Benjamini–Hochberg, adjusted p
  0.011; 17 of 24 years better, better over the test years too). Close: FMAM-February February (unadjusted p 0.015) and
  JJAS June and August (0.045 and 0.032; Benjamini–Hochberg 0.075).
- **Ranges.** The clearest gain: the DRN's 10–90% ranges hold 75–90% of the observations (mean 81%), against 46–76% for the
  MVS ensemble, whose ranges are too narrow. EMOS is as well calibrated (80%).
- **Against EMOS:** about equal. The DRN's CRPS is lower for 9 of 20 targets; significantly so (unadjusted) only for
  FMAM-February February and JJAS August. **The network does not add a clear gain over EMOS.**
- **Against the linear control:** lower CRPS for 13 of 20 targets, significantly (unadjusted) for the JJAS season and ONDJ
  December: the hidden layers help a little at most. One hidden layer or two were chosen (32–16 units for 16 targets).
- **Against the no-forecast ablation:** the decisive check. The ablation (the cell's climate and location only) beats the
  MVS ensemble for 14 of 20 targets, because the MVS ensemble's amounts are worse than climatology for many targets. The
  DRN beats the ablation for only 11 of 20, significantly only for FMAM-February February, where SEAS5 has real skill
  (DRN RPSS +0.205, published +0.137). **Most of the DRN's gain over the published amounts comes from a well-calibrated
  distribution, not from the forecast.**
- **Tercile probabilities:** the DRN is below the published probabilities on average (RPSS +0.013 against +0.022) and better
  for 4 of 20 targets, none confirmed (FMAM-February February comes closest, unadjusted p 0.013).
- **Training:** early stopping ended most networks after about 30 steps (median), close to their starting point (a
  climatological distribution): with 18 training years per network, the held-out years stop the networks before they learn
  much from the forecast.
- **Pooled over the 20 targets and 1993–2025** (docs/50, "More statistical power"): the DRN's amounts are significantly
  better than the MVS ensemble (skill gain +2.2% of the climatology score, better in 27 of 33 years; Holm p 0.015,
  Benjamini–Hochberg 0.004); its probabilities are not (−1.2%).

**Reading.** The neural network does what a well-calibrated distribution model does: better amount ranges than the published
ensemble, about as good as EMOS. It does not find additional, nonlinear forecast signal: with about two dozen seasons per
fold, the year-to-year evidence is too thin for a network to learn more than EMOS's few coefficients. Where SEAS5 is skilful
(February), the DRN uses it and does well, as EMOS does. In the method selection the DRN becomes a candidate for JJAS
September amounts, and is selected there: its improvement over 1993–2016 (−1.10 mm) is slightly larger than quantile
regression's (−1.08 mm), which becomes an alternative. A recommendation would need three shadow-forecast seasons, and the
ablation result is a reason for caution. The results support the recommendation's order: a spatial CNN or a larger network is not
justified by these data; more forecast information (predictors) and more independent seasons would come first.

## 3b. Validation seasons (shadow forecasts)

A DRN listed by the method selection gets its own amount shadow (`scripts/dist_shadow.py`, docs/48), like every distribution
model: fitted on the cycle's reference years with the first 25 members (`members` in
`config/probability_calibration/amount_shadow.json`) and the cell coordinates, made when the cycle is run and scored once
CHIRPS is available. **2026, JJAS September (its first season):** CRPS skill +0.052 against +0.188 for the MVS ensemble —
worse, as EMOS and quantile regression were that season; 1 of the 3 seasons needed. From 2027 the shadows are made before
each season (docs/52).

## 3c. Second stage: more information, a neural correction of EMOS, the mirror ablation

A separate benchmark (`config/probability_calibration/<cycle>_neural_ext.json`, results in `.../neural_ext/`) with its own two
candidates, so their test family is separate from the first stage's:

| Model | Role | What it adds |
| --- | --- | --- |
| `drn_sst` — DRN + SST indices and regions | candidate | The DRN inputs plus the SEAS5 Niño 3.4 (5° S–5° N, 170°–120° W) and Indian Ocean Dipole (west 10° S–10° N, 50°–70° E minus east 10° S–0°, 90°–110° E) indices of the target months (first 25 members, cos-latitude weighted means; `scripts/sst_indices.py`), and the eight EMI homogeneous rainfall regions (Korecha & Sorteberg 2013, one-hot). The indices give the network large-scale information it did not have; they are known at issue time. The regions are a published regionalization: the project's own regime masks were not used because they are built from 1993–2025 CHIRPS, held-out years included. |
| `drn_emos_residual` — neural correction of EMOS | candidate | For each seed, EMOS (maximum likelihood) is fitted on the seed's training years; the network's three outputs are **added** to EMOS's linear predictors of μ, σ and δ. The output layer starts at zero, so training starts exactly at EMOS, and early stopping keeps EMOS when no step improves the held-out CRPS; a penalty (0.01) on the mean squared correction keeps it small. It asks the cleanest question: is there any nonlinear signal beyond EMOS? |
| `drn_forecast_only` — ablation | diagnostic | The network on the ensemble summaries only (no climatology, location or indices): the mirror of the no-forecast ablation. |
| `emos_csg` | diagnostic | EMOS in the same folds. |

The plain DRN is not refitted: the comparisons read its per-year scores from the first benchmark (same folds, years, members
and seeds; `external_models`, with that file's SHA-256 and commit recorded). Comparisons: DRN + SST against the DRN (the value
of the indices and regions), the neural correction against EMOS and against the DRN, the DRN against the forecast-only
ablation (the value of the local context). Both candidates also have amount shadows when selected (`amount_shadow.json`:
25 members; the SST indices and regions of the forecast year for `drn_sst`).

Results: pending (the benchmark runs after the first stage has been rerun with the weight-decay search).

## 3d. One network for the months of a cycle (`scripts/pooled_benchmark.py`)

Each per-target DRN learns from about 18 training seasons. `drn_pooled` fits **one** network to the four months of a cycle
(not the season, whose observations are the sum of the months'): the samples of every month (as `dist_benchmark.fold` makes
them, each month with total weight 1) are pooled, with the month's position in the season as four one-hot inputs. Four times
the samples per network — but from the same years, which are correlated across the months, so the gain in independent
information is smaller than the factor four. Early stopping holds out whole calendar years for the four months at once
(`year_index` of each row).

The driver works per year rather than per target (one fit serves the four months): outer leave-one-year-out over 1993–2016,
every month of the left-out year forecast and scored with the published references computed in the same folds, then one
fit on all training years for the test years. Results have the same format as `dist_benchmark.py`; Holm across the four
targets (the method selection: Benjamini–Hochberg); comparisons with the per-target DRN and EMOS read from the first stage.
If the pooled DRN becomes a candidate, its shadow needs a pooled fit as well: not yet implemented (`dist_shadow.py` skips
it with a message), so it could not collect validation seasons until then.

Config: `config/probability_calibration/<cycle>_neural_pooled.json`; results `.../neural_pooled/`. Results: pending.

## 3e. A separate tuning split (`tuning='separate'`)

In the first stage the architecture and weight decay are chosen on the same held-out years that stop the training. This
does not bias the reported scores (the outer left-out year is never seen) but can make the choice of configuration noisier.
With `tuning='separate'` the configuration is chosen by three inner folds of the training years: each fold's years are
scored by a network trained on the other years, early-stopped on a further 20% of them; then the three seeds of the chosen
configuration are trained as usual. `drn_csg_tuned` is the DRN with this procedure, run as a **diagnostic** on JJAS
(`config/probability_calibration/may_jjas_neural_tuning.json`, not a candidate): the comparison with the DRN shows whether
the tuning procedure matters. Results: pending.

## 4. Running

    python scripts/dist_benchmark.py --config config/probability_calibration/<cycle>_neural.json --workers 5

About two hours per cycle with five workers (15 networks per fold: 6 for the DRN, 6 for the ablation, 3 for the linear
control). Checkpoints per target in `outputs/probability_calibration/<cycle>/neural/parts/`. JAX was tried first for the
gradients: its incomplete gamma function made one step 0.7 s, against about 20 ms with SciPy and the derivatives above.

## 5. Possible next steps

Following the order recommended for this project: if the DRN improves on EMOS, test why (inputs, depth, a regularized
correction of the EMOS parameters); then pool the monthly targets with the target month and lead as inputs; then add
spatial context with a small patch CNN on the surrounding SEAS5 fields; then run the chosen network as a shadow forecast.

## References

- Rasp, S., & Lerch, S. (2018). Neural networks for postprocessing ensemble weather forecasts. *Monthly Weather Review*, 146(11), 3885–3900.
- Scheuerer, M., & Hamill, T. M. (2015). Statistical postprocessing of ensemble precipitation forecasts by fitting censored, shifted gamma distributions. *Monthly Weather Review*, 143(11), 4578–4596.
- Uttarwar et al. (2025), KIT (publikationen.bibliothek.kit.edu): a censored shifted gamma DRN for SEAS5 precipitation
  trained with the CRPS, where one hidden layer of 25 units did as well as deeper networks (daily forecasts in the first
  month, the Alps). Cited as in the recommendation that led to this benchmark; the full reference is to be completed.
