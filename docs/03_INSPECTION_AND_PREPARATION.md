# 03 — Inspect inputs and prepare seasonal totals

## Step A: run the inventory

Activate the environment and edit source paths first:

```bat
python scripts\inspect_inputs.py --config config\project.json
```

Outputs:

- `outputs/inspection/inspection_summary.md`: readable overview.
- `outputs/inspection/ecmwf_inventory.csv`: per-year inventory.
- `outputs/inspection/inventory.json`: detailed metadata/configuration report.

The script opens every configured forecast, verifies expected dimensions/initialization/member counts/interval dates, checks target-season coverage, and samples one cumulative series. It inventories CHIRPS time coverage without loading its entire rainfall array. Missing/error entries cause a nonzero exit after reports are saved. A sampled cumulative check is not a full-array audit; preparation checks all model values.

## Step B: run the synthetic tests

```bat
python -m unittest discover -s tests -v
```

Tests check daily accumulation conversion, May/September boundaries, both member counts, negative resets, missing timestamps, missing rainfall, wrong units, and NetCDF writing/reading. They generate small artificial datasets; they do not validate your real archive or forecast skill.

## Step C: prepare one historical season

```bat
python scripts\prepare_seasonal.py --config config\project.json --years 1993
```

Default outputs:

- `data/interim/init05_JJAS/ecmwf_1993_native.nc`
- `data/interim/init05_JJAS/chirps_1993_native.nc`
- `outputs/qc/preparation_init05_JJAS.json`

**These outputs remain on their separate native grids.** No interpolation, bias correction, tercile thresholds, or Dirichlet probabilities have been applied.

ECMWF contains `precip_season(member,lat,lon)` and `valid_day_count`. CHIRPS contains `precip_season(year,lat,lon)` and `valid_day_count`. Keeping model years in separate files preserves their actual member counts instead of padding an archive with artificial members.

## Exact time and unit rules

1. Decode accumulation endpoint timestamps.
2. Require first endpoint = initialization +24 hours and all differences =24 hours.
3. Compute `1000 * (C[t] - C[t-1])`; the starting cumulative amount is zero.
4. Label each interval by `valid_time - 1 day`.
5. Select June 1–September 30 inclusive (122 days).
6. Check the unmodified daily sum against `1000 * (C[Oct 1] - C[Jun 1])`.
7. Reject substantial negative increments. Clip only tiny negative increments within the configured 0.2 mm tolerance; record the total adjustment. SEAS5 `tp` is GRIB-packed at about 2^-13 m (0.122 mm), so rounding produces daily drops up to about 0.15 mm in every year (1993–2026 maximum: -0.1465 mm); 0.2 mm admits these but rejects real accumulation resets.
8. Require all season intervals to be finite per member/pixel. Incomplete totals remain NaN.
9. Sum CHIRPS on the same start-labeled dates; any missing daily observation makes that pixel's seasonal total NaN.

The first May 2 endpoint describes May 1. The final October 31 endpoint describes October 30, so this archive does not contain all October days. No forecast season is chosen by treating endpoint month as the rainfall month.

## Step D: check representative operational years

```bat
python scripts\prepare_seasonal.py --config config\project.json --years 2017 2025 2026
```

No observation file is written for 2026. The CLI checks the configured project expectation of 25 members before 2017 and 51 afterward. A mismatch is an inspection problem, not a reason to silently truncate members.

## Step E: prepare the full archive after representative checks

```bat
python scripts\prepare_seasonal.py --config config\project.json --all-years
```

Processes one model file/year at a time and selects only the requested CHIRPS season. This is deliberately sequential to keep Windows operation and memory behavior simple. Runtime depends on storage and source encoding; no runtime promise is made.

## Review before moving on

- All requested dates are present; JJAS has 122 intervals.
- Valid totals are nonnegative, with no unexplained extreme amounts.
- Member counts match the manifest.
- Missingness maps are understood and sources are unchanged.
- Source grid coordinates and cell-bound assumptions are checked before remapping.
- Daily sum and accumulation endpoint difference agree.

If a year fails, earlier derived outputs may already exist. Fix the issue and rerun the requested years; successful writes atomically replace only the corresponding derived files. The QC JSON summarizes the last successful invocation, so check its timestamp if a run fails.
