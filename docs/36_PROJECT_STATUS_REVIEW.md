# 36 — Project status review and remediation plan

Reviewed 2026-10-05 from docs 01–35, scripts, outputs and a full test run.
This document supersedes the "not implemented" statements in docs 04, 05, 07, 08 and 10.

## 1. Implemented

| Stage | Status | Main scripts |
| --- | --- | --- |
| Download, inventory, preparation (JJAS and monthly) | Done for 1993–2026 | `download_seasonal_forecasts_daily_c3s`, `inspect_inputs`, `prepare_seasonal`, `run_monthly` |
| Regridding 1° → 0.25° | Each 1° cell copied into its 4×4 CHIRPS block; alignment and conservation checked | `regrid_seasonal` |
| Ethiopia mask | 1,484 cells by cell-centre test; used for scoring and display | `build_region_mask` |
| Amount correction | Per-cell equal-year mean–variance correction as in docs/04 §3 | `calibration_core` |
| Out-of-fold terciles and probabilities | Leave-one-year-out | `run_calibration` |
| Dirichlet recalibration | Implemented, penalties not tuned; **not used** in the final product | `calibration_core`, `run_calibration` |
| Method comparison | Nested, 1993–2016 only | `compare_calibration`, `local_blend`, `evaluate_candidates` |
| Final method | Amount correction + count smoothing + one climatology-blend weight per target, fitted 1993–2025 | `final_shared_blend` |
| Regime experiments | Evaluated; not adopted (August spatially mixed) | `regime_core`, `github_regime_core`, `diagnose_august` |
| Maps and delivery | Bulletin, maps, bundle | `plot_*`, `finalize_forecast_delivery` |
| Freeze and verification | SHA-256 freeze; Jun/Jul/Aug verified | `prepare_verification_2026`, `verify_frozen_2026`, `build_verification_report` |
| Operational runner | Resumable stages, offline gallery | `run_operational`, `operational_core` |

### Skill

Ranked probability skill relative to climatology (RPSS), fitted on 1993–2016 and scored on 2017–2025.
The test period was seen during method selection, so treat these as exploratory.

| Target | Raw | Final blend | Note |
| --- | --- | --- | --- |
| JJAS | −0.41 | +0.050 | |
| Jun | — | +0.024 | |
| Jul | — | +0.036 | |
| Aug | — | +0.066 | Smoothed counts without the blend: +0.096 |
| Sep | — | +0.010 | |

2026 verification: Jun +0.19, Jul +0.25, Aug +0.28 (one season). Sep and JJAS are pending September CHIRPS.

## 2. Review findings

1. The root README had been overwritten by the Step 35 patch README.
2. `tests/test_verification_report.py` required a `completed_report/` folder that was never installed.
3. The Step 35 Windows publication fix was applied only in `verify2026_outputs.py`. The three byte-identical copies `output_runs.py`, `delivery_output_runs.py` and `review_output_runs.py` still deleted completed staging folders after a publication failure.
4. The map and contour modules are duplicated across plot, review and delivery copies.
5. There are 55 `_backup_` folders and no pruning. Switching runner workflow rebuilds all views.
6. Likely cause of the Dirichlet compression: about 6 % of cases have a zero-member category, and ε = 1e-12 turns those into log(p) ≈ −27.6.
7. The blend-weight fallback is inconsistent: λ = 1 in `local_blend`, λ = 0 in `compare_calibration`.
8. Stale docs: 04, 05, 07, 08 and 10 (calibration "not implemented"); doc 23 output folder name; the bulletin's verification statement.
9. Three verification output locations: `verification_followup`, `operational_2026`, `verification_report_2026`.

## 3. Remediation plan

### High priority

- **Phase 1 — repair the project.** README, failing test, shared publication helper, root clean-up, requirements, stale-doc banners.
- **Phase 2 — Sep/JJAS verification.** Check CHIRPS September availability, complete verification when available, update the bulletin statement.
- **Phase 3 — land/ocean and lake mask.** Quantify what the current domain-wide fits include. Run a sensitivity experiment with an Ethiopia-only or land-only fit domain without altering the frozen 2026 forecast.
- **Phase 4 — Jun–Aug zero clipping.** Quantify where and why 22–24 % of corrected member values are clipped, and test alternatives on 1993–2016 nested cross-validation.

### Medium priority

5. Significance gates (year-block bootstrap or Diebold–Mariano) before adopting any method.
6. An August-specific decision (no blend, or a regime-dependent weight) under a pre-registered rule.
7. Spatial-duplication-aware weighting and bootstrap (about 90 independent 1° cells).
8. Ensemble-size and system checks (25 vs 51 members), and recording SEAS5 system 51 provenance.
9. Regional skill tables and maps.
10. Monthly–seasonal probability consistency.

### Lower priority

11. A generic forecast-year adapter for 2027 (remove hard-coded years, member counts and `init05`).
12. Merge the duplicated modules, remove dead experimental paths, add a backup pruning command.
13. A 1991–2020 baseline option and a numerical ICPAC/EMI comparison.
14. Version control (git) with a `.gitignore` for data and outputs.

## 4. Progress log

Updated as each phase completes.

### Phase 1 — project repair (completed 2026-10-05)

