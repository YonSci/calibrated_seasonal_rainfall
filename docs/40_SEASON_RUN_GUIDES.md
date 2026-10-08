# 40 — Run guides for every season: JJAS, FMAM and ONDJ (forecast, verification, next year)

One pipeline serves all three seasons. Only the **cycle file** (and its project configuration) changes. This document
gives, for each season, every step from the ECMWF download to the published page, then the verification once CHIRPS
observations exist, then the update for the next year. All commands are for **Windows CMD**, run from
`D:\calibrated_seasonal_rainfall` after:

```bat
call .venv\Scripts\activate.bat
git pull
pip install -r requirements.txt
```

## 1. The three seasons at a glance

| | **JJAS** (Kiremt) | **FMAM** (Belg) | **ONDJ** (Deyr / Hagaya) |
| --- | --- | --- | --- |
| Initialization | 1 May | 1 January | 1 September |
| Target months | Jun, Jul, Aug, Sep | Feb, Mar, Apr, May | Oct, Nov, Dec, **Jan of the next year** |
| Lead days to download | 183 | 152 | 153 |
| Raw data folder | `data\raw\ecmwf\et_may_init` | `data\raw\ecmwf\et_jan_init` | `data\raw\ecmwf\et_sep_init` |
| Project config | `config\project.json` | `config\fmam\project.json` | `config\ondj\project.json` |
| Cycle file (2026) | `config\operational.json` | `config\cycles\jan_2026_fmam.json` | `config\cycles\sep_2026_ondj.json` |
| Folder tag | `init05_…` | `init01_…` | `init09_…` |
| Reference (CHIRPS) | 1993–2025 | 1993–2025 | 1993/94–2024/25 |
| Rainfall domain (presentation) | R1 + R2, ≥ 120 mm, ≥ 20 % of annual (833 cells) | R2, ≥ 80 mm (418 cells) | R3, ≥ 30 mm (575 cells) |
| Domain mask | `evidence\followup_regime_comparison_and_masks.nc` | `data\masks\init01_FMAM_regime_domain.nc` | `data\masks\init09_ONDJ_regime_domain.nc` |
| Verification possible when | CHIRPS for Sep 2026 is published | CHIRPS for Feb 2026 is published (Mar–May already) | CHIRPS for Jan 2027 is published (Oct–Dec as they appear) |
| Status (8 Oct 2026) | Forecast, freeze, Jun–Aug verified; Sep and JJAS pending | Forecast done; Mar–May verifiable now; **Feb 2026 is missing from the official CHIRPS archive** | Forecast done; verification from Nov 2026 onward |

The cycle file selects everything else. Always set it in the CMD window you use:

```bat
set CALIBRATION_CYCLE=<cycle file from the table>
```

`run_operational.py --config <cycle file>` sets it for its own stages.

---

## 2. Forecast steps (the same for every season)

Replace the placeholders with the season's values from the table: `<INIT>` initialization month number (5, 1, 9),
`<LEAD>` lead days, `<RAW>` raw data folder, `<PROJECT>` project config, `<CYCLE>` cycle file.

