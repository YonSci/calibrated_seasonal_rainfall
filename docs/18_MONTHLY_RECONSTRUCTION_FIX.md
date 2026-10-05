# Monthly reconstruction comparison fix

The error occurred after monthly preparation and regridding, in the final comparison against JJAS. The reported CHIRPS 1993 difference is 0.00048828125 mm. This is consistent with floating-point rounding when a float32 daily series is summed once over 122 days versus summed within four months and then added. It does not, by itself, indicate a missing day. The raw daily files have not been inspected here to independently establish their stored dtype.

The original comparison tolerance was too strict for this summation pattern. This patch:

- Converts stored monthly and seasonal totals to float64 before comparison and adds months in float64.
- Allows an absolute difference of `0.001 mm + 0.000001 * abs(JJAS total)` (one part per million plus 0.001 mm).
- Preserves exact coordinate alignment and missingness checks, and rejects infinite values.
- Records all 67 numeric comparisons (34 model years, 33 observation years), including failed numeric comparisons, before reporting failure.
- Does not alter rainfall values, preparation, regridding, or daily negative-increment tolerance.

Examples: the allowed difference is 0.002 mm at a JJAS total of 1000 mm, and 0.003 mm at 2000 mm. This is a practical numerical comparison tolerance, not a physical bias allowance. Tests include the reported 0.00048828125 mm difference, grouped float32 summation, rejection of a 0.01 mm difference at 1000 mm, and missingness mismatch.

## Install and run

Extract `monthly_reconstruction_fix.zip` into `D:\calibrated_seasonal_rainfall`. Replace the existing `scripts\run_monthly.py` with the patched file. This intentional replacement is the only existing script changed. Keep all generated monthly data folders.

In CMD:

```bat
cd /d D:\calibrated_seasonal_rainfall
.venv\Scripts\activate
python -m unittest discover -s tests -p test_monthly_reconstruction.py -v
python scripts\run_monthly.py --config config\project.json --stage check
```

Do not rerun `--stage prepare`; the existing files are sufficient for this check. The new check replaces the derived QC report at `outputs\qc\monthly_reconstruction.json`, not any rainfall data. Structural errors such as coordinate/missingness mismatches still stop immediately.

If the check passes, proceed:

```bat
python scripts\run_monthly.py --config config\project.json --stage training --region-mask data\masks\ethiopia_common.nc
```

If it still fails, send `outputs\qc\monthly_reconstruction.json` and the error. Do not increase the tolerance again without inspecting the pattern of differences.

## Correct seasonal local-calibration output

The recently uploaded `comparison_summary(1).json` and `fold_parameters(1).json` are identical to the earlier shared-method comparison. They contain `blend`, `temperature`, and Dirichlet candidates rather than local blends.

For the new seasonal comparison, upload the file at:

```text
D:\calibrated_seasonal_rainfall\outputs\local_calibration\init05_JJAS\training\local_comparison_summary.json
```

Its methods should include `shared_blend`, `local_blend`, and `regularized_local_blend`. The associated plots are `annual_local_rps.png`, `local_weights.png`, and `local_skill_difference.png`.

To locate it:

```bat
dir /s /b outputs\local_calibration\local_comparison_summary.json
```

If it does not exist, run the seasonal comparison:

```bat
python scripts\local_blend.py --config config\project.json --mode training --region-mask data\masks\ethiopia_common.nc
```

Existing result folders are protected against overwrite; if a run was interrupted and left a partial output folder, rename that folder before rerunning.