- [x] New general `README.md` (method, commands, folder map, freeze warning). The Step 35 patch README was moved to `archive/step35_windows_fix/README_root_copy.md`.
- [x] Windows publication fix applied everywhere. `output_runs.py`, `delivery_output_runs.py` and `review_output_runs.py` now re-export `verify2026_outputs` (bounded retries; completed staging kept on publication failure). All 20 importing scripts are unchanged.
- [x] `tests/test_verification_report.py` uses `completed_report/` if present, otherwise the local `outputs/verification_report_2026/Jun_Jul_Aug`, and skips when neither exists.
- [x] Root cleaned. `operational_windows_fix/`, its zip and `MANIFEST.json` moved to `archive/step35_windows_fix/`. `VALIDATION.md` and `VALIDATION.json` moved to `archive/step33_validation/`, and the doc 31 link was updated.
- [x] `requirements.txt` pins `cdsapi==0.7.7`, `pyshp==3.1.6` and `pyproj==3.7.2`, and notes that shapely is needed only for mask rebuilds.
- [x] Status banners added to docs 04, 05, 07, 08 and 10. Doc 23 output folder corrected to `forecast_maps_contours`.
- [x] Full suite: 73 tests OK (previously 70 tests, 1 error).
- Note: the runner fingerprints `delivery_output_runs.py`, so the next `run_operational.py` run rebuilds the views once. The frozen forecasts were not touched.

### Phase 2 — Sep/JJAS verification (checked 2026-10-05; waiting on data)

- [x] `complete_verification_2026.py --check`: Jun, Jul and Aug are available; **Sep is unavailable** on the official CHIRPS v2.0 p25 archive. Status is written to `outputs/verification_followup/season_status.json`.
- [x] Bulletin statement: **left unchanged on purpose.** `BULLETIN.md` is SHA-256 protected in `outputs/forecast_delivery/init05_2026/manifest.json`, and its "no verification in this package" line is true for the archived package. The post-event update is `outputs/verification_report_2026/Jun_Jul_Aug/VERIFICATION_ADDENDUM.md` (identical in `outputs/operational_2026/reports/`). Distribute it alongside the bulletin, as doc 32 specifies.
- [ ] When September CHIRPS is published (final CHIRPS usually appears about 3 weeks after month end):
  ```bat
  python scripts\complete_verification_2026.py --check
  python scripts\run_operational.py --workflow all --verification-targets Jun Jul Aug Sep JJAS
  ```
  Then distribute the regenerated `VERIFICATION_ADDENDUM.md` covering all five targets.

### Phase 3 — land/ocean mask and fitting domain (completed 2026-10-05)

Script: `scripts/mask_sensitivity.py` (read-only; output `outputs/mask_sensitivity/blend_domain_sensitivity.json`).

- [x] **What the mask can change.** Amount correction, terciles and eligibility are all per cell. Sea cells are already excluded because CHIRPS is NaN there (223 cells, constant over time). A land/ocean mask therefore changes nothing except the **pooled climatology-blend weight λ**.
- [x] **Lakes.** CHIRPS gives continuous values over Lake Tana and the Rift Valley lakes, close to the surrounding land (for example Tana 1,027 mm vs 1,003 mm nearby, JJAS 2000). No lake mask is needed for this pipeline.
- [x] **Domain finding.** 39–44 % of the area used to fit λ lies outside Ethiopia (Sudan, South Sudan, Eritrea, Djibouti, Somalia, Kenya).
- [x] **Sensitivity.** λ fitted on 1993–2016 LOYO records; RPS scored on Ethiopia cells for 2017–2025. The script reproduces the operational RPSS exactly for the full domain.

| Target | λ full domain | λ Ethiopia | RPSS full | RPSS Ethiopia | Δ RPS (Eth − full), 95 % CI | Years better |
| --- | --- | --- | --- | --- | --- | --- |
| JJAS | 0.490 | 0.425 | +0.0505 | +0.0508 | −0.0001 [−0.0029, +0.0029] | 5/9 |
| Jun | 0.720 | 0.673 | +0.0243 | +0.0264 | −0.0010 [−0.0038, +0.0015] | 6/9 |
| Jul | 0.613 | 0.599 | +0.0364 | +0.0370 | −0.0003 [−0.0012, +0.0008] | 5/9 |
| Aug | 0.600 | 0.524 | +0.0664 | **+0.0748** | **−0.0038 [−0.0071, −0.0006]** | 7/9 |
| Sep | 0.776 | 0.748 | +0.0096 | +0.0101 | −0.0002 [−0.0016, +0.0009] | 4/9 |

- **Interpretation.** Fitting over Ethiopia always gives a lower climatology weight, meaning more weight on the model, and never scores worse. The gain is negligible except in August, where the interval excludes zero. This is consistent with the earlier finding that the blend dampens a real August signal. The comparison uses years already seen (exploratory) and five targets, so the August result needs confirmation.
- [x] **Decision.** The frozen 2026 forecasts are unchanged. Recommendation for the next cycle: fit λ on the Ethiopia mask (a pre-registered change, recorded before seeing 2026 Sep/JJAS results), and verify it again on 1993–2016 nested cross-validation.

### Phase 4 — Jun–Aug zero clipping (completed 2026-10-05)

Script: `scripts/clipping_analysis.py` (read-only; output `outputs/clipping_analysis/amount_correction_alternatives.json`).
Ethiopia cells; training = LOYO 1993–2016 (clean), operational = 1993–2016 fit scored on 2017–2025 (exploratory).

- [x] **Where clipping happens.** Almost entirely in arid cells with climatological totals below 50 mm (Afar and Somali lowlands). There the variance ratio sits at its 0.5 floor (model too variable), and 11–33 % of member values go negative. No clipping occurs above 150 mm.
  The 22–24 % in `final_report.json` is measured over the whole rectangle for 2026. Within Ethiopia it is 11–13 % for the months and 3 % for JJAS.
