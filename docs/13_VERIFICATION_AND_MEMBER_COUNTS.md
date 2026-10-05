# Stage 4: Verification, anomaly diagnostics and ensemble-size sensitivity

## 1. What happened to the 51 operational members?

All 51 members were used. We did not discard 26 to match the 25-member reforecasts.

- In development fitting, 1993–2016 has 25 members per year.
- Development evaluation uses all 51 members in each 2017–2025 forecast.
- Final fitting uses all available members, but averages within a year before averaging over years. A 51-member year therefore has the same total statistical weight as a 25-member year when estimating model moments.
- Forecast probabilities use actual counts divided by the actual member count. Resolution is 1/25 = 4% or 1/51 = approximately 1.96%.
- The development Dirichlet mapping is learned from 25-member probabilities, then applied to 51-member probabilities. This is a distribution difference; equal-year weighting does not remove it.

Using more members generally reduces Monte Carlo sampling noise if members provide additional information. It does not automatically make the model more skilful, and dependent members provide less information than independent ones. Empirical scores can also depend on ensemble size. For example, zero-probability events are more frequent in smaller samples, and log loss is very sensitive to them.

Member counts alone cannot establish that model systems and hindcast/operational distributions are identical. Subsampling tests the count effect conditional on the existing forecasts; it cannot correct system changes or sampling dependence.

## 2. What this update adds

The scripts read existing development results. They do not tune, refit or change the calibration, and they do not replace prior outputs.

| Metric or diagnostic | Previous update | This update |
|---|---|---|
| Category Brier score | Yes, JSON | Included with maps and bootstrap intervals |
| Category Brier Skill Score | No | Added, against training-climatology probabilities |
| Ranked Probability Score / RPSS | Yes, JSON | Included with maps and bootstrap intervals |
| Log loss | Yes, JSON | Included with bootstrap intervals |
| Reliability | Bin data only | Diagrams and bin JSON |
| Probability histogram / sharpness | Bin weights available | Plotted explicitly |
| ROC / AUC | No | Added per category |
| CRPS | No | Added for raw and corrected rainfall ensembles |
| Fair CRPS | No | Added as a finite-member sensitivity diagnostic |
| CRPSS | No | Added against empirical training-CHIRPS distribution |
| Deterministic climatology baseline | No | Added for rainfall bias, MAE, MSE/RMSE and MSE skill |
| Anomalies | No | Regional time series and cellwise temporal correlation |
| Clipping locations | Aggregate fraction only | Spatial fraction map |
| 25 vs 51 members | No | Repeated 25-of-51 comparison, frozen fitted parameters |
| Uncertainty | No | Paired bootstrap of whole evaluation years |

All requested metrics are applicable to this project, but CRPS applies to continuous rainfall ensembles, not directly to a vector of three tercile probabilities. Dirichlet calibration changes the three probabilities and does not define the full continuous rainfall distribution. Its verification uses BS/BSS, RPS/RPSS, log loss, reliability and ROC. CRPS compares raw versus amount-corrected ensembles; it is not a score of the Dirichlet stage.

## 3. Install and run

Merge the ZIP's `scripts`, `tests` and `docs` folders into `D:\calibrated_seasonal_rainfall`. Keep the previous update installed: this extension imports its calibration scripts and `common.py`.

No new dependencies are needed. Matplotlib was already included in the starter.

```bat
cd /d D:\calibrated_seasonal_rainfall
.venv\Scripts\activate
python -m unittest discover -s tests -p test_verification.py -v
python scripts\verify_calibration.py --config config\project.json
```

Defaults: 5,000 year-bootstrap draws, 100 repeated 25-member subsets, fixed random seed 20261003. The script displays progress during yearly verification, bootstrap and member comparison.

For a quicker initial execution:

```bat
python scripts\verify_calibration.py --config config\project.json --bootstrap 1000 --subsamples 20
```

Then run the default command for the reports you send back. Repeat runs replace this diagnostic folder only. A failed run can leave older results; require the final `Complete` message.

## 4. Outputs

All files are written under:

```text
outputs\verification\init05_JJAS\full_domain\
```

| File | Contents |
|---|---|
| `verification_summary.json` | Annual scores, aggregate scores, skill scores and paired year-bootstrap intervals |
| `member_count_sensitivity.json` | All-51 scores vs mean and 2.5–97.5 percentile range of 25-member subsets |
| `training_compression_diagnostics.json` | Training base vs mapped entropy, maximum probability, zero-probability frequency, scores and fitted matrix |
| `regional_anomalies.json` | Area-weighted forecast/observed seasonal anomalies relative to 1993–2016 |
| `roc_auc.json` | One-vs-rest AUC for below, near and above categories |
| `reliability_bins.json` | Area/year-weighted reliability and histogram bins |
| `spatial_verification.nc` | Cellwise errors, skill ratios, temporal anomaly correlations and clipping fraction |
| `figures/spatial_diagnostics.png` | Six-panel skill/correlation/clipping maps |
| `figures/regional_anomalies.png` | Raw, corrected and observed anomaly time series |
| `figures/reliability_and_histograms.png` | Reliability curves and forecast-probability histograms |
| `figures/roc_curves.png` | Category ROC curves and AUC |
| `figures/member_count_sensitivity.png` | RPS comparison of 51 members and repeated 25-member subsets |

