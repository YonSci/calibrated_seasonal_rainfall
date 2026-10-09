# 41. Comparison with official outlooks (ICPAC, EMI)

Compares the platform's native forecast with official seasonal outlooks. It runs as three stages of `run_operational.py` and is published by `build_site.py`. First use: ONDJ 2026/27 (September initialization) against the ICPAC October–December 2026 update and EMI's Bega 2026/27 outlook.

## Files

| File | Role |
|---|---|
| `scripts/external_forecasts.py` | ICPAC/EMI adapters, versioned downloads, standardized records, ICPAC map digitization, `review` command |
| `scripts/compare_external_forecasts.py` | Metric eligibility, structured findings, comparison maps |
| `scripts/interpret_external_forecasts.py` | Deterministic interpretation rules, `interpretation.json`, review `report.html` |
| `config/external_forecasts/ondj_2026_27.json` | Registry: platform target, sources, discovery rules, target dates, anomaly-product check |
| `config/external_forecasts/extractions/*.json` | Extraction records (draft/validated), each tied to one source SHA-256 |
| `config/cycles/sep_2026_ondj.json` → `external_comparison` | Enables the stages; registry, cache root, output root, engine `rules` |
| `data/external_forecasts/<registry>/` | Original downloads by content hash, metadata, `current.json`, `retrieval_log.jsonl` (tracked as evidence) |
| `outputs/operational_2026_ondj/comparisons/{sources,comparison,interpretation}/` | Stage outputs |

## Run

```bat
python scripts\run_operational.py --config config\cycles\sep_2026_ondj.json --workflow products --compare-external --refresh-external
python scripts\build_site.py
```

Without `--refresh-external` the stages use the saved snapshots and resume if nothing changed. The online check runs before any stage hashes its inputs, so a product replaced at the same URL is detected. Routine check times go to `retrieval_log.jsonl`, not into stage inputs.

## Review (required before numbers are published)

Draft extractions are never used for published comparisons. Open `outputs/operational_2026_ondj/comparisons/interpretation/report.html`. Then, for each source:

1. Check every item of its "Reviewer checklist" against the original figure shown in the report. These cover printed values, category order (EMI prints A/N/B), season, legend, arrow-tip locations and the digitized ICPAC map.
2. Run, for example:
   ```bat
   python scripts\external_forecasts.py review --registry config\external_forecasts\ondj_2026_27.json --record emi_bega_2026_27_outlook --reviewer "Your name"
   python scripts\external_forecasts.py review --registry config\external_forecasts\ondj_2026_27.json --record icpac_ond_2026_update_rainfall --reviewer "Your name"
   ```
   Use `--reject --note "..."` if something is wrong, then correct the record.
3. Rerun the two commands above. The validated findings, numbers and comparison maps then appear on the site.

The validation is stored with the source hash. If a provider replaces the image or PDF, the record no longer applies and the source returns to `needs_extraction_review`. A new extraction record is needed for the new file. `python scripts\external_forecasts.py status --registry ...` lists the states.

## What the sources contain (checked 2026-10-09)

- **ICPAC**: `seasonal-forecast/october-december-2026_update/?region=1&resource_type=27`. Original image `GHA-PRCP.original.png` (the thumbnail name differs, so the download link is followed rather than constructed).
  - The map shows the favoured tercile with printed intervals: Above 40–100 %; Normal and Below 40–90 %.
  - Grey areas are not explained in the legend and are treated as "no forecast shown".
  - It is digitized on the 0.25° grid from the detected axis frame and tick marks (residual < 1 px) and the legend's own colour boxes.
  - Target: OND 2026. The platform target is ONDJ 2026/27, so `target_window_mismatch` is attached (January 2027 only in the platform).
- **EMI**: the hydromet bulletin "Kiremt 2026 Assessment and Bega 2026_27 Outlook". Only the outlook half of combined titles is matched.
  - The outlook page is found from the PDF text (page 21, "Bega (ONDJ), 2026-27"), and the embedded figure "NATIONAL OUTLOOK FOR (ONDJ 2026/27)" is extracted unchanged.
  - Four zone annotations are printed in A/N/B order (III 55/25/20, VI 60/25/15, VII 60/15/25, VIII 75/15/10). These values are a draft transcription awaiting review.
  - Zones are located only by arrows, so `geometry_status = requires_alignment`.
- **Issue date, initialization and reference period**: not stated by either provider and kept `null`. HTTP Last-Modified and PDF creation dates are recorded under their own names.
- **Rainfall-amount anomaly**: no official anomaly product was found for this season, so `rainfall_anomaly_difference` is `unavailable`.

## Metrics and eligibility

| Metric | Requirement | First release |
|---|---|---|
| Official probabilities shown | validated transcription | after review |
| Favoured-category relationship | validated values and arrow-tip locations | after review; uses the platform's area mean of local probabilities within ±0.5° of the arrow tip, labelled as such |
| Platform mean over an official zone | zone polygons | unavailable (`zone_geometry_requires_alignment`) |
| Mapped category agreement (ICPAC) | validated digitization, common valid footprint | after review; computed over the overlap where both show a favoured category, with coverage |
| Same-event probability difference | same window, support and event | unavailable |
| Rainfall-anomaly difference | official anomaly product | unavailable |
| Which forecast is more accurate | observations, separate design | out of scope (see Verification) |

The favoured category uses the map rule: the leading tercile where it reaches 40 %, otherwise "no clear category". An OND probability is never built by averaging monthly probabilities.

## Interpretation rules

| Finding | Sentence |
|---|---|
| Both favour above | Both outlooks favour wetter-than-normal conditions in the specified overlap |
| Above vs below | The outlooks disagree on the favoured rainfall category |
| Weak or tied | That source shows no clear category preference under its rule |
| Windows differ | Names the months that differ; spatial tendency only |
| Product missing | States which comparison cannot be calculated and why |

Every paragraph keeps its status and evidence identifiers. The draft results (not published) show agreement on above-normal rainfall in zones VI, VII and VIII and over the ONDJ R3 domain, and **disagreement in zone III** (western Ethiopia). There the platform's mean local probabilities near the arrow tip are 50 / 31 / 19 % (below / near / above), against EMI's 20 / 25 / 55 %. An LLM rewording step is not implemented; only `rules` is accepted.

## Tests

`tests/test_external_forecasts.py` covers:
- title matching and year formats;
- hash-bound extraction status;
- the relationship and window rules;
- the ICPAC digitization;
- that drafts are never published;
- that review publishes the zone III disagreement with the required wording;
- that a replaced source returns to review.