- [x] **Impact.** Tercile probabilities are **unaffected**, because eligibility requires q1 > 0 and a clipped member is below q1 either way. Amounts are slightly inflated: +0.1 to +0.4 mm on the Ethiopia area mean, concentrated in the dry lowlands.
- [x] **Alternatives tested.**

| Target | CRPS (mm) affine / mult / sqrt-affine / QM (training) | Δ CRPS sqrt − affine, training [95 % CI] | Δ CRPS operational [95 % CI] | RPS affine → sqrt (training) |
| --- | --- | --- | --- | --- |
| JJAS | 34.23 / 36.05 / **34.09** / 34.66 | −0.13 [−0.24, −0.03] | −0.20 [−0.29, −0.12], 9/9 yrs | 0.4429 → 0.4422 |
| Jun | 11.00 / 11.87 / **10.87** / 11.03 | −0.13 [−0.21, −0.06] | −0.03 [−0.13, +0.08] | 0.4803 → 0.4757 |
| Jul | 15.80 / 16.28 / **15.70** / 15.93 | −0.10 [−0.14, −0.05] | −0.09 [−0.16, −0.02] | 0.4653 → 0.4633 |
| Aug | 14.68 / 15.36 / **14.58** / 14.76 | −0.10 [−0.14, −0.06] | −0.04 [−0.09, +0.02] | 0.4555 → 0.4530 |
| Sep | 13.32 / 14.07 / **13.21** / 13.34 | −0.11 [−0.15, −0.05] | −0.17 [−0.20, −0.13], 9/9 yrs | 0.4803 → 0.4760 |

- **Interpretation.**
  - Multiplicative scaling is clearly worse, because it matches the mean but not the spread.
  - Quantile mapping brings no gain with 24 training years.
  - Square-root-space affine correction is better than the current affine in every target on the clean training check, with all intervals excluding zero. It is also better or equal on 2017–2025, except July RPS (0.4636 vs 0.4631).
  - The gains are small: about 1 % CRPS and RPS reductions of up to 0.005, before blending.
- [x] **Decision.** The 2026 product is unchanged. Recommendation for the next cycle: adopt `sqrt_affine` as a pre-registered candidate, confirm it with the blend applied (nested 1993–2016), and report clipping by climate zone in `final_report.json` instead of one domain-wide fraction.

### High-priority status

| Phase | Status |
| --- | --- |
| 1 Project repair | Done |
| 2 Sep/JJAS verification | Waiting for CHIRPS September (command recorded above) |
| 3 Mask / fitting domain | Done; Ethiopia-λ recommendation **withdrawn** in Phase 5 (no clean-period support) |
| 4 Zero clipping | Done; square-root correction **for amounts only** (Phase 5 gate passed) |

## 5. Medium-priority work

### Adoption rule (recorded 2026-10-05, before running `decision_gates.py`)

A candidate change replaces the current method for a target only if both conditions hold:

1. **Clean evidence.** On nested leave-one-year-out 1993–2016 scores (outer year excluded from every inner fit), the mean tercile RPS improves with a one-sided paired sign-flip permutation p-value below 0.05. The p-value is Holm-adjusted across the five targets.
2. **No harm.** On 2017–2025 (1993–2016 fits), the mean RPS is not worse than the current method.

Units are whole years: one area-weighted Ethiopia score per year. 95 % year-block bootstrap intervals are reported alongside. Implementation: `scripts/significance.py`; comparisons: `scripts/decision_gates.py`.
Caveat: the Ethiopia-λ and square-root candidates were proposed after looking at 2017–2025 results (Phases 3–4). That is why clean evidence must come from 1993–2016.

### Phase 5 — significance gates and spatial duplication (items 5 and 7; completed 2026-10-05)

Output: `outputs/decision_gates/decision_gates.json` (per-year scores, tests, decisions).
Δ = candidate − current mean RPS (negative favours the candidate).

| Candidate (probabilities, with blend) | Training Δ RPS, 1993–2016 | Holm p | Operational Δ RPS, 2017–2025 | Adopt |
| --- | --- | --- | --- | --- |
| Ethiopia-only λ | +0.0003 to +0.0013 (worse in all 5) | 1.00 | −0.0001 to −0.0038 | **No** (all targets) |
| Square-root correction | −0.0007 to +0.0003 | 1.00 | −0.0006 to −0.0030 | **No** (all targets) |
| Both | −0.0002 to +0.0014 | 1.00 | −0.0004 to −0.0062 | **No** (all targets) |
| No blend (smoothed counts) | +0.011 to +0.032 (worse in all 5) | 1.00 | Aug −0.0137; others +0.012 to +0.021 | **No** (all targets) |
| Climatology | +0.002 to +0.021 (worse in all 5) | 1.00 | +0.004 to +0.030 | **No** (all targets) |

| Candidate (rainfall amounts, CRPS in mm) | Training Δ CRPS | Holm p | Operational Δ CRPS | Adopt |
| --- | --- | --- | --- | --- |
| Square-root correction | −0.10 to −0.13 (16–22 of 24 years better) | 0.0003–0.0125 | −0.03 to −0.20 | **Yes, all 5 targets** |

**Corrections to Phases 3 and 4.**
- The Ethiopia-only λ gain, including August, was a 2017–2025 effect only. It does not hold on clean 1993–2016 evidence. **Withdrawn.**
- The square-root correction does not improve tercile probabilities once the blend is applied. It does improve the **rainfall amount** product significantly. **Recommendation narrowed:** use the square-root correction for corrected amounts (ensemble members, mean and anomaly maps) from the next cycle. Keep the affine correction for tercile probabilities, or accept either, since the probability difference is not significant.

