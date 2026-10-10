# 43 — Run guide: February-initialized FMAM 2026 forecast (second FMAM cycle)

A second FMAM 2026 forecast from the **1 February 2026** ECMWF SEAS5 initialization. It runs **alongside** the January
cycle (`docs/39_FMAM_RUN_GUIDE.md`), not instead of it. Both appear on the site and can be compared with the official
ICPAC and EMI outlooks.

**Why:** the official outlooks were issued in mid- and late February 2026 (the EMI PDF was created on 16 February, and the ICPAC MAM *update* file is dated 25 February).
These outlooks had information from February initializations, so a February-initialized platform forecast is the fairer comparison. The January
cycle stays as the earlier, longer-lead forecast.

**Retrospective run.** This forecast is produced in October 2026, after the season. It uses the frozen final method and
only data up to 2025 (reference 1993–2025, plus the 2026 ECMWF ensemble). No 2026 observations enter the forecast, but say
so when you present it.

Every command is for **Windows CMD**, run from the project folder.

| File | Content |
| --- | --- |
| `config/fmam_feb/project.json` | Season FMAM (02-01 to 05-31), init month 2, raw data `data/raw/ecmwf/et_feb_init`, archive 1993–2026, CHIRPS 1993–2025 |
| `config/cycles/feb_2026_fmam.json` | Forecast year 2026, reference 1993–2025, targets Feb, Mar, Apr, May, FMAM, outputs `outputs/operational_2026_fmam_feb`, domain mask `data/masks/init02_FMAM_regime_domain.nc`, site id `fmam2026feb`, official comparison enabled (same registry and extraction records as January) |

Folder tag: `init02_…` (January is `init01_…`, so the two cycles never share outputs).

## Differences from the January cycle

| | January cycle | February cycle |
| --- | --- | --- |
| Initialization | 1 January 2026 | 1 February 2026 |
| Lead days to download | 152 | **121** (Feb 1 – May 31, covers leap years) |
| February | 1-month lead | **lead 0**: the season starts on the initialization date |
| Raw data | `data\raw\ecmwf\et_jan_init` | `data\raw\ecmwf\et_feb_init` |
| Project config | `config\fmam\project.json` | `config\fmam_feb\project.json` |
| Cycle file | `config\cycles\jan_2026_fmam.json` | `config\cycles\feb_2026_fmam.json` |
| Site / download names | `fmam2026…` | `fmam2026feb…` |

Total time: about 1–1.5 hours, mostly the CDS download queue (shorter than January because it requests 121 instead of 152 days).

---

## Step 0 — Prepare the session

```bat
cd /d D:\calibrated_seasonal_rainfall
call .venv\Scripts\activate.bat
git pull
```

## Step 1 — Download ECMWF SEAS5 (1 February, 1993–2026)

Open **three CMD windows** (repeat Step 0 in each) and run one batch per window:

```bat
set PYTHONIOENCODING=utf-8
python scripts\download_seasonal_forecasts_daily_c3s.py --models ecmwf --system ecmwf=51 --variables total_precipitation --year-start 1993 --year-end 2003 --months 2 --init-day 1 --leadtime-days 121 --north 15 --west 33 --south 3 --east 48 --outdir data\raw\ecmwf\et_feb_init
```

Second window: the same command with `--year-start 2004 --year-end 2014`. Third window: `--year-start 2015 --year-end 2026`.

**Expect:** `Succeeded : 11 file(s)` (the third: `12`) and `Done.`; 34 files `ecmwf_YYYY02_d01.nc` in
`data\raw\ecmwf\et_feb_init`. Re-running skips existing files.

## Step 2 — Select the February cycle (keep this window open for Steps 3–10)

```bat
set CALIBRATION_CYCLE=config\cycles\feb_2026_fmam.json
```

## Step 3 — Inventory

```bat
python scripts\inspect_inputs.py --config config\fmam_feb\project.json
```

