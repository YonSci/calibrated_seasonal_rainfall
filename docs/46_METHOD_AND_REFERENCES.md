# 46 — Method and references

How the published forecasts are calibrated, step by step, with the scientific literature each step belongs to.
Code: `scripts/calibration_core.py` (`fit_amount`, `correct_amount`, `probabilities`), `scripts/compare_calibration.py`
(`smooth`), `scripts/local_blend.py` (`fit_weights`), `scripts/final_shared_blend.py` (`fit_final`, `forecast`).

## 1. Inputs

* **Forecasts:** ECMWF SEAS5 (system 51) total precipitation, 25 hindcast members 1993–2016 and 51 members from 2017
  (Johnson et al. 2019), summed over the target period (a month or a season) and remapped from 1° to the 0.25° CHIRPS grid
  by first-order conservative (area-preserving) remapping: each 1° cell fills an aligned 4 × 4 block of 0.25° cells.
* **Observations:** CHIRPS v3.0 monthly totals since 11 October 2026 (Funk et al. 2026), averaged from the official 0.05°
  product onto the 0.25° grid; CHIRPS v2.0 before (Funk et al. 2015). Training period 1993–2025 (ONDJ 1993/94–2024/25).

## 2. Rainfall amounts: mean–variance scaling per cell

For every 0.25° cell and target, each member value *x* is corrected as

    x' = max(0, μ_obs + r · (x − μ_model)),   r = clip(σ_obs / σ_model, 0.5, 2)

* μ_obs, σ_obs — mean and standard deviation of the CHIRPS totals over the training years;
* μ_model, σ_model — mean and standard deviation of the hindcast totals pooled over all members and years, with every
  year weighted equally whatever its member count;
* the scale ratio is bounded to 0.5–2; where σ_model < 1 mm only the mean is corrected (r = 1);
* negative corrected values are set to 0. This is the method's known weakness in dry months, where 22–29 % of member
  values can be clipped (issue I-08, docs/38).

This is the *simple bias adjustment* (also *variance scaling*, *mean and variance adjustment*) of the seasonal
forecasting and climate-impact literature (Teutschbein & Seibert 2012; Torralba et al. 2017; Manzanas et al. 2019). It
corrects the mean and the spread, not the shape of the distribution (it is not quantile mapping). A square-root-space
variant was gated (docs/36, Phase 5): it did not improve the tercile probabilities, but it passed the gate for rainfall
amounts and is recommended for the amount maps from the next cycle; the published products still use the correction above.

## 3. Tercile probabilities from member counts

Tercile limits q₁, q₂ are each cell's 1/3 and 2/3 quantiles of the CHIRPS training totals. The probability of each
category is the share of corrected members in it (ensemble relative frequency; Wilks 2019), then smoothed so no category
is exactly 0 or 1:

    p_s = (n · p + 0.5) / (n + 1.5)          (n = number of members; additive smoothing with α = 0.5)

## 4. Blend with climatology

    p = (1 − λ) · p_s + λ · p_clim

p_clim is the observed category frequency in the training years at that cell (about one third each). One weight λ per
target, shared by all cells, is fitted by minimising the ranked probability score of out-of-sample (leave-one-year-out)
probabilities, area-weighted within each year and with equal weight per year; λ is bounded to 0–1. Weighting model
probabilities against climatology follows Rajagopalan et al. (2002) and Robertson et al. (2004), who choose the weights by
maximising the likelihood; this project fits one shared weight by minimising the ranked probability score instead.

## 5. Evaluation

* Probability skill: ranked probability score (Epstein 1969) and its skill score against climatology; Brier scores and
  reliability diagrams (Wilks 2019).
* Rainfall amounts: continuous ranked probability score of the corrected ensemble (Hersbach 2000) and its skill score
  against the CHIRPS climatology.
* Design: nested leave-one-year-out over 1993–2016 (cross-validated) and fits on 1993–2016 scored on 2017 onwards
  (exploratory); method changes must pass `scripts/decision_gates.py` (Holm-adjusted whole-year tests).

## Project choices (not taken from a single paper)

The 0.5–2 bounds on the scale ratio, equal weighting of years, clipping at zero, the α = 0.5 count smoothing and a single
λ shared by all cells are choices of this project, fixed before the 2026 forecasts and evaluated with the design above.

## References

* Epstein, E. S. (1969). A scoring system for probability forecasts of ranked categories. *Journal of Applied
  Meteorology*, 8(6), 985–987. https://doi.org/10.1175/1520-0450(1969)008<0985:ASSFPF>2.0.CO;2
* Funk, C., Peterson, P., Landsfeld, M., et al. (2015). The climate hazards infrared precipitation with stations — a new
  environmental record for monitoring extremes. *Scientific Data*, 2, 150066. https://doi.org/10.1038/sdata.2015.66
* Funk, C., Peterson, P., Harrison, L., et al. (2026). The Climate Hazards Center Infrared Precipitation with Stations,
  Version 3. *Scientific Data*, 13, 718. https://doi.org/10.1038/s41597-026-07096-4
* Hersbach, H. (2000). Decomposition of the continuous ranked probability score for ensemble prediction systems.
  *Weather and Forecasting*, 15(5), 559–570. https://doi.org/10.1175/1520-0434(2000)015<0559:DOTCRP>2.0.CO;2
* Johnson, S. J., Stockdale, T. N., Ferranti, L., et al. (2019). SEAS5: the new ECMWF seasonal forecast system.
  *Geoscientific Model Development*, 12, 1087–1117. https://doi.org/10.5194/gmd-12-1087-2019
* Manzanas, R., Gutiérrez, J. M., Bhend, J., Hemri, S., Doblas-Reyes, F. J., Torralba, V., Penabad, E., & Brookshaw, A.
  (2019). Bias adjustment and ensemble recalibration methods for seasonal forecasting: a comprehensive intercomparison
  using the C3S dataset. *Climate Dynamics*, 53, 1287–1305. https://doi.org/10.1007/s00382-019-04640-4
* Rajagopalan, B., Lall, U., & Zebiak, S. E. (2002). Categorical climate forecasts through regularization and optimal
  combination of multiple GCM ensembles. *Monthly Weather Review*, 130(7), 1792–1811.
  https://doi.org/10.1175/1520-0493(2002)130<1792:CCFTRA>2.0.CO;2
* Robertson, A. W., Lall, U., Zebiak, S. E., & Goddard, L. (2004). Improved combination of multiple atmospheric GCM
  ensembles for seasonal prediction. *Monthly Weather Review*, 132(12), 2732–2744. https://doi.org/10.1175/MWR2818.1
* Teutschbein, C., & Seibert, J. (2012). Bias correction of regional climate model simulations for hydrological
  climate-change impact studies: Review and evaluation of different methods. *Journal of Hydrology*, 456–457, 12–29.
  https://doi.org/10.1016/j.jhydrol.2012.05.052
* Torralba, V., Doblas-Reyes, F. J., MacLeod, D., Christel, I., & Davis, M. (2017). Seasonal climate prediction: A new
  source of information for the management of wind energy resources. *Journal of Applied Meteorology and Climatology*,
  56(5), 1231–1247. https://doi.org/10.1175/JAMC-D-16-0204.1
* Wilks, D. S. (2019). *Statistical Methods in the Atmospheric Sciences* (4th ed.). Elsevier.

All DOIs were checked against Crossref on 2026-10-11 (authors, year, journal, volume and pages match).