**Skill against climatology.** The current blend beats climatology on nested 1993–2016 scores for every target (JJAS −0.021, one-sided p = 0.026). After Holm adjustment over five targets, none is significant (JJAS 0.13; months 0.36–0.58). Present monthly skill as "small and not statistically established".

**Spatial duplication (item 7).**
- Every test uses one area-weighted score per year and resamples or permutes whole years. A season's ~1,480 correlated Ethiopia cells (from ~90 independent 1° model cells) therefore count as one observation, and the intervals are not overconfident.
- Area weighting gives each 1° model cell weight in proportion to its valid area. That is the correct weighting for area-mean scores, and the λ fit uses the same weights, so duplication does not bias λ.
- No change needed. Cell-level significance maps should not be produced without this year-level resampling.

### Phase 6 — August decision (item 6; completed 2026-10-05)

- Evidence for removing the August blend came only from 2017–2025 (−0.0137 RPS). On nested 1993–2016 scores the blend is better (+0.0122 for no blend; 14 of 24 years favour the blend).
- The regime-dependent blend (doc 28) showed −0.0028 in training, but was spatially inconsistent and was not adopted.
- **Decision under the rule: keep the shared blend for August.** Revisit after 2026 and 2027 verification add independent years.
- If August is revisited, the only candidate with clean-period support is the regularized regime blend (doc 28). It should be gated with `significance.gate`, not re-selected on 2017–2025.

### Phase 7 — ensemble size and system consistency (item 8; completed 2026-10-05)

Script: `scripts/ensemble_checks.py` → `outputs/ensemble_checks/ensemble_checks.json`. Ethiopia cells; final-method chain with 1993–2016 fits.

| Target | RPS, 51 members (2017–25) | RPS, 25-member subsets [95 %] | Raw spread, hindcast → oper (mm), p | Spread/error ratio, hindcast → oper |
| --- | --- | --- | --- | --- |
| JJAS | 0.4284 | 0.4307 [0.4242, 0.4373] | 66.1 → 70.5, p = 0.008 | 0.72 → 0.80 |
| Jun | 0.4590 | 0.4600 [0.4515, 0.4670] | 24.5 → 27.7, p < 0.001 | 0.68 → 0.64 |
| Jul | 0.4506 | 0.4522 [0.4455, 0.4591] | 31.2 → 33.7, p = 0.002 | 0.74 → 0.74 |
| Aug | 0.4264 | 0.4284 [0.4229, 0.4340] | 32.3 → 33.9, p = 0.084 | 0.78 → 0.76 |
| Sep | 0.4548 | 0.4557 [0.4518, 0.4594] | 31.3 → 33.6, p = 0.025 | 0.78 → 0.73 |

- [x] **Ensemble-size transfer is safe.** A blend weight fitted on 25-member hindcasts gives slightly better RPS with 51 members than with 25-member subsets, in every target. No member-count adjustment is needed.
- [x] **Spread is 5–13 % larger in operational years.** The SDs use ddof = 1; sample-size bias explains under 1 %. Possible causes are the wetter 2017–2025 seasons (spread scales with amount) or hindcast/forecast configuration differences. Raw mean bias shows no significant shift except September (26.0 → 16.6 mm, p = 0.048, not significant after multiplicity). The correction refits per cell, so this is a monitoring item, not a defect.
- [x] **New finding: the corrected ensemble is under-dispersive.** Spread/error is 0.64–0.80 in both periods (1.0 is ideal), consistent with 30 % of observations falling outside the ensemble range (section 3.4). The large climatology weights (λ = 0.49–0.78) partly compensate for this in the probabilities. **Candidate for a future cycle:** an explicit spread correction (variance inflation of the ensemble anomalies, or EMOS-type), gated with `significance.gate`. Expected effect: lower λ and more usable signal.
- [x] **Provenance recorded** in `data/raw/ecmwf/et_may_init/PROVENANCE.md` (CDS SEAS5 system 51, bit-identical re-download). `config/project.json` was left unchanged so the runner fingerprints stay stable. Copy the note into `provenance_note` at the next deliberate config revision.

### Phase 8 — regional skill (item 9; completed 2026-10-05)

Script: `scripts/regional_skill.py` (uses stored out-of-fold probabilities; no refitting) → `outputs/regional_skill/regional_skill.json` and per-cell RPSS fields in `regional_skill_fields.nc`.
Regions come from `github_regime_cleaned` in `evidence/followup_regime_comparison_and_masks.nc`.
Blend RPSS vs climatology is shown as nested training 1993–2016 (one-sided p) | 2017–2025.

| Region | JJAS | Jun | Jul | Aug | Sep |
| --- | --- | --- | --- | --- | --- |
| Ethiopia | **+0.046 (0.03)** \| +0.050 | +0.010 (0.29) \| +0.024 | +0.017 (0.09) \| +0.036 | +0.021 (0.09) \| +0.066 | +0.004 (0.32) \| +0.010 |
| R0 arid / marginal | **+0.108 (0.03)** \| +0.071 | −0.007 \| −0.005 (55 % cov.) | +0.006 \| +0.004 | **+0.073 (0.01)** \| +0.105 | +0.008 \| −0.045 |
| R1 western unimodal | **+0.055 (0.04)** \| +0.052 | +0.008 \| +0.015 | **+0.031 (0.01)** \| +0.019 | +0.004 \| +0.050 | +0.005 \| +0.010 |
| R2 Belg–Kiremt | **+0.101 (0.01)** \| +0.029 | +0.028 \| +0.031 | **+0.036 (0.04)** \| +0.022 | **+0.050 (0.01)** \| +0.053 | +0.007 \| +0.014 |
| R3 Gu–Deyr | −0.008 \| +0.062 | −0.007 \| +0.031 (55 %) | −0.030 \| +0.090 (48 %) | −0.004 \| +0.098 (53 %) | −0.000 \| +0.013 |
| R1+R2 JJAS domain | **+0.078 (0.01)** \| +0.040 | +0.018 \| +0.023 | **+0.034 (0.01)** \| +0.020 | **+0.027 (0.04)** \| +0.051 | +0.006 \| +0.012 |

