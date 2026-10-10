# 44 — Rainfall-domain review (FMAM): climatology, references, candidate cutoffs, export

The review decides **which area a season's forecast summaries describe** from observed climatology, before any
forecast is involved. It never moves a boundary to improve a forecast score.

```text
CHIRPS calendar cache (monthly_total) → FMAM / annual climatology → EMI reference registry → comparison
→ 20 amount/share candidates + named comparators → review report → (explicit selection) → versioned mask
```

## Files

| File | Role |
| --- | --- |
| `config/rainfall_domains/fmam_review.json` | Periods, thresholds, comparators, references, outputs, selection |
| `config/climatology_references/registry.json` | EMI long-term Belg maps 2(e) mean rainfall and 3(e) share of annual (document and panel hashes; undocumented fields are `null` with a reason) |
| `config/climatology_references/extractions/<id>.json` | Analyst choices: registration (control and check points), legend colours, classification settings, edge convention, review |
| `scripts/rainfall_climatology_core.py` | Config validation, monthly-cache checks, climatology, period availability, country area weights |
| `scripts/climatology_reference_core.py` | Reference acquisition, legend detection, georeferencing, image classification, comparison modes and functions |
| `scripts/rainfall_domain_assessment.py` | Candidate codes, comparators, regional inclusion, neighbour changes, baseline sensitivity, reference agreement |
| `scripts/run_rainfall_domain_review.py` | Stage runner (`inspect`, `climatology`, `references`, `compare`, `sensitivity`, `report`, `export`) |
| `scripts/build_rainfall_domain_review.py` | Figures, JSON results, offline HTML report, input fingerprint |
| `tests/test_rainfall_domain_review.py` | Calendar, baseline, ratio-of-means, identities, area weights, classes, monotonicity, provenance, export contract |

## Method in one paragraph

FMAM and annual totals are sums of actual-calendar monthly totals (February 29 kept; daily CHIRPS values are mm per
day-interval, so there is no 86 400 factor). The climatology is the **ratio of climatological means**
(`100 × mean FMAM / mean annual`), computed only where every year of the period is complete. A requested period that is
not fully in the data (1981–2010, 1991–2020 with the 1993–2025 archive) is recorded as unavailable, never shortened.
A candidate includes a cell when FMAM ≥ T mm **and** share ≥ T %; codes are 1 included, 0 excluded, −1 insufficient
data, −2 outside Ethiopia. No patch removal or smoothing. Areas are cell/Ethiopia-polygon intersections on the WGS84
ellipsoid, so percentages are shares of the country's area (the 3.6 km² beyond the grid count as unknown).

## Run

```bat
cd /d D:\calibrated_seasonal_rainfall
call .venv\Scripts\activate.bat
python scripts\run_rainfall_domain_review.py --config config\rainfall_domains\fmam_review.json --stage report
start "" outputs\rainfall_domain_review\fmam_v1\report\review_report.html
```

Each stage runs its prerequisites and resumes when inputs, settings and code are unchanged. Outputs:
`outputs\rainfall_domain_review\fmam_v1\{inspect,climatology,references,compare,sensitivity,report}`.

## EMI references: review the digitization

The first `references` run downloads EMI's *Belg 2026 Seasonal Climate Forecast* (Amharic, 38 pages), extracts maps
2(e) (p. 23) and 3(e) (p. 24) and writes **draft** extraction records with an automatic registration (country-outline
fit; points touching the map frame are not used) and the legend colours. Until reviewed, both references are
**visual only**; the class metrics are shown as an unreviewed preview.

1. Open `report\georeference_qc_emi_belg_map_2e.png` and `..._3e.png`: the red boundary must follow the map outline,
   and the digitized classes must look like the published map.
2. If needed, edit the control points or legend colours in `config\climatology_references\extractions\<id>.json`
   (or replace them with GCPs from QGIS Georeferencer; keep `role: "check"` points out of the fit).
3. Mark each one reviewed (bound to the document, the panel and your choices; any later change makes it stale):

```bat
python scripts\run_rainfall_domain_review.py --config config\rainfall_domains\fmam_review.json --review-reference emi_belg_map_3e --reviewer "Your name"
python scripts\run_rainfall_domain_review.py --config config\rainfall_domains\fmam_review.json --review-reference emi_belg_map_2e --reviewer "Your name"
python scripts\run_rainfall_domain_review.py --config config\rainfall_domains\fmam_review.json --stage report
```

The references then become **exploratory class comparisons** (EMI does not document the reference period), with
exact and within-one-class agreement, an area-weighted confusion matrix, the distance outside the EMI class interval
(percentage points for shares) and comparable/uncertain areas. Draft automatic registration (first run): 3(e) outline
IoU 0.996, check RMSE 8 km; 2(e) IoU 0.971 but check RMSE 63 km (its frame clips the north and south tips) — review 2(e)
carefully.

## Selected (2026-10-10)

**`mm100_share20` — FMAM >= 100 mm and >= 20 % of annual rainfall** is the main FMAM working domain for Ethiopia
(820,657 km², 72.6 %). Exported to `data\masks\fmam_coverage_chirps_v2_1993_2025_v1.nc` and used as the
`season_domain_mask` of both FMAM cycles; the 40 % main-season mask remains a second view. Rationale: in the config.

## Select and export

After choosing a candidate for what the domain should mean, record it in the config (`"selected_candidate"`,
`"selection_rationale"`) or pass it on the command line:

```bat
python scripts\run_rainfall_domain_review.py --config config\rainfall_domains\fmam_review.json --stage export --candidate mm100_share20 --rationale "Belg brings considerable rain (EMI description): >= 20% of annual and >= 100 mm"
```

Export refuses a stale report, writes `data\masks\fmam_coverage_chirps_v2_1993_2025_v1.nc` (the existing mask contract:
`season_domain`, `season_climatology_mm`, `annual_climatology_mm`, `season_share_of_annual` as a 0–1 fraction, plus
provenance) and its smooth boundary, and refuses to overwrite a different domain of the same version. Then point the
FMAM cycles at it (`season_domain_mask` or an `extra_domain_masks` entry) and rerun `run_operational.py --workflow
products --compare-external`, `regional_skill.py --cycle …`, `historical_diagnostics.py --cycle …` and `build_site.py`.

## Site

`build_site.py` publishes the report under **Rainfall domains** (`#domains`): Climatology, References, Candidate domains
(cutoff selector with map, areas, EMI agreement, baselines and regional inclusion) and Assessment. If any input changed
after the report was built, the section names the changed inputs.
