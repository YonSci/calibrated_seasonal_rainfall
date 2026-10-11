# 45 — CHIRPS v3.0: a parallel track before any switch

**Adopted 2026-10-11 (release 2026-10-11.1).** CHIRPS v3.0 replaced v2.0 for calibration and verification, and the 2026
cycles were republished on v3.0 (retrospective: recalibrated after their outcomes were known). The CHIRPS v2.0 versions
are release 2026-10-10.2 in the site's release archive; locally their working data are in `outputs_chirps_v2/`,
`models_chirps_v2/`, `data/interim_chirps_v2/` and `data/processed_chirps_v2/` (git-ignored). The first decision was
Option A (keep 2026 on v2.0); it was replaced the same day by republishing on v3.0.

## Steps

| Step | What | Status |
|---|---|---|
| 1 | v3 archive on the project's 0.25° grid | done (`prepare_chirps_v3.py`) |
| 2 | v2 vs v3 comparison over Ethiopia | done (`compare_chirps_versions.py`) |
| 3 | v3 calibration in separate configs and outputs (development + final), decision gates, domain reviews | done (worktree `chirps-v3`, `compare_v3_calibration.py`) |
| 4 | Adopt v3 and republish every cycle on it (method release 2026-10-11.1) | done |

## Step 1 — the v3 archive

```bat
python scripts\prepare_chirps_v3.py --first 1993-01 --last 2026-08
```

CHIRPS v3 is published at 0.05° only (no p25), monthly is its native product (daily values are disaggregated from
pentads with ERA5 `rnl` or IMERG `sat`), and every target here is a whole month or a season of whole months. The
script downloads the official Africa monthly GeoTIFFs (one receipt per file; ~5 MB each), checks each file's grid
(0.05°, origin 20°W 40°N, 1500 × 1600) and averages each 5 × 5 block onto the 0.25° cells of the existing grid (edges at
multiples of 0.25°, so the blocks align exactly). A cell needs at least 13 of its 25 sub-cells valid; the count is
stored. Output: `data\raw\chirps\et\et_chirps3_monthly_r25.nc` (1993-01 to 2026-08). Provenance:
`data\raw\chirps\v3\PROVENANCE.md`. New dependencies (pinned): `tifffile`, `imagecodecs`.

## Step 2 — v2 vs v3 over Ethiopia, 1993–2025

```bat
python scripts\compare_chirps_versions.py
```

