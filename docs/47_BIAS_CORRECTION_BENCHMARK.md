# 47 — Rainfall bias-correction benchmark (all cycles; September ONDJ in detail)

Sections 1–6 describe the protocol and the September-initialized ONDJ results in detail; section 7 gives the results of the
same benchmark for the May (JJAS), January (FMAM) and February (FMAM) cycles.

Purpose: compare 13 rainfall-amount bias-correction methods with the operational one, member by member, for every 0.25° cell of
Ethiopia and every target (October, November, December, January and the ONDJ season), in two stages:

1. **Screening** — the amount correction alone, under one protocol (`scripts/bias_benchmark.py`).
2. **Confirmation** — every method through the full probability pipeline, with the blend weight fitted inside the folds, and
   selection-aware procedures that choose the method from training-only scores (`scripts/bias_confirmation.py`).

This is a read-only experiment: the operational forecasts still use mean–variance scaling (MVS). The site shows it under
**Bias correction** (`scripts/site_bias.py`).

* Methods: `scripts/bias_methods.py` (one `fit` / `apply` pair per method); tests: `tests/test_bias_methods.py`,
  `tests/test_bias_confirmation.py`
* Configuration: `config/bias_correction/sep_ondj.json` (targets, years, regions, methods and parameters, confirmation family)
* Outputs: `outputs/bias_correction_benchmark/sep_ondj/` — `benchmark.json`, `manifest.json`, `cell_scores_full_loyo.nc`,
  `forecast_2026_members.nc`, `figures/`, `confirmation/confirmation.json`, `confirmation/figures/`, `confirmation/parts/`
  (checkpoints)

```
python scripts\bias_benchmark.py --config config\bias_correction\sep_ondj.json        (screening; targets in parallel)
python scripts\bias_confirmation.py --config config\bias_correction\sep_ondj.json     (confirmation; resumes from checkpoints)
```

Revision 3 (11 October 2026; code at commit 1278483) answers the review of revision 2 (commits 007ce47 / 1e59fea);
revision 2 answered the review of revision 1 (e252baa). The changes are listed in section 8.

## 1. Common rules

* **Inputs:** the per-member totals the operational tool uses (`data/processed/init09_<target>/`): ECMWF SEAS5 remapped to
  0.25°, CHIRPS v3.0, one value per member, cell and year. Each calendar month and the season are corrected separately.
* **All members, equal years:** 25 members 1993–2016 and 51 from 2017 are all used. A training year has total weight 1/Y
  (each member of year y weighs 1/(Y·M<sub>y</sub>)); every observed year weighs 1/Y — in means, variances, empirical CDFs
  and gamma fits. A test checks that repeating one year's members changes no method's result.
