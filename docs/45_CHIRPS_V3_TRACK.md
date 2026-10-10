# 45 — CHIRPS v3.0: a parallel track before any switch

**Decision (2026-10-11, Option A):** the 2026 forecasts and their verification stay on CHIRPS v2.0. CHIRPS v3.0 is
evaluated in a parallel track and, if adopted, used from the next forecast cycle. Nothing published is changed.

## Steps

| Step | What | Status |
|---|---|---|
| 1 | v3 archive on the project's 0.25° grid | done (`prepare_chirps_v3.py`) |
| 2 | v2 vs v3 comparison over Ethiopia | done (`compare_chirps_versions.py`) |
| 3 | v3 calibration in separate configs and outputs (development + final), decision gates, domain reviews | next |
| 4 | Decision: adopt v3 from the next cycle, as a method release | after step 3 |

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

## Step 3 — what it needs (next)

1. `prepare_seasonal.py` reads a daily archive; the v3 track needs it to accept the monthly archive (sums of whole
   months — exact for every target).
2. Separate project and cycle configs for v3 (e.g. `config\v3\…`) with their own processed, calibration, model and
   output folders, so no v2 file is overwritten.
3. Development and final calibration, the decision gates (`decision_gates.py`), historical diagnostics and the domain
   reviews with the v3 climatology.
4. The verification downloads (`prepare_verification_2026.py`, `run_operational.py`, `verify2026_common.py`) and the
   site's "CHIRPS v2.0" text read the observation source from the configuration instead of hard-coded v2 URLs.
