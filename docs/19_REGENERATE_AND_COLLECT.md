# Regenerate local results and collect summaries

Extract `regenerate_outputs_update.zip` into `D:\calibrated_seasonal_rainfall`. Replace `scripts\local_blend.py` and `scripts\run_monthly.py`. Keep all previous dependency scripts. This update retains the monthly reconstruction tolerance fix and adds `output_runs.py` and `collect_local_results.py`.

## Regenerate monthly calibration outputs

```bat
python scripts\run_monthly.py --config config\project.json --stage training --region-mask data\masks\ethiopia_common.nc --regenerate
```

To regenerate June only:

```bat
python scripts\run_monthly.py --config config\project.json --stage training --months 6 --region-mask data\masks\ethiopia_common.nc --regenerate
```

For JJAS:

```bat
python scripts\local_blend.py --config config\project.json --mode training --region-mask data\masks\ethiopia_common.nc --regenerate
```

The same flag works with `--stage operational` or `--mode operational`. It does not change the fitting method, fixed regularization, data split, or masks. It reruns fitting and generates all six local-comparison outputs; it is not merely a plot-refresh option.

## What happens to old files

The existing result folder remains in place while calculation and output generation proceed. New files are written to a temporary sibling folder. After successful generation, the previous folder is renamed to a unique `training_backup_<UTC timestamp>_<id>` (or `operational_backup_...`), and the new folder takes the normal name.

If calculation or output generation fails before publication, the previous results remain intact. If the final folder rename fails, the script attempts to restore the original folder name. Ordinary failures clean the temporary folder; a forced process kill or power loss can leave a `_building_...` folder. Do not run two jobs for the same target/mode concurrently. Backups accumulate and use disk space; none are automatically deleted.

Without `--regenerate`, an existing output still triggers protection. This avoids accidental recomputation. Add the flag when an intentional rebuild is wanted.

The flag applies only to calibration outputs. Monthly preparation/regridding is unchanged, and `--stage prepare --regenerate` is rejected. Your monthly preparation and reconstruction check have already succeeded, so they need not be repeated.

## Collect all summaries into one upload

You can do this immediately with existing outputs, without regeneration:

```bat
python scripts\collect_local_results.py --mode training
```

Upload this single file:

```text
outputs\local_calibration\all_local_summaries_training.json
```

It contains the JJAS, June, July, August and September summary reports with explicit target labels and source paths. Missing reports are listed rather than silently omitted. Target labels for older reports are taken from the established folder names. New regenerated summaries also contain their target configuration to support identity checks.

For operational evaluation:

```bat
python scripts\collect_local_results.py --mode operational
```

This creates `all_local_summaries_operational.json` in the same folder. Collection only reads result summaries and writes the combined derived JSON; it does not fit models or modify any individual result. Rerunning collection refreshes the combined file.

The JSON summaries contain the annual scores, aggregate scores, uncertainty ranges and shared weights needed for the first review. Large NetCDF files and all plots are not required for that review; they can be uploaded later if a specific diagnostic is needed.

## Tests

```bat
python -m unittest discover -s tests -p test_output_runs.py -v
```

Tests verify first-run publication, successful replacement with backup, protection without the flag, and preservation of previous files after a simulated output failure.
