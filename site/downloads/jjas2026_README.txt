Seasonal Rainfall Outlook Platform
JJAS 2026 — May initialization - forecast and evidence package
============================================================

Research reconstruction: produced after the initialization date with the published method; not an official EMI or ICPAC forecast
Built 2026-10-19 12:20 UTC (site release 2026-10-19.0) from https://github.com/YonSci/calibrated_seasonal_rainfall

What this forecast is
---------------------
The forecast leans toward below normal rainfall in the JJAS R1+R2 rainfall domain:
averaged over the area, the local probability of below normal is 51%, against about 33%
for climatology. Mean forecast rainfall is 700 mm against a 1993–2025 average of 831 mm
(−131 mm, −16%).

Model initialization: 1 May 2026 · ECMWF SEAS5 (system 51), 51 members
Target period: 1 Jun 2026 – 30 Sep 2026
Forecast record: Frozen 10 Oct 2026. Recalibrated with CHIRPS v3.0 when its observations for Jun 2026–Aug 2026 were already available (the fit itself uses 1993–2025 only): a retrospective reconstruction, not a forecast frozen before its outcome (SHA-256 manifest)
Publication status: Research reconstruction: produced after the initialization date with the published method; not an official EMI or ICPAC forecast
Reference period: CHIRPS v3.0 JJAS 1993–2025 (33 seasons)
Observations processed through: September 2026 (Jun, Jul, Aug, Sep)
CHIRPS archive: Official CHIRPS v3.0 monthly listing checked 19 Oct 2026: monthly files through Sep 2026
Verification last run: 16 Oct 2026
Method / version: Shared climatology blend (λ = 0.59 for JJAS) · code 17707ef
Rainfall domain: Fixed 1993-2025 descriptive domain: cleaned GitHub-refined R1/R2; JJAS climatological rainfall >=120 mm and >=20% of annual rainfall. The same domain is used for Jun, Jul, Aug, Sep and JJAS. No onset gate.

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
