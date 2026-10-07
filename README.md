# Ethiopia calibrated seasonal rainfall (ECMWF SEAS5 → CHIRPS)

Calibrated tercile probabilities and corrected rainfall amounts for Ethiopia from
the ECMWF SEAS5 May initialization, verified against CHIRPS v2.0 (0.25°).

Targets: **JJAS** season and the months **Jun, Jul, Aug, Sep** (May initialization), and **ONDJ** with **Oct, Nov, Dec, Jan** (September initialization; `config/ondj/`, `config/cycles/sep_2026_ondj.json`).
Reference period 1993–2025 (25-member hindcasts 1993–2016, 51-member forecasts 2017 onward).
Platform: Windows 11, CMD, Python 3.11 x64, project `.venv`.

**Results site:** https://yonsci.github.io/calibrated_seasonal_rainfall/ (built by `scripts/build_site.py`; rebuild after results change).
**Current status and open items:** [docs/36_PROJECT_STATUS_REVIEW.md](docs/36_PROJECT_STATUS_REVIEW.md).
**Reproducible runbook, issue log and automation blueprint:** [docs/38_REPRODUCIBLE_RUNBOOK.md](docs/38_REPRODUCIBLE_RUNBOOK.md).
**Training notebook (ONDJ walkthrough):** [notebooks/ONDJ_training_walkthrough.ipynb](notebooks/ONDJ_training_walkthrough.ipynb) — regenerate with `python notebooksuild_ondj_training_notebook.py` (needs `pip install -r requirements-notebook.txt`).
**Training notebook (rainfall regimes and JJAS / FMAM / ONDJ domains):** [notebooks/Rainfall_domains_JJAS_FMAM_ONDJ.ipynb](notebooks/Rainfall_domains_JJAS_FMAM_ONDJ.ipynb) — regenerate with `python notebooksuild_rainfall_domains_notebook.py`.
**Hands-on run guide (January-initialized FMAM 2026, download → GitHub page):** [docs/39_FMAM_RUN_GUIDE.md](docs/39_FMAM_RUN_GUIDE.md).
**Next forecast cycle (2027):** [docs/37_NEW_FORECAST_CYCLE.md](docs/37_NEW_FORECAST_CYCLE.md). Cycle files live in `config/cycles/`; select one with `set CALIBRATION_CYCLE=...`.

## Final method (frozen for 2026)

1. Prepare native seasonal and monthly totals (`prepare_seasonal.py`, `run_monthly.py`).
2. Copy each 1° ECMWF cell into its 4×4 block of 0.25° CHIRPS cells (`regrid_seasonal.py`).
3. Correct per-cell mean and variance of member amounts (`calibration_core.py`).
4. Form smoothed member-count tercile probabilities, (n + 0.5) / (M + 1.5).
5. Blend with climatology using one weight per target, fitted on leave-one-year-out RPS
   over 1993–2025 (`final_shared_blend.py`).

Dirichlet recalibration, local blends and regime blends were evaluated and not adopted
(docs 13–17, 25–28).

## Common commands (CMD)

```bat
cd /d D:\calibrated_seasonal_rainfall
call .venv\Scripts\activate.bat

:: Inputs
python scripts\inspect_inputs.py --config config\project.json
python scripts\prepare_seasonal.py --config config\project.json --all-years

:: Final fit and 2026 forecast (do NOT rerun after the freeze; see below)
python scripts\final_shared_blend.py --config config\project.json --region-mask data\masks\ethiopia_common.nc

:: Operational products, verification and gallery
python scripts\run_operational.py --workflow products
python scripts\run_operational.py --workflow all
start "" outputs\operational_2026\index.html

:: Housekeeping: preview, then delete old --regenerate backups (keeps newest per output)
python scripts\prune_backups.py
python scripts\prune_backups.py --apply

:: Tests
python -m unittest discover -s tests
```

The 2026 forecasts are frozen with SHA-256 hashes in
`outputs/verification_2026/frozen_forecasts/freeze_manifest.json`. Regenerating
`outputs/final_shared_blend` changes those hashes and blocks verification by design.

## Folder map

| Path | Purpose |
| --- | --- |
| `config/` | `project.json` (JJAS), `monthly_*.json`, `operational.json` (2026 cycle), `cycles/` (2027 template, 2025 backtest) |
| `scripts/` | Pipeline, verification, delivery and runner scripts |
| `tests/` | Unit and smoke tests |
| `docs/` | Numbered step documents 01–36 (read in order; 36 is the current status) |
| `data/raw/` | ECMWF and CHIRPS sources |
| `data/interim/`, `data/processed/` | Native-grid and common-grid seasonal/monthly totals |
| `data/masks/`, `data/boundaries/` | Ethiopia mask and admin boundary |
| `evidence/` | Regime masks and evidence snapshots used by delivery and verification |
| `outputs/final_shared_blend/` | Fitted 2026 forecasts per target |
| `outputs/forecast_delivery/` | Bulletin, maps and bundle |
| `outputs/verification_2026/`, `outputs/verification_report_2026/` | Frozen forecasts and verification |
| `outputs/operational_2026/` | Runner outputs and offline gallery |
| `archive/` | Superseded patch packages (Step 33 validation, Step 35 Windows fix) |

## Documentation order

01–08 setup, data, inspection and design · 09–17 regridding, calibration and method
comparison · 18–20 monthly fixes and final blend · 21–24 maps · 25–28 regimes and the
August review · 29–32 delivery, freeze and verification · 33–35 operational runner ·
36 status review · 37 new forecast cycle · 38 runbook and issue log · 39 FMAM run guide.
