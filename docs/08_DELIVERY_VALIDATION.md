# 08 — Delivery validation and limitations

> **Status update (2026-10-05):** this describes the original starter package. For current validation status see [36_PROJECT_STATUS_REVIEW.md](36_PROJECT_STATUS_REVIEW.md) and docs 30–32.

## Checks performed when preparing this starter

- Python files compiled for syntax; JSON configuration parsed.
- Bootstrap recreated the project, safely preserved identical reruns, and refused to overwrite an edited configuration.
- Archive file contents checked against source files.
- Nine synthetic tests passed under Linux with Python 3.12, NumPy 1.26.4, pandas 2.2.3, xarray 2024.11.0, SciPy 1.14.1, and netCDF4 1.7.2 installed in an isolated task-local package directory.
- Tests cover 25/51 members, daily-to-seasonal aggregation, calendar boundaries, negative resets, timestamp gaps, missing values, units, and NetCDF round-trip.

The first package-install attempt was blocked by the execution environment's network restrictions. A subsequent authorized isolated installation succeeded, allowing the scientific tests to run. The Linux test runtime emitted datetime-precision and binary-compatibility warnings, but all nine assertions and NetCDF read/write checks passed. This does not establish a clean Windows binary environment; run the supplied setup checks there.

## Checks requiring your local run

The Windows CMD setup script was inspected but was not executed on Windows here. Full requirements resolution and imports on your Windows machine must succeed before proceeding. The local test installation used the scientific subset needed by the tests; the setup script additionally checks Dask and Matplotlib.

Run `call setup_project.cmd`. It checks package consistency/imports and executes the synthetic suite; failures stop setup. Then prepare one real year and inspect outputs before processing the archive.

Only inspection text and screenshots were used to define the source contract. The full original climate archive was not processed here. Unexpected file structures deliberately fail instead of being guessed.

This is a first-stage starter, not a validated operational forecast system. Regridding, scientific calibration, independent forecast evaluation, and final production are the next stages in doc 04.
