# 47 — Rainfall bias-correction benchmark (September initialization, ONDJ)

Purpose: compare 13 rainfall-amount bias-correction methods member by member, for every 0.25° cell of Ethiopia and every
target (October, November, December, January and the ONDJ season), under one protocol, so a method can be chosen for
the operational tool on evidence. This is a read-only experiment: the operational forecasts are unchanged.

* Methods: `scripts/bias_methods.py` (one `fit` / `apply` pair per method; tests: `tests/test_bias_methods.py`)
* Runner: `scripts/bias_benchmark.py`, figures: `scripts/bias_benchmark_figures.py`
* Configuration: `config/bias_correction/sep_ondj.json` (targets, years, regions, methods and their parameters)
* Outputs: `outputs/bias_correction_benchmark/sep_ondj/` — `benchmark.json`, `cell_scores_full_loyo.nc`,
  `forecast_2026_members.nc`, `figures/`

```
python scripts\bias_benchmark.py --config config\bias_correction\sep_ondj.json
python scripts\bias_benchmark.py --methods mvs eqm qdm --targets ONDJ --no-figures     (a subset)
```

## 1. Common rules

* **Inputs:** the same per-member totals as the operational tool (`data/processed/init09_<target>/`): ECMWF SEAS5 remapped
  to 0.25°, CHIRPS v3.0, one value per member, cell and year. Each calendar month and the season are corrected separately.
* **All members, equal years:** 25 members 1993–2016 and 51 from 2017 are all used. A training year has total weight 1/Y
  whatever its member count (each member of year y weighs 1/(Y·M<sub>y</sub>)); every observed year weighs 1/Y. This is the
  operational rule (`calibration_core.fit_amount`), applied to means, variances, empirical CDFs and gamma fits alike. A
  test checks that repeating one year's members changes no method's result.
* **Member-wise:** each member is corrected individually and keeps its identity, so corrected members can be compared
  one by one. Delta Change is the only exception (see its definition).
* **Cells:** the 1,484 Ethiopia cells; a cell is corrected only if CHIRPS is complete in every training year.
* **"Future" period.** DC, DQM, QDM, SDM and CDF-t were designed for climate change: they keep the model's change between a
  reference period and a future period. In seasonal forecasting the "future" is the forecast itself: the target year's
  ensemble, compared with the model climatology of the training years. Its distribution is estimated from 25 or 51
  members only.

## 2. Methods (13; the list's two "Delta Change" entries are one method)