* **Member-wise:** every member is corrected individually. Delta Change is the exception (historical scenarios).
* **Dry totals and ties:** a total ≤ 1 mm in the month or season is "dry" (not a dry day); exactly 0 mm is reported
  separately. For the quantile-mapping methods (EQM, Gamma QM, DQM, QDM) the dry shares of the model climatology and of
  CHIRPS are estimated with the equal-year weights; a forecast's dry members are spread evenly over the model's dry
  probability by rank (deterministic stratified tie-breaking, with ties resolved by member index), and a probability within
  the CHIRPS dry share maps to 0 mm — also after any extrapolation of the upper tail (revision 3). Without this, tied zeros share one probability and the corrected dry share does not follow
  CHIRPS (in the review's example, 25 % CHIRPS zeros and 50 % model zeros gave 0 % corrected zeros). CDF-t, LOCI and the
  scaling methods have no occurrence adjustment; SDM uses its own rain-member rule.
* **Diagnostics:** every method reports how often its limits, caps and fallbacks act (share of the corrected area for
  per-cell limits; share of members or cells for events).
* **"Future" period:** DC, DQM, QDM, SDM and CDF-t were designed for climate change. Here the "future" is the forecast
  itself: the target year's ensemble against the model climatology of the training years.

## 2. Methods (13; the requested list's two "Delta Change" entries are one method)

| Key | Method | Definition (per cell and target; μ, σ: equal-year weighted mean and standard deviation) | References |
| --- | --- | --- | --- |
| `ls` | Linear Scaling | x′ = x · μ<sub>obs</sub>/μ<sub>model</sub> (ratio 1 where μ<sub>model</sub> < 0.1 mm) | Lenderink et al. 2007; Teutschbein & Seibert 2012 |
| `mvs` | Mean–Variance Scaling — **operational reference** | x′ = max(0, μ<sub>obs</sub> + r(x − μ<sub>model</sub>)), r = clip(σ<sub>obs</sub>/σ<sub>model</sub>, 0.5, 2); r = 1 where σ<sub>model</sub> < 1 mm | Torralba et al. 2017; Manzanas et al. 2019 |
| `vs` | Variance Scaling | Same algebra **and the same r = 1 fallback** as MVS, without the 0.5–2 limits — the comparison isolates the limits | Teutschbein & Seibert 2012 |
| `sqrt_mvs` | Square-root-space MVS | MVS on √x (limits 0.5–2; r = 1 where the √-space σ < 0.1), clipped at 0, squared back (docs/36) | Manzanas et al. 2019 |
| `pt` | Power Transformation | x′ = a·x<sup>b</sup>: b (0.1–3) matches the coefficient of variation where reachable (bound hits reported), a the mean | Leander & Buishand 2007; Teutschbein & Seibert 2012 |
| `dc` | Delta Change | CHIRPS totals of the training years × a, a = forecast ensemble mean / μ<sub>model</sub> (0.2–5): **historical scenarios, not corrected members** (one value per training year). Member-wise it would be Linear Scaling. | Hay et al. 2000; Teutschbein & Seibert 2012 |
| `loci` | Local Intensity Scaling | Model threshold with the observed frequency of totals above 1 mm; intensity scaling above it. Designed for daily rainfall; here monthly or seasonal totals, where most cells are always "wet" and it acts like a scaling anchored at 0. | Schmidli et al. 2006 |
| `eqm` | Empirical Quantile Mapping | x′ = Q<sub>obs</sub>(F<sub>model</sub>(x)) with the dry policy; weighted empirical CDFs (mid-point positions); constant-ratio extrapolation outside the training range | Boé et al. 2007; Themeßl et al. 2011; Gudmundsson et al. 2012 |
| `gqm` | Gamma Quantile Mapping | x′ = G<sub>obs</sub><sup>−1</sup>(G<sub>model</sub>(x)), G = dry mass (≤ 1 mm) + gamma by weighted maximum likelihood, with the dry policy; linear scaling where fewer than 3 wet values; 0 mm where CHIRPS is never wet | Piani et al. 2010 |
| `dqm` | Detrended Quantile Mapping | x′ = a · EQM(x/a), a = forecast ensemble mean / μ<sub>model</sub> (0.2–5): removes and reapplies the bounded ratio while quantile-mapping the normalized forecast. **Exact preservation of the final mean anomaly is not guaranteed** (the mapping changes the normalized mean). | Cannon et al. 2015 |
| `qdm` | Quantile Delta Mapping | τ = rank of x in the forecast ensemble; x′ = Q<sub>obs</sub>(τ) · x / Q<sub>model</sub>(τ). The relative change is capped at 5 and replaced by Q<sub>obs</sub>(τ) where Q<sub>model</sub>(τ) ≤ 1 mm (both counted), so the quantile changes are only partly preserved there. | Cannon et al. 2015 |
| `sdm` | Scaled Distribution Mapping | Switanek et al. (2017), precipitation steps 1–7: gamma fits to the wet CHIRPS, model-climatology and forecast values; recurrence intervals RI = 1/(1 − CDF) computed first and then linearly interpolated to the forecast's length (keeping their range); RI<sub>scaled</sub> = max(1, RI<sub>obs</sub>·RI<sub>fc</sub>/RI<sub>model</sub>); x = ICDF<sub>obs</sub>(CDF<sub>scaled</sub>)·SF; number of rain members from Eq. (1), never increased. Model climatology with equal-year weights (positions by cumulative weight). Checked numerically against an independent implementation of the steps. | Switanek et al. 2017 |
| `cdft` | CDF-transform | F<sub>obs,f</sub> = F<sub>obs</sub>(F<sub>model</sub><sup>−1</sup>(F<sub>fc</sub>)); x′ = F<sub>obs,f</sub><sup>−1</sup>(F<sub>fc</sub>(x)) = Q<sub>fc</sub>(F<sub>model</sub>(Q<sub>obs</sub>(F<sub>fc</sub>(x)))). Implementation choices: model and forecast first scaled to the CHIRPS mean; values stay within the scaled forecast range (members at its edge counted). | Michelangeli et al. 2009; Vrac et al. 2012 |

Baseline (`raw`): the uncorrected ECMWF members, scored with the same rules but not screened.

Variant (`mvs_zero_guard`, revision 3): operational MVS, but corrected totals are 0 mm where every training year has exactly
0 mm. Without it, MVS returns positive totals there because its spread ratio cannot fall below 0.5 (CHIRPS always 0 mm and
members 0, 0, 20, 40 mm give 0, 0, 2.5, 12.5 mm). It is a documented modelling choice — a finite history of zero rainfall does
not make rain impossible — screened against MVS within method, outside the declared family, and never selected by SEL-P or
SEL-A.

## 3. Screening (`bias_benchmark.py`)

| Design | Fits | Scored | Role |
| --- | --- | --- | --- |
| training | leave-one-year-out within 1993–2016 | each 1993–2016 year | clean screening evidence |
| test ("operational") | 1993–2016 | 2017–2024 | exploratory (years seen before) |
| full | leave-one-year-out within 1993–2024 | each year | per-cell maps and distribution checks (descriptive) |
| forecast | 1993–2024 | 2026 members | member-by-member comparison |

* **Amounts:** CRPS of the corrected ensemble's empirical distribution as delivered (primary) and CRPSS against the CHIRPS
  training climatology, scored the same way. The **fair CRPS** (Ferro 2014) is reported and screened separately as a
  diagnostic under the sampling interpretation, which DC's rescaled years and the methods tied to the forecast mean or ranks
  only approximate. Revision 1 used the fair CRPS as primary.
* **Ensemble:** ensemble-mean bias, MAE, RMSE, correlation; spread–error ratio; rank histograms (each rank interval shared
  among the bins it overlaps) and the reliability index Σ|f<sub>i</sub> − 1/10| (Delle Monache et al. 2006).
* **Probabilities:** tercile RPS/RPSS of α = 0.5 smoothed member counts **without** the climatology blend (isolates the
  amount correction).
* **Distribution and dry shares:** pooled out-of-fold corrected members (equal-year weights) against CHIRPS of the same
  years — mean, standard deviation, 10th/50th/90th percentiles (area-weighted medians of cell ratios), shares at exactly
  0 mm and ≤ 1 mm.
* **Coverage:** cells and area share scored for amounts and for probabilities (tercile scores need two distinct tercile
  boundaries defining three categories, a CHIRPS standard deviation of at least 1 mm and a lower boundary above 0 mm).
* **Climate groups (revision 3):** each cell is grouped by its CHIRPS totals in the fold's training years only — every year
  exactly 0 mm; every year ≤ 1 mm; mixed dry and wet years; never dry — and the area-weighted CRPS difference from MVS is
  split by group (the parts add up to the national difference).
* **Screening rule:** per target and score (CRPS, fair CRPS, RPS), one-sided sign-flip test on the 1993–2016 per-year scores
  against MVS and no harm over 2017–2024. Two multiplicity families: **within one method** across its 5 targets
  (`screen_pass`, ✓) and **across all 12 methods × 5 targets** (`screen_pass_family`, ✓✓). A pass is screening evidence, not
  an adoption decision; the field is no longer called `adopt`.
* **Variants:** sensitivity variants (the MVS all-zero guard) are scored and screened within method, outside the declared
  family: they do not enter the family-wide correction and are never chosen by the selection-aware procedures.
* **Provenance:** `benchmark.json` records the commit (and whether the working tree had changes), SHA-256 of the code, the
  configuration, the masks and every input file (one digest per target), the scoring version and the software versions;
  `manifest.json` lists the SHA-256 of every output file.

## 4. Confirmation (`bias_confirmation.py`)

* **Pipeline** for each method (the operational one with the amount correction swapped): corrected members → tercile counts
  against the training CHIRPS terciles → α smoothing → blend with climatology, one λ per target from leave-one-year-out
  within the training years (`local_blend.fit_weights`, over the full rectangle as operationally). A test checks that with
  MVS the pipeline reproduces the operational records (`compare_calibration.make_record`) exactly, and the ONDJ MVS score
  reproduces the operational nested cross-validated RPSS (+0.039).
* **Design:** outer leave-one-year-out over 1993–2016. For outer year y every fit — amount correction, terciles,
  climatology and λ (inner leave-one-year-out within the other 23 years) — uses only the other training years. Each pair
  of excluded years is fitted once and reused.
* **Selection-aware procedures:** for each outer year, **SEL-P** chooses the method with the lowest inner blended RPS
  (probability product) and **SEL-A** the lowest inner CRPS (amount product), from training-only scores; their outer
  scores therefore include the choice among the declared family (all 13 methods). Test years: fits, λ and the choice on
  1993–2016, scored on 2017–2024 (exploratory).
* **Scores:** blended RPS/RPSS, category Brier scores and skill (below and above normal), reliability tables, amount CRPS
  (and fair CRPS).
* **Tests:** each method against MVS with Holm across the whole family (12 methods × 5 targets); SEL-P and SEL-A against MVS
  with Holm across the 5 targets (the search is inside the procedure). "Confirmed" = better with adjusted p < 0.05 and not
  worse over 2017–2024.

## 5. Screening results (national aggregate, all Ethiopia)

Full numbers, including the ONDJ R3 (Deyr) domain, per-year scores, diagnostics and every screening statistic:
`benchmark.json`. ✓ = screening pass within the method; ✓✓ = also across all 60 method–target comparisons.

**Amount skill, CRPSS (ensemble CRPS), leave-one-year-out 1993–2016**

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| Raw ECMWF (no correction) | -0.203 | -0.033 | -0.118 | -0.551 | -0.180 |
| Linear Scaling | -0.016 | +0.073 | -0.008 | -0.132 | +0.070 |
| Mean-Variance Scaling (operational) | -0.002 | +0.084 | +0.028 | -0.048 | +0.070 |
| Variance Scaling (unbounded) | -0.004 | +0.082 | +0.031 | -0.007 ✓ | +0.063 |
| Square-root-space Mean-Variance Scaling | +0.006 | +0.089 | +0.037 ✓ | +0.034 ✓✓ | +0.080 ✓ |
| Power Transformation | +0.001 | +0.082 | +0.020 | -0.025 | +0.071 |
| Delta Change | +0.021 | +0.085 | +0.026 | -0.047 | +0.093 |
| Local Intensity Scaling | -0.016 | +0.079 | +0.010 | -0.104 | +0.070 |
| Empirical Quantile Mapping | -0.012 | +0.075 | +0.033 | +0.010 | +0.053 |
| Gamma Quantile Mapping | +0.007 | +0.088 | +0.030 | +0.015 ✓✓ | +0.082 ✓ |
| Detrended Quantile Mapping | +0.005 | +0.075 | -0.001 | -0.065 | +0.072 |
| Quantile Delta Mapping | +0.010 | +0.076 | +0.014 | -0.027 | +0.075 |
| Scaled Distribution Mapping | -0.002 | +0.068 | -0.021 | -0.216 | +0.061 |
| CDF-transform | +0.002 | +0.073 | -0.019 | -0.108 | +0.074 |
| MVS with all-zero guard (variant) | -0.002 | +0.084 | +0.028 | -0.048 | +0.070 |

**Amount skill, CRPSS, fit 1993–2016, scored 2017–2024 (exploratory)**

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| Raw ECMWF (no correction) | -0.120 | +0.031 | -0.183 | -0.573 | -0.116 |
| Linear Scaling | +0.054 | +0.125 | -0.114 | -0.182 | +0.131 |
| Mean-Variance Scaling (operational) | +0.059 | +0.158 | -0.033 | -0.078 | +0.178 |
| Variance Scaling (unbounded) | +0.056 | +0.159 | -0.032 | +0.007 | +0.182 |
| Square-root-space Mean-Variance Scaling | +0.060 | +0.162 | -0.026 | +0.093 | +0.189 |
| Power Transformation | +0.049 | +0.165 | -0.062 | +0.007 | +0.188 |
| Delta Change | +0.028 | +0.117 | -0.019 | -0.030 | +0.114 |
| Local Intensity Scaling | +0.052 | +0.134 | -0.079 | -0.115 | +0.131 |
| Empirical Quantile Mapping | +0.033 | +0.158 | -0.015 | +0.105 | +0.168 |
| Gamma Quantile Mapping | +0.059 | +0.165 | -0.037 | +0.053 | +0.192 |
| Detrended Quantile Mapping | +0.034 | +0.116 | -0.042 | -0.063 | +0.115 |
| Quantile Delta Mapping | +0.036 | +0.123 | -0.043 | +0.032 | +0.118 |
| Scaled Distribution Mapping | +0.025 | +0.103 | -0.055 | -0.184 | +0.108 |
| CDF-transform | +0.030 | +0.120 | -0.097 | -0.151 | +0.118 |
| MVS with all-zero guard (variant) | +0.059 | +0.158 | -0.033 | -0.078 | +0.178 |

**Fair CRPSS (diagnostic), 1993–2016**

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| Raw ECMWF (no correction) | -0.226 | -0.048 | -0.136 | -0.599 | -0.205 |
| Linear Scaling | -0.031 | +0.068 | -0.007 | -0.119 | +0.060 |
| Mean-Variance Scaling (operational) | -0.009 | +0.082 | +0.023 | -0.066 | +0.066 |
| Variance Scaling (unbounded) | -0.011 | +0.080 | +0.026 | -0.019 ✓✓ | +0.060 |
| Square-root-space Mean-Variance Scaling | -0.002 | +0.085 | +0.032 ✓ | +0.030 ✓✓ | +0.075 ✓ |
| Power Transformation | -0.006 | +0.079 | +0.016 | -0.029 | +0.067 |
| Delta Change | +0.022 | +0.089 | +0.027 | -0.049 | +0.097 |
| Local Intensity Scaling | -0.031 | +0.075 | +0.009 | -0.099 | +0.059 |
| Empirical Quantile Mapping | -0.020 | +0.071 | +0.027 | +0.004 ✓ | +0.046 |
| Gamma Quantile Mapping | -0.001 | +0.083 | +0.024 | +0.008 ✓✓ | +0.076 |
| Detrended Quantile Mapping | -0.002 | +0.072 | -0.007 | -0.073 | +0.066 |
| Quantile Delta Mapping | +0.005 | +0.074 | +0.010 | -0.030 | +0.071 |
| Scaled Distribution Mapping | -0.013 | +0.059 | -0.035 | -0.240 | +0.052 |
| CDF-transform | -0.009 | +0.067 | -0.026 | -0.117 | +0.065 |
| MVS with all-zero guard (variant) | -0.009 | +0.082 | +0.023 | -0.066 | +0.066 |

**Tercile skill, RPSS of smoothed member counts (no blend), 1993–2016**

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| Raw ECMWF (no correction) | -0.165 | -0.043 | -0.175 | -0.516 | -0.149 |
| Linear Scaling | -0.033 | +0.035 | -0.080 | -0.144 | +0.025 |
| Mean-Variance Scaling (operational) | -0.009 | +0.044 | -0.068 | -0.213 | +0.035 |
| Variance Scaling (unbounded) | -0.009 | +0.045 | -0.060 | -0.176 ✓ | +0.036 |
| Square-root-space Mean-Variance Scaling | -0.005 | +0.060 ✓✓ | -0.030 ✓ | -0.017 ✓✓ | +0.038 |
| Power Transformation | -0.013 | +0.044 | -0.049 | -0.046 ✓✓ | +0.036 |
| Delta Change | -0.003 | +0.044 | -0.154 | -0.214 | +0.028 |
| Local Intensity Scaling | -0.028 | +0.047 | -0.109 | -0.153 | +0.024 |
| Empirical Quantile Mapping | -0.023 | +0.046 | -0.065 | -0.010 ✓ | +0.025 |
| Gamma Quantile Mapping | -0.006 | +0.052 | -0.111 | -0.038 ✓✓ | +0.039 |
| Detrended Quantile Mapping | -0.020 | +0.031 | -0.189 | -0.211 | +0.010 |
| Quantile Delta Mapping | -0.015 | +0.020 | -0.116 | -0.074 | +0.009 |
| Scaled Distribution Mapping | -0.025 | +0.018 | -0.192 | -0.321 | -0.005 |
| CDF-transform | -0.026 | +0.010 | -0.241 | -0.254 | +0.011 |
| MVS with all-zero guard (variant) | -0.009 | +0.044 | -0.068 | -0.213 | +0.035 |

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
| Empirical Quantile Mapping | 0.93 | 1.02 | 0.99 | 0.98 | 0.97 |
| Gamma Quantile Mapping | 0.90 | 0.96 | 0.94 | 0.98 | 0.93 |
| Detrended Quantile Mapping | 0.96 | 1.04 | 1.04 | 1.06 | 0.98 |
| Quantile Delta Mapping | 0.99 | 1.07 | 1.08 | 1.20 | 1.04 |
| Scaled Distribution Mapping | 0.81 | 0.87 | 0.81 | 0.75 | 0.86 |
| CDF-transform | 0.83 | 0.96 | 1.03 | 1.13 | 0.83 |
| MVS with all-zero guard (variant) | 0.90 | 1.01 | 0.96 | 0.83 | 0.96 |

**Rank-histogram reliability index, 1993–2016 (0 = flat)**

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| Raw ECMWF (no correction) | 0.45 | 0.14 | 0.38 | 1.02 | 0.37 |
| Linear Scaling | 0.38 | 0.13 | 0.38 | 0.66 | 0.16 |
| Mean-Variance Scaling (operational) | 0.10 | 0.11 | 0.22 | 0.68 | 0.09 |
| Variance Scaling (unbounded) | 0.10 | 0.11 | 0.21 | 0.69 | 0.10 |
| Square-root-space Mean-Variance Scaling | 0.15 | 0.15 | 0.26 | 0.11 | 0.07 |
| Power Transformation | 0.18 | 0.11 | 0.28 | 0.26 | 0.05 |
| Delta Change | 0.05 | 0.13 | 0.42 | 0.50 | 0.05 |
| Local Intensity Scaling | 0.33 | 0.13 | 0.40 | 0.65 | 0.17 |
| Empirical Quantile Mapping | 0.09 | 0.07 | 0.25 | 0.23 | 0.10 |
| Gamma Quantile Mapping | 0.13 | 0.13 | 0.23 | 0.42 | 0.08 |
| Detrended Quantile Mapping | 0.08 | 0.10 | 0.45 | 0.52 | 0.08 |
| Quantile Delta Mapping | 0.09 | 0.08 | 0.33 | 0.27 | 0.09 |
| Scaled Distribution Mapping | 0.17 | 0.15 | 0.53 | 0.78 | 0.18 |
| CDF-transform | 0.22 | 0.19 | 0.53 | 0.59 | 0.12 |
| MVS with all-zero guard (variant) | 0.10 | 0.11 | 0.22 | 0.68 | 0.09 |

**Share of corrected totals ≤ 1 mm (%), pooled leave-one-year-out 1993–2024.** CHIRPS: Oct 2.3% / Nov 5.2% / Dec 18.9% / Jan 16.6% / ONDJ 0.0%

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| Raw ECMWF (no correction) | 0.8 | 8.5 | 32.5 | 55.3 | 0.0 |
| Linear Scaling | 0.9 | 7.7 | 32.2 | 43.1 | 0.0 |
| Mean-Variance Scaling (operational) | 5.0 | 9.4 | 22.2 | 16.8 | 1.6 |
| Variance Scaling (unbounded) | 5.2 | 10.0 | 21.3 | 16.1 | 2.1 |
| Square-root-space Mean-Variance Scaling | 2.7 | 6.3 | 19.6 | 17.2 | 0.1 |
| Power Transformation | 1.5 | 6.5 | 26.1 | 27.2 | 0.0 |
| Delta Change | 2.4 | 5.7 | 20.4 | 20.6 | 0.0 |
| Local Intensity Scaling | 2.3 | 5.5 | 21.5 | 28.1 | 0.0 |
| Empirical Quantile Mapping | 2.4 | 5.3 | 19.0 | 16.7 | 0.0 |
| Gamma Quantile Mapping | 3.2 | 7.9 | 23.4 | 18.7 | 0.0 |
| Detrended Quantile Mapping | 2.4 | 5.6 | 21.4 | 21.6 | 0.0 |
| Quantile Delta Mapping | 2.6 | 6.1 | 20.7 | 17.2 | 0.0 |
| Scaled Distribution Mapping | 3.7 | 12.8 | 39.8 | 56.4 | 0.7 |
| CDF-transform | 2.0 | 4.9 | 20.0 | 19.3 | 0.0 |
| MVS with all-zero guard (variant) | 5.0 | 9.4 | 22.2 | 16.8 | 1.6 |

**Share of corrected totals at exactly 0 mm (%).** CHIRPS: Oct 0.4% / Nov 0.7% / Dec 0.6% / Jan 1.0% / ONDJ 0.0%

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| Raw ECMWF (no correction) | 0.0 | 0.5 | 6.5 | 20.0 | 0.0 |
| Linear Scaling | 0.0 | 0.5 | 6.5 | 20.0 | 0.0 |
| Mean-Variance Scaling (operational) | 4.3 | 7.6 | 12.0 | 4.6 | 1.5 |
| Variance Scaling (unbounded) | 4.4 | 8.2 | 8.9 | 1.5 | 2.0 |
| Square-root-space Mean-Variance Scaling | 0.9 | 2.2 | 2.7 | 0.8 | 0.0 |
| Power Transformation | 0.0 | 0.5 | 6.5 | 20.0 | 0.0 |
| Delta Change | 0.4 | 0.7 | 0.6 | 1.0 | 0.0 |
| Local Intensity Scaling | 2.3 | 5.5 | 21.5 | 28.1 | 0.0 |
| Empirical Quantile Mapping | 2.3 | 5.2 | 18.9 | 16.6 | 0.0 |
| Gamma Quantile Mapping | 2.5 | 5.5 | 18.2 | 14.9 | 0.0 |
| Detrended Quantile Mapping | 2.2 | 4.9 | 18.6 | 16.5 | 0.0 |
| Quantile Delta Mapping | 2.3 | 5.2 | 18.9 | 16.6 | 0.0 |
| Scaled Distribution Mapping | 3.6 | 12.4 | 36.0 | 48.1 | 0.7 |
| CDF-transform | 0.0 | 0.3 | 0.3 | 0.2 | 0.0 |
| MVS with all-zero guard (variant) | 4.3 | 7.6 | 12.0 | 4.6 | 1.5 |

**Standard deviation of the pooled corrected members / CHIRPS (area-weighted median of cell ratios)**

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
| Empirical Quantile Mapping | 1.00 | 0.99 | 1.00 | 1.00 | 0.98 |
| Gamma Quantile Mapping | 0.98 | 0.91 | 0.88 | 0.91 | 0.92 |
| Detrended Quantile Mapping | 0.99 | 1.00 | 1.09 | 1.29 | 0.96 |
| Quantile Delta Mapping | 1.01 | 1.03 | 1.16 | 1.37 | 0.99 |
| Scaled Distribution Mapping | 0.88 | 0.85 | 0.87 | 0.97 | 0.86 |
| CDF-transform | 0.93 | 0.98 | 1.13 | 1.53 | 0.89 |
| MVS with all-zero guard (variant) | 1.00 | 0.99 | 1.01 | 1.02 | 0.99 |

**Score coverage (share of the national area, mean per year, 1993–2016)**

| Target | Amount area | Probability area |
| --- | --- | --- |
| Oct | 100% | 100% |
| Nov | 100% | 100% |
| Dec | 100% | 93% |
| Jan | 100% | 77% |
| ONDJ | 100% | 100% |

**Where the CRPS differences from MVS come from: cells grouped by their training-year climate (January; mm, negative
favours the method; the groups add up to the total; groups from each fold's training years only)**

| Method | Total | all 0 mm (0.0% of area) | all ≤ 1 mm (9.2% of area) | mixed (10.6% of area) | always wet (80.2% of area) |
| --- | --- | --- | --- | --- | --- |
| Linear Scaling | +0.487 | +0.000 | +0.003 | +0.003 | +0.480 |
| Variance Scaling (unbounded) | -0.240 | +0.000 | -0.005 | -0.006 | -0.229 |
| Square-root-space Mean-Variance Scaling | -0.479 | +0.000 | -0.003 | -0.018 | -0.458 |
| Power Transformation | -0.134 | +0.000 | +0.001 | -0.004 | -0.131 |
| Delta Change | -0.005 | +0.000 | +0.001 | -0.006 | -0.001 |
| Local Intensity Scaling | +0.325 | +0.000 | +0.010 | +0.011 | +0.303 |
| Empirical Quantile Mapping | -0.337 | +0.000 | +0.010 | +0.011 | -0.359 |
| Gamma Quantile Mapping | -0.365 | +0.000 | +0.010 | +0.003 | -0.378 |
| Detrended Quantile Mapping | +0.100 | +0.000 | +0.010 | +0.011 | +0.079 |
| Quantile Delta Mapping | -0.121 | +0.000 | +0.010 | +0.012 | -0.144 |
| Scaled Distribution Mapping | +0.977 | +0.000 | +0.003 | +0.027 | +0.947 |
| CDF-transform | +0.350 | +0.000 | +0.004 | +0.003 | +0.343 |
| MVS with all-zero guard (variant) | +0.000 | +0.000 | +0.000 | +0.000 | +0.000 |

**The same for December**

| Method | Total | all 0 mm (0.0% of area) | all ≤ 1 mm (2.9% of area) | mixed (23.6% of area) | always wet (73.6% of area) |
| --- | --- | --- | --- | --- | --- |
| Linear Scaling | +0.266 | +0.000 | -0.001 | +0.002 | +0.264 |
| Variance Scaling (unbounded) | -0.022 | +0.000 | -0.001 | -0.004 | -0.017 |
| Square-root-space Mean-Variance Scaling | -0.065 | +0.000 | -0.001 | -0.014 | -0.051 |
| Power Transformation | +0.063 | +0.000 | -0.001 | -0.013 | +0.077 |
| Delta Change | +0.019 | +0.000 | -0.001 | -0.028 | +0.048 |
| Local Intensity Scaling | +0.136 | +0.000 | +0.001 | +0.005 | +0.130 |
| Empirical Quantile Mapping | -0.033 | +0.000 | +0.001 | +0.011 | -0.044 |
| Gamma Quantile Mapping | -0.015 | +0.000 | +0.001 | +0.010 | -0.026 |
| Detrended Quantile Mapping | +0.218 | +0.000 | +0.001 | +0.018 | +0.199 |
| Quantile Delta Mapping | +0.105 | +0.000 | +0.001 | +0.007 | +0.097 |
| Scaled Distribution Mapping | +0.360 | +0.000 | -0.001 | +0.006 | +0.354 |
| CDF-transform | +0.346 | +0.000 | -0.001 | -0.006 | +0.353 |
| MVS with all-zero guard (variant) | +0.000 | +0.000 | +0.000 | +0.000 | +0.000 |

No cell of Ethiopia has exactly 0 mm in every training year for any target, so the "all 0 mm" group is empty and the MVS
all-zero guard (variant) is identical to MVS everywhere.

**Limits, caps and fallbacks (December, January and ONDJ; 1993–2016, mean over folds)**

| Method | Target | Activated |
| --- | --- | --- |
| Linear Scaling | Dec | mean fallback 0.4% of area |
| Linear Scaling | Jan | mean fallback 2.8% of area |
| Mean-Variance Scaling (operational) | Dec | sd fallback 1.3% of area; ratio lower limit 17.3% of area; ratio upper limit 5.8% of area; clipped at zero 12.2% |
| Mean-Variance Scaling (operational) | Jan | sd fallback 3.9% of area; ratio lower limit 25.8% of area; ratio upper limit 28.2% of area; clipped at zero 4.5% |
| Mean-Variance Scaling (operational) | ONDJ | ratio lower limit 2.2% of area; ratio upper limit 22.3% of area; clipped at zero 1.7% |
| Variance Scaling (unbounded) | Dec | sd fallback 1.3% of area; clipped at zero 8.9% |
| Variance Scaling (unbounded) | Jan | sd fallback 3.9% of area; clipped at zero 1.8% |
| Variance Scaling (unbounded) | ONDJ | clipped at zero 2.2% |
| Square-root-space Mean-Variance Scaling | Dec | ratio lower limit 14.0% of area; clipped at zero 2.9% |
| Square-root-space Mean-Variance Scaling | Jan | ratio lower limit 30.9% of area; ratio upper limit 0.3% of area; clipped at zero 1.0% |
| Square-root-space Mean-Variance Scaling | ONDJ | ratio lower limit 0.0% of area; ratio upper limit 1.8% of area; clipped at zero 0.0% |
| Power Transformation | Dec | b at bound 1.7% of area |
| Power Transformation | Jan | b at bound 23.3% of area |
| Delta Change | Dec | mean fallback 0.4% of area; ratio capped 0.1% |
| Delta Change | Jan | mean fallback 2.8% of area; ratio capped 1.1% |
| Local Intensity Scaling | Dec | always wet 73.6% of area; never wet 2.9% of area |
| Local Intensity Scaling | Jan | always wet 80.2% of area; never wet 9.2% of area |
| Local Intensity Scaling | ONDJ | always wet 100.0% of area |
| Empirical Quantile Mapping | Dec | model has dry 98.9% of area; obs has dry 26.4% of area; extrapolated 0.2% |
| Empirical Quantile Mapping | Jan | model has dry 100.0% of area; obs has dry 19.8% of area; extrapolated 0.2% |
| Empirical Quantile Mapping | ONDJ | model has dry 1.6% of area; extrapolated 0.4% |
| Gamma Quantile Mapping | Dec | gamma fallback 2.7% of area; model has dry 98.9% of area; obs has dry 26.4% of area |
| Gamma Quantile Mapping | Jan | gamma fallback 4.5% of area; model has dry 100.0% of area; obs has dry 19.8% of area |
| Gamma Quantile Mapping | ONDJ | model has dry 1.6% of area |
| Detrended Quantile Mapping | Dec | model has dry 98.9% of area; obs has dry 26.4% of area; ratio capped 0.1%; extrapolated 0.1% |
| Detrended Quantile Mapping | Jan | model has dry 100.0% of area; obs has dry 19.8% of area; ratio capped 1.1%; extrapolated 0.1% |
| Detrended Quantile Mapping | ONDJ | model has dry 1.6% of area; extrapolated 0.2% |
| Quantile Delta Mapping | Dec | model has dry 98.9% of area; obs has dry 26.4% of area; low denominator 31.5%; ratio capped 0.4% |
| Quantile Delta Mapping | Jan | model has dry 100.0% of area; obs has dry 19.8% of area; low denominator 54.4%; ratio capped 0.2% |
| Quantile Delta Mapping | ONDJ | model has dry 1.6% of area; ratio capped 0.0% |
| Scaled Distribution Mapping | Dec | gamma fallback 5.5% of area; linear scaling fallback 5.9% |
| Scaled Distribution Mapping | Jan | gamma fallback 13.7% of area; linear scaling fallback 23.4% |
| CDF-transform | Dec | mean fallback 0.4% of area; at forecast range edge 2.2% |
| CDF-transform | Jan | mean fallback 2.8% of area; at forecast range edge 0.6% |
| CDF-transform | ONDJ | at forecast range edge 9.5% |
| MVS with all-zero guard (variant) | Dec | sd fallback 1.3% of area; ratio lower limit 17.3% of area; ratio upper limit 5.8% of area; clipped at zero 12.2% |
| MVS with all-zero guard (variant) | Jan | sd fallback 3.9% of area; ratio lower limit 25.8% of area; ratio upper limit 28.2% of area; clipped at zero 4.5% |
| MVS with all-zero guard (variant) | ONDJ | ratio lower limit 2.2% of area; ratio upper limit 22.3% of area; clipped at zero 1.7% |

## 6. Confirmation results (national aggregate)

Full numbers: `confirmation/confirmation.json`. ✓ = better than MVS with Holm-adjusted p < 0.05 (methods: across all 60
method–target comparisons; SEL-P and SEL-A: across the 5 targets) and not worse over 2017–2024.

**Blended tercile RPSS (the published product), outer leave-one-year-out 1993–2016**

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| Mean-Variance Scaling (operational) | +0.013 | +0.040 | +0.003 | +0.001 | +0.039 |
| Linear Scaling | +0.013 | +0.038 | +0.006 | -0.000 | +0.037 |
| Variance Scaling (unbounded) | +0.013 | +0.041 | +0.004 | +0.001 | +0.039 |
| Square-root-space Mean-Variance Scaling | +0.014 | +0.050 | +0.007 | +0.007 | +0.040 |
| Power Transformation | +0.012 | +0.039 | +0.005 | +0.003 | +0.038 |
| Delta Change | +0.004 | +0.035 | -0.000 | -0.006 | +0.026 |
| Local Intensity Scaling | +0.012 | +0.043 | +0.006 | +0.001 | +0.037 |
| Empirical Quantile Mapping | +0.002 | +0.034 | +0.005 | -0.003 | +0.028 |
| Gamma Quantile Mapping | +0.014 | +0.044 | +0.006 | +0.005 | +0.041 |
| Detrended Quantile Mapping | +0.003 | +0.028 | +0.001 | -0.006 | +0.020 |
| Quantile Delta Mapping | +0.004 | +0.021 | +0.006 | -0.005 | +0.018 |
| Scaled Distribution Mapping | +0.004 | +0.028 | +0.006 | -0.002 | +0.015 |
| CDF-transform | +0.005 | +0.023 | -0.001 | -0.003 | +0.022 |
| MVS with all-zero guard (variant) | +0.013 | +0.040 | +0.003 | +0.001 | +0.039 |
| SEL-P | +0.014 | +0.050 | +0.007 | +0.007 | +0.040 |
| SEL-A | +0.004 | +0.050 | +0.002 | +0.007 | +0.026 |

**Blended tercile RPSS, fit 1993–2016, scored 2017–2024 (exploratory)**

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| Mean-Variance Scaling (operational) | +0.027 | +0.053 | +0.015 | -0.005 | +0.075 |
| Linear Scaling | +0.056 | +0.038 | +0.025 | +0.044 | +0.071 |
| Variance Scaling (unbounded) | +0.025 | +0.055 | +0.017 | -0.001 | +0.074 |
| Square-root-space Mean-Variance Scaling | +0.031 | +0.062 | +0.014 | +0.043 | +0.080 |
| Power Transformation | +0.026 | +0.057 | +0.019 | +0.027 | +0.075 |
| Delta Change | -0.001 | +0.006 | +0.024 | +0.021 | +0.029 |
| Local Intensity Scaling | +0.045 | +0.031 | +0.027 | +0.043 | +0.071 |
| Empirical Quantile Mapping | +0.000 | +0.036 | +0.023 | +0.053 | +0.062 |
| Gamma Quantile Mapping | +0.021 | +0.057 | +0.003 | +0.016 | +0.082 |
| Detrended Quantile Mapping | +0.003 | +0.020 | +0.021 | +0.031 | +0.045 |
| Quantile Delta Mapping | +0.007 | +0.024 | +0.029 | +0.038 | +0.041 |
| Scaled Distribution Mapping | +0.004 | +0.005 | +0.029 | +0.028 | +0.040 |
| CDF-transform | +0.013 | +0.031 | +0.026 | +0.044 | +0.049 |
| MVS with all-zero guard (variant) | +0.027 | +0.053 | +0.015 | -0.005 | +0.075 |
| SEL-P | +0.021 | +0.062 | +0.014 | +0.043 | +0.082 |
| SEL-A | -0.001 | +0.062 | +0.014 | +0.043 | +0.029 |

**Brier skill, below normal, 1993–2016**

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| Mean-Variance Scaling (operational) | +0.013 | +0.003 | -0.013 | -0.002 | +0.028 |
| Linear Scaling | +0.007 | +0.008 | -0.002 | -0.007 | +0.018 |
| Variance Scaling (unbounded) | +0.013 | +0.005 | -0.012 | -0.001 | +0.029 |
| Square-root-space Mean-Variance Scaling | +0.016 | +0.017 | -0.004 | +0.004 | +0.030 |
| Power Transformation | +0.013 | +0.008 | -0.006 | +0.004 | +0.028 |
| Delta Change | +0.003 | +0.019 | -0.009 | -0.009 | +0.016 |
| Local Intensity Scaling | +0.008 | +0.015 | -0.004 | -0.006 | +0.018 |
| Empirical Quantile Mapping | +0.004 | +0.013 | -0.006 | -0.004 | +0.016 |
| Gamma Quantile Mapping | +0.017 | +0.016 | -0.006 | +0.003 | +0.031 |
| Detrended Quantile Mapping | +0.003 | +0.011 | -0.006 | -0.009 | +0.007 |
| Quantile Delta Mapping | +0.004 | -0.001 | -0.005 | -0.005 | +0.003 |
| Scaled Distribution Mapping | +0.004 | +0.005 | -0.004 | -0.005 | -0.000 |
| CDF-transform | +0.003 | +0.002 | -0.009 | -0.004 | +0.009 |
| MVS with all-zero guard (variant) | +0.013 | +0.003 | -0.013 | -0.002 | +0.028 |
| SEL-P | +0.017 | +0.017 | -0.004 | +0.004 | +0.030 |
| SEL-A | +0.003 | +0.017 | -0.007 | +0.004 | +0.016 |

**Brier skill, above normal, 1993–2016**

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| Mean-Variance Scaling (operational) | +0.013 | +0.078 | +0.019 | +0.003 | +0.051 |
| Linear Scaling | +0.019 | +0.068 | +0.015 | +0.007 | +0.056 |
| Variance Scaling (unbounded) | +0.012 | +0.078 | +0.021 | +0.003 | +0.050 |
| Square-root-space Mean-Variance Scaling | +0.011 | +0.082 | +0.019 | +0.010 | +0.050 |
| Power Transformation | +0.011 | +0.070 | +0.016 | +0.002 | +0.049 |
| Delta Change | +0.005 | +0.051 | +0.008 | -0.004 | +0.035 |
| Local Intensity Scaling | +0.017 | +0.070 | +0.016 | +0.007 | +0.056 |
| Empirical Quantile Mapping | +0.000 | +0.055 | +0.015 | -0.002 | +0.040 |
| Gamma Quantile Mapping | +0.012 | +0.071 | +0.018 | +0.006 | +0.050 |
| Detrended Quantile Mapping | +0.004 | +0.045 | +0.008 | -0.004 | +0.032 |
| Quantile Delta Mapping | +0.003 | +0.042 | +0.017 | -0.004 | +0.033 |
| Scaled Distribution Mapping | +0.005 | +0.051 | +0.016 | +0.000 | +0.030 |
| CDF-transform | +0.007 | +0.045 | +0.008 | -0.002 | +0.036 |
| MVS with all-zero guard (variant) | +0.013 | +0.078 | +0.019 | +0.003 | +0.051 |
| SEL-P | +0.011 | +0.082 | +0.019 | +0.010 | +0.050 |
| SEL-A | +0.005 | +0.082 | +0.011 | +0.010 | +0.035 |

**Amount CRPSS in the confirmation design, 1993–2016**

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| Mean-Variance Scaling (operational) | -0.002 | +0.084 | +0.028 | -0.048 | +0.070 |
| Linear Scaling | -0.016 | +0.073 | -0.008 | -0.132 | +0.070 |
| Variance Scaling (unbounded) | -0.004 | +0.082 | +0.031 | -0.007 | +0.063 |
| Square-root-space Mean-Variance Scaling | +0.006 | +0.089 | +0.037 | +0.034 ✓ | +0.080 |
| Power Transformation | +0.001 | +0.082 | +0.020 | -0.025 | +0.071 |
| Delta Change | +0.021 | +0.085 | +0.026 | -0.047 | +0.093 |
| Local Intensity Scaling | -0.016 | +0.079 | +0.010 | -0.104 | +0.070 |
| Empirical Quantile Mapping | -0.012 | +0.075 | +0.033 | +0.010 | +0.053 |
| Gamma Quantile Mapping | +0.007 | +0.088 | +0.030 | +0.015 ✓ | +0.082 |
| Detrended Quantile Mapping | +0.005 | +0.075 | -0.001 | -0.065 | +0.072 |
| Quantile Delta Mapping | +0.010 | +0.076 | +0.014 | -0.027 | +0.075 |
| Scaled Distribution Mapping | -0.002 | +0.068 | -0.021 | -0.216 | +0.061 |
| CDF-transform | +0.002 | +0.073 | -0.019 | -0.108 | +0.074 |
| MVS with all-zero guard (variant) | -0.002 | +0.084 | +0.028 | -0.048 | +0.070 |
| SEL-P | +0.007 | +0.089 | +0.037 | +0.034 | +0.081 |
| SEL-A | +0.021 | +0.089 | +0.034 | +0.034 ✓ | +0.093 |

**Mean blend weight on climatology (λ), 1993–2016**

| Method | Oct | Nov | Dec | Jan | ONDJ |
| --- | --- | --- | --- | --- | --- |
| Mean-Variance Scaling (operational) | 0.43 | 0.30 | 0.68 | 0.91 | 0.20 |
| Linear Scaling | 0.52 | 0.43 | 0.75 | 0.78 | 0.28 |
| Variance Scaling (unbounded) | 0.43 | 0.30 | 0.65 | 0.90 | 0.21 |
| Square-root-space Mean-Variance Scaling | 0.38 | 0.14 | 0.58 | 0.60 | 0.18 |
| Power Transformation | 0.44 | 0.29 | 0.66 | 0.67 | 0.19 |
| Delta Change | 0.34 | 0.37 | 0.77 | 0.87 | 0.23 |
| Local Intensity Scaling | 0.50 | 0.39 | 0.77 | 0.79 | 0.29 |
| Empirical Quantile Mapping | 0.47 | 0.30 | 0.73 | 0.60 | 0.22 |
| Gamma Quantile Mapping | 0.41 | 0.33 | 0.73 | 0.68 | 0.18 |
| Detrended Quantile Mapping | 0.46 | 0.46 | 0.83 | 0.84 | 0.32 |
| Quantile Delta Mapping | 0.43 | 0.44 | 0.77 | 0.80 | 0.31 |
| Scaled Distribution Mapping | 0.49 | 0.50 | 0.80 | 0.89 | 0.38 |
| CDF-transform | 0.50 | 0.52 | 0.81 | 0.83 | 0.32 |
| MVS with all-zero guard (variant) | 0.43 | 0.30 | 0.68 | 0.91 | 0.20 |

**Selection-aware procedures against MVS** (Δ: RPS for SEL-P, CRPS in mm for SEL-A; negative favours the procedure)

| Procedure | Target | Chosen (years) | Δ vs MVS | Holm p (targets) | Δ test | Confirmed |
| --- | --- | --- | --- | --- | --- | --- |
| SEL-P | Oct | Gamma Quantile Mapping 23, Square-root-space Mean-Variance Scaling 1 | -0.0007 | 1.0000 | +0.0025 | no |
| SEL-P | Nov | Square-root-space Mean-Variance Scaling 24 | -0.0043 | 0.7338 | -0.0037 | no |
| SEL-P | Dec | Square-root-space Mean-Variance Scaling 24 | -0.0021 | 1.0000 | +0.0009 | no |
| SEL-P | Jan | Square-root-space Mean-Variance Scaling 24 | -0.0028 | 1.0000 | -0.0212 | no |
| SEL-P | ONDJ | Gamma Quantile Mapping 18, Square-root-space Mean-Variance Scaling 6 | -0.0003 | 1.0000 | -0.0033 | no |
| SEL-A | Oct | Delta Change 24 | -0.6772 | 0.2275 | +0.9372 | no |
| SEL-A | Nov | Square-root-space Mean-Variance Scaling 24 | -0.0931 | 0.2275 | -0.1049 | no |
| SEL-A | Dec | Square-root-space Mean-Variance Scaling 23, Empirical Quantile Mapping 1 | -0.0424 | 0.2027 | -0.0334 | no |
| SEL-A | Jan | Square-root-space Mean-Variance Scaling 24 | -0.4787 | 0.0018 | -0.6902 | yes |
| SEL-A | ONDJ | Delta Change 24 | -1.0435 | 0.2275 | +3.2167 | no |

### Findings (national aggregate)

1. **All tested corrections improve national ONDJ rainfall-amount CRPSS over raw ECMWF in 1993–2016** (raw −0.180;
   corrected +0.053 to +0.093). Performance varies for monthly tercile probabilities: DQM, SDM and CDF-t score below the raw
   model on December RPSS.
2. **Accounting for the whole search** (Holm across all 60 comparisons), the amount screening passes are square-root MVS
   (January) and Gamma QM (January); the tercile passes are square-root MVS (November, January), Power Transformation
   (January) and Gamma QM (January). Square-root MVS's December and ONDJ passes, Gamma QM's ONDJ pass and the January passes
   of EQM and VS hold only within their method.
3. **Square-root MVS is at least as good as MVS in the national aggregate for every tested target and period**, on amounts
   and unblended terciles (ONDJ CRPSS +0.080 vs +0.070 in 1993–2016, +0.189 vs +0.178 in 2017–2024), and clips fewer members
   at 0 mm (1.0–2.9 % vs 4.5–12.2 % in the months). This need not hold in each region: in the ONDJ R3 domain it is slightly
   below MVS on 2017–2024 RPSS for October and December (−0.006 each).
4. **The ratio limits of MVS matter most in January**, where the raw model is far too narrow (spread–error 0.39): with the
   same fallback in both, the upper limit is active over 28 % of the area and MVS stays too narrow (0.83) while unbounded
   scaling reaches 1.00.
5. **EQM reproduces the CHIRPS distribution and, with the dry policy, its dry share** (≤ 1 mm: December 19.0 % vs 18.9 %,
   January 16.7 % vs 16.6 %) but its ONDJ amount skill is lower than MVS (+0.053 vs +0.070). A possible explanation is
   sampling noise in an empirical quantile function of 23 values per fold; the results do not isolate it.
6. **SDM follows the published algorithm** (checked against an independent implementation of the steps). Where the model is
   drier than CHIRPS it cannot add rain: in January 46 % of model members exceed 1 mm against 83 % of CHIRPS years, and SDM
   keeps the model's number of rain members, so its corrected dry share is 55 % (CHIRPS 17 %).
7. **Delta Change** has a high 1993–2016 ONDJ CRPSS (+0.093) that does not pass the screening, is lower in 2017–2024 (+0.114 vs
   +0.178) and is too wide (spread–error 1.16): historical scenarios rescaled by the forecast mean.
8. **The methods that use the forecast's own distribution (DQM, QDM, SDM, CDF-t)** score lower on ONDJ terciles (−0.005 to
   +0.011 vs +0.035); a possible explanation is that one forecast's 25–51 members estimate the "future" distribution these
   methods need poorly. QDM falls back to the CHIRPS quantile for 32 % (December) and 54 % (January) of members.
9. **Linear Scaling and LOCI** stay too narrow (ONDJ spread–error 0.78 and 0.77). **December** remains hard: every method has
   negative amount skill over 2017–2024.
10. **Confirmation, published probabilities: no tested method demonstrates a statistically significant improvement over MVS
    under this validation protocol** (several have slightly higher point estimates). After the blend (fitted inside the
    folds) the methods' ONDJ RPSS spans 0.025 against 0.044 unblended, and the selection-aware SEL-P — which picks square-root
    MVS in nearly every year for November–January and Gamma QM for October and ONDJ — is confirmed for no target (ONDJ
    +0.040 vs +0.039). A better amount correction is trusted more by the blend (January λ 0.60 with square-root MVS against
    0.91 with MVS), which absorbs much of the difference.
11. **Confirmation, rainfall amounts: square-root MVS and Gamma QM are confirmed for January** against the whole family
    (Δ CRPS −0.479 and −0.365 mm in 1993–2016, Holm p 0.021 and 0.008; −0.690 and −0.529 mm in 2017–2024), and the
    selection-aware SEL-A (square-root MVS in all 24 folds) is confirmed for January. These comparisons establish
    improvement against MVS, not that one candidate is better than the other.
12. **Choosing by training scores can backfire.** SEL-A chooses Delta Change for October and ONDJ from the 1993–2016 scores.
    The training-selected Delta Change has a worse mean ONDJ CRPS over 2017–2024 (Δ +3.22 mm, 95 % interval −1.22 to
    +9.21 mm), with large losses in 2019 (+16.6 mm) and 2023 (+14.9 mm); it is better than MVS in 5 of the 8 years. It
    fails the no-harm rule, but the interval does not establish a significant deterioration. October is similar (Δ +0.94 mm,
    −0.23 to +2.40; 4 of 8 years better), and SEL-P's October choice (Gamma QM) is slightly worse in RPS.
13. **The January gains come from wet cells.** About 96 % of square-root MVS's January improvement (−0.458 of −0.479 mm)
    comes from cells that are wet in every training year (80 % of the area); cells dry in every year (≤ 1 mm, 9 %) and
    mixed cells (11 %) contribute −0.003 and −0.018 mm. Gamma QM's gain is entirely from the always-wet cells (−0.378 mm);
    it is slightly worse than MVS in the dry and mixed cells. No cell has 0 mm in every training year, so the MVS all-zero
    behaviour does not arise in these data and the all-zero guard never acts.

### What the evidence supports

* **Keep MVS for the published tercile probabilities** of the September cycle: no tested method demonstrates a
  statistically significant improvement over MVS under this validation protocol.
* **January rainfall amounts**: square-root MVS and Gamma QM are each confirmed better than MVS (not against each other);
  an amount-only January pilot is reasonable. The gain is a wet-cell gain (finding 13). The blended January
  probabilities are not confirmed better.
* If amounts and probabilities come to use different correction paths, record both methods in the product metadata so
  every output can be traced.
* **Do not select by training-period rank alone** (finding 12).
* Run the same screening and confirmation for JJAS (May) and FMAM (January, February) before any cross-cycle decision; one
  configuration file each.

## 7. All cycles

The same configuration and protocol (`config/bias_correction/may_jjas.json`, `jan_fmam.json`, `feb_fmam.json`; screening and
confirmation, 13 declared methods plus the all-zero guard variant) for the other cycles: training 1993–2016, test 2017–2025
(one more test year than ONDJ), forecast 2026; the second region is each season's domain (JJAS R1+R2, FMAM rainfall
contribution domain). Run at commit 9f39792 (clean tree); ONDJ at bed63b9. National aggregate (all Ethiopia) throughout.
Full numbers: `outputs/bias_correction_benchmark/<cycle>/` and the site's Bias correction section (cycle picker).

