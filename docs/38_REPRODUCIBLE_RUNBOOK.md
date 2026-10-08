# 38 — Reproducible runbook, issue log and automation blueprint

Written 2026-10-05 for anyone reproducing the system or building an automation tool around it.
It records every stage as it is actually run, with exact commands, inputs, outputs and checks.
It also lists every issue met during development, with its cause, its fix and how an automated check can catch it.

Scientific background: docs 04 and 11 (methods), docs 36 (status and decisions), docs 37 (new cycles).

---

## 1. Environment

| Item | Value | Notes |
| --- | --- | --- |
| OS / shell | Windows 11, CMD (scripts use `\` paths in examples) | Git Bash also works. CI runs `windows-latest` |
| Python | 3.11 x64, project `.venv` | `python -m venv .venv` then `pip install -r requirements.txt` |
| Pinned packages | numpy 1.26.4, pandas 2.2.3, xarray 2024.11.0, scipy 1.14.1, netCDF4 1.7.2, dask 2024.11.2, matplotlib 3.9.2, cdsapi 0.7.7, pyshp 3.1.6, pyproj 3.7.2 | `shapely` only for rebuilding the Ethiopia mask |
| CDS access | `%USERPROFILE%\.cdsapirc` (url + key) | Never commit it. Automation: inject as a secret |
| Console encoding | `set PYTHONIOENCODING=utf-8` before the downloader | Prevents `UnicodeEncodeError` on `→` (issue I-03) |
| GitHub | `gh` CLI 2.x, `gh auth login --web` in an interactive terminal; `gh auth setup-git` | Token in the Windows keyring |
| Git | `.gitattributes` has `* -text` | Scripts are SHA-256 fingerprinted; line endings must never change (I-12) |

Folders that are not in git and must exist locally: `data/raw/`, `data/interim/`, `data/processed/`, `outputs/`, `.venv/`.

---

## 2. Configuration model

Three layers. All paths are relative to the project root.

1. **Project config**: the season and its data.
   - `config/project.json` is May-initialized JJAS.
   - `config/ondj/project.json` is September-initialized ONDJ.
   - Keys: `ecmwf_directory`, `ecmwf_pattern`, `chirps_file`, `initialization_month`, `season{name,start,end}`, `archive_years` (model years), `observation_years` (complete CHIRPS seasons), `negative_increment_tolerance_mm` (0.2).
2. **Monthly configs**: created by `run_monthly.py` next to their project config.
   - JJAS: `config/monthly_Jun.json`, …
   - ONDJ: `config/ondj/monthly_Oct.json`, …
3. **Cycle file**: one forecast issue.
   - Files: `config/operational.json` (default, May 2026), `config/cycles/may_2027.json`, `config/cycles/sep_2026_ondj.json`, `config/cycles/backtest_may_2025.json`.
   - Keys: `forecast_year`, `initialization_month`, `reference_years`, `targets`, `project_config`, `expected_members`, `development_years`, `overlap_year`, `regime_mask_years`, output roots, `display`.
   - Selected with `set CALIBRATION_CYCLE=<file>`. `run_operational.py --config <file>` sets it for its stages.

Season calendar rule (`common.season_window`):
- The period starts in the initialization year if its start month is on or after the initialization month, otherwise in the next year.
- It ends in the following year if its end month precedes its start month.

So JJAS from May 2026 is 2026-06-01 to 2026-09-30, and ONDJ from September 2026 is 2026-10-01 to 2027-01-31. January from September 2026 is in 2027.

Folder tag for every derived product: `init<MM>_<target>`, for example `init05_JJAS`, `init09_Jan`.

---

## 3. Pipeline stages (May-initialized JJAS; the reference implementation)

Run from the project root after `call .venv\Scripts\activate.bat`. Each stage refuses to overwrite its outputs unless `--regenerate` is given. A regenerated output keeps the previous version as `<name>_backup_<UTC>_<id>`.

| # | Stage | Command | Inputs | Outputs | Built-in checks | Typical time |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Download ECMWF | `set PYTHONIOENCODING=utf-8` then `python scripts\download_seasonal_forecasts_daily_c3s.py --models ecmwf --system ecmwf=51 --variables total_precipitation --year-start 1993 --year-end 2026 --months 5 --init-day 1 --leadtime-days 183 --north 15 --west 33 --south 3 --east 48 --outdir data\raw\ecmwf\et_may_init` | CDS | `ecmwf_YYYY05_d01.nc` (1° grid, 25 / 51 members) | Skips existing files | 1–3 min per year (CDS queue) |
| 2 | Inventory | `python scripts\inspect_inputs.py --config config\project.json` | raw ECMWF, CHIRPS archive | `outputs/inspection/*` | Init date, lead coverage, member rule, sample increments, CHIRPS dates | < 1 min |
| 3 | Prepare seasonal totals | `python scripts\prepare_seasonal.py --config config\project.json --all-years` | raw files | `data/interim/init05_JJAS/*_native.nc`, `outputs/qc/preparation_init05_JJAS.json` | Units, +24 h endpoints, daily steps, negative increments ≤ 0.2 mm, telescoping sum, 122 complete days, member counts | about 15 s |
| 4 | Regrid | `python scripts\regrid_seasonal.py --config config\project.json` | interim | `data/processed/init05_JJAS/*_common.nc` | Nested 1°→0.25° blocks, matching outer edges, area conservation | < 1 min |
| 5 | Monthly targets | `python scripts\run_monthly.py --config config\project.json --stage prepare` | raw files | `config/monthly_*.json`, `data/processed/init05_<Mon>/` | Same as 3–4, plus Σ months = season (0.001 mm + 1e-6×total) | about 2 min |
| 6 | Method evaluation (fixed design) | `python scripts\local_blend.py --config <cfg> --mode training` and `--mode operational` (or `run_monthly.py --stage training/operational`) | processed | `outputs/local_calibration/<tag>/{training,operational}/` | Nested leave-one-year-out; outer year excluded from all inner fits | 30–60 s per target |
| 7 | Decision gates (when changing method) | `python scripts\decision_gates.py` | processed | `outputs/decision_gates/decision_gates.json` | Holm-adjusted whole-year permutation test on 1993–2016 plus no harm on 2017–2025 | about 3 min |
| 8 | Final fit and forecast | `python scripts\final_shared_blend.py --config config\project.json --region-mask data\masks\ethiopia_common.nc` | processed | `outputs/final_shared_blend/init05_<T>/2026/forecast_2026.nc` and parameters | Probabilities finite, in [0,1], sum to 1; reports clipped fraction | about 13 s |
| 9 | Delivery package | `python scripts\finalize_forecast_delivery.py --check-only`, then without `--check-only` | forecasts, evidence | `outputs/forecast_delivery/init05_2026/` (bulletin, maps, `manifest.json`) | SHA-256 manifest | < 1 min |
| 10 | Freeze | `python scripts\prepare_verification_2026.py --months Jun --input-root outputs\final_shared_blend --root outputs\verification_2026` | forecasts | `outputs/verification_2026/frozen_forecasts/freeze_manifest.json` | Never replaces an existing freeze | seconds |
| 11 | Products and gallery | `python scripts\run_operational.py --workflow products` | frozen forecasts, masks | `outputs/operational_2026/` (views, `index.html`) | Resumable stages with input/output fingerprints | about 40 s |
| 12 | Verification | `python scripts\run_operational.py --workflow all` (checks CHIRPS availability first) | official CHIRPS p25 monthly files | `outputs/verification_2026/{observations,results}`, reports | Overlap with archive ≤ 1e-4 mm/day; complete days; frozen hashes unchanged | 1–5 min plus downloads |
| 13 | Results site | `python scripts\build_site.py` | outputs JSON and gallery | `site/` | Reads numbers only from result files | seconds |
| 14 | Publish | `git add -A && git commit && git push` | `site/`, code, docs | GitHub Pages (Actions deploy), CI tests | `pages.yml`, `tests.yml` | about 3 min |
| 15 | Housekeeping | `python scripts\prune_backups.py` (preview), then `--apply` | outputs | – | Keeps newest backup per output; never touches `_building_` | seconds |

Next cycle: `python scripts\extend_observations.py --year 2026 --source outputs\verification_2026\observations` adds verified CHIRPS to the training archive. See docs/37.

### Exact numerical contracts (an automation tool should assert these)

- ECMWF `tp` is in metres and accumulated since initialization. The first endpoint is init + 24 h, then every 24 h. Daily value = `1000·(C[t]−C[t−1])` mm, labelled at the start of the interval.
- Negative daily increments down to −0.2 mm are GRIB packing rounding and are clipped to 0. The seasonal sum must equal the endpoint difference before clipping (rtol 1e-10).
- Members: 25 for 1993–2016, 51 from 2017 (`expected_members` in the cycle file).
- CHIRPS sea cells (223 on the 48×60 grid) are permanently NaN. No partial seasons are allowed.
- Regridding: each 1° cell maps to an exact 4×4 block of 0.25° cells. Outer edges 3–15°N, 33–48°E.

---

## 4. Running another season (September-initialized ONDJ, 2026)

The same scripts, with a different project config and cycle file. These are the steps actually used:

```bat
:: 1. Download (153 daily leads = 1 Sep to 1 Feb endpoints)
set PYTHONIOENCODING=utf-8
python scripts\download_seasonal_forecasts_daily_c3s.py --models ecmwf --system ecmwf=51 --variables total_precipitation --year-start 1993 --year-end 2026 --months 9 --init-day 1 --leadtime-days 153 --north 15 --west 33 --south 3 --east 48 --outdir data\raw\ecmwf\et_sep_init

:: 2. Select the cycle for every following command
set CALIBRATION_CYCLE=config\cycles\sep_2026_ondj.json

:: 3. Inventory, seasonal and monthly preparation (Oct, Nov, Dec, Jan)
python scripts\inspect_inputs.py --config config\ondj\project.json
python scripts\prepare_seasonal.py --config config\ondj\project.json --all-years
python scripts\regrid_seasonal.py --config config\ondj\project.json
python scripts\run_monthly.py --config config\ondj\project.json --stage prepare

:: 4. Historical skill (fixed design: nested 1993-2016, fits on 1993-2016 scored 2017-2024)
python scripts\local_blend.py --config config\ondj\project.json --mode training --region-mask data\masks\ethiopia_common.nc
python scripts\local_blend.py --config config\ondj\project.json --mode operational --region-mask data\masks\ethiopia_common.nc
python scripts\run_monthly.py --config config\ondj\project.json --stage training
python scripts\run_monthly.py --config config\ondj\project.json --stage operational

:: 5. Season rainfall domain (same rule as JJAS R1+R2), forecast, products, site
python scripts\build_season_domain.py --config config\ondj\project.json --method regime
python scripts\final_shared_blend.py --config config\ondj\project.json --region-mask data\masks\ethiopia_common.nc
python scripts\build_season_products.py
python scripts\build_site.py
```

ONDJ-specific facts:
- **Reference seasons:** 1993/94–2024/25 (32). The CHIRPS archive ends in December 2025, so the 2025/26 season lacks January 2026; `observation_years` is `[1993, 2024]`.
- **Forecast:** ONDJ 2026/27 from the 1 September 2026 initialization.
- **Verification:** possible after CHIRPS January 2027 is published. Note that verification scripts still assume the season lies in one calendar year (see section 6).
- **Rainfall domain:** `data/masks/init09_ONDJ_rainfall_domain.nc` (ONDJ ≥ 120 mm and ≥ 20 % of annual rainfall, climatology 1993–2024). That is 487 cells, 33 % of Ethiopia, in the south and south-east.
- **Downloads** went much slower than the May run (CDS queue). Three year batches ran in parallel.

Results of this run are recorded in section 7 once complete.

---

## 5. Issue log

Each entry gives the symptom, the cause, the fix and how to detect or prevent it automatically. "Doc" points to where it is discussed in more detail.

### Data and preprocessing

| ID | Symptom | Cause | Fix | Automated guard | Doc |
| --- | --- | --- | --- | --- | --- |
| I-01 | `inspect_inputs` reported "negative accumulation increments" for 1996, 2003, 2020 and 2023 | GRIB packing quantizes `tp` to 2⁻¹³ m (0.122 mm), so dry days can show drops of up to 0.147 mm. Re-downloading gave bit-identical files. The tolerance was 0.001 mm | Tolerance raised to 0.2 mm. Small negatives are clipped after the telescoping-sum check | Assert min increment ≥ −0.2 mm per file; record the maximum clipping (`clipping_adjustment_max_mm`) | 03, 36 §1.1 |
| I-02 | Which years "failed" looked random | The inspector checks one series (member 0, centre pixel); all 34 years have rounding drops | Preparation checks every member, cell and day | Whole-field check in preparation; inventory is advisory | 36 |
| I-03 | Downloader crashed with `UnicodeEncodeError: 'charmap' … '→'` | Windows console code page cp1252 cannot print `→` | `set PYTHONIOENCODING=utf-8` | Always set the variable in automation | 37 |
| I-04 | `ModuleNotFoundError: cdsapi` | Not in the venv or requirements | Installed and pinned `cdsapi==0.7.7` | `pip check` and import test at startup | 36 |
| I-05 | Preparation QC JSON contained only the last run's years | Each invocation overwrites `preparation_<tag>.json` | Added `--all-years`; archive a dated copy | Run all years in one invocation | 36 |
| I-06 | Seasons crossing the year boundary were rejected ("same-calendar-year seasons only") | Calendar logic assumed `year-start` to `year-end` | `common.season_window()` used by preparation, regridding and loading | Unit tests for JJAS, ONDJ and January windows (`tests/test_cycle.py`) | 38 §2 |
| I-07 | NaN pattern of verification CHIRPS looked different from the archive | A false alarm: arrays of shape (1,48,60) and (48,60) were compared | Compare after squeezing the `year` dimension | Shape assertion before comparisons | – |
| I-08 | 22–24 % of corrected June–August member values were clipped at 0 | Additive mean–variance correction in arid cells with the variance ratio at its 0.5 floor | Diagnosed (dry cells < 50 mm). Square-root-space correction passes the gate for amounts; scheduled for the next cycle | Report clipping by climate zone in `final_report.json` | 36 Phase 4 |

### Method decisions

| ID | Symptom | Cause | Fix | Automated guard | Doc |
| --- | --- | --- | --- | --- | --- |
| I-09 | Ethiopia-only λ and the square-root correction looked better in early experiments | Proposed after looking at 2017–2025, years already used during method selection | Pre-registered significance gate: Holm-adjusted permutation test on nested 1993–2016 plus no harm on 2017–2025. Both withdrawn for probabilities | Every method change must pass `decision_gates.py` before adoption | 36 Phase 5 |
| I-10 | "Remove the August blend" looked better on 2017–2025 | The same selection effect; the blend is better on 1993–2016 | Keep the shared blend | Same gate | 36 Phase 6 |
| I-11 | The Dirichlet recalibration collapsed forecasts towards ⅓ | About 6 % zero-member categories → log(1e-12) inputs | Not used. Smoothing the counts first avoids it | If reintroduced, smooth counts before taking logs | 36 §2 |

### Software and repository

| ID | Symptom | Cause | Fix | Automated guard | Doc |
| --- | --- | --- | --- | --- | --- |
| I-12 | Whole-file diffs after edits; runner rebuilt everything | Python text-mode writes on Windows produced CRLF; git `autocrlf=true` would also rewrite files | Restored LF; `.gitattributes` `* -text`; write with `newline=''` | CI check that no tracked text file contains `\r` | 38 |
| I-13 | Root README replaced by a patch README | A patch package was copied over the project root | New README; patch files moved to `archive/` | Never unpack patches into the root; use git | 36 Phase 1 |
| I-14 | The Windows publication fix only partly applied | Three byte-identical copies of the output helper; only one was patched | Copies became aliases of `verify2026_outputs.py` | Duplicate-module check (identical hashes) in CI | 36 Phase 1, 11 |
| I-15 | Map and contour code existed in three copies | Copy-paste between review, delivery and plot steps | Aliases of `plot_forecast_products`, `plot_smooth_forecasts` and `delivery_render` | Same as I-14 | 36 Phase 11 |
| I-16 | 55 `_backup_` folders (87 MB) | `--regenerate` keeps every previous version | `prune_backups.py` (preview / `--apply`) | Prune after successful runs, keeping the newest | 36 Phase 11 |
| I-17 | Bulk year rewrite produced `calendar.monthrange({YEAR}, m)` (a set) and wrong script names (`prepare_verification_{YEAR}.py`) | Token-level rewrite of strings also touched f-string expressions and file names | Fixed by hand. Regression checks then confirmed identical 2026 outputs | After any refactor: refit into a scratch folder and compare with frozen files; compare presentation PNGs byte for byte | 38 §6 |
| I-18 | A test passed alone but failed after another test | `configuration()` set `CALIBRATION_CYCLE` in the process and leaked into later subprocesses | The variable is set only in `run_operational.main()` | No global state changes in library functions | – |
| I-19 | A non-default cycle could still use 2026 constants | `cycle.py` reads the cycle at import; the runner imported it before setting the variable | The variable is set before any import of `cycle.py` | Assert `cycle.CYCLE.path` equals the requested file in each stage log | – |
| I-20 | Runner tests failed with `No module named …` | Tests copy the runner's script list into a temporary project; new dependencies (`cycle.py`, `common.py`, `run_monthly.py`) were missing | Added to `PRODUCT_SCRIPTS` (also makes fingerprints follow them) | Keep the list equal to the import closure of the runner | – |
| I-21 | CI tests failed on GitHub but passed locally | The runner's temp folder is reached via an 8.3 short name (`RUNNER~1`); the code compares resolved paths | Tests use `Path(tmp).resolve()` | Always resolve temp paths in tests | 36 Phase 13 |
| I-22 | Clean clone failed one test | An 11 MB evidence JSON was git-ignored | Tracked (stored once; about 1.6 MB compressed) | CI runs from a clean checkout | 36 Phase 13 |
| I-23 | A test needed `completed_report/` that was never installed | It depended on a delivered folder | Falls back to local `outputs/verification_report_2026`, otherwise skips | Tests must not depend on hand-installed folders | 36 Phase 1 |
| I-24 | Running one target overwrote a combined result (`regional_skill.json` with JJAS only) | Experiment scripts write one summary per invocation | Rerun all targets; noted | Write per-target files or merge instead of overwrite | – |

### Tooling and publication

| ID | Symptom | Cause | Fix | Automated guard | Doc |
| --- | --- | --- | --- | --- | --- |
| I-25 | `gh` not found | Not installed | `winget install GitHub.cli` | Check tool versions at startup | 38 §1 |
| I-26 | `! gh auth login` in the Claude prompt did nothing | The web login is interactive (code plus Enter) | Run it in a normal terminal | In CI use `GITHUB_TOKEN`; locally a one-time login | – |
| I-27 | First Pages deploy raced Pages enablement | The workflow ran in the same minute Pages was enabled | It succeeded; otherwise rerun the workflow | Enable Pages (`gh api -X POST repos/<r>/pages -f build_type=workflow`) before the first push | – |
| I-28 | Headless screenshots looked clipped or blank | Edge headless has a minimum window width (~500 px), and `#fragment` with a virtual time budget can render blank | Check at ≥ 520 px; verify behaviour with `--dump-dom` | Validate the site with DOM checks, not only images | – |
| I-29 | A long inline Python script failed in Git Bash ("unexpected EOF") | Shell parsing of quotes inside the here-document | Write patch scripts to files and run them | Never inline long scripts in shell commands | – |
| I-31 | The ONDJ fit overwrote the JJAS combined report `final_reports_2026.json` | File name keyed on year only | JJAS file rebuilt from per-target `final_report.json` (no refit); other cycles write `final_reports_<tag>_<year>.json` | Key every summary file on the cycle tag | – |
| I-32 | ONDJ inventory overwrote the JJAS inventory in `outputs/inspection/` | Fixed output names | Non-JJAS seasons write to `outputs/inspection/<tag>/`; JJAS inventory regenerated | Same | – |
| I-33 | ONDJ map rendering stopped: "Expected May-initialized … file"; map footer said "May-initialized" | Hidden May checks and texts in `plot_forecast_products` and the presentation footer | Use the cycle's initialization month | Grep for month and season literals when adding a cycle; render a backtest cycle | – |
| I-30 | Commits are public with the author email | `git config user.email` is a personal address | Owner chose to keep the Gmail address | Decide before the first push (noreply option) | 36 Phase 13 |

---

## 6. Known limitations (to handle before full automation)

1. **[Resolved 2026-10-08, docs/40]** ~~Verification of cross-year seasons.~~ The verification chain and runner now follow the cycle season (FMAM, ONDJ with January in the next year); tested on an ONDJ 2024/25 backtest and FMAM Mar–May 2026. Original note: `prepare_verification_2026.py` and `verify_frozen_2026.py` build dates as `YEAR-<start>` to `YEAR-<end>`. ONDJ verification needs `season_window()` there too, plus downloads of January in `YEAR+1`. This is required by February 2027.
2. **[Resolved 2026-10-08]** ~~Operational runner and gallery~~ still use the JJAS R1+R2 view and the May verification chain. For other seasons use `build_season_products.py` until the runner adopts season domains.
3. **Script names carry `_2026`** (`prepare_verification_2026.py`, …), although they follow the cycle. Rename with compatibility aliases when building the automation.
4. **Observation extension** (`extend_observations.py`) promotes verified totals per year. ONDJ needs the cross-year version (October–December from year Y, January from Y+1).
5. **Method changes** must pass `decision_gates.py` first. The research scripts (`compare_calibration`, `evaluate_candidates`, …) keep the fixed 1993–2016 / 2017–2025 study design on purpose.
6. **Regression safety net:** after any code change, (a) refit into a scratch `--output-root` and compare with the frozen forecasts; (b) rebuild presentation into a scratch `output_root` and compare PNGs. Both were done for every refactor in this project (exact match).

---

## 7. Run log of the September 2026 ONDJ cycle (completed 2026-10-05)

| Step | Result |
| --- | --- |
| Download | 34/34 files, three parallel batches, about 1.5 h of CDS queue. Every file: correct members (25 / 51), 153 daily endpoints from 2 Sep to 1 Feb of the next year, minimum increment ≥ −0.2 mm |
| Inventory | All 34 years `ok` (outputs in `outputs/inspection/init09_ONDJ/`) |
| Seasonal preparation | 34 years, 123 days each (Oct 31 + Nov 30 + Dec 31 + Jan 31), no missing values, clipping ≤ 0.18 mm; CHIRPS for seasons 1993/94–2024/25 |
| Regridding | 66 files (34 ECMWF + 32 CHIRPS), conservation error ≤ 1e-14 |
| Monthly targets | Oct, Nov, Dec, Jan prepared; 66/66 month-sum checks passed (max 0.0004 mm); January dated in the following year (e.g. 2027-01-01 to 2027-01-31) |
| Rainfall domain | First built with the ≥ 120 mm / 20 % rule (487 cells). **Replaced 2026-10-08** by the walkthrough ONDJ R3 (Deyr) domain, `build_season_domain.py --method regime` (575 cells, 39 % of Ethiopia) |
| Forecast | 51 members; λ: Oct 0.44, Nov 0.23, Dec 0.64, Jan 0.82, ONDJ 0.28. Clipped member values: Dec 29 %, Jan 28 % (dry months, see I-08), ONDJ 0.6 % |
| Products | 5 targets × 2 views (`outputs/operational_2026_ondj/`), listed in `entries.json`; on the site as the group "September initialization · ONDJ 2026/27" |

Historical skill (RPSS vs climatology, Ethiopia cells):

| Target | Nested 1993–2016 | Fits on 1993–2016, scored 2017–2024 |
| --- | --- | --- |
| ONDJ | +0.020 (14/24 years better) | +0.063 (4/8) |
| Oct | −0.001 | +0.024 |
| Nov | +0.046 (15/24) | +0.005 |
| Dec | +0.011 | +0.027 |
| Jan | +0.002 | +0.004 |

None is significant at p < 0.05 per target. November and the season carry the clearest signal.

ONDJ 2026/27 forecast (area-mean probabilities, below / near / above):
- All Ethiopia: 28 / 27 / 45 %, +26.5 mm.
- ONDJ rainfall domain: **20 / 24 / 56 %**, +64.5 mm.
- November in the domain: 20 / 22 / 58 %.

The forecast leans wetter than normal over the south and south-east short-rains areas. December and January are near climatology.

Regression after all ONDJ changes: JJAS 2026 refit identical to the frozen files; the 46 JJAS presentation PNGs byte-identical; 84 tests pass.

---

## 8. Automation blueprint

A tool that runs these cycles unattended should treat the stages above as a directed graph. Each stage is idempotent (it refuses to overwrite and keeps backups) and fingerprinted (re-run only if inputs or code changed). `scripts/operational_core.py` already implements fingerprinted, resumable stages and is the natural engine to extend.

| Trigger | When | Stages |
| --- | --- | --- |
| New initialization available on CDS | About the 5th–13th of the initialization month. Poll CDS for the forecast year | 1 (forecast year only) → 2 → 3–5 for that year → 8 → 9 → 10 → 11 → 13 → 14 |
| New CHIRPS month published | About 3 weeks after month end. Poll the `by_month` listing (HTTP 200 vs 404) | 12 → 13 → 14 |
| Season fully verified | All target months available | `extend_observations.py` → next cycle's reference grows by one year |
| New season or initialization | Manual: write project config and cycle file | Full history: 1–8, `build_season_domain.py --method regime` (add the season to `REGIME_RULES`), products, site |
| Method change proposed | Manual | 7 (gate) → only if adopted: 8 for the next cycle, never for a frozen one |

Guards the tool must enforce:
- Never refit or overwrite a frozen cycle. Check `freeze_manifest.json` hashes before and after each stage.
- Treat "unknown" CHIRPS availability (network error) as unknown, not missing.
- Fail closed on any QC contract in section 3. Never substitute data (for example preliminary CHIRPS).
- Secrets: CDS key and GitHub token come from a secret store, never from the repository.
- After each run: run the tests, prune backups (keep the newest), rebuild the site, commit and push. The deploy workflow publishes.
- Log for every run: cycle file, code commit, input hashes, timings, and the outcome of each stage (the runner already writes `state/` and logs).