| Key | Method | Definition (per cell and target; μ, σ: equal-year weighted mean and standard deviation) | References |
| --- | --- | --- | --- |
| `ls` | Linear Scaling | x′ = x · μ<sub>obs</sub>/μ<sub>model</sub> (multiplicative, the precipitation form). Mean only. | Lenderink et al. 2007; Teutschbein & Seibert 2012 |
| `mvs` | Mean–Variance Scaling — **operational reference** | x′ = max(0, μ<sub>obs</sub> + r(x − μ<sub>model</sub>)), r = clip(σ<sub>obs</sub>/σ<sub>model</sub>, 0.5, 2); r = 1 where σ<sub>model</sub> < 1 mm | Torralba et al. 2017; Manzanas et al. 2019 |
| `vs` | Variance Scaling | The textbook form: the same algebra as MVS **without the project's limits** (r = σ<sub>obs</sub>/σ<sub>model</sub>, unbounded; clipped at 0). Kept separate only to test those limits. | Teutschbein & Seibert 2012 |
| `sqrt_mvs` | Square-root-space MVS | MVS on √x (r limits 0.5–2, r = 1 where σ<sub>model</sub> < 0.1 √mm), clipped at 0, squared back (docs/36) | Manzanas et al. 2019 |
| `pt` | Power Transformation | x′ = a·x<sup>b</sup>: b (0.1–3) makes the model's coefficient of variation equal CHIRPS's, then a matches the mean | Leander & Buishand 2007; Teutschbein & Seibert 2012 |
| `dc` | Delta Change | The CHIRPS totals of the training years, each multiplied by the forecast signal a = (forecast ensemble mean)/μ<sub>model</sub> (a limited to 0.2–5). **Not member-wise**: its ensemble has one value per training year. (Applied to each member instead, x·μ<sub>obs</sub>/μ<sub>model</sub>, it would be Linear Scaling.) | Hay et al. 2000; Teutschbein & Seibert 2012 |
| `loci` | Local Intensity Scaling | Model threshold with the observed frequency of totals above 1 mm; above it x′ = 1 + s(x − thr<sub>model</sub>), with s matching the mean wet intensity; below it 0. Designed for daily rainfall; for totals that are always wet it reduces to a scaling anchored at 0. | Schmidli et al. 2006 |
| `eqm` | Empirical Quantile Mapping | x′ = Q<sub>obs</sub>(F<sub>model</sub>(x)), weighted empirical CDFs (mid-point plotting positions, linear between values); outside the training range the end correction is kept as a ratio | Boé et al. 2007; Themeßl et al. 2011; Gudmundsson et al. 2012 |
| `gqm` | Gamma Quantile Mapping | x′ = G<sub>obs</sub><sup>−1</sup>(G<sub>model</sub>(x)), G = dry mass (≤ 1 mm) + gamma fitted by weighted maximum likelihood; Linear Scaling where fewer than 3 wet values | Piani et al. 2010 |
| `dqm` | Detrended Quantile Mapping | x′ = a · EQM(x/a), a = forecast ensemble mean / μ<sub>model</sub> (0.2–5): the forecast's relative anomaly is kept exactly, the distribution is mapped | Cannon et al. 2015 |
| `qdm` | Quantile Delta Mapping | τ = rank of x in the forecast ensemble; x′ = Q<sub>obs</sub>(τ) · x / Q<sub>model</sub>(τ) (ratio ≤ 5; x′ = Q<sub>obs</sub>(τ) where Q<sub>model</sub>(τ) ≤ 1 mm): each quantile's relative change is kept | Cannon et al. 2015 |
| `sdm` | Scaled Distribution Mapping | Relative form: gamma fits to CHIRPS, model climatology and the forecast ensemble; scaled relative change in recurrence intervals and rain frequency (1 mm threshold) | Switanek et al. 2017 |
| `cdft` | CDF-transform | F<sub>obs,f</sub> = F<sub>obs</sub>(F<sub>model</sub><sup>−1</sup>(F<sub>fc</sub>)), x′ = F<sub>obs,f</sub><sup>−1</sup>(F<sub>fc</sub>(x)) = Q<sub>fc</sub>(F<sub>model</sub>(Q<sub>obs</sub>(F<sub>fc</sub>(x)))); model and forecast first scaled to the CHIRPS mean (multiplicative form of the CDFt convention). Values stay within the scaled forecast ensemble's range. | Michelangeli et al. 2009; Vrac et al. 2012 |

Baseline (`raw`): the uncorrected ECMWF members, scored with the same rules but not gated.

Families: scaling (LS, MVS, VS, sqrt-MVS, PT, LOCI) and quantile mapping (EQM, GQM) use only the training statistics; the
change-preserving methods (DC, DQM, QDM, SDM, CDF-t) also use the forecast ensemble's own distribution.

## 3. Evaluation

| Design | Fits | Scored | Role |
| --- | --- | --- | --- |
| training | leave-one-year-out within 1993–2016 | each 1993–2016 year | clean evidence, gated |
| operational | 1993–2016 | 2017–2024 | exploratory (years seen before) |
| full | leave-one-year-out within 1993–2024 | each year | per-cell maps and distribution checks (descriptive) |
| forecast | 1993–2024 | 2026 members | member-by-member comparison (`forecast_2026_members.nc`) |

No method has a parameter tuned on scores, so plain leave-one-year-out is out-of-sample.

* **Amounts:** fair ensemble CRPS (Ferro 2014; fair for any ensemble size, so DC's 31-value ensembles compare with 25/51
  members) and CRPSS against the CHIRPS training climatology (the training years as an ensemble). The development run
  (`verify_calibration.py`) reports the ordinary CRPS, so its CRPSS is a little higher for the same members (ONDJ MVS
  2017–2024: 0.178 there, 0.164 here; ensemble-mean bias −25.46 mm in both).