| Cycle | Published tercile probabilities: confirmed better than MVS | Amounts: fixed methods confirmed | Amounts: SEL-A confirmed (method chosen) |
| --- | --- | --- | --- |
| January · FMAM | none | none | Feb (square-root MVS in 24/24 folds; Δ CRPS −0.275 mm, Holm p 0.022; 2017–2025 −0.109) |
| February · FMAM | **Feb: square-root MVS** (blended RPSS +0.207 vs +0.126, better in 18 of 24 years, Holm p 0.026 across all methods and targets; 2017–2025 +0.072 vs +0.056, 6 of 9 years); SEL-P also confirmed for Feb | none | Feb (square-root MVS 24/24; −0.184 mm, p 0.013) and Mar (square-root MVS 24/24; −0.341 mm, p 0.045) |
| May · JJAS | none | Jul: VS (−0.139 mm). Aug: VS (−0.129), Gamma QM (−0.128), PT (−0.124), square-root MVS (−0.096); Holm p ≤ 0.002 | Jun (Gamma QM 24/24; −0.131 mm, p 0.029), Aug (VS 16, Gamma QM 6, PT 2), Sep (Gamma QM 24/24; −0.072 mm, p 0.007) |
| September · ONDJ | none | Jan: square-root MVS (−0.479), Gamma QM (−0.365) | Jan (square-root MVS 24/24) |