**Expect:** `1993: ok` … `2026: ok`, `Inventory passed.` Report: `outputs\inspection\init02_FMAM\`.

## Step 4 — Seasonal totals and regridding

```bat
python scripts\prepare_seasonal.py --config config\fmam_feb\project.json --all-years
python scripts\regrid_seasonal.py --config config\fmam_feb\project.json
```

**Expect:** `Prepared 1993: 25 members; 120 days` (leap years: **121 days**); conservation error ~1e-14.

## Step 5 — Monthly targets

```bat
python scripts\run_monthly.py --config config\fmam_feb\project.json --stage prepare
```

**Expect:** `config\fmam_feb\monthly_Feb.json` … `monthly_May.json` written, then `Passed: monthly totals reproduce FMAM …`.

## Step 6 — Historical skill

```bat
python scripts\local_blend.py --config config\fmam_feb\project.json --mode training --region-mask data\masks\ethiopia_common.nc
python scripts\local_blend.py --config config\fmam_feb\project.json --mode operational --region-mask data\masks\ethiopia_common.nc
python scripts\run_monthly.py --config config\fmam_feb\project.json --stage training
python scripts\run_monthly.py --config config\fmam_feb\project.json --stage operational
```

**Expect:** a `shared_blend … RPSS=…` line per target. Results: `outputs\local_calibration\init02_*`. February should
show clearly higher skill than in the January cycle (lead 0 instead of 1 month).

## Step 7 — FMAM rainfall domain

```bat
python scripts\build_season_domain.py --config config\fmam_feb\project.json --method regime
```

**Expect:** `FMAM R2 (Belg) rainfall domain: 418 cells, 28.0% of Ethiopia -> …\data\masks\init02_FMAM_regime_domain.nc`.
The domain comes from CHIRPS only, so it is identical to the January cycle's mask.

## Step 8 — Final fit and the forecast

```bat
python scripts\final_shared_blend.py --region-mask data\masks\ethiopia_common.nc
```

**Expect:** `Saved: …\outputs\final_shared_blend\init02_<target>\2026` for Feb … FMAM;
report `outputs\final_shared_blend\final_reports_init02_2026.json` (λ per target).

## Step 9 — Freeze

```bat
python scripts\prepare_verification_2026.py --config config\fmam_feb\project.json --input-root outputs\final_shared_blend --root outputs\verification_2026_fmam_feb --freeze-only
```

**Expect:** `Freeze ready: …\outputs\verification_2026_fmam_feb\freeze_manifest.json`.

## Step 10 — Maps, skill summaries, verification and the official comparison

```bat
python scripts\run_operational.py --config config\cycles\feb_2026_fmam.json --workflow all --verification-targets Feb Mar Apr May FMAM --compare-external
python scripts\regional_skill.py --cycle config\cycles\feb_2026_fmam.json
python scripts\historical_diagnostics.py --cycle config\cycles\feb_2026_fmam.json
```

**Expect:** `Ready: …\outputs\operational_2026_fmam_feb\index.html`; the verification for all five targets; and
`outputs\operational_2026_fmam_feb\comparisons\…` with the ICPAC and EMI comparison. The comparison reuses the FMAM
registry and the extraction records you reviewed for January (same official products), so no new extraction work is
needed. Records still in draft show up only in the review report, not on the site.

February 2026 comes from the official annual CHIRPS p25 file because its `by_month` file was never published (see Step 14 of
`docs/39_FMAM_RUN_GUIDE.md`).

## Step 11 — Site, tests, publish

```bat
set CALIBRATION_CYCLE=
python scripts\build_site.py
python -m http.server 8000 --directory site
```

Open <http://localhost:8000>. The cycle selector now has **FMAM 2026 — January initialization** and **FMAM 2026 —
February initialization**. The February cycle's downloads are named `fmam2026feb_…`; the January cycle's links are
unchanged.

```bat
python -m unittest discover -s tests
git add -A
git commit -m "Add February-initialized FMAM 2026 forecast"
git push
```

Add a release entry to `config\site_releases.json` first if you want this version archived (or ask me to do this part).

## What to look at

* **λ per target** (`final_reports_init02_2026.json`) compared with January (0.70 / 0.81 / 0.71 / 0.57 / 0.43 for
  Feb / Mar / Apr / May / FMAM). A lower λ means the model carries more weight.
* **The FMAM 2026 probabilities over the R2 domain** compared with January (34 / 32 / 34), and with ICPAC and EMI.
* **March**: observed +142 % of normal (96 % of Ethiopia above normal). The January run favoured nothing there; check
  whether the February initialization picked up the wet signal.

## Troubleshooting

As in `docs/39_FMAM_RUN_GUIDE.md`, with `init02` in place of `init01` and `config\fmam_feb\project.json` in place of
`config\fmam\project.json`. If outputs appear under `init01_…`, `CALIBRATION_CYCLE` is not set to the February cycle in
that window.