* **Ensemble mean:** bias, MAE, RMSE and correlation over years.
* **Ensemble reliability:** spread–error ratio (√(mean ensemble variance·(K+1)/K) / RMSE of the ensemble mean; 1 is ideal)
  and rank (PIT) histograms of CHIRPS within the ensemble (10 bins), with the reliability index Σ|f<sub>i</sub> − 1/10|
  (Delle Monache et al. 2006).
* **Probabilities:** tercile RPS/RPSS of α = 0.5 smoothed member counts against the training CHIRPS terciles,
  **without** the climatology blend (the blend would partly hide differences between methods).
* **Distribution:** the pooled out-of-fold corrected members (equal-year weights) against CHIRPS of the same years: mean,
  standard deviation, 10th/50th/90th percentile ratios and the zero-fraction difference.
* **Regions:** all Ethiopia (primary) and the ONDJ R3 (Deyr) domain; area weights, then equal weight per year.
* **Gate (docs/36 rule):** each method against MVS, per target, for CRPS and for RPS: one-sided paired sign-flip test on the
  1993–2016 per-year scores, Holm-adjusted over the five targets, p < 0.05, and not worse over 2017–2024. With 12
  candidates this is a **screening**: a method that passes is a candidate, and adoption needs a confirmation run with the
  climatology blend (the `decision_gates.py` protocol) before it can replace MVS.

## 4. Results (September initialization, all Ethiopia)

Full numbers, including the ONDJ R3 (Deyr) domain, per-year scores and every gate statistic: `benchmark.json`.
✓ = passes the gate against MVS (Holm-adjusted p < 0.05 on 1993–2016 and not worse 2017–2024).

**Amount skill, CRPSS, leave-one-year-out 1993–2016 (gated: CRPS)**

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| Raw ECMWF (no correction) | -0.226 | -0.048 | -0.136 | -0.599 | -0.205 |
| Linear Scaling | -0.031 | +0.068 | -0.007 | -0.119 | +0.060 |
| Mean-Variance Scaling (operational) | -0.009 | +0.082 | +0.023 | -0.066 | +0.066 |
| Variance Scaling (unbounded) | -0.011 | +0.080 | +0.026 | -0.019 ✓ | +0.060 |
| Square-root-space Mean-Variance Scaling | -0.002 | +0.085 | +0.032 ✓ | +0.030 ✓ | +0.075 ✓ |
| Power Transformation | -0.006 | +0.079 | +0.016 | -0.029 | +0.067 |
| Delta Change | +0.022 | +0.089 | +0.027 | -0.049 | +0.097 |
| Local Intensity Scaling | -0.031 | +0.075 | +0.009 | -0.099 | +0.059 |
| Empirical Quantile Mapping | -0.020 | +0.071 | +0.033 | +0.011 ✓ | +0.046 |
| Gamma Quantile Mapping | -0.001 | +0.083 | +0.022 | +0.000 ✓ | +0.076 |
| Detrended Quantile Mapping | -0.002 | +0.072 | -0.004 | -0.071 | +0.066 |
| Quantile Delta Mapping | +0.005 | +0.074 | +0.016 | -0.022 | +0.071 |
| Scaled Distribution Mapping | +0.001 | +0.071 | -0.018 | -0.193 | +0.066 |
| CDF-transform | -0.009 | +0.067 | -0.026 | -0.117 | +0.065 |