| Step | Command | Expect |
| --- | --- | --- |
| 1. Download (three windows: 1993–2003, 2004–2014, 2015–2026) | `set PYTHONIOENCODING=utf-8` then `python scripts\download_seasonal_forecasts_daily_c3s.py --models ecmwf --system ecmwf=51 --variables total_precipitation --year-start 1993 --year-end 2003 --months <INIT> --init-day 1 --leadtime-days <LEAD> --north 15 --west 33 --south 3 --east 48 --outdir <RAW>` | 34 files, `Done.` |
| 2. Select the cycle | `set CALIBRATION_CYCLE=<CYCLE>` | — |
| 3. Inventory | `python scripts\inspect_inputs.py --config <PROJECT>` | every year `ok`; `Inventory passed.` |
| 4. Seasonal totals | `python scripts\prepare_seasonal.py --config <PROJECT> --all-years` | JJAS 122 days; FMAM 120 (121 in leap years); ONDJ 123 |
| 5. Regrid | `python scripts\regrid_seasonal.py --config <PROJECT>` | conservation error ~1e-14 |
| 6. Monthly targets | `python scripts\run_monthly.py --config <PROJECT> --stage prepare` | `Passed: monthly totals reproduce <SEASON> …` |
| 7. Historical skill | `python scripts\local_blend.py --config <PROJECT> --mode training --region-mask data\masks\ethiopia_common.nc` (and `--mode operational`), then `python scripts\run_monthly.py --config <PROJECT> --stage training` (and `--stage operational`) | `shared_blend … RPSS=` per target |
| 8. Rainfall domain (FMAM, ONDJ) | `python scripts\build_season_domain.py --config <PROJECT> --method regime` | cell count as in the table |
| 9. Final fit and forecast | `python scripts\final_shared_blend.py --region-mask data\masks\ethiopia_common.nc` | `Saved: …\final_shared_blend\<TAG>_<target>\<YEAR>` |
| 10. **Freeze** (immediately after issuing) | `python scripts\prepare_verification_2026.py --config <PROJECT> --input-root outputs\final_shared_blend --root <verification_root> --freeze-only` | `Freeze ready: …\freeze_manifest.json` |
| 11. Maps and gallery | `python scripts\run_operational.py --config <CYCLE> --workflow products` | `Ready: …\index.html` |
| 11b. Domain and regional skill | `python scripts\regional_skill.py --cycle <CYCLE>` | `Saved: …\regional_skill\<TAG>_regional_skill.json` (historical skill of the rainfall domain and the regimes, shown on the site) |
| 11c. Historical diagnostics | `python scripts\historical_diagnostics.py --cycle <CYCLE>` | `Saved: …\historical_diagnostics\<TAG>_diagnostics.json` (performance by year, reliability, signal histogram, category Brier skill for the explorer) |
| 11d. Release entry | add an entry to `config\site_releases.json` (id, date, title, change types, `"commit": null`) and set the previous entry's `commit` to the commit that published it | the change log and the archived page of the previous release appear under `site/releases/` |
| 12. Site | `set CALIBRATION_CYCLE=` then `python scripts\build_site.py` (add `--offline` without internet) | cycle appears in the cycle selector; statuses checked against the CHIRPS listing |
| 13. Tests | `python -m unittest discover -s tests` | `OK` |
| 14. Publish | `git add -A`, `git commit -m "<message>"`, `git push`, then `"C:\Program Files\GitHub CLI\gh.exe" run watch` | green Deploy site and Tests; page updated (Ctrl + F5) |

`<verification_root>` is in the cycle file (`verification_root`), e.g. `outputs\verification_2026_fmam`.
For JJAS, steps 1–9 have already been run for 2026; JJAS does not need step 8 (its R1+R2 domain is part of the
regime reconciliation mask). `build_season_products.py` (used earlier for FMAM/ONDJ) still works, but step 11 also
prepares the verification views later.

---

## 3. Verification steps (the same for every season)

The forecasts stay **frozen**: verification only reads them (SHA-256 checked before and after every stage).

1. **Check which months are published** (official CHIRPS v2.0 p25 monthly files):

   ```bat
   set CALIBRATION_CYCLE=<CYCLE>
   python scripts\run_operational.py --config <CYCLE> --workflow all --plan
   ```

   The plan prints `CHIRPS availability: <month> available | unavailable` for each target month (January of ONDJ is
   checked in the following year automatically) and the targets ready for verification.

