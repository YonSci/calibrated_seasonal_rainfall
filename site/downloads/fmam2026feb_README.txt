FMAM 2026 — February initialization - forecast and evidence package
============================================================

Research reconstruction; not an official EMI or ICPAC forecast.
Built 2026-10-10 08:13 UTC (site release 2026-10-09.11) from https://github.com/YonSci/calibrated_seasonal_rainfall

What this forecast is
---------------------
The forecast leans toward above normal rainfall in the FMAM rainfall domain (FMAM >= 20%
of annual and >= 100 mm): averaged over the area, the local probability of above normal is
43%, against about 33% for climatology. Mean forecast rainfall is 316 mm against a
1993–2025 average of 287 mm (+29 mm, +10%).

Model initialization: 1 February 2026 · ECMWF SEAS5 (system 51), 51 members
Target period: 1 Feb 2026 – 31 May 2026
Forecast record: Frozen 9 Oct 2026 (after the target period ended, before this project downloaded its observations; SHA-256 manifest)
Publication status: Research reconstruction: produced after the initialization date with the published method; not an official EMI or ICPAC forecast
Reference period: CHIRPS v2.0 FMAM 1993–2025 (33 seasons)
Observations processed through: May 2026 (Feb, Mar, Apr, May)
CHIRPS archive: Official CHIRPS v2.0 p25 by_month listing checked 10 Oct 2026: monthly files through Aug 2026; Feb 2026 file not found
Verification last run: 10 Oct 2026
Method / version: Shared climatology blend (λ = 0.44 for FMAM) · code ca3165c
Rainfall domain: Fixed 1993-2025 CHIRPS v2.0 domain: cells where mean FMAM rainfall (actual-calendar monthly totals, February 29 included) is >= 100 mm and FMAM brings >= 20% of the mean annual rainfall (ratio of climatological means); complete baseline required; no patch removal or smoothing. Selected in assessment fmam_chirps_domain_review_v1. The same domain is used for the season and each of its months.

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
CHIRPS v2.0: Climate Hazards Center, UC Santa Barbara.