Outputs in `outputs\chirps_v3_comparison\` (`comparison.json`, `climatology_v2_v3.png`, `agreement_v2_v3.png`,
`domains_v2_v3.png`, `national_series_v2_v3.png`). Area-weighted over the 1,478 Ethiopia cells complete in both
(v2 misses 6 country cells, v3 none):

| | FMAM | JJAS | ONDJ (1993/94–2024/25) | Annual |
|---|---|---|---|---|
| Mean, v2 → v3 | 249 → 279 mm (+12 %) | 441 → 518 mm (+17 %) | 141 → 163 mm (+16 %) | 830 → 959 mm (+15 %) |
| Share of annual, v2 → v3 | 35.3 → 34.9 % | 43.7 → 44.3 % | 21.1 → 21.0 % | — |
| Median cell correlation of seasonal totals | 0.94 | 0.89 | 0.94 | — |
| National (area-mean) series correlation | 0.978 | 0.973 | 0.984 | — |
| Same tercile category (cell-years, own terciles) | 78 % | 71 % | 78 % | — |
| Opposite outer categories | 0.4 % | 1.5 % | 0.5 % | — |
| Tercile limits, median change (lower / upper) | +8 / +13 % | +18 / +21 % | +6 / +16 % | — |
| Domain rule (≥ 100 or 120 mm, ≥ 20 %), share of Ethiopia | 72.9 → 75.6 % | 65.0 → 67.9 % | 33.2 → 36.2 % | — |

2026 months (v3 against the v2 files the 2026 verification used): v3 is wetter in every month (national means
+3 % in April to +22 % in January), with spatial correlations of 0.85–0.97.

**Reading.** v3 is systematically wetter (about +15 % a year), almost everywhere — consistent with CHC's published
Legates–Willmott gauge-undercatch corrections in v3 (see `diagnostics/legates-willmott_corrections` on the CHC server).
The *seasonal shares* hardly change, so share-based domain rules move little (a few percent of the country, mostly
added at the edges), but *amount* thresholds and every tercile limit move up. Year-to-year variations agree well
nationally (r ≈ 0.97–0.98) and over most cells; agreement is weakest in the dry south-east in JJAS, where totals are
small. A quarter of cell-years would fall in a different tercile — mostly adjacent; opposite categories are rare.

**Consequences for step 3.** Because the climatology and the tercile limits change, every calibration (amount
correction, terciles, blend weights) must be refitted with v3 — a v2-calibrated forecast must not be verified against
v3 (Option A). The amount thresholds of the domain rules (100/120 mm) would cover a slightly larger area with v3; the
domain reviews should be rerun with v3 before a domain is chosen for a v3 cycle.

## Step 3 — the v3 calibration (done 2026-10-11)

**Where it runs.** Branch `chirps-v3`, checked out as a separate git worktree `..\calibrated_seasonal_rainfall_v3`. Its project and
monthly configs read the v3 archive (`"chirps_file": "data/raw/chirps/et/et_chirps3_monthly_r25.nc"`, `"chirps_variable":
"monthly_total"`, `"chirps_temporal": "monthly"`; `prepare_seasonal.py` sums whole months). `data/interim`, `data/processed`,
`outputs` and `models` are git-ignored, so the worktree has its own and nothing of the v2 track can be overwritten. Raw ECMWF
and CHIRPS data are linked from the main folder (directory junctions and hard links, no copies). One command runs the chain
for the four cycles — seasonal and monthly preparation, nested historical evaluation (1993–2016) and the exploratory years
(2017 onwards), the final shared blend, regional skill, the development calibration with its amount verification,
historical diagnostics — and then the JJAS decision gates:

```bat
cd /d D:\calibrated_seasonal_rainfall_v3
D:\calibrated_seasonal_rainfall\.venv\Scripts\python.exe scriptsun_chirps_v3_track.py
D:\calibrated_seasonal_rainfall\.venv\Scripts\python.exe scriptsun_rainfall_domain_review.py --config configainfall_domainsmam_review.json
cd /d D:\calibrated_seasonal_rainfall
python scripts\compare_v3_calibration.py
```

Results (`outputs\chirps_v3_comparison\calibration_comparison.json`). Each side is scored against **its own** observations,
so the numbers say how well the method works with each dataset, not which dataset is right.

| Cycle · season | λ v2 → v3 | Cross-validated RPSS 1993–2016, v2 → v3 | Exploratory RPSS, v2 → v3 | Amount CRPSS (dev. run), v2 → v3 |
|---|---|---|---|---|
| May · JJAS | 0.50 → 0.59 | +0.046 [+0.003, +0.087] → +0.027 [−0.006, +0.057] | +0.050 → +0.039 | +0.017 → −0.018 |
| January · FMAM | 0.43 → 0.34 | +0.027 → +0.032 | −0.004 → +0.017 | −0.001 → +0.016 |
| February · FMAM | 0.44 → 0.40 | +0.022 → +0.021 | +0.043 → +0.059 | +0.053 → +0.071 |
| September · ONDJ | 0.28 → 0.18 | +0.020 → +0.039 | +0.063 → +0.075 (2017–2024) | +0.181 → +0.178 |
| February · Feb (month) | 0.48 → 0.50 | +0.120 → +0.126 | +0.007 → +0.056 | — |

* **Method decisions are unchanged.** The JJAS decision gates give the same outcome with v3 as with v2: none of the
  candidate changes (Ethiopia-only λ, square-root correction, no blend, plain climatology) passes, so the shared
  climatology blend stays.
* **Skill is similar overall, with season differences.** FMAM and ONDJ score slightly better with v3; JJAS scores lower
  (its cross-validated interval now includes zero, and amount skill turns slightly negative). All differences are
  within the year-to-year uncertainty.
* **2026 season forecasts would change little** (national mean probabilities, below / near / above): JJAS 51/25/24 % →
  47/27/27 %; FMAM (January) 34/32/34 % → 34/31/35 %; FMAM (February) 27/33/40 % → 26/32/42 %; ONDJ 28/27/45 % → 27/27/46 %.
  These v3 forecasts are for comparison only and are not published (Option A).
* **Domains under the same rules grow slightly** with v3: the FMAM working rule (≥ 100 mm and ≥ 20 %) covers 72.6 → 75.6 % of
  Ethiopia; its draft agreement with the EMI Belg maps rises 0.91 → 0.93. JJAS and ONDJ candidates move by up to a few
  percent. The regime-based domains (R1+R2, R3) are fixed masks and do not change; the regimes themselves are a v2 daily
  product and are not rebuilt (v3 has no observed daily product).

## Step 4 — adoption (2026-10-11)

* **Configuration.** The `chirps-v3` branch was merged: every project and monthly config reads
  `data/raw/chirps/et/et_chirps3_monthly_r25.nc` (`"chirps_temporal": "monthly"`). `scripts/obs_source.py` gives every script
  the observation facts (label, product, official listing, monthly file names, citation), so verification downloads,
  availability checks, reports, maps, the bulletin, the README and the site name CHIRPS v3.0 from the configuration.
* **Verification.** Months come from the official v3 monthly files (`chirps-v3.0.YYYY.MM.tif`), averaged onto the grid
  exactly as the archive is and checked against the archive in the overlap year (2025).
* **Recalibration.** `run_chirps_v3_track.py` (the full chain) was rerun in the main folder; its forecasts equal those of the
  worktree bit for bit. Evidence scripts (`ensemble_checks.py`, `monthly_consistency.py`, `clipping_analysis.py`) and the
  JJAS decision gates were rerun on v3.0.
* **Domains.** FMAM keeps its rule on the v3.0 climatology: `data/masks/fmam_coverage_chirps_v3_1993_2025_v1.nc` (1,196
  cells, 75.6 % of Ethiopia). The FMAM main-season view, JJAS R1+R2 and ONDJ R3 masks are unchanged (regime/descriptive
  masks from the CHIRPS v2.0 daily climatology; CHIRPS v3 has no observed daily product).
* **Republication.** Every 2026 cycle was frozen anew and verified against v3.0 (FMAM February–May and the season; JJAS
  June–August; ONDJ pending). The site says these forecasts are retrospective.
* **Not carried over:** the original JJAS forecast bulletin and the historical blend review (both v2.0 artefacts).