Bold: training p < 0.05 (per region, not multiplicity-adjusted).

- **Where the forecast can be trusted:** JJAS in R0, R1 and R2 (the main JJAS rainfall domain); July in R1 and R2; August in R0 and R2.
- **R3 (Gu–Deyr, south and south-east) has no clean-period skill for any target.** The positive 2017–2025 values are not supported by 1993–2016, and monthly probability coverage there is only 48–55 %. Recommendation: label R3 JJAS–monthly probabilities "climatology-equivalent / low confidence" in bulletins, or mask them in the R1+R2 presentation layer (already available, doc 34).
- **June and September have no clean-period skill in any region.** Present them as low confidence.
- Maps: `regional_skill_fields.nc` holds per-cell blend RPSS (training and operational) for each target. Single-cell values are noisy, so read them together with these regional tables.

### Phase 9 — monthly–seasonal consistency (item 10; completed 2026-10-05)

Script: `scripts/monthly_consistency.py` → `outputs/monthly_consistency/monthly_consistency.json`. Member identifiers were verified identical across months, so members are summed member by member.

| | Training LOYO 1993–2016 | Operational 2017–2025 |
| --- | --- | --- |
| Amount: sum of monthly corrected means − JJAS corrected mean | +0.9 mm | +0.6 mm |
| CRPS, direct JJAS vs sum of months (mm) | 34.23 vs 33.92 (p = 0.14) | 33.33 vs 32.85 (p = 0.04) |
| Tercile RPS, direct vs sum of months (smoothed, no blend) | 0.4429 vs 0.4475 (sum worse, n.s.) | 0.4427 vs 0.4340 (n.s.) |
| Mean absolute probability difference per category | 0.054 | 0.045 |
| Dominant-category agreement | 79 % | 83 % |

Frozen 2026 products (Ethiopia area means):
- **Amounts:** JJAS 375.1 mm vs Jun–Sep sum 378.5 mm (+3.3 mm, 0.9 %).
- **Probabilities (below / near / above):** JJAS 50 / 25 / 24; Jun 43 / 30 / 27; Jul 45 / 29 / 26; Aug 51 / 26 / 24; Sep 36 / 31 / 33. These are coherent: three months lean below normal and September is near neutral.

- [x] **Amounts are consistent** (under 1 %). No reconciliation needed.
- [x] **Probabilities are consistent at the area level, but cell-level dominant categories differ in about 20 % of cells.** Building JJAS from summed months is not better on clean data, so keep the direct JJAS product.
- [ ] Optional presentation item: add a note to the bulletin that the monthly and seasonal outlooks are calibrated separately and need not add up cell by cell. Optionally add a "seasonal/monthly disagreement" flag layer.

### Medium-priority status

| Item | Status |
| --- | --- |
| 5 Significance gates | Done (`significance.py`, `decision_gates.py`) |
| 6 August decision | Done: keep the shared blend |
| 7 Spatial duplication | Done: year-level tests handle it; no change |
| 8 Ensemble size and system | Done: 51-member transfer safe; under-dispersion found (spread/error 0.64–0.80) |
| 9 Regional skill | Done: R3 and Jun/Sep lack clean skill |
| 10 Monthly–seasonal consistency | Done: amounts consistent; ~20 % cell-level category disagreement |

## 6. Lower-priority work

### Phase 10 — version control (item 14; completed 2026-10-05)

- [x] Git repository on `main`. Initial commit `a2d8040`: code, configs (including `config/project.json`), docs, tests, `data/masks/*.nc`, `evidence/` summaries and the regime mask, and `PROVENANCE.md`.
- [x] Ignored: raw and derived data, `outputs/`, large shapefiles, the two 11 MB experiment dumps, `_backup_` and `_building_` folders, and zips outside `archive/`.
- [x] `.gitattributes` sets `* -text`, so git never rewrites line endings. Scripts are SHA-256 fingerprinted by the runner and reports.
- [ ] Optional: add a remote (for example a private GitHub repository) and push.

### Phase 11 — duplicate modules and backup pruning (item 12; completed 2026-10-05)

- [x] Single implementations: `plot_forecast_products.py` (maps), `plot_smooth_forecasts.py` (contours), `delivery_render.py` (review/delivery package), and `verify2026_outputs.py` (publication, from Phase 1).
- [x] `review_map_base.py`, `delivery_map_base.py`, `review_contours.py`, `delivery_contours.py` and `build_forecast_review.py` are now aliases. Imports resolve to the same module object, and the documented commands still run the canonical `main()`.
- [x] `run_operational.py` `PRODUCT_SCRIPTS` now includes `plot_forecast_products.py` and `output_runs.py`, so fingerprints follow the real code. The next runner run rebuilds the views once.
- [x] New `scripts/prune_backups.py`. It previews by default (`--apply` deletes) and keeps the newest `--keep` backups per output. It never deletes a backup whose live output is missing and never touches `_building_` folders. Current preview: 25 removable backups (87.5 MB); 30 kept.
- [x] Checks: 79 tests pass. `run_operational.py --plan` and `finalize_forecast_delivery.py --check-only` pass on the real project.

### Phase 12 — generic forecast-cycle adapter (item 11; completed 2026-10-05)

