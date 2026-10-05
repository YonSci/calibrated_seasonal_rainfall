# Stage 2: Put seasonal rainfall on a common grid

## 1. Install this update

This update adds `scripts/regrid_seasonal.py` and this guide to the existing starter project. It requires the existing `scripts/common.py` and Python environment. It contains no configuration replacements and no new dependencies.

Extract the ZIP into a temporary folder. Copy its `scripts` and `docs` folders into `D:\calibrated_seasonal_rainfall`, merging them with the existing folders. The script must end up at `D:\calibrated_seasonal_rainfall\scripts\regrid_seasonal.py`.

## 2. Activate the project in VS Code CMD

```bat
cd /d D:\calibrated_seasonal_rainfall
.venv\Scripts\activate
```

## 3. Test the two supplied ECMWF years

```bat
python scripts\regrid_seasonal.py --config config\project.json --years 1993 2026
```

The script always reads the first configured observation year (1993 here) as its coordinate reference. Therefore `chirps_1993_native.nc` must exist even for a forecast-only invocation.

Expected messages: 1993 has 25 members; 2026 has 51 members; both have 48 x 60 grid cells. Conservation error should be near machine precision (approximately 1e-14 or less for the supplied files).

## 4. Process the complete archive

Omitting `--years` processes the inclusive `archive_years` range from your configuration, currently 1993–2026.

```bat
python scripts\regrid_seasonal.py --config config\project.json
```

It writes:

```text
data\processed\init05_JJAS\ecmwf_1993_common.nc
...
data\processed\init05_JJAS\ecmwf_2026_common.nc

data\processed\init05_JJAS\chirps_1993_common.nc
...
data\processed\init05_JJAS\chirps_2025_common.nc

outputs\qc\regridding_init05_JJAS.json
```

Check the file counts:

```bat
dir /b data\processed\init05_JJAS\ecmwf_*_common.nc | find /c /v ""
dir /b data\processed\init05_JJAS\chirps_*_common.nc | find /c /v ""
```

Expected: 34 ECMWF and 33 CHIRPS files. Counts alone do not establish success: the command must finish successfully and the JSON must list all requested years. The JSON describes only the latest successful invocation. A failed invocation can leave an older report; do not treat it as evidence that the failed run completed. Re-running replaces the corresponding derived outputs. Original and native seasonal files are read-only inputs.

## 5. What the method does and why

**Scientific method:** first-order conservative remapping on aligned nested regular latitude–longitude cells, assuming a constant rainfall depth within each source cell.

1. **Verify season and units.** Confirm rainfall is in mm, dates/configuration match, and model cells have complete daily coverage. This prevents mixing different seasons or incomplete totals.
2. **Sort coordinates northward/eastward.** ECMWF latitudes arrive descending, while CHIRPS latitudes ascend. Sorting aligns their physical locations.
3. **Infer cell boundaries.** These files supply centres without native cell-bound arrays. Boundaries are inferred halfway between regularly spaced centres, extending half a spacing at the outside. Both grids then cover latitude 3–15 and longitude 33–48 degrees. This is an explicit cell-area interpretation of the supplied grid; it is not independent verification of upstream grid construction.
4. **Require exact nesting.** Each target cell must fit completely inside one source cell, and outer boundaries must agree. The script stops if they do not. It is deliberately limited to aligned nested regular grids, not a general-purpose remapper.
5. **Assign rainfall depth to target cells.** Each 1-degree source cell contains 4 x 4 target cells at 0.25 degrees. If the source seasonal depth is 600 mm, every contained target cell receives 600 mm. Do not divide rainfall depth by 16: cell areas already account for the smaller water volumes.
6. **Check conservation for every member.** Compare the sum of rainfall depth multiplied by spherical cell area before and after remapping. Cell areas are proportional to longitude width times the difference of sine latitude boundaries. Equal proportionality constants cancel in the conservation check.
7. **Retain observational missing values.** CHIRPS is already on the target grid and is copied without changing rainfall. Its `observation_valid` flag equals 1 only for a complete seasonal observation. No missing rainfall is replaced with zero.
8. **Write outputs and quality report.** Forecast files retain actual member counts. There is no artificial padding from 25 to 51 members.

The resulting ECMWF map will have repeated 4 x 4 blocks. This is expected. Regridding does not create subgrid forecast information and is not statistical downscaling or bias correction.

## 6. Mask handling

The 1993 CHIRPS sample has 2,657 complete cells and 223 cells with zero valid days; there are no partly complete cells in this sample. Their cause is not established by the prepared file. Do not label them automatically as ocean or outside Ethiopia.

The ECMWF grid stays complete. Use each year's observation validity when forming forecast–observation pairs. Do not permanently mask every forecast using 1993 alone. Later calibration must establish eligibility from its training observations without selecting cells based on withheld-year outcomes. An Ethiopia administrative mask, if wanted for presentation, is a separate input.

## 7. Validation completed on the uploaded files

| Input | Units | Dimensions | Finite seasonal totals | Range (mm) |
|---|---|---|---|---|
| ECMWF 1993 | mm | 25 x 12 x 15 | 4,500 / 4,500 | 0.2441–1,615.0665 |
| ECMWF 2026 | mm | 51 x 12 x 15 | 9,180 / 9,180 | 0–1,815.3229 |
| CHIRPS 1993 | mm | 1 x 48 x 60 | 2,657 / 2,880 | 0–1,436.0372 |

Both ECMWF files have 122 valid days everywhere. The command-line test produced the expected 48 x 60 output grids and NetCDF files. Regridded arrays matched explicit 4 x 4 repetition after sorting. Maximum relative conservation errors were 5.63e-15 (1993) and 7.14e-15 (2026). CHIRPS values and NaNs were unchanged after writing/reading. A shifted target grid was rejected.

Tests ran on Linux with the starter's scientific dependencies. Windows itself and the other 32 years were not executed here. The full local command applies the same checks to every year. Prepared totals cannot independently verify the cause of negative increments in the original cumulative files.

## 8. Troubleshooting

- `No module named ...`: activate the existing `.venv`; no new package installation is required for this update.
- Missing `common.py`: merge the update into the original project's scripts folder.
- Missing native file: complete preparation for that year; ensure the configured season name matches the prepared folder.
- Season mismatch: use the configuration that generated these native files.
- Grid or conservation failure: retain the error and send it for review; do not bypass the guard or use extrapolation.
- Permission denied on output: close applications holding the NetCDF file and rerun.

## 9. Next stage

Upload `outputs\qc\regridding_init05_JJAS.json` after the full run. No additional large NetCDF uploads are needed if it succeeds.

The next module will implement pooled, equal-year-weight mean–variance rainfall bias correction and year-withheld tercile probabilities. Regularized Dirichlet probability calibration follows those probabilities. Development uses 1993–2016; 2017–2025 stays withheld for evaluation. Final fitting can use observations through 2025 for the 2026 initialization. As of October 2026 the target JJAS season has elapsed, so this is a reconstruction of that initialized forecast; verification still requires 2026 observations, which are absent from the supplied CHIRPS archive.