### Findings across cycles

1. **Published probabilities: MVS is not significantly beaten in any cycle except one month.** For the first month of the
   February-initialized cycle (February, lead 0, where the forecast has its highest skill), square-root MVS is confirmed
   better after the blend and the whole method search, and the selection-aware SEL-P (which picks it in every fold) is
   confirmed too. The blend trusts the better-corrected members more (mean λ 0.30 against 0.48). The 2017–2025 gain is
   smaller (+0.016 RPSS) than the 1993–2016 gain (+0.081).
2. **Amount gains are month-specific:** ONDJ January, FMAM February (both initializations) and March (February
   initialization), and JJAS June to September. They come mostly from cells wet in every training year — e.g. VS in JJAS
   August, −0.103 of −0.129 mm from the always-wet cells (95 % of the area) — and no cell of Ethiopia has 0 mm in every
   training year for any target of any cycle, so the MVS all-zero guard never acts.
3. **The 0.5–2 ratio limits of MVS are the part most worth revisiting.** In JJAS July and August the lower limit (r ≥ 0.5)
   is active over 32 % and 28 % of the area — where the model is far more variable than CHIRPS — and unbounded VS (same
   fallback) is confirmed better in both months; in ONDJ January it was the upper limit (r ≤ 2, 28 % of the area).
