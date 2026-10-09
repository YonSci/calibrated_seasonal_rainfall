ONDJ 2026/27 — September initialization - forecast and evidence package
============================================================

Research reconstruction; not an official EMI or ICPAC forecast.
Built 2026-10-09 09:37 UTC (site release 2026-10-09.5) from https://github.com/YonSci/calibrated_seasonal_rainfall

What this forecast is
---------------------
The forecast leans toward above normal rainfall in the ONDJ R3 (Deyr) rainfall domain:
averaged over the area, the local probability of above normal is 57%, against about 33%
for climatology. Mean forecast rainfall is 240 mm against a 1993/94–2024/25 average of 176
mm (+64 mm, +37%).

Model initialization: 1 September 2026 · ECMWF SEAS5 (system 51), 51 members
Target period: 1 Oct 2026 – 31 Jan 2027
Forecast record: Generated 7 Oct 2026; not yet frozen for verification (freeze before observations are used)
Publication status: Research reconstruction: produced after the initialization date with the published method; not an official EMI or ICPAC forecast
Reference period: CHIRPS v2.0 ONDJ 1993/94–2024/25 (32 seasons)
Observations processed through: None yet
CHIRPS archive: Official CHIRPS v2.0 p25 by_month listing checked 9 Oct 2026: monthly files through Aug 2026; Feb 2026 file not found
Verification last run: Not run
Method / version: Shared climatology blend (λ = 0.28 for ONDJ) · code d932d97
Rainfall domain: Fixed 1993-2025 descriptive domain (Deyr / Hagaya): rainfall regime R3 (GitHub-refined classification of the CHIRPS daily climatology) with ONDJ climatological CHIRPS rainfall >=30 mm; patches smaller than 3 cells removed. Scientific masking walkthrough logic; no onset gate. The same domain is used for the season and each of its months.

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
