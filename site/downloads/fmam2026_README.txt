FMAM 2026 — January initialization - forecast and evidence package
============================================================

Research reconstruction; not an official EMI or ICPAC forecast.
Built 2026-10-09 15:02 UTC (site release 2026-10-09.11) from https://github.com/YonSci/calibrated_seasonal_rainfall

What this forecast is
---------------------
The forecast is close to climatology in the FMAM R2 (Belg) rainfall domain: no tercile
stands out on average. Mean forecast rainfall is 212 mm against a 1993–2025 average of 213
mm (0 mm, 0%).

Model initialization: 1 January 2026 · ECMWF SEAS5 (system 51), 51 members
Target period: 1 Feb 2026 – 31 May 2026
Forecast record: Frozen 8 Oct 2026 (after the target period ended, before this project downloaded its observations; SHA-256 manifest)
Publication status: Research reconstruction: produced after the initialization date with the published method; not an official EMI or ICPAC forecast
Reference period: CHIRPS v2.0 FMAM 1993–2025 (33 seasons)
Observations processed through: May 2026 (Mar, Apr, May)
CHIRPS archive: Official CHIRPS v2.0 p25 by_month listing checked 9 Oct 2026: monthly files through Aug 2026; Feb 2026 file not found
Verification last run: 8 Oct 2026
Method / version: Shared climatology blend (λ = 0.43 for FMAM) · code c5c825d
Rainfall domain: Fixed 1993-2025 descriptive domain (Belg): rainfall regime R2 (GitHub-refined classification of the CHIRPS daily climatology) with FMAM climatological CHIRPS rainfall >=80 mm; patches smaller than 3 cells removed. Scientific masking walkthrough logic; no onset gate. The same domain is used for the season and each of its months.

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