4. **Square-root MVS is the most frequent winner but not uniformly better:** it is slightly worse than MVS in May of both
   FMAM cycles over 2017–2025 (≤ 0.015 blended RPSS) and within ±0.002 in several JJAS comparisons.
5. **Selection by training scores again picks Delta Change for some season totals** (January FMAM: 21 of 24 folds; ONDJ:
   24) and JJAS July (14 folds); none of these choices is confirmed.

### What the evidence supports across cycles

* Keep MVS for the published tercile probabilities in every cycle. The one exception supported by the evidence is a
  **pilot of square-root MVS for the February target of the February-initialized cycle**.
* Amount-only pilots per target where a method is confirmed: square-root MVS for ONDJ January and FMAM February–March;
  VS or Gamma QM for JJAS June–September. Confirmations establish improvement against MVS, not a ranking among candidates.
* Consider revising the MVS ratio limits (a single operational change that addresses both the JJAS and the ONDJ January
  findings), and evaluate that change with the same screening and confirmation before adoption.
* Record the correction method per product and target in the metadata if amounts and probabilities diverge.

## 8. Changes

### Revision 3 (response to the review of 007ce47 / 1e59fea)

| Review point | Change |
| --- | --- |
| Two advertised NetCDF downloads returned 404 (`*.nc` ignored outside `site/downloads/data/`) | `.gitignore` exception for `site/downloads/bias/**/*.nc`; the site build now fails if any local link of the page (HTML or page data) is missing or git-ignored |
| Checkpoints could pair old scores with new provenance | One complete dependency fingerprint (`bias_benchmark.dependencies`: benchmark, project and cycle configuration contents, masks, every input file, and the calculation code including the CRPS, smoothing and blend helpers) validates the per-target checkpoints and is recorded as provenance; `--no-resume` |
| The confirmation ignored a nondefault smoothing α | `smooth(..., alpha=self.alpha)`; test with α = 2 against the explicit formula |
| EQM/DQM extrapolation could override the dry rule | The dry mask is applied after the extrapolation; test with every CHIRPS year at 0.5 mm |
| SDM assigned corrected values out of rank order | Step 7 assigns the sorted corrected values by raw-member rank; rank-preservation test (per-cell values and scores are unchanged) |
| All-zero cells under MVS | January (and every target) decomposition of the CRPS differences by training-year climate group; an MVS all-zero guard evaluated as a separate variant |
| Wording | Links pinned to the producing commit; "deterministic stratified tie-breaking"; "two distinct tercile boundaries"; "no tested method demonstrates a statistically significant improvement"; Delta Change's test-year loss given with its interval; confirmed January candidates are not ranked against each other; metadata note for split correction paths |