- [x] `scripts/cycle.py`: one cycle file defines forecast year, reference period, member rule, development years, regime-mask baseline, overlap year and folders. Selected with `CALIBRATION_CYCLE` or `run_operational.py --config`. The default `config/operational.json` (2026) is unchanged.
- [x] Cycle-driven: `final_shared_blend`, `run_monthly`, the member checks in `prepare_seasonal`, `regrid_seasonal`, `inspect_inputs` and `run_calibration`, the whole verification chain, the maps, the delivery package, the presentation layers and the runner.
- [x] Fixed by design: the historical method study (1993–2016 / 2017–2025) and the descriptive regime-mask baseline (1993–2025).
- [x] New `scripts/extend_observations.py` adds verified CHIRPS years (for example 2026) to the training archive, with grid, missing-cell and JJAS = Σ months checks. It never overwrites.
- [x] Cycle files: `config/cycles/may_2027.json` (template) and `config/cycles/backtest_may_2025.json` (regression). Guide: `docs/37_NEW_FORECAST_CYCLE.md`.
- [x] Regression checks for 2026:
  - Refitted forecasts are identical to the frozen files (all variables and attributes).
  - Jun–Aug verification reports are identical.
  - Presentation PNG and NetCDF files are byte-identical; PDFs differ only in their creation date.
- [x] 2025 backtest (fit 1993–2024, verify 2025): fit, products, freeze, Jun–Aug verification and report all complete.
  - Final-blend RPSS: Jun −0.025, Jul −0.077, Aug +0.062.
  - Smoothed counts without the blend: Jun −0.19, Jul −0.24.
  - **2025 was a poor year for the model, and the blend limited the damage**, which is consistent with the Phase 5 decision to keep it.
- [x] Tests: `tests/test_cycle.py` added; 83 tests pass.

### Phase 13 — GitHub repository and results site (2026-10-05)

- [x] `scripts/build_site.py` generates `site/` (a single page, 3 MB) entirely from result files: workflow, data and methods, historical and regional skill, significance gates, ensemble diagnostics, the 2026 forecast (maps per target) and the Jun–Aug 2026 verification. It is labelled a research reconstruction and not an official EMI/ICPAC forecast. Responsive layout with light and dark themes.
- [x] `.github/workflows/pages.yml` deploys `site/` to GitHub Pages. `.github/workflows/tests.yml` runs the test suite on Windows, Python 3.11.
- [x] `evidence/*all_regime_experiments.json` is now tracked (identical content, stored once, about 1.6 MB compressed), so a clean clone passes the tests.
- [x] Pushed to https://github.com/YonSci/calibrated_seasonal_rainfall (public). Pages is enabled with GitHub Actions as the source; the site is live at https://yonsci.github.io/calibrated_seasonal_rainfall/. The Deploy and Tests workflows pass. Two tests were fixed to resolve temp paths, because GitHub's runner uses 8.3 short names.
- After September and JJAS verification: rerun `build_verification_report.py` for all targets, then `python scripts\build_site.py`, and push.
- [x] Site update: the forecast and verification sections now follow the operational gallery (`outputs/operational_2026/index.html`):
  - the same entries, images and statistics rows;
  - both views, **All Ethiopia** and the **JJAS R1+R2 rainfall domain** (833 cells, 56 % of the country area, fixed 1993–2025 descriptive domain);
  - side-by-side comparison tables and target/view selectors.

  Images come from `outputs/operational_2026/presentation/`. Rebuild with `python scripts\build_site.py` after rerunning the runner.
- [x] Runbook, issue log (30 issues with causes, fixes and automated guards) and automation blueprint: docs/38_REPRODUCIBLE_RUNBOOK.md.

### Phase 14 — second season: September-initialized ONDJ (completed 2026-10-05)

- [x] Pipeline generalized to any initialization month and to seasons that cross the year boundary (`common.season_window`), with JJAS outputs unchanged (regression checks in docs/38 §7).
- [x] ONDJ 2026/27: ECMWF downloaded (34 years), prepared, regridded, monthly targets, skill, rainfall domain, forecast and products. On the site, with the explorer's dropdowns for target, product and rainfall domain.
- [x] ONDJ verification: the cross-year verification calendar is implemented (Phase 16) and was tested on the 2024/25 backtest. ONDJ 2026/27 is verified after CHIRPS January 2027 is published; freeze the forecast (`prepare_verification_2026.py --freeze-only`) before October observations are used.
- [x] Training notebook `notebooks/ONDJ_training_walkthrough.ipynb` (17 sections, TOC, executed outputs), generated by `notebooks/build_ondj_training_notebook.py`.
- [x] Training notebook `notebooks/Rainfall_domains_JJAS_FMAM_ONDJ.ipynb`: walkthrough regime logic (harmonics, peak timing, 4 regimes) and JJAS (833 cells), FMAM (418) and ONDJ (575) domains; JJAS identical to the project R1+R2 mask; 18/20 reference stations agree. Masks saved to `outputs/regime_domains/seasonal_regime_domains.nc`.
- [x] Shapefiles and GeoJSON (WGS 84) for the four regimes and the JJAS, FMAM and ONDJ domains, exported in the domains notebook (section 13); zip tracked at `data/masks/ethiopia_rainfall_regimes_and_domains_shp.zip`.

### Phase 15 — forecasts on the walkthrough rainfall domains (2026-10-08)

