# Step 35 — Windows output-folder publication fix

## What happened

The command passed preflight and reached `forecast_view_Sep`. The reported failure
was the rename from `Sep_building_...` to `Sep`, which publishes a completed output
folder. This error does not itself indicate a rainfall, calibration or mask problem.

Windows can refuse a rename because of open file/directory handles or permissions.
The traceback cannot identify the blocking process. File viewers, previews,
indexing or security scanning are possible causes, not confirmed diagnoses.

Microsoft's rename documentation describes the required delete/parent-directory
permissions and handle-sharing behavior:

- https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexa
- https://devblogs.microsoft.com/oldnewthing/20211022-00/?p=105822

## Install the small patch

Close any image/PDF/NetCDF previews showing files beneath
`outputs/operational_2026/presentation`. Close File Explorer windows in those
output folders, including their preview panes. Keep your project CMD terminal open.
Check that no other runner is writing to the same output folders.

Extract this ZIP and copy its two `scripts` files into:

```text
D:\calibrated_seasonal_rainfall\scripts
```

Replace these existing files:

- `verify2026_outputs.py`
- `operational_core.py`

The included `tests` and `docs` folders can also be merged into the project.
There is no configuration change, package installation, regridding or recalibration.

Then rerun the same command, without `--force`:

```cmd
cd /d D:\calibrated_seasonal_rainfall
.venv\Scripts\activate
python scripts\run_operational.py --workflow products
```

After success:

```cmd
start "" "outputs\operational_2026\index.html"
```

The first run after installing this patch may rebuild June, July and August because
the runner fingerprints script contents. Previous results get backups. That is
expected; do not delete the existing stage records or forecast outputs.

## What the patch changes

1. It retries permission/sharing/busy rename errors up to nine attempts, with
   21.75 seconds of total waiting per rename operation and progress messages.
2. It retains fully rendered staging files when publication is still blocked.
   The old helper deleted staging files even after a publication failure.
3. If an existing output was moved to a backup and publishing the new output
   fails, it attempts to restore the previous output. If restoration is blocked
   too, the error identifies the preserved backup location.
4. For in-process forecast/verification presentation stages, the runner records a
   pending publication with file hashes. After releasing the lock, rerunning the
   same command republishes those completed files without rendering them again,
   provided the settings, inputs and completed files still match.
5. It never changes permissions, deletes an existing completed output, or copies
   partially rendered files into the public output folder. Forecast values,
   calibration, eligibility and domain definitions are unchanged.

The recovery applies to failures occurring **after this patch is installed**.
The original failed September staging folder may already have been removed by
the old helper, so that target may need rendering once again.

Subprocess stages also get the shared helper's retries and retention, but automatic
pending-publication recovery is limited to the runner's in-process presentation
actions. The runner does not guess that an arbitrary `_building_` folder is complete.

## If access is still denied

The error will print the retained completed staging path. Close the affected
viewers/previews and rerun the same command. If a process still holds the folder,
restart VS Code or Windows, then retry. Do not disable security software or delete
the forecast data as a workaround. If the error persists without any open viewer,
check the folder's permissions; retries cannot repair an actual permission denial.

If the process ended normally with `ERROR`, its run lock should already be removed.
Only after a crash, and only after confirming no runner is active, remove a stale
`outputs/operational_2026/state/RUNNING.lock` if it is reported on the next run.

## Optional tests

```cmd
python -m unittest discover -s tests -p test_windows_publication.py -v
```

Tests simulate Windows-style access-denied errors, including transient and
persistent locks, backup rollback, failed rendering, automatic publication recovery
and rejection of altered staging files. They use temporary folders and do not
touch your existing project products.

The tests run on Linux with simulated Windows errors; the specific process or
permission causing the error on your Windows computer has not been inspected.
