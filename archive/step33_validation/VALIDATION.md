# Validation of the Step 33 update

Completed 5 October 2026. This document distinguishes actual-data checks from
synthetic integration tests.

## Automated tests

Five test groups passed in the assembled project containing the existing Step
29–32 dependencies and the three new scripts:

1. Stage resume checks input/output hashes; changed outputs or inputs rebuild.
   A nonzero child exit fails the stage; no successful receipt is written. The
   exclusive run lock is respected and released.
2. Availability distinguishes ready, HTTP-404 unavailable, and unknown responses.
   September absence keeps JJAS pending. Requiring unavailable targets raises an
   error; all four ready months enable JJAS.
3. The same fixed mask applies to all five targets. A wrong climatological baseline
   is rejected. Continuous constant fields remain constant; categorical display
   contains only the original discrete codes.
4. The real CLI creates all five forecast views and the three existing verification
   targets in a temporary synthetic project. A second invocation reuses every
   stage. Forecast probabilities and every original verification variable retain
   their native values. Frozen forecast hashes remain unchanged. `--plan` does
   not create project output directories.
5. The actual preparation/scoring/regime/report CLI chain runs against locally
   cached, explicitly synthetic daily observations. It creates a complete 122-day
   JJAS total and a five-target report, preserves the freeze, and resumes every
   completed stage on repetition. No live observations were downloaded for this
   test and these synthetic results are not supplied as forecast verification.

Final suite result: `Ran 5 tests in 21.535s — OK`.

## Actual JJAS forecast check

The supplied preview is rendered from the user's uploaded `forecast_2026.nc`.
Its SHA-256 remained:

```text
c38412a35bdde258c93346e4455f3d71edfffb7cffd47592f778ce3f8c3e82ef
```

Checks include the target period, 51 unique members, corrected-member mean,
member-count probabilities, additive smoothing, shared-blend formula, tercile
thresholds, units, country/domain grid alignment and mask baseline.

The fixed domain has 833 cells and covers 55.9321737633% of country-grid area.
Country means reproduce the earlier JJAS forecast: corrected mean 375.1438788 mm,
reference mean 441.1164721 mm, and mean anomaly −65.9725933 mm. Domain values are
documented in `docs/34_R12_PRESENTATION_LAYERS.md` and the example summary JSON.

## Visual and gallery checks

The actual JJAS domain tercile and anomaly PNGs were inspected for layout, clipping,
legends and readability. A separate synthetic verification figure was inspected
to check six-panel layout and category handling. Synthetic verification figures
are excluded from the package.

The offline gallery's JavaScript passes `node --check`. The generated actual-data
gallery fixture's eight PNG and eight PDF links resolve. Browser interaction was
not exercised in a Windows desktop browser here; the HTML uses embedded data and
standard local image links, without fetch requests or external assets.

## Tested environment and limits

Tests ran on Linux with Python 3.12.14, NumPy 1.26.4, pandas 2.2.3, xarray 2024.11.0,
netCDF4 1.7.2, SciPy 1.14.1, Matplotlib 3.10.8, pyshp 2.3.1 and pyproj 3.7.0.
The runtime emitted a NumPy binary-size warning during extension import; the
NetCDF reads, writes, numerical identity checks and complete test suite passed.
The user's existing Windows/Python environment has not been modified or directly
tested here. The code uses argument-list subprocess execution and platform-neutral
paths, with commands documented for Windows CMD.

Only the actual JJAS forecast NetCDF was used to create the shipped example maps.
Actual monthly forecast maps and actual 2026 verification maps are generated on
the user's computer from their own full NetCDF inputs. No monthly field or
observation field was inferred from uploaded screenshots or summary statistics.

This verifies implementation behavior, not a new statistical improvement to the
forecast. No fitting, calibration-method selection or assessment of long-term
skill was performed in this update.
