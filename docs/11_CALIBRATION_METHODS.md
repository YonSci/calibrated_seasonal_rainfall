# Scientific methods and simple examples

## A. Rainfall amounts: mean–variance bias correction

The scientific description is **affine mean–variance bias correction**, with a bounded scale factor and nonnegative truncation. It is a bias-correction method. It is not quantile mapping.

This implementation adapts the original member-specific approach: ensemble members are treated as exchangeable, with one correction per grid cell shared by all members. It does not carry over the original member-wise beta shrinkage. This allows 25-member hindcasts and 51-member operational forecasts to be processed consistently.

### Step 1: choose training years and eligible cells

For each fitting operation, require finite seasonal CHIRPS values in every included training year. If a static land mask was supplied, the cell must also be marked land. A fitting operation needs at least 20 years. Development has 24 years; each withheld-year fit has 23. Final fitting has 33; its folds have 32.

This strict completeness rule is an explicit initial choice. If observations are missing intermittently, it can exclude more cells than a minimum-valid-years policy. Reported per-fold counts make this visible. The withheld year's missingness never controls which cells are eligible to make predictions; it only controls whether the resulting predictions can be scored.

### Step 2: estimate model mean and variability with equal year weights

Let H[y,m] be seasonal rainfall for member m of year y, and M[y] its member count. At each cell:

```text
mu_H = mean_over_years(mean_over_members(H))
variance_H = mean_over_years(mean_over_members(H^2)) - mu_H^2
sigma_H = sqrt(max(variance_H, 0))
```

A 51-member year has the same total weight as a 25-member year. Model variability here is the pooled variability across years and members, not only variability of the ensemble mean.

For CHIRPS, calculate the training-year mean mu_O and population standard deviation sigma_O (ddof=0). The same denominator convention is used for model moments.

### Step 3: calculate and apply the adjustment

```text
r = clip(sigma_O / sigma_H, 0.5, 2.0)
corrected = max(0, mu_O + r * (forecast - mu_H))
```

When sigma_H < 1 mm, use r=1 (mean-only correction) to avoid division by a tiny value. These limits are safeguards fixed before test evaluation, not universal scientific constants.

Example:

- Historical ECMWF mean = 800 mm; SD = 200 mm.
- Historical CHIRPS mean = 600 mm; SD = 150 mm.
- One forecast member = 1,000 mm.
- r = 150/200 = 0.75.
- Corrected member = 600 + 0.75 x (1,000 - 800) = **750 mm**.

The mean shift addresses systematic wet/dry bias; scaling adjusts variability. Negative corrected values are set to zero. The report gives the fraction requiring that truncation. Bounds and truncation mean corrected moments need not match observational moments exactly. This procedure does not guarantee improved ensemble spread, extremes or forecast skill: evaluate those claims independently.

## B. Convert members to tercile probabilities

### Step 1: estimate observed thresholds from training years only

Use the empirical 1/3 and 2/3 CHIRPS quantiles, with linear interpolation. Call them q1 and q2. Thresholds are specific to each cell and each fitting fold.

### Step 2: assign categories consistently

- Below-normal: rainfall < q1.
- Near-normal: q1 <= rainfall <= q2.
- Above-normal: rainfall > q2.

Use the same boundary rules for forecast members and observations. Ties mean realized historical frequencies are not necessarily exactly one-third. The training-climatology baseline therefore uses empirical category frequencies, not an assumed 1/3 vector.

Cells with observational SD < 1 mm, q1 <= 0 mm, or q2-q1 <= 0.000001 mm are excluded from categorical calibration. Amount correction may still be available there. This explicitly avoids reporting three distinct rainfall categories where the climatology does not meaningfully separate them. Requiring q1 > 0 also avoids a below-normal category that would require physically impossible negative rainfall.

### Step 3: count ensemble members

If corrected rainfall places 5 of 25 members below, 8 near and 12 above, the base probability vector is:

```text
[5/25, 8/25, 12/25] = [0.20, 0.32, 0.48]
```

For operational forecasts, divide by the actual 51 members. No padding or invented members are used. These base probabilities have undergone amount correction but not probability calibration.

The output also includes raw member-count probabilities using the same observed thresholds, allowing evaluation of each processing stage.

## C. Why training probabilities must be out of fold

To generate the 1993 training probability:

1. Fit rainfall correction, cell eligibility and thresholds using 1994–2016 only.
2. Correct the 1993 forecast and count its categories.
3. Assign the observed 1993 category using those same training-only thresholds.
4. Store the forecast vector and observed label.