**Amount skill, CRPSS, fit 1993–2016, scored 2017–2024 (exploratory)**

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| Raw ECMWF (no correction) | -0.152 | +0.009 | -0.239 | -0.656 | -0.146 |
| Linear Scaling | +0.029 | +0.109 | -0.155 | -0.214 | +0.112 |
| Mean-Variance Scaling (operational) | +0.038 | +0.144 | -0.075 | -0.125 | +0.164 |
| Variance Scaling (unbounded) | +0.036 | +0.145 | -0.073 | -0.032 | +0.168 |
| Square-root-space Mean-Variance Scaling | +0.038 | +0.148 | -0.067 | +0.063 | +0.175 |
| Power Transformation | +0.028 | +0.152 | -0.103 | -0.026 | +0.174 |
| Delta Change | +0.028 | +0.121 | -0.026 | -0.038 | +0.117 |
| Local Intensity Scaling | +0.027 | +0.118 | -0.120 | -0.148 | +0.112 |
| Empirical Quantile Mapping | +0.010 | +0.144 | -0.045 | +0.089 | +0.153 |
| Gamma Quantile Mapping | +0.038 | +0.150 | -0.081 | +0.021 | +0.178 |
| Detrended Quantile Mapping | +0.013 | +0.101 | -0.078 | -0.106 | +0.098 |
| Quantile Delta Mapping | +0.015 | +0.108 | -0.076 | +0.010 | +0.101 |
| Scaled Distribution Mapping | +0.012 | +0.098 | -0.107 | -0.226 | +0.098 |
| CDF-transform | +0.008 | +0.104 | -0.143 | -0.197 | +0.100 |

**Tercile skill, RPSS of smoothed member counts (no blend), 1993–2016 (gated: RPS)**

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| Raw ECMWF (no correction) | -0.165 | -0.043 | -0.175 | -0.516 | -0.149 |
| Linear Scaling | -0.033 | +0.035 | -0.080 | -0.144 | +0.025 |
| Mean-Variance Scaling (operational) | -0.009 | +0.044 | -0.068 | -0.213 | +0.035 |
| Variance Scaling (unbounded) | -0.009 | +0.045 | -0.060 | -0.175 ✓ | +0.036 |
| Square-root-space Mean-Variance Scaling | -0.005 | +0.060 ✓ | -0.030 ✓ | -0.017 ✓ | +0.038 |
| Power Transformation | -0.013 | +0.044 | -0.049 | -0.046 ✓ | +0.036 |
| Delta Change | -0.003 | +0.044 | -0.154 | -0.214 | +0.028 |
| Local Intensity Scaling | -0.028 | +0.047 | -0.109 | -0.153 | +0.024 |
| Empirical Quantile Mapping | -0.021 | +0.049 | -0.005 ✓ | -0.006 ✓ | +0.025 |
| Gamma Quantile Mapping | -0.006 | +0.051 | -0.113 | -0.161 | +0.039 |
| Detrended Quantile Mapping | -0.019 | +0.035 | -0.170 | -0.219 | +0.010 |
| Quantile Delta Mapping | -0.014 | +0.025 | -0.054 | -0.070 | +0.009 |
| Scaled Distribution Mapping | -0.018 | +0.022 | -0.163 | -0.275 | +0.001 |
| CDF-transform | -0.026 | +0.010 | -0.241 | -0.254 | +0.011 |

**Spread–error ratio, 1993–2016 (1 = spread matches the error)**

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| Raw ECMWF (no correction) | 0.61 | 0.68 | 0.63 | 0.39 | 0.54 |
| Linear Scaling | 0.72 | 0.94 | 1.15 | 1.81 | 0.78 |
| Mean-Variance Scaling (operational) | 0.90 | 1.01 | 0.96 | 0.83 | 0.96 |
| Variance Scaling (unbounded) | 0.93 | 1.02 | 1.00 | 1.00 | 1.01 |
| Square-root-space Mean-Variance Scaling | 0.90 | 0.97 | 0.95 | 1.07 | 0.94 |
| Power Transformation | 0.95 | 1.04 | 1.01 | 0.98 | 1.01 |
| Delta Change | 1.04 | 1.15 | 1.18 | 1.16 | 1.16 |
| Local Intensity Scaling | 0.72 | 0.95 | 1.10 | 1.59 | 0.77 |
| Empirical Quantile Mapping | 0.93 | 1.02 | 0.99 | 0.97 | 0.97 |
| Gamma Quantile Mapping | 0.90 | 0.96 | 0.94 | 0.98 | 0.93 |
| Detrended Quantile Mapping | 0.96 | 1.04 | 1.04 | 1.06 | 0.98 |
| Quantile Delta Mapping | 0.99 | 1.06 | 1.08 | 1.20 | 1.04 |
| Scaled Distribution Mapping | 1.00 | 1.07 | 1.05 | 1.00 | 1.05 |
| CDF-transform | 0.83 | 0.96 | 1.03 | 1.13 | 0.83 |

