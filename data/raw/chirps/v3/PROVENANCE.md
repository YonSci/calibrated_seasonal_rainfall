# CHIRPS v3.0 monthly (Africa, 0.05°) — parallel v3 track

- **Source:** https://data.chc.ucsb.edu/products/CHIRPS/v3.0/monthly/africa/tifs/ (`chirps-v3.0.YYYY.MM.tif`, final product,
  GeoTIFF, LZW, 1500 × 1600 cells, origin 20°W 40°N, 0.05°, −9999 = missing).
- **Reference:** Funk, C., Peterson, P., Harrison, L., et al. (2026). The Climate Hazards Center Infrared Precipitation with
  Stations, Version 3. *Scientific Data*, 13, 718. https://doi.org/10.1038/s41597-026-07096-4
- **Downloaded by:** `scripts/prepare_chirps_v3.py` into `africa_monthly/`, one `<file>.download.json` receipt per file (URL,
  bytes, SHA-256, HTTP Last-Modified, retrieval time). Files are reused only while they match their receipt.
- **Derived file:** `data/raw/chirps/et/et_chirps3_monthly_r25.nc` — monthly totals on the project's 0.25° Ethiopia grid
  (5 × 5 block mean of the valid 0.05° cells; missing when fewer than 13 of 25 are valid; `valid_subcells` stored), with
  `et_chirps3_monthly_r25.receipts.json` (SHA-256 of every source file).
- **Why monthly:** CHIRPS v3 has no 0.25° (p25) product, and its daily values are disaggregated from pentads (ERA5 `rnl` or
  IMERG `sat`); every target of this project is a whole month or a season of whole months.
- **Status:** comparison track only (decision 2026-10-11: the 2026 forecasts and their verification stay on CHIRPS v2.0;
  v3 is considered from the next cycle). Nothing in the published v2 pipeline reads these files.