Repeat for every development year. This prevents each year's observation from influencing the preprocessing that generated its own base forecast probability.

The Dirichlet map is trained on these 24 sets of pairs. Applying that map back to the same pairs would still be in-sample for the Dirichlet stage, so the script does not label such scores as independent validation. Independent evaluation uses 2017–2025.

## D. Regularized Dirichlet probability calibration

The underlying family follows Kull et al. (2019): take logarithms of class probabilities, apply a linear transformation, then softmax. The particular identity-centred penalty and weighting below are explicit project choices. This implementation is not claimed to reproduce every detail of the paper's ODIR configuration.

### Step 1: protect logarithms

A category with zero members has p=0. Before taking logs, replace each component below 1e-12 with 1e-12 and renormalize the vector. This numerical floor is not an estimate of a truly tiny meteorological probability. Predictions from small ensembles have substantial sampling uncertainty.

### Step 2: transform the vector

```text
z = A @ log(p) + b
calibrated_probability[k] = exp(z[k]) / sum(exp(z))
```

A is a 3 x 3 matrix; b has three entries. If A is the identity matrix and b is zero, the output equals the input after numerical flooring. Off-diagonal entries allow one category's probability to affect another's calibrated score.

One global mapping is fitted by pooling eligible cells and years. It is not a separate fit at every pixel. Each year receives equal total weight, with spherical cell-area weights normalized among valid cells within that year. Spatially neighbouring cells remain dependent; pooling does not increase the number of independent seasons.

### Step 3: learn the matrix and intercepts

Minimize weighted negative log likelihood of the observed categories plus:

```text
0.01  * sum(off-diagonal A entries squared)
+ 0.001 * sum((diagonal A entries - 1) squared)
+ 0.001 * sum(b entries squared)
```

The data loss is a weighted mean (weights sum to one), and penalties are sums. This specifies their numerical meaning. L-BFGS-B with an analytic gradient performs optimization; failed convergence stops the run.

Regularization discourages large departures from the identity map, especially cross-category mixing. These fixed values are starting settings inherited from the earlier workflow, not values optimized for Ethiopia. If they are changed based on test results, 2017–2025 ceases to be an untouched test set. Proper tuning requires nested year-based folds inside the development period and rebuilding all preprocessing inside those folds.

### Step 4: apply to unseen years

For 2017–2025, amount correction and thresholds use 1993–2016 only, and the Dirichlet matrix is frozen. For example, a base [0.20, 0.32, 0.48] could become [0.25, 0.35, 0.40] if training evidence supports reducing overconfidence. That output is illustrative; actual values come from the fitted A and b.

Calibrated probabilities sum to one. This step changes category probabilities; it does not change the corrected member rainfall amounts or create a full calibrated continuous rainfall distribution. Consequently the Dirichlet probabilities need not equal category counts of the saved corrected ensemble.

## E. Evaluation

- Amount bias = forecast ensemble mean minus observation, averaged with area weights; positive means wet bias.
- MAE and RMSE use the ensemble mean. They do not assess the full ensemble distribution.
- Category Brier score = mean((probability - observed indicator)^2), reported separately for each category.
- RPS = sum of squared cumulative-probability errors at the two category boundaries; this script does not divide by two. Lower is better.
- Log loss = -log(probability assigned to the observed category), with a 1e-12 floor for scoring. Lower is better; empirical zero probabilities can dominate this metric.
- RPS skill = 1 - forecast RPS / training-climatology RPS. Positive indicates improvement over that baseline.
- Reliability bins compare mean forecast probability with observed frequency. Bin weights describe sharpness/usage.

Scores are area-weighted within each year and equally weighted across years. Summary RMSE is sqrt(mean of annual area-weighted MSE), not mean annual RMSE. All probability methods are compared on the same available verification cells per year.

A single pooled Dirichlet map can hide regional differences. Later evaluation should include subregions, year-block uncertainty and sensitivity to using 25 instead of 51 operational members. The ensemble-size transition is respected computationally but is not statistically removed by the mapping.

## Reference

Kull et al. (2019), *Beyond temperature scaling: Obtaining well-calibrated multi-class probabilities with Dirichlet calibration*, NeurIPS 32.

https://proceedings.neurips.cc/paper/2019/hash/8ca01ea920679a0fe3728441494041b9-Abstract.html

https://papers.nips.cc/paper/2019/file/8ca01ea920679a0fe3728441494041b9-Paper.pdf
