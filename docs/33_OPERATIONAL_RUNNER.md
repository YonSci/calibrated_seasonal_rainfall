# Step 33 — Reusable operational runner

## 1. What this update implements

The runner coordinates the existing May-initialized 2026 forecast and verification
workflow. It adds consistent entry points, input checks, stage logs, output
inventories, SHA-256 provenance, backup-on-regeneration, and content-checked resume.

The main new product is an offline gallery with **All Ethiopia** and **JJAS R1+R2
rainfall domain** views for each forecast target and each verified target.

The runner starts from the selected final forecasts. It does not retrain them,
select a new calibration method, repeat historical experiments or regrid data.
Preparation in this document means preparation of **verification observations**.

The engine in `operational_core.py` is reusable. The adapter in `run_operational.py`
explicitly supports May 2026 and a 1993–2025 reference. Several established science
scripts are fixed to those dates; this update does not pretend that changing one
configuration value is sufficient to generate a different forecast cycle.

## 2. Install into the existing project

Extract the ZIP into a temporary folder, then merge its `scripts`, `config`,
`docs` and `tests` folders into:

```text
D:\calibrated_seasonal_rainfall
```

Also copy `requirements-operational.txt` into the project root. The `examples`
folder is optional; it contains the actual JJAS forecast preview supplied here.

There are three new scripts:

| File | Responsibility |
|---|---|
| `scripts/run_operational.py` | Supported workflow adapter, preflight, availability and stage ordering |
| `scripts/operational_core.py` | Run lock, logging, fingerprints, resume and subprocess execution |
| `scripts/presentation_layers.py` | Fixed-domain masks, summaries, smooth maps and offline gallery |

There is one new configuration file: `config/operational.json`.
Keep your current `config/project.json`, including the existing 0.2 mm daily
increment tolerance. This update does not replace it.

Keep the existing scripts from Steps 29–32. The new runner uses:

| Earlier step | Required files |
|---|---|
| 29 | `delivery_map_base.py`, `delivery_output_runs.py` |
| 30 | `prepare_verification_2026.py`, `verify_frozen_2026.py`, `verify2026_common.py`, `verify2026_math.py`, `verify2026_outputs.py` |
| 31 | `followup_common.py`, `verify_2026_regimes.py`, `evidence/followup_regime_comparison_and_masks.nc` |
| 32 | `build_verification_report.py`, `verification_report_core.py` |

The expected boundary remains `data/boundaries/ethiopia/eth_admin0.shp`, with its
`.shx`, `.dbf` and `.prj` companions. The earlier shapefile is reused. It is a country
outline, not an independent physical land–ocean/lake mask.

## 3. Python environment

Use your existing `.venv`:

```cmd
cd /d D:\calibrated_seasonal_rainfall
.venv\Scripts\activate
python --version
```

The runtime dependencies are already used by the previous stages: NumPy, pandas,
xarray, netCDF4, SciPy, Matplotlib, pyshp and pyproj. No new environment is required.
If an import is missing, install the listed packages in the activated environment:

```cmd
python -m pip install -r requirements-operational.txt
```

This is an additive dependency list, not a complete replacement for the original
project requirements. The runner records actual package versions in each run.

## 4. Check the configuration

All relative paths resolve against the project root, **not** the current terminal
folder. Forward slashes in JSON work on Windows and avoid JSON backslash escaping.

| Configuration key | Default and purpose |
|---|---|
| `project_config` | `config/project.json`; used to find the historical CHIRPS archive during verification preparation |
| `forecast_root` | `outputs/final_shared_blend` |
| `verification_root` | `outputs/verification_2026`; existing freeze, observations and score fields |
| `processed_root` | `data/processed`; historical common-grid references and raw 2026 ensembles |
| `download_cache` | `data/raw/chirps/verification_p25`; existing official CHIRPS cache and receipts |
| `regime_mask` | `evidence/followup_regime_comparison_and_masks.nc` |
| `boundary` | `data/boundaries/ethiopia/eth_admin0.shp` |
| `historical_review` | `outputs/verification_followup/historical/historical_blend_review.json`; optional report section |
| `output_root` | `outputs/operational_2026`; new gallery, views, reports and run state |