**Rank-histogram reliability index, 1993–2016 (0 = flat histogram; each rank interval shared among the bins it overlaps)**

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| Raw ECMWF (no correction) | 0.45 | 0.14 | 0.38 | 1.02 | 0.37 |
| Linear Scaling | 0.38 | 0.13 | 0.38 | 0.66 | 0.16 |
| Mean-Variance Scaling (operational) | 0.10 | 0.11 | 0.22 | 0.68 | 0.09 |
| Variance Scaling (unbounded) | 0.10 | 0.11 | 0.22 | 0.71 | 0.10 |
| Square-root-space Mean-Variance Scaling | 0.15 | 0.15 | 0.26 | 0.11 | 0.07 |
| Power Transformation | 0.18 | 0.11 | 0.28 | 0.26 | 0.05 |
| Delta Change | 0.05 | 0.13 | 0.42 | 0.50 | 0.05 |
| Local Intensity Scaling | 0.33 | 0.13 | 0.40 | 0.65 | 0.17 |
| Empirical Quantile Mapping | 0.11 | 0.07 | 0.10 | 0.16 | 0.10 |
| Gamma Quantile Mapping | 0.13 | 0.12 | 0.13 | 0.51 | 0.08 |
| Detrended Quantile Mapping | 0.10 | 0.10 | 0.41 | 0.51 | 0.08 |
| Quantile Delta Mapping | 0.11 | 0.05 | 0.12 | 0.13 | 0.09 |
| Scaled Distribution Mapping | 0.08 | 0.15 | 0.50 | 0.73 | 0.09 |
| CDF-transform | 0.22 | 0.19 | 0.53 | 0.59 | 0.12 |

**Share of corrected member values at 0 mm, 1993–2016**

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| Raw ECMWF (no correction) | 0.000 | 0.004 | 0.062 | 0.195 | 0.000 |
| Linear Scaling | 0.000 | 0.004 | 0.062 | 0.195 | 0.000 |
| Mean-Variance Scaling (operational) | 0.065 | 0.080 | 0.122 | 0.045 | 0.017 |
| Variance Scaling (unbounded) | 0.068 | 0.082 | 0.081 | 0.000 | 0.022 |
| Square-root-space Mean-Variance Scaling | 0.015 | 0.023 | 0.029 | 0.010 | 0.000 |
| Power Transformation | 0.000 | 0.004 | 0.062 | 0.195 | 0.000 |
| Delta Change | 0.005 | 0.008 | 0.006 | 0.010 | 0.000 |
| Local Intensity Scaling | 0.029 | 0.060 | 0.214 | 0.279 | 0.000 |
| Empirical Quantile Mapping | 0.003 | 0.004 | 0.003 | 0.004 | 0.000 |
| Gamma Quantile Mapping | 0.032 | 0.061 | 0.159 | 0.104 | 0.000 |
| Detrended Quantile Mapping | 0.002 | 0.004 | 0.003 | 0.004 | 0.000 |
| Quantile Delta Mapping | 0.003 | 0.004 | 0.003 | 0.004 | 0.000 |
| Scaled Distribution Mapping | 0.031 | 0.120 | 0.334 | 0.444 | 0.000 |
| CDF-transform | 0.000 | 0.003 | 0.003 | 0.002 | 0.000 |

