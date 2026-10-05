# 02 — Configure data and season

Open `config/project.json`. JSON permits no comments and no trailing commas. Use forward slashes in Windows paths.

## Use original files in place

Replace these two values with the **actual complete paths on your PC**:

```json
"ecmwf_directory": "D:/YOUR_ACTUAL_FOLDER/dashboard_ons_cess_sl/data/seasonal_pr_downloads_et/ecmwf",
"chirps_file": "D:/YOUR_ACTUAL_FOLDER/dashboard_ons_cess_sl/data/chirps_pr_et/et_chirps_pr_r25_1993_2025.nc"
```

The `YOUR_ACTUAL_FOLDER` text is a placeholder, not a known path. The screenshot did not show the whole path. In File Explorer select the file/folder, use Copy as path, remove the surrounding quotes when inserting into the JSON string, and replace backslashes with forward slashes.

Do not leave either value pointing to a directory/file that does not exist. The CHIRPS value must include the filename. The ECMWF value is a directory.

Alternatively, keep the default relative paths and manually place files in `data/raw/ecmwf/` and `data/raw/chirps/`. Avoid unnecessary duplicate copies. Paths in the config are resolved relative to the **project root**, not the `config` directory.

## Filename pattern

`ecmwf_{year}{month:02d}_d01.nc` with initialization month 5 gives `ecmwf_199305_d01.nc`, etc. The inspection checks every year 1993–2026. A smaller sample inventory can be requested by temporarily narrowing `archive_years`, but restore it before archive-wide review.

## Default season

```json
"initialization_month": 5,
"season": {"name": "JJAS", "start": "06-01", "end": "09-30"}
```

For JJA use:

```json
"season": {"name": "JJA", "start": "06-01", "end": "08-31"}
```

For a separate product, copy the config first:

```bat
copy config\project.json config\jja.json
notepad config\jja.json
```

Keep season names consistent with dates. Output directories include the initialization month and season name. The starter supports same-calendar-year seasons with midnight boundaries. Cross-year seasons require an explicit extension; the config loader rejects them.

## Source contract

ECMWF: `tp` in metres, cumulative from initialization, first endpoint +24 hours, one initialization, dimensions `forecast_period, number, latitude, longitude`, `valid_time` endpoints. Unexpected structures fail and require an explicit reader change. This does not infer daily/cumulative semantics from a filename.

CHIRPS: `precip`, dimensions `time, lat, lon`, daily totals with start-of-day timestamps. Units `mm/day` (or documented equivalent) are accepted. The erroneous source `standard_name` is not used to infer the physical quantity. Derived totals get `units=mm`; sources remain unchanged.

The observation period is 1993–2025. The 2026 file is processed without inventing a CHIRPS 2026 verification target.

No credentials are stored in this configuration. Model provenance must be preserved separately from the inference based on member counts.