- [x] `build_season_domain.py --method regime` builds seasonal domains with the scientific masking walkthrough rules: JJAS R1+R2 (≥ 120 mm, ≥ 20 % of annual), FMAM R2 (≥ 80 mm), ONDJ R3 (≥ 30 mm). Masks: `data/masks/init05_JJAS_regime_domain.nc`, `data/masks/init09_ONDJ_regime_domain.nc`. They are identical to the domains notebook.
- [x] **JJAS (May initialization): no change needed.** The regime-based JJAS domain is identical cell for cell (833) to the R1+R2 domain the JJAS products already use.
- [x] **ONDJ (September initialization): switched** from the earlier ≥ 120 mm / 20 % rule (487 cells) to the ONDJ R3 (Deyr) domain (575 cells, 39 % of Ethiopia). The cycle file points to the new mask; products, site and both notebooks were rebuilt. Over the domain, ONDJ 2026/27 is 19 / 24 / 57 % (below / near / above), +64 mm (previously 20 / 24 / 56 %, +65 mm). November is 21 / 22 / 57 %.
- Calibration and forecast values are unchanged; only the presentation and summary domain changed.
- [x] FMAM 2026 (January initialization; corrected from February on 2026-10-08): configs `config/fmam/project.json`, `config/cycles/jan_2026_fmam.json` and run guide `docs/39_FMAM_RUN_GUIDE.md`. Run end to end by the project team (download to products, freeze and March–May verification; commit e6304a3).

### Phase 16 — verification for every season (2026-10-08)

- [x] Verification chain and runner generalized from May/JJAS to any cycle season: season profile in `cycle.py` (targets, calendar window per target, domain view), cross-year months (January of ONDJ downloaded and checked in the next year), season mask for the regime/domain breakdown, report and gallery wording, `--freeze-only`, and site sections that show a cycle's verification.
- [x] JJAS regression: Jun–Aug 2026 verification reports and regime summaries identical; 46 presentation PNGs byte-identical.
- [x] ONDJ backtest 2024/25 (`config/cycles/backtest_sep_2024_ondj.json`): full `run_operational.py --workflow all` on official CHIRPS Oct 2024–Jan 2025. Observations match the archive within 1e-4 mm. Domain RPSS −0.17 (forecast leaned dry, observed mixed to wet), December +0.15.
- [x] FMAM 2026: March–May verify end to end (scratch test). **February 2026 is missing from the official CHIRPS v2.0 archive**, so February and FMAM stay pending.
- [x] Guide for all seasons: `docs/40_SEASON_RUN_GUIDES.md`. 86 tests pass.
- [x] FMAM 2026 run end to end by the project team, including the freeze and March–May verification against official CHIRPS. February and FMAM wait for CHIRPS February 2026.

### Phase 17 — site redesign after external review (2026-10-08)

An external review asked for a forecast-first page that a new visitor can understand within a minute. `scripts/build_site.py` was rewritten:

- [x] One cycle selector (FMAM 2026 · January, JJAS 2026 · May, ONDJ 2026/27 · September; default: the latest initialization) and an area selector. They update the headline, targets, maps, verification, historical evidence, status and downloads. The state is kept in the URL (`?cycle=…&target=…&view=…&kind=…&product=…`), and the map viewer has "Copy link to this view".
- [x] Outlook first: an interpretation sentence, "average local probability" (probabilities and amounts shown separately, with probability and amount coverage) and the tercile map near the top. Forecast signal (from probabilities only) is shown separately from historical skill.
- [x] Status panel per cycle: model initialization, target period, freeze or generation date, publication status (research reconstruction, kept separate from the initialization date), reference period, observations processed through, CHIRPS archive check, last verification run and method/version. Per-target statuses are specific: target period ongoing or not started, awaiting CHIRPS (names the missing months, read from the official by_month listing at build time; `--offline` reports "not checked"), observations awaiting processing, verification not yet run, verification published.
- [x] Map viewer with product tabs (tercile, total, anomaly mm, anomaly %, verification), HTML explanations of colours, grey and white areas, display smoothing and the 0.25° grid vs ~1° model information; "Open full-size" and "Download PNG" with descriptive filenames.
- [x] Verification as an assessment: "What happened? What did the forecast capture? What did it miss?", a paired forecast-vs-observed anomaly chart, and public metric labels (probability skill RPSS, rainfall amount skill CRPSS, average rainfall error, observed category distribution, assessed area, raw benchmark). Scores are decimals with the percentage explanation (+0.193 = 19.3% lower score than climatology).
- [x] Historical performance: cross-validated 1993–2016 RPSS as the main number with a whole-year 95% bootstrap interval and years better; later years labelled exploratory. The regional table is labelled as applying to May-initialized JJAS only.
- [x] Six-item navigation (Outlooks · Maps · Verification · Historical performance · Methods & data · Downloads); technical material (workflow, equations, method selection, ensemble diagnostics, QC, limitations, reproduce) in expandable sections; bounded wording for the 25→51 member transfer; raw benchmark defined.
- [x] Downloads: per-cycle summary CSV, verification reports and the JJAS bulletin.
- [x] Accessibility: skip link, `aria-live` updates, `noscript` summary table, table captions, image error messages, phone layout checked at 520 px.
- [x] Split the six-panel verification image into separate web panels (done in Phase 18, at site build).

### Phase 18 — second site review: scope, wording and interaction (2026-10-08)