**Standard deviation of the pooled corrected members / CHIRPS (area-weighted median of cell ratios, 1993–2024)**

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| Raw ECMWF (no correction) | 0.79 | 0.77 | 1.05 | 0.96 | 0.69 |
| Linear Scaling | 0.81 | 0.94 | 1.26 | 2.50 | 0.84 |
| Mean-Variance Scaling (operational) | 1.00 | 0.99 | 1.01 | 1.02 | 0.99 |
| Variance Scaling (unbounded) | 1.00 | 0.99 | 1.01 | 1.02 | 0.99 |
| Square-root-space Mean-Variance Scaling | 0.98 | 0.94 | 0.93 | 1.11 | 0.94 |
| Power Transformation | 1.00 | 1.00 | 1.01 | 1.00 | 1.00 |
| Delta Change | 1.06 | 1.09 | 1.17 | 1.34 | 1.07 |
| Local Intensity Scaling | 0.81 | 0.96 | 1.16 | 1.70 | 0.83 |
| Empirical Quantile Mapping | 1.00 | 0.99 | 0.99 | 1.00 | 0.98 |
| Gamma Quantile Mapping | 0.98 | 0.91 | 0.88 | 0.93 | 0.92 |
| Detrended Quantile Mapping | 0.99 | 1.00 | 1.09 | 1.34 | 0.96 |
| Quantile Delta Mapping | 1.01 | 1.03 | 1.16 | 1.41 | 0.99 |
| Scaled Distribution Mapping | 1.02 | 1.02 | 1.07 | 1.16 | 1.00 |
| CDF-transform | 0.93 | 0.98 | 1.13 | 1.53 | 0.89 |

**10th percentile of the pooled corrected members / CHIRPS (same)**

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| Raw ECMWF (no correction) | 1.27 | 0.52 | 0.06 | 0.00 | 0.93 |
| Linear Scaling | 1.25 | 0.73 | 0.07 | 0.00 | 1.03 |
| Mean-Variance Scaling (operational) | 0.88 | 0.61 | 0.62 | 1.16 | 0.86 |
| Variance Scaling (unbounded) | 0.85 | 0.58 | 0.72 | 1.17 | 0.82 |
| Square-root-space Mean-Variance Scaling | 0.95 | 0.75 | 0.57 | 0.86 | 0.91 |
| Power Transformation | 1.00 | 0.64 | 0.24 | 0.00 | 0.89 |
| Delta Change | 0.92 | 0.86 | 0.71 | 0.62 | 0.91 |
| Local Intensity Scaling | 1.20 | 0.65 | 0.26 | 0.00 | 1.04 |
| Empirical Quantile Mapping | 0.97 | 0.98 | 0.99 | 1.00 | 0.97 |
| Gamma Quantile Mapping | 0.97 | 0.80 | 0.68 | 1.02 | 0.94 |
| Detrended Quantile Mapping | 0.96 | 0.88 | 0.71 | 0.64 | 0.96 |
| Quantile Delta Mapping | 0.97 | 0.91 | 0.84 | 0.98 | 0.97 |
| Scaled Distribution Mapping | 0.95 | 0.68 | 0.00 | 0.00 | 0.96 |
| CDF-transform | 1.01 | 0.87 | 0.61 | 0.58 | 0.98 |

### Findings

1. **Every method is far better than the raw model.** Raw ECMWF scores CRPSS −0.205 for ONDJ (1993–2016): it is too
   dry (ensemble mean 14 % below CHIRPS for the season, 66 % below in January) and too narrow (spread–error ratio 0.54).
2. **Square-root-space MVS is the one consistent improvement.** It passes the amount gate for December, January and
   ONDJ and the tercile gate for November, December and January, and it is at least as good as MVS for every target in
   both periods (ONDJ CRPSS +0.075 vs +0.066 in 1993–2016 and +0.175 vs +0.164 in 2017–2024; January +0.030 vs −0.066).
   It cuts the members clipped to 0 mm from 6.5–12 % to 1.5–3 % in October–December (issue I-08). This repeats the
   May-initialized JJAS result (docs/36), where it passed the gate for amounts.
3. **Gamma QM is second.** Best ONDJ amount skill over Ethiopia in 2017–2024 (+0.178; in the ONDJ domain +0.382, after
   Power Transformation's +0.388), but it passes the gate only for January amounts and its tercile skill is lower than MVS
   in December.
4. **Empirical QM matches the CHIRPS distribution best** (standard deviation and percentile ratios ≈ 1 by construction) and
   passes in the dry months (January amounts; December and January terciles), but it is worse than MVS for October and
   the ONDJ season (CRPSS +0.046 vs +0.066): with 23 training years the CHIRPS quantile function has 23 points, and the
   mapping follows their noise.
5. **The project's ratio limits matter mainly in January.** Unbounded Variance Scaling is close to MVS elsewhere (slightly
   lower ONDJ amount skill, +0.060 vs +0.066). In January the raw model is far too narrow (spread–error 0.39), the upper
   limit r ≤ 2 binds and MVS stays too narrow (0.83), while unbounded scaling reaches 1.00 and passes both gates.
