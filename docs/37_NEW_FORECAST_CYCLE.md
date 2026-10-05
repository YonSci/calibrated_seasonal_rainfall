# 37 — Running a new forecast cycle (example: May 2027)

All operational scripts read their forecast year, reference period, member-count rule
and output folders from one **cycle file**. `scripts/cycle.py` loads it.

| Cycle file | Purpose |
| --- | --- |
| `config/operational.json` | Default: the frozen May 2026 cycle (1993–2025 reference) |
| `config/cycles/may_2027.json` | Template for May 2027 (1993–2026 reference) |
| `config/cycles/backtest_may_2025.json` | Regression/backtest: 2025 from 1993–2024; writes only to `outputs/_backtest_2025` |

Select a cycle for every script in a CMD session:

```bat
set CALIBRATION_CYCLE=config\cycles\may_2027.json
```

`run_operational.py --config <cycle file>` sets this automatically for its stages.
With no variable set, everything behaves exactly as for 2026.

## Cycle file fields

| Field | Meaning |
| --- | --- |
| `adapter` | `may_shared_blend` (or the legacy `may_2026_shared_blend`) |
| `forecast_year`, `initialization_month` | Forecast year; only May (5) is implemented |
| `reference_years` | `[first, last]` CHIRPS years used to fit; must end before `forecast_year` |
| `expected_members` | Member-count rule, e.g. `[{"last_year": 2016, "members": 25}, {"members": 51}]` |
| `development_years` | Fixed method-development period (default 1993–2016) |
| `regime_mask_years` | Baseline of the descriptive regime mask in `evidence/` (stays 1993–2025 unless the mask is rebuilt) |
| `overlap_year` | Last year of the historical CHIRPS archive file. Official downloads are checked against it (2025) |
| `forecast_root`, `verification_root`, `output_root`, … | Folders. Use a new `verification_root` and `output_root` per cycle |

## Steps for May 2027

Run in CMD from the project folder after `call .venv\Scripts\activate.bat`.

**1. Close the 2026 cycle.** When CHIRPS September 2026 is published, complete the 2026 verification:

```bat
python scripts\run_operational.py --workflow all --verification-targets Jun Jul Aug Sep JJAS
```

**2. Add 2026 observations to the training archive.** This uses the verified totals, which were checked against the archive:

```bat
python scripts\extend_observations.py --year 2026 --source outputs\verification_2026\observations --check-only
python scripts\extend_observations.py --year 2026 --source outputs\verification_2026\observations
```

It refuses to run unless all five targets are present, the grid and missing-cell pattern match the archive, and JJAS equals the sum of the months. It never overwrites.

**3. Download the May 2027 ECMWF forecast:**

```bat
set PYTHONIOENCODING=utf-8
python scripts\download_seasonal_forecasts_daily_c3s.py --models ecmwf --system ecmwf=51 --variables total_precipitation --years 2027 --months 5 --init-day 1 --leadtime-days 183 --north 15 --west 33 --south 3 --east 48 --outdir data\raw\ecmwf\et_may_init
```

Check the system number on CDS first. If SEAS5 is replaced, the hindcasts must be replaced too, and the whole calibration must be refitted and re-evaluated. Do not mix systems.

**4. Prepare 2027 for JJAS and each month.** First set `archive_years` to `[1993, 2027]` in `config/project.json`. Leave `observation_years` at `[1993, 2025]`, because it describes the CHIRPS archive file. Then:

```bat
set CALIBRATION_CYCLE=config\cycles\may_2027.json
python scripts\inspect_inputs.py --config config\project.json
python scripts\prepare_seasonal.py --config config\project.json --years 2027
python scripts\regrid_seasonal.py --config config\project.json --years 2027
for %m in (Jun Jul Aug Sep) do python scripts\prepare_seasonal.py --config config\monthly_%m.json --years 2027 && python scripts\regrid_seasonal.py --config config\monthly_%m.json --years 2027
python scripts\run_monthly.py --config config\project.json --stage check
```

**5. Fit and forecast.** This fits on 1993–2026 and writes `outputs/final_shared_blend/init05_<target>/2027/`:

```bat
python scripts\final_shared_blend.py --config config\project.json --region-mask data\masks\ethiopia_common.nc
```

Before issuing, apply any method change adopted for this cycle, for example the square-root amount correction (docs/36, Phase 5), and document it.

**6. Products and freeze:**

```bat
python scripts\run_operational.py --config config\cycles\may_2027.json --workflow products
python scripts\prepare_verification_2026.py --months Jun --input-root outputs\final_shared_blend --root outputs\verification_2027
```

The second command creates the SHA-256 freeze manifest. Run it immediately after issuing.

**7. Verify during and after the season** (in 2027, as observations appear):

```bat
python scripts\run_operational.py --config config\cycles\may_2027.json --workflow all
```

Script names keep the `_2026` suffix for continuity. They now follow the selected cycle.

## Regression and backtest

`config/cycles/backtest_may_2025.json` runs the full chain for a year that already has observations:

```bat
set CALIBRATION_CYCLE=config\cycles\backtest_may_2025.json
python scripts\final_shared_blend.py
python scripts\prepare_verification_2026.py --months Jun Jul Aug --input-root outputs\_backtest_2025\final_shared_blend --root outputs\_backtest_2025\verification
python scripts\run_operational.py --config config\cycles\backtest_may_2025.json --workflow all --verification-targets Jun Jul Aug
```

Validated 2026-10-05:
- The default (2026) cycle reproduces the frozen forecasts, the Jun–Aug verification reports and all presentation images exactly.
- The 2025 backtest completes fit, products, freeze, verification and report.