- [x] Historical skill per area: `regional_skill.py --cycle <cycle>` scores each cycle's rainfall domain and the R0–R3 regimes from the stored cross-validated probabilities (no refitting), writing `outputs/regional_skill/<tag>_regional_skill.json`. JJAS R1+R2 reproduces the existing table (+0.078). New: FMAM R2 domain, FMAM +0.057 (95% +0.006 to +0.109); ONDJ R3 domain, ONDJ +0.093 (+0.012 to +0.182). The skill card and the historical table follow the selected area and name it; a domain without scores falls back to "All Ethiopia" with a note that the domain has not been evaluated.
- [x] Verbal skill labels reflect the interval: "improvement (interval above zero)", "small estimated improvement; skill uncertain", "no demonstrated improvement". One-target and Holm-adjusted p-values (over the cycle's five targets) are shown; no target of any cycle stays significant after adjustment.
- [x] The verification narrative always states the signed rainfall error and how much of the observed anomaly the forecast captured (August 2026, R1+R2: forecast 20.6 mm too wet, deficit underestimated by about 44%); larger discrepancies are emphasised. "Nothing notable" is gone.
- [x] Climatology described as implemented: per-cell observed tercile frequencies of the training years (about one-third), with `p_final = (1 − λ)·p_model + λ·p_climatology`. Signal labels state that they use a one-third reference.
- [x] The map viewer keeps a requested verification view when it is unavailable and explains why, with a button to the forecast. Verification maps are offered as separate panels (cut from the six-panel figure at site build; layout checked by image size) plus the composite.
- [x] Status wording: "file not found in the checked CHIRPS listing (last checked …)" instead of "not yet published". Probability coverage column in the targets table.
- [x] Accessibility: anchor offset follows the measured header height, research label visible on phones, `site/downloads/index.html` for the no-JavaScript fallback, pressed-state buttons instead of incomplete tab roles, focus kept on the equivalent control after re-rendering.

### Phase 19 — evidence explorer, package, comparison and release archive (2026-10-08)

Third site review: two remaining interface fixes, then four optional features.

- [x] Fixes: the phone research label rule now follows its base rule (visible at ≤ 560 px); activating "View the … forecast" in an unavailable-verification message moves focus to the persistent Forecast control (tested in Edge). Also fixed a horizontal overflow below ~420 px caused by the cycle selector (selectors stack full-width on phones; no overflow at 375 px).
- [x] Historical verification explorer: `scripts/historical_diagnostics.py --cycle <cycle>` computes, from the stored out-of-fold probabilities (no refitting), per target, period (cross-validated 1993–2016 or exploratory later years) and area: performance by year, reliability per tercile with cell-year counts, a histogram of leading-probability strength and category Brier scores and skill. The per-year scores reproduce the published RPSS (JJAS R1+R2 +0.078, 19/24 years). Each view states its period, benchmark, area coverage and sample size, and notes that cell-years are spatially correlated. Sparse reliability bins (fewer than 0.5% of cell-years, at least 50) are shown open and not joined. Rainfall-amount diagnostics exist only for May JJAS (2017–2025, all Ethiopia); elsewhere the explorer says they have not been generated (a cross-validated amount evaluation is a separate scientific task).
- [x] Download package: a 3-page PDF bulletin per cycle (outlook and interpretation, probability bar, signal and area skill, tercile map; targets, skill with Holm p, verification, cycle record, how to read, limitations; monthly maps), README and metadata JSON, forecast NetCDF files per target, and a "Download package (ZIP)" button that zips the bulletin, CSV, metadata, README, every map, reports and NetCDF in the browser (JSZip from cdnjs, jsDelivr fallback). Individual downloads remain.
- [x] Map comparison: forecast and observed anomaly side by side (same colour scale, cut from one figure), with "Show error map", "Open full-size comparison" and "Download comparison figure".
- [x] Release archive and change log: `config/site_releases.json` lists releases (id, date, title, change types: verification, display, domain, analysis, method). `site/releases/<id>/` holds the exact page published at each release commit, with maps and files served from that commit on raw.githubusercontent.com, and the change log lists, per release, what changed and how it differs from the current release (statuses, verification added, forecast numbers, domain views). Releases 2026-10-08.0–.2 were back-filled from commits e6304a3, a473e73 and 385448c; 2026-10-08.3 is this release.

### Phase 20 — comparison with official outlooks (2026-10-09)

- [x] New pipeline (guide: docs/41): `external_forecasts.py` (ICPAC/EMI adapters, versioned downloads by SHA-256, standardized records, ICPAC map digitization, `review`), `compare_external_forecasts.py` (eligibility per metric, structured findings, maps), `interpret_external_forecasts.py` (deterministic rules, review report). Runner flags `--compare-external` and `--refresh-external`; three resumable stages before the gallery; the ONDJ cycle file has an `external_comparison` block.
- [x] Sources retrieved: the ICPAC OND 2026 update rainfall map (IGAD region) and the EMI Kiremt 2026 assessment and Bega 2026/27 outlook bulletin. Page 21 was found automatically from the PDF text, and its embedded figure was extracted unchanged. Unstated issue dates, initialization dates and reference periods stay null.
- [x] The ICPAC map is digitized onto the 0.25° grid with a tick-fit residual under 1 px. The EMI zone values (III, VI, VII, VIII) are a draft transcription with arrow-tip locations.
- [x] Review: both extraction records were validated by the project team on 2026-10-09 (EMI 09:20 UTC, ICPAC 09:21 UTC) against the source hashes, and the comparison was rerun. The site now publishes the findings: agreement on above-normal rainfall over the ONDJ R3 domain and in EMI zones VI, VII and VIII, and disagreement in EMI zone III (west), where the platform favours below normal near the arrow tip (50 / 31 / 19 %) and EMI prints 55 % above.
- [x] Unavailable metrics are stated with reasons: zone means (no zone polygons), same-event probability differences (OND vs ONDJ windows; ICPAC publishes intervals only), rainfall-anomaly differences (no official anomaly product), accuracy (needs verification).
- [x] Tests: `tests/test_external_forecasts.py` (9 tests). Re-rendered ONDJ maps are byte-identical to the earlier ones; a rerun resumes every stage.