The runner requires the corrected GitHub refinement and its 1993–2025 baseline.
It checks the exact coordinates and country mask against every requested forecast.
It does not interpolate a mismatched mask into place.

## 5. Run the new presentation products now

First inspect the planned run:

```cmd
python scripts\run_operational.py --plan
```

The default is the offline `products` workflow. The plan validates inputs and
prints the stages; it does not create project outputs or download observations.

Then run:

```cmd
python scripts\run_operational.py --workflow products
start "" "outputs\operational_2026\index.html"
```

The gallery has selectors for target, product, and view. Forecast outputs contain:

- Leading tercile probability.
- Corrected ensemble-mean rainfall in mm.
- Mean rainfall anomaly in mm.
- Mean rainfall anomaly in percent, with a low-climatology display exclusion.

Verification outputs contain a six-panel figure: observed anomaly, forecast mean
anomaly, forecast minus observation, observed tercile, shared-minus-climatology RPS,
and corrected ensemble CRPS. Each has national and R1+R2 views.

The `products` workflow makes no internet requests. It discovers complete existing
verification outputs, reproduces the national scores, validates their provenance,
and builds the requested presentation layers. A partially written score result
causes an error instead of being treated as a valid verification product.

**With your current stage of work:** expect all five forecast targets and the
existing June–August verification targets. September and JJAS verification appear
when complete valid results exist on your computer.

## 6. Prepare and verify available observations automatically

Use this workflow when you want the runner to check availability and perform the
established observation preparation and scoring steps:

```cmd
python scripts\run_operational.py --workflow all --plan
python scripts\run_operational.py --workflow all
```

The sequence is:

1. Validate the configuration, dependencies, forecast files, fixed domain and
   existing frozen-forecast manifest.
2. Check the official CHIRPS v2 daily p25 monthly URLs for the requested months.
   HTTP 404 means unavailable. Connection errors and other uncertain responses
   stop the verification workflow rather than being treated as missing data.
3. For available months, call `prepare_verification_2026.py`. It checks the
   historical 2025 daily overlap, file provenance, units, grids and complete daily
   calendars before creating totals. Existing derived observations get backups.
4. Create JJAS only when all four complete calendar months are requested and
   prepared together. JJAS has 122 days. A three-month subtotal is never labeled
   JJAS.
5. Call `verify_frozen_2026.py` for each ready target. This uses the frozen forecast
   and existing 33-year reference, not a new fit.
6. Call `verify_2026_regimes.py` and `build_verification_report.py` for the ready
   combination of targets.
7. Build both presentation views, the offline gallery and run records.

The first `all` run may regenerate existing verification stages because the new
runner has no previous completion records. Those outputs are backed up. Subsequent
runs with matching fingerprints reuse them. When September becomes available,
the four-month preparation stage replaces the earlier three-month stage and the
dependent verification/report stages rebuild consistently.

The cache remains governed by the earlier download receipts and hashes. The runner
does not silently replace cached official data with revised downloads. Availability
checks alone do not test for every possible provider revision.

`--workflow verify` runs observation preparation, scoring, reports and verification
presentation only. Its gallery includes verification products from that run. Use
`all` to get the combined forecast-and-verification gallery.

## 7. Resume, regenerate and select targets

Resume is automatic:

```cmd
python scripts\run_operational.py --workflow products
```

The equivalent explicit form is:

```cmd
python scripts\run_operational.py --workflow products --resume
```

A stage is reused only when all of the following match its successful record:

- Configuration, Python version and recorded dependency versions.
- Relevant script bytes and declared input bytes.
- Complete contents of every declared output file or directory.

This uses SHA-256, not just file existence or modification time. Hashing large
archives can take time. If an output is missing or changed, the stage rebuilds.
A failed stage is never marked complete, and later stages are not run.

To intentionally regenerate derived views despite matching fingerprints:

```cmd
python scripts\run_operational.py --workflow products --force
```

Previous per-target product directories are retained with `_backup_...` suffixes.
Input data and frozen forecasts are not outputs of these stages. `--force` is not
permission to retrain or replace them.

