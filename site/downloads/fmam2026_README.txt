Seasonal Rainfall Outlook Platform
FMAM 2026 — January initialization - forecast and evidence package
============================================================

Research reconstruction: produced after the initialization date with the published method; not an official EMI or ICPAC forecast
Built 2026-10-27 09:53 UTC (site release 2026-10-27.0) from https://github.com/YonSci/calibrated_seasonal_rainfall

What this forecast is
---------------------
The forecast is close to climatology in the FMAM rainfall contribution domain: no tercile
stands out on average. Mean forecast rainfall is 307 mm against a 1993–2025 average of 310
mm (−3 mm, −1%).

Model initialization: 1 January 2026 · ECMWF SEAS5 (system 51), 51 members
Target period: 1 Feb 2026 – 31 May 2026
Forecast record: Frozen 10 Oct 2026. Recalibrated with CHIRPS v3.0 when its observations for Feb 2026–May 2026 were already available (the fit itself uses 1993–2025 only): a retrospective reconstruction, not a forecast frozen before its outcome (SHA-256 manifest)
Publication status: Research reconstruction: produced after the initialization date with the published method; not an official EMI or ICPAC forecast
Reference period: CHIRPS v3.0 FMAM 1993–2025 (33 seasons)
Observations processed through: May 2026 (Feb, Mar, Apr, May)
CHIRPS archive: Official CHIRPS v3.0 monthly listing checked 27 Oct 2026: monthly files through Sep 2026
Verification last run: 16 Oct 2026
Method / version: Shared climatology blend (λ = 0.34 for FMAM) · code b4e5b00
Rainfall domain: Fixed 1993-2025 CHIRPS v3.0 domain: cells where mean FMAM rainfall (actual-calendar monthly totals, February 29 included) is >= 100 mm and FMAM brings >= 20% of the mean annual rainfall (ratio of climatological means); complete baseline required; no patch removal or smoothing. Selected in assessment fmam_chirps_domain_review_v1. The same domain is used for the season and each of its months. The included share of Ethiopia describes this rule; it is not an independently established official share of FMAM-dependent area.

Contents
--------
bulletin.pdf            Outlook, interpretation, evidence, record and monthly maps
summary.csv             Every target and area: probabilities, amounts, coverage, status, verification scores
metadata.json           Initialization, target dates, reference period, method version, freeze status, files
maps/forecast/...       PNG maps per target and area: tercile, total, anomaly (mm and %)
maps/verification/...   Verification panels, comparison figures and the six-panel figure (verified targets)
reports/                Verification reports (HTML), where verification exists
data/                   Forecast NetCDF files per target (0.25 deg; corrected ensemble, probabilities)

How to read
-----------
Terciles split the reference-period CHIRPS rainfall into three equally likely parts;
climatology assigns about one-third to each (the observed tercile frequencies of the
training years). Area probabilities are averages of grid-cell probabilities, not
probabilities of the area-total rainfall. Skill scores are decimals: +0.05 means a 5%
lower score than climatology. RPSS refers to the blended probabilities, CRPSS and bias to
the amount-corrected ensemble.

Sources and attribution
-----------------------
Contains modified Copernicus Climate Change Service information (ECMWF SEAS5, system 51).
CHIRPS v3.0: Climate Hazards Center, UC Santa Barbara. Funk et al. (2026), The Climate Hazards Center Infrared Precipitation with Stations, Version 3, Scientific Data 13, 718, doi:10.1038/s41597-026-07096-4
