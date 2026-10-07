# 39 — Run guide: January-initialized FMAM 2026 forecast, from download to the GitHub page

A complete, hands-on test of the system on a third season: **FMAM (February–May, Belg)** from the
**1 January 2026** ECMWF SEAS5 initialization. Every command is for **Windows CMD**, run from the project folder.
Each step lists what to expect, so you can tell immediately whether it worked.

The configurations are already in the repository:

| File | Content |
| --- | --- |
| `config/fmam/project.json` | Season FMAM (02-01 to 05-31), init month 1, raw data `data/raw/ecmwf/et_jan_init`, archive 1993–2026, CHIRPS 1993–2025 |
| `config/cycles/jan_2026_fmam.json` | Forecast year 2026, reference 1993–2025, targets Feb, Mar, Apr, May, FMAM, outputs `outputs/operational_2026_fmam`, domain mask `data/masks/init01_FMAM_regime_domain.nc` |

Total time: about 1.5–2 hours, mostly the CDS download queue. Everything after the download takes about 10 minutes.

---

## Step 0 — Prepare the session

```bat
cd /d D:\calibrated_seasonal_rainfall
call .venv\Scripts\activate.bat
git pull
pip install -r requirements.txt
type %USERPROFILE%\.cdsapirc
```

**Expect:** `git pull` reports "Already up to date" or fast-forwards; the `.cdsapirc` file shows a `url:` and a `key:` line.
If it is missing, create it from your Copernicus CDS profile page.

## Step 1 — Download ECMWF SEAS5 (1 January, 1993–2026)