6. **Delta Change** has the highest 1993–2016 ONDJ CRPSS (+0.097) but the gain is not significant (Holm p = 0.18), it is
   worse in 2017–2024 (+0.117 vs +0.164), its ensemble is too wide (spread–error 1.16) and its tercile skill is low: it
   is essentially the CHIRPS climatology shifted by the forecast's mean.
7. **The change-preserving methods (DQM, QDM, SDM, CDF-t) do not help here.** Their tercile skill is lower (ONDJ RPSS
   +0.001 to +0.011 vs +0.035), and they are clearly worse than MVS in the south-east, where the ONDJ signal is
   (`figures/crpss_minus_mvs_ONDJ.png`). They rely on the distribution of one forecast's 25–51 members, which is too
   noisy; they were built for 30-year future periods. SDM sets 33–44 % of December–January members to 0 mm and is 37 %
   too dry in January; CDF-t stays too narrow (0.83) because its values cannot leave the forecast ensemble's range.
8. **Linear Scaling and LOCI** correct only the mean (LOCI, for always-wet totals, nearly so): too narrow in the wet
   months (spread–error 0.72–0.78) and too wide in January (1.6–1.8).
9. **Reliability of the ensemble (rank histograms).** MVS is reliable for October, November and ONDJ (index 0.09–0.11)
   but not for January (0.68). Empirical QM and QDM give the flattest histograms in the dry months (December 0.10–0.12,
   January 0.13–0.16), and square-root MVS is among the best for January (0.11) and ONDJ (0.07).
10. **December and January remain hard.** In 2017–2024 every method has negative December CRPSS; January is positive only
   for EQM (+0.089), square-root MVS (+0.063), Gamma QM (+0.021) and QDM (+0.010).

### Recommendation

* Shortlist **square-root-space MVS** (first) and **Gamma QM** (second) for the September cycle. Before either replaces
  MVS, run the confirmation with the climatology blend (nested λ, the `decision_gates.py` protocol): this screening
  compares 12 candidates, and the probabilities on the site are blended.
* Do not pursue DC, DQM, QDM, SDM or CDF-t for single-forecast seasonal ensembles; keep them in the benchmark for
  completeness.
* Scale to the other cycles with one configuration file each (`config/bias_correction/may_jjas.json`,
  `jan_fmam.json`, `feb_fmam.json`): only `cycle`, `project_config`, `targets`, the region masks and `output_root` change.

### Figures (`outputs/bias_correction_benchmark/sep_ondj/figures/`)

* `skill_summary.png` — CRPSS and RPSS by method and target, with gate marks
* `crpss_maps_<target>.png`, `crpss_minus_mvs_<target>.png` — per-cell skill and difference from MVS
* `pit_<target>.png` — rank histograms; `distribution.png` — distribution ratios
* `members_2026_<target>.png` — every 2026 member after each correction at three cells;
  `forecast_2026_percent_<target>.png` — 2026 corrected ensemble mean, % of normal, by method

## References

* Boé, J., Terray, L., Habets, F., & Martin, E. (2007). Statistical and dynamical downscaling of the Seine basin climate for
  hydro-meteorological studies. *International Journal of Climatology*, 27, 1643–1655. https://doi.org/10.1002/joc.1602
* Cannon, A. J., Sobie, S. R., & Murdock, T. Q. (2015). Bias correction of GCM precipitation by quantile mapping: how well
  do methods preserve changes in quantiles and extremes? *Journal of Climate*, 28, 6938–6959.
  https://doi.org/10.1175/JCLI-D-14-00754.1
* Delle Monache, L., Hacker, J. P., Zhou, Y., Deng, X., & Stull, R. B. (2006). Probabilistic aspects of meteorological and
  ozone regional ensemble forecasts. *Journal of Geophysical Research: Atmospheres*, 111, D24307.
  https://doi.org/10.1029/2005JD006917
