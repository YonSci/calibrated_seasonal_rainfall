# Provenance — ECMWF SEAS5 May-initialized daily total precipitation

- Dataset: Copernicus CDS `seasonal-original-single-levels`, originating centre `ecmwf`, **system 51**.
- Variable `total_precipitation` (`tp`, metres, accumulated since initialization). Init day 1 May, 00 UTC.
- Lead times 24–4392 h (183 daily endpoints). Area N15 W33 S3 E48. Native 1° grid.
- Members: 25 for 1993–2016 (hindcast), 51 for 2017–2026 (forecast).
- Verification (2026-10-03): 1996, 2003, 2020 and 2023 were re-downloaded with
  `scripts/download_seasonal_forecasts_daily_c3s.py --models ecmwf --system ecmwf=51 --variables total_precipitation --months 5 --init-day 1 --leadtime-days 183 --north 15 --west 33 --south 3 --east 48`.
  Coordinates were identical and max |difference| = 0.000000 mm, so the archive matches CDS system 51 bit for bit.
- GRIB packing produces daily accumulation drops of up to 0.147 mm. Tolerance: 0.2 mm (docs/03).