2. **Verify what is available:**

   ```bat
   python scripts\run_operational.py --config <CYCLE> --workflow all
   ```

   With the default `--verification-targets auto` it verifies every published month, and the **season** once all its
   months are published. To ask for specific targets: `--verification-targets Mar Apr May`. A month that is not yet
   published is reported as pending; no incomplete total is ever created.

   What happens, per month: download the official monthly file; check it against the historical CHIRPS archive (same
   month of the archive's last year, tolerance 1e-4 mm/day); build the total on the project grid; score it against the
   frozen forecast (RPS/RPSS, Brier, log loss, CRPS, bias); stratify by regime and the season's rainfall domain; write
   the consolidated report and the verification maps (both views).

3. **Look at the results:**

   | Output | Where |
   | --- | --- |
   | Scores per target | `<verification_root>\results\<target>\verification_report.json` |
   | Regime / domain summary | `<output_root>\regimes\<targets>\regime_verification_summary.json` |
   | Consolidated report | `<output_root>\reports\<targets>\VERIFICATION_REPORT.html` |
   | Gallery (forecast and verification, both views) | `<output_root>\index.html` |

4. **Publish:** `set CALIBRATION_CYCLE=`, `python scripts\build_site.py`, tests, `git add/commit/push` (steps 12–14). The
   site picks up the cycle's verification automatically (season section *Verification against CHIRPS* table and the map
   explorer's *Verification* product).

5. **Repeat** when further months are published; already verified months are kept (content-checked resume).

---

## 4. Season notes

### JJAS (May initialization)

* Already done for 2026: forecast, freeze, Jun–Aug verification. **Remaining:** September and JJAS once CHIRPS
  September 2026 is published: `python scripts\run_operational.py --workflow all` (the default config is the JJAS cycle).
* The presentation domain is the JJAS R1+R2 rainfall domain from the regime reconciliation mask; the regime-based
  rebuild (`build_season_domain.py --config config\project.json --method regime`) gives the identical 833 cells.

### FMAM (January initialization)

* January is lead time only; the target months are February–May of the same year.
* **February 2026 is not in the official CHIRPS v2.0 monthly archive** (8 Oct 2026: Jan and Mar–Aug 2026 are listed,
  Feb is not). Verify March–May now:

  ```bat
  set CALIBRATION_CYCLE=config\cycles\jan_2026_fmam.json
  python scripts\prepare_verification_2026.py --config config\fmam\project.json --input-root outputs\final_shared_blend --root outputs\verification_2026_fmam --freeze-only
  python scripts\run_operational.py --config config\cycles\jan_2026_fmam.json --workflow all --verification-targets Mar Apr May
  ```

  February and FMAM follow automatically (`--workflow all`) once the file appears.
* Leap years: February and FMAM have 29 / 121 days in 1996, 2000, …, 2024; this is handled automatically.

### ONDJ (September initialization)

* The season crosses the year boundary: October–December in the initialization year, **January in the next year**.
  Tags, downloads and checks handle this automatically (e.g. ONDJ 2026/27 verifies January against
  `chirps-v2.0.2027.01`).
* Reference seasons end with 2024/25 because the archive file ends in December 2025.
* Freeze now (`--freeze-only`); verify October as soon as CHIRPS October 2026 is published (around late November
  2026), and the full ONDJ after January 2027 (around late February 2027):

  ```bat
  set CALIBRATION_CYCLE=config\cycles\sep_2026_ondj.json
  python scripts\prepare_verification_2026.py --config config\ondj\project.json --input-root outputs\final_shared_blend --root outputs\verification_2026_ondj --freeze-only
  python scripts\run_operational.py --config config\cycles\sep_2026_ondj.json --workflow all
  ```

* Tested end to end on a **backtest**: ONDJ 2024/25 (`config\cycles\backtest_sep_2024_ondj.json`, reference
  1993–2023), verified against official CHIRPS Oct 2024–Jan 2025. The verification observations matched the CHIRPS
  archive totals for the same season within 1e-4 mm. Writes only under `outputs\_backtest_ondj_2024`.

---

## 5. Next year (for example JJAS 2027, FMAM 2027, ONDJ 2027/28)

1. When all months of a season are verified, add that year's observations to the training archive:

   ```bat
   set CALIBRATION_CYCLE=<CYCLE of the verified year>
   python scripts\extend_observations.py --year <YEAR> --source <verification_root>\observations --check-only
   python scripts\extend_observations.py --year <YEAR> --source <verification_root>\observations
   ```

2. Copy the cycle file to the new year and change `forecast_year`, `reference_years` (end + 1), `verification_root`
   and `output_root` (template: `config\cycles\may_2027.json`). Add the new model year to `archive_years` of the
   project config.
3. Download only the new initialization (`--year-start <YEAR> --year-end <YEAR>`), then run steps 3–14 of section 2 for
   that year (`prepare_seasonal.py --years <YEAR>`, `regrid_seasonal.py --years <YEAR>`, monthly `--years <YEAR>` as in
   `docs/37`). Method changes require `scripts\decision_gates.py` first.

---

## 6. Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `… is not available at the official archive` / `Requested verification is not ready` | That CHIRPS month is not published (e.g. Feb 2026) | Verify the available months (`--verification-targets …`) or wait; never substitute preliminary data |
| `Observation availability is unknown` | Network/server problem | Retry later; unknown is not treated as missing |
| `The existing Step 30 freeze is required` | No freeze for this cycle | Run step 10 (`--freeze-only`) |
| `Frozen forecast has changed` / `Original final forecast differs from frozen snapshot` | Forecast files were regenerated after the freeze | Restore the frozen files (`<verification_root>\frozen_forecasts`); do not refit a frozen cycle |
| Outputs under the wrong `initMM_` tag or year | `CALIBRATION_CYCLE` not set in this window | Set it (section 1) |
| `Historical overlap differs` | Official file differs from the archive in the overlap month | Investigate; do not loosen the tolerance |
| `UnicodeEncodeError … '\u2192'` (download) | Windows console | `set PYTHONIOENCODING=utf-8` |
| Page unchanged after push | Deployment running or browser cache | Wait for the green tick, then Ctrl + F5 |