### Revision 2 (response to the review of e252baa)

| Review point | Change |
| --- | --- |
| Checkmarks ignore the method search | Two families reported (within method ✓, across all methods ✓✓); `adopt` renamed `screen_pass`; selection-aware confirmation added |
| Shortlist used the test years | Removed; the decision now comes from the confirmation (SEL-P / SEL-A and family-wide tests) |
| Blend not evaluated; runner JJAS-specific | New cycle-aware `bias_confirmation.py` using the method registry, full pipeline with nested λ |
| SDM differs from the published algorithm | Rewritten after Switanek et al. (2017) steps 1–7 (RIs computed, then interpolated); test against an independent implementation |
| DQM "exact" claim; QDM qualification | Definitions corrected; QDM cap and low-denominator fallback counted and reported |
| Tied zeros and dry occurrence | Dry policy for the quantile-mapping methods; exactly-0 and ≤ 1 mm shares reported; tests for repeated zeros, all-dry and few-wet samples. The operational MVS keeps r ≥ 0.5 and so produces non-zero totals where CHIRPS is never wet (unchanged; noted) |
| VS changed two things | VS uses the same 1 mm fallback as MVS; activation shares of the limits reported |
| PT bound hits | Reported as the share of the area where b reaches a bound |
| Fair vs ordinary CRPS | Ordinary CRPS primary; fair CRPS reported and screened as a diagnostic |
| Region switch | Labelled "Region for the result tables"; summary, interpretation and figures labelled as national; regional differences noted |
| Presentation | Distribution plot shows out-of-range values at the edge; map titles give the evaluation period; at-a-glance table groups columns by period; coverage table |
| Provenance; gate description | Commit, hashes and manifest; gate description generated from the configuration |
| Wording | "All tested corrections improve national ONDJ CRPSS over raw" with the monthly RPSS exceptions; "national aggregate"; mechanisms stated as possible explanations |
| CI error (missing local cache in a domain test) | The test builds a small temporary NetCDF fixture |

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