* Ferro, C. A. T. (2014). Fair scores for ensemble forecasts. *Quarterly Journal of the Royal Meteorological Society*, 140,
  1917–1923. https://doi.org/10.1002/qj.2270
* Gudmundsson, L., Bremnes, J. B., Haugen, J. E., & Engen-Skaugen, T. (2012). Technical Note: Downscaling RCM precipitation
  to the station scale using statistical transformations — a comparison of methods. *Hydrology and Earth System Sciences*,
  16, 3383–3390. https://doi.org/10.5194/hess-16-3383-2012
* Hay, L. E., Wilby, R. L., & Leavesley, G. H. (2000). A comparison of delta change and downscaled GCM scenarios for three
  mountainous basins in the United States. *JAWRA Journal of the American Water Resources Association*, 36, 387–397.
  https://doi.org/10.1111/j.1752-1688.2000.tb04276.x
* Leander, R., & Buishand, T. A. (2007). Resampling of regional climate model output for the simulation of extreme river
  flows. *Journal of Hydrology*, 332, 487–496. https://doi.org/10.1016/j.jhydrol.2006.08.006
* Lenderink, G., Buishand, A., & van Deursen, W. (2007). Estimates of future discharges of the river Rhine using two
  scenario methodologies: direct versus delta approach. *Hydrology and Earth System Sciences*, 11, 1145–1159.
  https://doi.org/10.5194/hess-11-1145-2007
* Manzanas, R., et al. (2019). Bias adjustment and ensemble recalibration methods for seasonal forecasting: a comprehensive
  intercomparison using the C3S dataset. *Climate Dynamics*, 53, 1287–1305. https://doi.org/10.1007/s00382-019-04640-4
* Michelangeli, P.-A., Vrac, M., & Loukos, H. (2009). Probabilistic downscaling approaches: application to wind cumulative
  distribution functions. *Geophysical Research Letters*, 36, L11708. https://doi.org/10.1029/2009GL038401
* Piani, C., Weedon, G. P., Best, M., et al. (2010). Statistical bias correction of global simulated daily precipitation and
  temperature for the application of hydrological models. *Journal of Hydrology*, 395, 199–215.
  https://doi.org/10.1016/j.jhydrol.2010.10.024
* Schmidli, J., Frei, C., & Vidale, P. L. (2006). Downscaling from GCM precipitation: a benchmark for dynamical and
  statistical downscaling methods. *International Journal of Climatology*, 26, 679–689. https://doi.org/10.1002/joc.1287
* Switanek, M. B., Troch, P. A., Castro, C. L., et al. (2017). Scaled distribution mapping: a bias correction method that
  preserves raw climate model projected changes. *Hydrology and Earth System Sciences*, 21, 2649–2666.
  https://doi.org/10.5194/hess-21-2649-2017
* Teutschbein, C., & Seibert, J. (2012). Bias correction of regional climate model simulations for hydrological
  climate-change impact studies: review and evaluation of different methods. *Journal of Hydrology*, 456–457, 12–29.
  https://doi.org/10.1016/j.jhydrol.2012.05.052
* Themeßl, M. J., Gobiet, A., & Leuprecht, A. (2011). Empirical-statistical downscaling and error correction of daily
  precipitation from regional climate models. *International Journal of Climatology*, 31, 1530–1544.
  https://doi.org/10.1002/joc.2168
* Torralba, V., et al. (2017). Seasonal climate prediction: a new source of information for the management of wind energy
  resources. *Journal of Applied Meteorology and Climatology*, 56, 1231–1247. https://doi.org/10.1175/JAMC-D-16-0204.1
* Vrac, M., Drobinski, P., Merlo, A., et al. (2012). Dynamical and statistical downscaling of the French Mediterranean
  climate: uncertainty assessment. *Natural Hazards and Earth System Sciences*, 12, 2769–2784.
  https://doi.org/10.5194/nhess-12-2769-2012

DOIs checked against Crossref on 2026-10-11.
