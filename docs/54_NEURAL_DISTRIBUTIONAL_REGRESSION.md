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

## 3. Results

Pending: the benchmark is running (May-initialized JJAS first, the declared primary cycle).

## 4. Running

    python scripts/dist_benchmark.py --config config/probability_calibration/may_jjas_neural.json --workers 5

About an hour per target with one worker (15 networks per fold: 6 for the DRN, 6 for the ablation, 3 for the linear
control). Checkpoints per target in `outputs/probability_calibration/<cycle>/neural/parts/`.

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