For one target:

```cmd
python scripts\run_operational.py --workflow products --targets Aug
```

The gallery then shows the selected scope. Rerun the default command to restore
the five-target gallery; per-target results for other targets are not deleted.

To require September and the complete season rather than accept pending targets:

```cmd
python scripts\run_operational.py --workflow all --verification-targets Jun Jul Aug Sep JJAS
```

This stops if any required month is unavailable. The default `auto` uses what is
ready and records the rest as pending. A successful run with pending observations
exits with code 0 and records `completed_with_pending_verification`; it does not
claim a complete seasonal assessment. Failures exit with code 2, interruption 130.

## 8. Output locations

| Path beneath `outputs/operational_2026` | Contents |
|---|---|
| `index.html` | Offline target/product/domain gallery |
| `presentation_summary.json` | Combined summaries, definitions, coverage and pending targets |
| `presentation/forecast/TARGET/all_ethiopia/` | National forecast PNG/PDF maps |
| `presentation/forecast/TARGET/jjas_r12_rainfall_domain/` | Focused forecast PNG/PDF maps |
| `presentation/verification/TARGET/all_ethiopia/` | National verification maps |
| `presentation/verification/TARGET/jjas_r12_rainfall_domain/` | Focused verification maps |
| `presentation/forecast/TARGET/presentation_fields.nc` | Original-grid derived forecast fields plus a separate domain mask |
| `presentation/verification/TARGET/presentation_fields.nc` | Unchanged native verification variables plus the separate domain mask |
| `regimes/TARGET_COMBINATION/` | Existing-method regime summaries from the `all`/`verify` workflows |
| `reports/TARGET_COMBINATION/` | Consolidated verification report from the `all`/`verify` workflows |
| `state/latest_run.json` | Latest run status and stages |
| `state/runs/RUN_ID/` | Archived run record, preflight, environment and stage logs |
| `state/stages/` | Successful stage fingerprints and output hashes used for resume |

Each target presentation folder also contains `presentation_summary.json`.
Keep the gallery and its `presentation` folder together when copying it elsewhere.
It has no external JavaScript, font, CDN or server dependency.

## 9. Troubleshooting

**Missing helper script:** merge the relevant earlier update; the table in section
2 identifies its source. This package is an additive update, not the entire project.

**Missing mask:** point `regime_mask` at the existing Step 31 copy, or the identical
corrected reconciliation mask. Do not substitute the older peak-only classifier.

**Forecast changed:** investigate the difference against the freeze manifest.
Do not delete the manifest to make the error disappear. The verification belongs
to the frozen forecast version.

**Grid/mask mismatch:** recover the matching native-grid inputs. The presentation
stage deliberately does not perform another regridding operation.

**Unavailable observation:** use the offline `products` workflow meanwhile. The
`all` workflow with default `auto` processes ready months. No scheduler is installed;
run the command again when you want a new availability check.

**Lock after a crash:** check that no runner or child Python process is still
working. Only after confirming it has stopped, remove this lock:

```cmd
del outputs\operational_2026\state\RUNNING.lock
```

Then rerun the same command. Preserve `state/stages` so completed stages can resume.
The lock coordinates this runner only; do not run older preparation/scoring scripts
concurrently against the same outputs.

**Historical review missing:** the consolidated report explicitly marks that
section unavailable. Existing observation verification is still assessed; no
historical scores are invented.

## 10. Optional validation tests

```cmd
python -m unittest discover -s tests -p test_operational_runner.py -v
```

Tests use temporary synthetic projects, check resume/tamper/failure behavior,
preserve native data, and execute the real cached-data preparation/scoring/report
chain. No current project observations or forecasts are changed by these tests.

## 11. Future forecast cycles

For another year, initialization or target season, first update the scientific
adapters: source paths and dates, hindcast/reference availability, fitting periods,
model/system/member checks, masks and verification calendar. Fit and evaluate the
new forecast with the appropriate matching hindcasts, then freeze that version
before its verification workflow. The stage engine can be reused, but the May-2026
coefficients and fixed assumptions must not be applied automatically to other cycles.