Map colour scales show skill/correlation from -1 to 1. Values below -1 are saturated in the figure but retained in NetCDF. Undefined scores are missing, not zero. Maps show coordinates without country outlines; they must not be presented as Ethiopia-only products.

## 5. Ethiopian or regional evaluation

No Ethiopia polygon or aligned country mask has been supplied. The default evaluation remains the full eligible rectangular domain, which includes neighbouring countries.

To evaluate Ethiopia specifically, provide a NetCDF with:

```text
region_mask(lat, lon)
1 = inside the evaluation region
0 = outside
Coordinates exactly match the 48 x 60 common grid
```

Then run:

```bat
python scripts\verify_calibration.py --config config\project.json --region-mask data\masks\ethiopia_common.nc --region-name Ethiopia
```

Outputs go to `outputs\verification\init05_JJAS\Ethiopia\`, preserving full-domain results. The same option can evaluate independently defined rainfall regions. It only changes evaluation selection: it does not refit the pooled Dirichlet mapping or retroactively restrict its training domain.

This **region mask** is distinct from a **land–ocean mask**. A physical land mask belongs after regridding and before calibration fitting. If it is added to calibration later, rerun calibration with it and then rerun verification. A regional evaluation mask can be applied to existing forecasts without refitting. Do not label missing CHIRPS cells as ocean.

## 6. Baselines and anomaly interpretation

The deterministic baseline is the 1993–2016 CHIRPS mean at each cell, fixed for all test years. Its anomaly prediction is zero. Compare corrected rainfall against it, not only against biased raw forecasts.

```text
MSE skill = 1 - MSE(forecast) / MSE(training-mean forecast)
```

Positive is improvement over climatology, zero is equal, negative is worse. MSE and skill are calculated on matched available cells in each year.

The continuous probabilistic baseline is the empirical distribution of the 24 CHIRPS training seasons at each cell. It is evaluated as a fixed forecast distribution using ordinary empirical CRPS.

```text
CRPSS = 1 - mean CRPS(forecast ensemble) / mean CRPS(training empirical climatology)
```

Forecast and observed anomalies subtract the same local training-observed mean. Regional series are area-weighted over matched available cells. A persistent bias in raw forecasts remains visible in raw anomalies.

Cellwise temporal anomaly correlation is Pearson correlation across test years, requiring at least six valid pairs and nonzero variance. With a fixed climatology, this equals temporal correlation of the underlying amounts; subtracting a constant does not change Pearson correlation. Nine seasons offer limited evidence, and correlation alone ignores bias and amplitude errors. A constant climatology forecast has undefined correlation, not automatically zero.

## 7. CRPS and ensemble size

For M members x_i and observation y:

```text
empirical CRPS = mean_i |x_i - y| - sum_i sum_j |x_i - x_j| / (2 M^2)
fair CRPS      = mean_i |x_i - y| - sum_i sum_j |x_i - x_j| / (2 M (M-1))
```

Both use rainfall units, mm; lower is better. The code uses sorted values to evaluate the pairwise term efficiently.

Ordinary CRPS scores the actual empirical forecast distribution. Fair CRPS adjusts the finite-sample contribution when members are an independent, identically distributed sample of an underlying distribution. Exchangeability alone is not enough for every fairness interpretation; member dependence and control/perturbed-member differences can violate assumptions. The fair score is therefore labelled a diagnostic, not a guarantee that ensemble-size effects have been removed.

The script reports ordinary CRPSS with the fixed empirical climatology. It does not apply a fair correction to the Dirichlet probabilities or claim a Dirichlet CRPS.

## 8. How the 25-member comparison works

For each repetition:

1. Select 25 unique members from each 51-member operational ensemble, without replacement.
2. Use one selected member list for every grid cell in that year, preserving spatial structure.
3. Recalculate raw and corrected member-count probabilities.
4. Apply the already fitted Dirichlet matrix to the subset probabilities.
5. Score rainfall MSE, empirical/fair CRPS, RPS and log loss.
6. Average equally across the nine evaluation years.

The amount correction, thresholds, eligible cells and probability-calibration coefficients remain frozen. The reported 2.5–97.5 percentile range reflects variation among member subsets; it is **not** an independent-season confidence interval. The all-51 forecast is compared against that subset distribution.

This tests the deployment sensitivity of the fitted pipeline. It does not recreate independent 25-member forecasts, test different forecast systems, or justify choosing members using observed outcomes. No members are dropped from the saved original forecasts.

## 9. Bootstrap uncertainty

The same sampled year indices are applied to every method and baseline. Each draw resamples nine complete years with replacement and recomputes aggregate means and skill ratios. Grid cells and members are never treated as independent bootstrap samples.

The interval is the 2.5–97.5 percentile range over draws. `dirichlet_minus_base_rps` below zero favours Dirichlet; an interval spanning zero does not establish a consistent improvement under this bootstrap. Skill above zero favours the forecast over the reference.

Limitations: only nine years; independent-year resampling does not model serial dependence; the fitted model is held fixed, so the intervals omit training uncertainty. These are approximate descriptive uncertainty estimates, not proof of operational skill. The update does not calculate confidence bands for every reliability point, ROC curve or map cell.

## 10. Investigating probability compression

The training diagnostic evaluates the year-withheld base probabilities, then applies the fitted Dirichlet map to them. That latter evaluation is **in-sample for the Dirichlet stage**, even though its inputs were produced out of fold. It must not be reported as independent calibrated skill.

Inspect:

- Mean maximum probability: strong movement toward 1/3 indicates reduced sharpness.
- Entropy: values near log(3), approximately 1.099, indicate nearly uniform probabilities.
- Fraction of cases with at least one zero base probability: these receive extreme log inputs under the 1e-12 numerical floor.
- Training versus heldout reliability and category frequencies.

The existing results show compression, but do not establish its cause. Candidate explanations include limited predictive signal, a pooled mapping across different rainfall regimes, finite-member zeros, and shifts between training and evaluation distributions. This script diagnoses without changing the model.

If tuning or comparing alternative mappings is required, use nested year-based validation entirely inside 1993–2016, rebuilding bias correction, masks and thresholds inside each inner training split. Do not tune toward the now-observed 2017–2025 frequencies. The magnitudes of diagonal matrix entries alone cannot diagnose the mapping because softmax is invariant to shared logit shifts.

## 11. Interpreting the requested metrics

- **BS/BSS:** probability accuracy for each category separately. BSS uses the matching training-climatology category probability and can be negative.
- **RPS/RPSS:** respects the ordering below–near–above. The implemented RPS sums errors at two cumulative boundaries without dividing by two.
- **Log loss:** strongly penalizes assigning very little probability to the observed outcome; numerical floor 1e-12 for comparability with the earlier run.
- **Reliability diagrams:** agreement between issued probabilities and observed frequencies; histogram weights show how much evidence each bin has.
- **Probability histograms:** distribution/sharpness of issued category probabilities, not ensemble rank histograms. Sharpness is useful only alongside calibration and skill.
- **ROC/AUC:** ability to discriminate whether each category occurs. AUC around 0.5 has no discrimination; AUC does not establish reliable probabilities. Ties are handled exactly. The plotted ROC pools cells/years with area/equal-year weights and can hide regional differences.
- **CRPS/CRPSS:** continuous ensemble rainfall accuracy, comparing raw and amount-corrected ensembles.

All aggregate scores use equal year weights and area weights among valid cells within each year. Aggregate skill is a ratio of aggregate scores, not a mean of local skill scores. ROC/histogram/reliability use the equivalent per-case weights.

## 12. Validation and next files to send

Four test cases cover pairwise CRPS equivalence, perfect forecasts, weighted ROC ties, missing labels, temporal correlation, complete synthetic development-plus-verification execution, regional exclusion, NetCDF maps and five figure outputs. Tests passed with the starter dependencies on Linux. Real multiyear verification still needs your local common-grid and corrected files. No scientific results are inferred from the synthetic tests.

After a successful full run, upload:

```text
outputs\verification\init05_JJAS\full_domain\verification_summary.json
outputs\verification\init05_JJAS\full_domain\member_count_sensitivity.json
outputs\verification\init05_JJAS\full_domain\training_compression_diagnostics.json
outputs\verification\init05_JJAS\full_domain\roc_auc.json
outputs\verification\init05_JJAS\full_domain\figures\reliability_and_histograms.png
outputs\verification\init05_JJAS\full_domain\figures\spatial_diagnostics.png
```

The full-data tests may produce runtime warnings when computing on permanently missing cells; the script explicitly masks those cells. Errors or failure to print `Complete` must be investigated, not ignored. No additional pip installs are required.

## References

Ferro (2014), *Fair scores for ensemble forecasts*, Quarterly Journal of the Royal Meteorological Society. DOI: 10.1002/qj.2270.
https://rmets.onlinelibrary.wiley.com/doi/abs/10.1002/qj.2270

ECMWF Forecast User Guide, verification metrics:
https://confluence.ecmwf.int/spaces/FUG/pages/673551584/Section+8.3.5+Using+verification+metrics+with+the+output