FMAM needs daily lead times from the 1 January start to the end of May: Jan 31 + Feb (28/29) + Mar 31 + Apr 30 +
May 31 = **152 days** (covers leap years). January itself is lead time only; it is not part of the target season.
Open **three CMD windows** (repeat Step 0's `cd` and `activate` in each) and run one batch per window, so the CDS queue
works on them in parallel:

```bat
set PYTHONIOENCODING=utf-8
python scripts\download_seasonal_forecasts_daily_c3s.py --models ecmwf --system ecmwf=51 --variables total_precipitation --year-start 1993 --year-end 2003 --months 1 --init-day 1 --leadtime-days 152 --north 15 --west 33 --south 3 --east 48 --outdir data\raw\ecmwf\et_jan_init
```

Second window: the same command with `--year-start 2004 --year-end 2014`. Third window: `--year-start 2015 --year-end 2026`.

**Expect:** each window ends with `Succeeded : 11 file(s)` (the third: `12`) and `Done.`; 34 files
`ecmwf_YYYY01_d01.nc` in `data\raw\ecmwf\et_jan_init`. Re-running a batch skips files that already exist, so an
interrupted download can simply be restarted.

> `set PYTHONIOENCODING=utf-8` prevents the `UnicodeEncodeError … '\u2192'` crash in the Windows console (issue I-03).

## Step 2 — Select the FMAM cycle (keep this window open for Steps 3–9)

```bat
set CALIBRATION_CYCLE=config\cycles\jan_2026_fmam.json
```

Every script now uses the FMAM cycle (forecast year, reference period, folders). **Run Steps 3–9 in this same window.**
If you open a new window, set the variable again.

## Step 3 — Inventory

```bat
python scripts\inspect_inputs.py --config config\fmam\project.json
```

**Expect:** `1993: ok` … `2026: ok` and `Inventory passed.` Report: `outputs\inspection\init01_FMAM\`.
Members must be 25 for 1993–2016 and 51 from 2017.

## Step 4 — Seasonal totals and regridding

```bat
python scripts\prepare_seasonal.py --config config\fmam\project.json --all-years
python scripts\regrid_seasonal.py --config config\fmam\project.json
```

**Expect:** `Prepared 1993: 25 members; 120 days` … leap years (1996, 2000, 2004, …, 2024) show **121 days**;
`Regridded … conservation error ~1e-14`. QC: `outputs\qc\preparation_init01_FMAM.json`.

## Step 5 — Monthly targets (Feb, Mar, Apr, May)

```bat
python scripts\run_monthly.py --config config\fmam\project.json --stage prepare
```

**Expect:** monthly configs written to `config\fmam\monthly_Feb.json` … `monthly_May.json`, each month prepared and
regridded, then `Passed: monthly totals reproduce FMAM within numerical comparison tolerance.`

## Step 6 — Historical skill

```bat
python scripts\local_blend.py --config config\fmam\project.json --mode training --region-mask data\masks\ethiopia_common.nc
python scripts\local_blend.py --config config\fmam\project.json --mode operational --region-mask data\masks\ethiopia_common.nc
python scripts\run_monthly.py --config config\fmam\project.json --stage training
python scripts\run_monthly.py --config config\fmam\project.json --stage operational
```

**Expect:** for each target a table ending with a `shared_blend … RPSS=…` line and `Complete:`. Training = nested
1993–2016; operational = fits on 1993–2016 scored on 2017–2025. Results: `outputs\local_calibration\init01_*`.

## Step 7 — FMAM rainfall domain (Belg, regime R2)

```bat
python scripts\build_season_domain.py --config config\fmam\project.json --method regime
```

**Expect:** `FMAM R2 (Belg) rainfall domain: 418 cells, 28.0% of Ethiopia -> …\data\masks\init01_FMAM_regime_domain.nc`
(the same domain as `notebooks/Rainfall_domains_JJAS_FMAM_ONDJ.ipynb`).

## Step 8 — Final fit and the FMAM 2026 forecast

```bat
python scripts\final_shared_blend.py --region-mask data\masks\ethiopia_common.nc
```

**Expect:** `Final target: Feb` … `Final target: FMAM`, each followed by `Saved: …\outputs\final_shared_blend\init01_<target>\2026`.
Combined report: `outputs\final_shared_blend\final_reports_init01_2026.json` (climatology weight λ per target).

## Step 9 — Forecast maps for both views

```bat
python scripts\build_season_products.py
```

**Expect:** `Rendered Feb 2026` … `Rendered FMAM 2026` and `Entries: …\outputs\operational_2026_fmam\entries.json`.
Look at a map, for example
`outputs\operational_2026_fmam\presentation\forecast\FMAM\fmam_rainfall_domain\tercile_outlook.png`.
Its title should read *FMAM 2026 | rainfall tercile outlook*, *January initialization*, and the view *FMAM R2 (Belg)
rainfall domain*.

## Step 10 — Rebuild the results site and check it locally

Clear the cycle variable first (the site combines all cycles):

```bat
set CALIBRATION_CYCLE=
python scripts\build_site.py
start "" site\index.html
```

**Expect:** a new section **"January initialization · FMAM 2026 forecast"** (also in the top menu as *FMAM*), and in the
*Map explorer* a new target group with Feb 2026 … FMAM 2026 and the views *All Ethiopia* / *FMAM R2 (Belg) rainfall
domain*. The JJAS and ONDJ sections are unchanged.

## Step 11 — Run the tests

```bat
python -m unittest discover -s tests
```

**Expect:** `OK` (about 85 tests, 1–2 minutes).

## Step 12 — Commit and push

```bat
git status
git add -A
git commit -m "Add January-initialized FMAM 2026 forecast"
git push
```

**Expect:** `git status` lists `site/…` (the new FMAM maps), `config/fmam/monthly_*.json` and
`data/masks/init01_FMAM_regime_domain.nc`. Raw data and `outputs/` are not committed (by design, `.gitignore`).

## Step 13 — Watch the deployment and view the page

```bat
"C:\Program Files\GitHub CLI\gh.exe" run list --limit 3
"C:\Program Files\GitHub CLI\gh.exe" run watch
```

or open <https://github.com/YonSci/calibrated_seasonal_rainfall/actions>. Wait until **Deploy site** and **Tests** show a
green tick (about 1 and 3 minutes). Then open <https://yonsci.github.io/calibrated_seasonal_rainfall/> and press
**Ctrl + F5** (the browser may keep the previous version for a few minutes).

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `UnicodeEncodeError … '\u2192'` during download | Windows console encoding | `set PYTHONIOENCODING=utf-8` (Step 1) |
| A download batch stops with a CDS error | Queue or network problem | Re-run the same command; existing files are skipped |
| `exists. Add --regenerate to rebuild` | Output from an earlier attempt | Add `--regenerate` (the old output is kept as a `_backup_` folder) |
| `… exists. Rename partial/old monthly folder before preparation.` in Step 5 | A previous partial monthly run | Rename or delete `data\interim\init01_<Mon>` and `data\processed\init01_<Mon>`, re-run Step 5 |
| Outputs appear under `init05_…` or for JJAS | `CALIBRATION_CYCLE` not set in this window | Repeat Step 2 in the window you are using |
| `Project configuration does not match the selected cycle` | `--config` and cycle disagree | Use `config\fmam\project.json` with `jan_2026_fmam.json` |
| `Unexpected member count` | Incomplete download for that year | Delete that year's file and re-download it |
| Page unchanged after push | Deployment running or browser cache | Wait for the green tick, then Ctrl + F5 |

## What this test does not cover

* **Verification of FMAM 2026.** CHIRPS for February–May 2026 is already published, so the forecast could be verified,
  but the verification runner (`run_operational.py`) is still wired to the May-initialized JJAS cycle. Generalizing it
  is the next step (see `docs/38_REPRODUCIBLE_RUNBOOK.md`, section 6).
* **Method changes.** The FMAM run uses the frozen final method; any change must pass `scripts/decision_gates.py` first.

When the run is finished, record its key numbers (λ per target, skill, the FMAM 2026 probabilities over the R2 domain)
in a run log like section 7 of `docs/38_REPRODUCIBLE_RUNBOOK.md`.
