# 42. Comparing FMAM 2026 with the official outlooks: step by step

This guide adds the official-outlook comparison (docs/41) to the January-initialized FMAM 2026 cycle. Every command runs from the project folder in the activated environment (`.venv\Scripts\activate`). I tested these steps in a scratch folder on 2026-10-09; the results expected at each step are given so you can check your run.

## What will be compared

| Source | Product | Target period | Format |
|---|---|---|---|
| Platform | FMAM 2026 forecast (frozen, `outputs\verification_2026_fmam\frozen_forecasts\init01_FMAM`) | 1 Feb – 31 May 2026 | grid |
| ICPAC | "Rainfall forecast – March – May 2026 – IGAD Region" (`GHA-MAM-Rainfall.original.png`) | 1 Mar – 31 May 2026 | favoured-category map with probability intervals |
| EMI | "Bega 2025-26 Assessment and Belg2026 hydro met Bulletin" (English PDF), page 22 | Belg (FMAM) 2026 | four shaded zones with printed A/N/B values |

How these differ from ONDJ:
- **ICPAC's MAM map has a different legend.** Each colour bar has seven boxes (90–100 down to 40–50, plus 33–40), and the frame is dark grey. The record template therefore differs, and `draft-record` detects it for you.
- **EMI's Belg figure draws its zones as filled polygons** without numbers, arrows or axes. The zones are digitized from their fill colours and placed by fitting the country outline. That gives platform means over each whole zone; there are no arrow samples.
- **ICPAC covers March–May only**, so February appears in the page text as a month only in the platform.

## Step 1 — Create the registry

Create `config\external_forecasts\fmam_2026.json` with exactly this content:

```json
{
  "schema_version": 1,
  "id": "fmam_2026",
  "description": "Official seasonal rainfall outlooks compared with the platform's January-initialized FMAM 2026 forecast.",
  "platform": {"target": "FMAM", "label": "FMAM 2026", "target_start": "2026-02-01", "target_end": "2026-05-31"},
  "extractions_dir": "config/external_forecasts/extractions",
  "sources": [
    {
      "id": "icpac_mam_2026_rainfall",
      "provider": "ICPAC", "adapter": "icpac",
      "product": "rainfall_tercile_probability", "representation": "dominant_category_map",
      "index_url": "https://www.icpac.net/seasonal-forecast/?year=2026&resource_type=27&region=1",
      "slug": "Mar-May-2026", "region": "1", "resource_type": "27",
      "image_alt": "Rainfall forecast",
      "expected_label": ["Rainfall forecast", "March - May 2026", "IGAD Region"],
      "season_label": "MAM 2026",
      "target_start": "2026-03-01", "target_end": "2026-05-31",
      "issue_date": null, "initialization": null, "reference_period": null
    },
    {
      "id": "emi_belg_2026_outlook",
      "provider": "EMI", "adapter": "emi",
      "product": "rainfall_tercile_probability", "representation": "zone_tercile_probabilities",
      "listing_urls": ["https://www.ethiomet.gov.et/products/seasonal-hydromet-bulletin/",
                       "https://www.ethiomet.gov.et/products/seasonal-forecast/"],
      "outlook_season": "belg", "outlook_years": [2026],
      "page_keywords": ["FMAM", "Belg", "2026"],
      "season_label": "Belg (FMAM) 2026",
      "target_start": "2026-02-01", "target_end": "2026-05-31",
      "issue_date": null, "initialization": null, "reference_period": null
    }
  ],
  "anomaly_products_checked": {
    "ICPAC": "Products listed for Mar-May-2026 (IGAD region): rainfall tercile probability (27) only; no rainfall-anomaly product.",
    "EMI": "The Belg 2026 outlook bulletin gives zone tercile probabilities; no rainfall-amount anomaly map."
  }
}
```

Notes:
- **`index_url` must include `resource_type=27&region=1`.** ICPAC's plain 2026 index does not list the March–May products.
- **The hydromet listing comes first** on purpose. EMI's "Belg 2026 Seasonal Climate Forecast" PDF is in Amharic, and its text cannot be searched for the outlook page; the English hydromet bulletin can.

## Step 2 — Enable the comparison for the FMAM cycle

In `config\cycles\jan_2026_fmam.json`, add this block after `"season_domain_mask"` (mind the comma before it):

```json
  "external_comparison": {
    "enabled": true,
    "registry": "config/external_forecasts/fmam_2026.json",
    "cache_root": "data/external_forecasts",
    "output_root": "outputs/operational_2026_fmam/comparisons",
    "products": ["rainfall_probability", "rainfall_anomaly"],
    "interpretation_engine": "rules"
  },
```

Check it with `python scripts\run_operational.py --config config\cycles\jan_2026_fmam.json --workflow products --compare-external --plan`. The plan should list "prepare official outlook records", "compare with the native FMAM forecast" and "interpretation and review report".

## Step 3 — Download the official products

```bat
python scripts\external_forecasts.py refresh --registry config\external_forecasts\fmam_2026.json
```

Expected:

```
icpac_mam_2026_rainfall: new a9d7f6106eb5 (281 kB) from https://www.icpac.net/media/images/GHA-MAM-Rainfall.original.png
emi_belg_2026_outlook: new 4a0d4eedcc7c (2651 kB) from https://www.ethiomet.gov.et/documents/625/Bega_2025_26_and_Belg_outlook2026E_Hydromet_bulletin_English_bulletin.pdf
```

The files are saved under `data\external_forecasts\fmam_2026\`. If a hash differs from the one above, the provider has changed the product since 2026-10-09. That's fine: the steps are the same, but the values may differ.

## Step 4 — Write draft extraction records

```bat
python scripts\external_forecasts.py draft-record --registry config\external_forecasts\fmam_2026.json --record icpac_mam_2026_rainfall
python scripts\external_forecasts.py draft-record --registry config\external_forecasts\fmam_2026.json --record emi_belg_2026_outlook
```

Expected:
- **ICPAC:** `Detected 6 x ticks, 7 y ticks, legend column 883, bars with [7, 7, 7] boxes.`
- **EMI:** `Outlook page 22`, a saved figure `config\external_forecasts\extractions\_emi_belg_2026_outlook_page22_figure_for_drafting.jpg`, and a list of detected colours:

```
{'fill_rgb': [18, 138, 54],  'pixels': 73222, 'position': [0.48, 0.4]}    <- the large zone in the north and centre
{'fill_rgb': [18, 162, 66],  'pixels': 48002, 'position': [0.67, 0.74]}   <- south-east
{'fill_rgb': [54, 222, 42],  'pixels': 42558, 'position': [0.22, 0.59]}   <- west (lightest green)
{'fill_rgb': [42, 114, 18],  'pixels': 37871, 'position': [0.37, 0.82]}   <- south-centre (darkest green)
{'fill_rgb': [114, 114, 114], 'pixels': 32500, 'position': [0.26, 0.28]}  <- grey "Climatological Dry"
```

`position` is the colour's mean location on the figure, as fractions of its width and height from the top-left corner. Use it to match each colour to the zone where its numbers are printed.

## Step 5 — Complete the ICPAC record

Open `config\external_forecasts\extractions\icpac_mam_2026_rainfall.json` next to the map (the PNG named in step 4). Replace the `TODO` values:

```json
"x_ticks_deg": [25, 30, 35, 40, 45, 50],
"y_ticks_deg": [20, 15, 10, 5, 0, -5, -10],
```

The three `legend_bars`, from top to bottom, are `above`, `near` and `below`. Each has seven boxes:

```json
"category": "above",
"intervals_top_down": [[90, 100], [80, 90], [70, 80], [60, 70], [50, 60], [40, 50], [33, 40]]
```

Use the same intervals for `near` and `below`. The keys ending in `_detected` can stay; they are ignored.

## Step 6 — Complete the EMI record

Open `config\external_forecasts\extractions\emi_belg_2026_outlook.json` next to the drafting figure. Fill in:

```json
"source_locator": {"pdf_page": 22, "figure_title": "Belg (FMAM) 2026 zone outlook (no printed title)"},
"geometry": {"method": "fill_colour_zones", "colour_tolerance": 40, "bbox_deg": null,
             "excluded_fills": [{"label": "Climatologically dry", "fill_rgb": [114, 114, 114]}]},
"zones": [
  {"zone_label": "West", "printed_order": "A/N/B", "printed": "A 45, N 30, B 25",
   "probabilities": {"below": 0.25, "near": 0.30, "above": 0.45}, "fill_rgb": [54, 222, 42]},
  {"zone_label": "North-central", "printed_order": "A/N/B", "printed": "A 60, N 30, B 10",
   "probabilities": {"below": 0.10, "near": 0.30, "above": 0.60}, "fill_rgb": [18, 138, 54]},
  {"zone_label": "South-central", "printed_order": "A/N/B", "printed": "A 55, N 30, B 15",
   "probabilities": {"below": 0.15, "near": 0.30, "above": 0.55}, "fill_rgb": [42, 114, 18]},
  {"zone_label": "Southeast", "printed_order": "A/N/B", "printed": "A 45, N 35, B 20",
   "probabilities": {"below": 0.20, "near": 0.35, "above": 0.45}, "fill_rgb": [18, 162, 66]}
]
```

Read the values from the figure yourself; the values above are what I read. Check that each zone's three probabilities add up to 1, because `prepare` refuses any that don't. `bbox_deg: null` means the country outline in `data\boundaries` is used. The `detected_colours` list can stay.

## Step 7 — Run the comparison

```bat
python scripts\run_operational.py --config config\cycles\jan_2026_fmam.json --workflow products --compare-external
```

Expected:
- the forecast and verification views are reused (`RESUME`);
- `RUN: external_prepare`, `external_compare`, `external_interpret` and `gallery` run;
- the outputs are in `outputs\operational_2026_fmam\comparisons\`.

Check the state with:

```bat
python scripts\external_forecasts.py status --registry config\external_forecasts\fmam_2026.json
```

Both sources should read `extraction needs_extraction_review (Draft extraction awaiting review)`.

## Step 8 — Check the review report

Open `outputs\operational_2026_fmam\comparisons\interpretation\report.html`. Everything there is marked [draft] and watermarked. Check:

1. **ICPAC map.** The middle panel of the comparison map should look like ICPAC's map over Ethiopia: mostly bright green (above normal, 40–50%), with pale-cyan near-normal patches and grey in the far north-west.
   - Dry-run QC: tick-fit residual below 0.5 px.
   - ICPAC shows a category on about 89% of Ethiopia, 11% grey.
2. **EMI zones.** The platform map should show four zone outlines matching EMI's figure: West, North-central, South-central and Southeast, with the dry north-west excluded.
   - Dry-run QC (in the report's source section): outline overlap (IoU) about 0.93.
   - Zone sizes: West 324 cells, North-central 431, South-central 270, Southeast 375, dry 202.
3. **The reviewer checklists** for both sources.

Expected draft results (the platform FMAM 2026 forecast is close to climatology, about 33 / 32 / 35 %):

| EMI zone | EMI below / near / above | Platform over the whole zone | Relationship |
|---|---|---|---|
| West | 25 / 30 / 45 | 33 / 32 / 35 | no clear category in the platform |
| North-central | 10 / 30 / 60 | 35 / 32 / 33 | no clear category in the platform |
| South-central | 15 / 30 / 55 | 38 / 31 / 31 | no clear category in the platform |
| Southeast | 20 / 35 / 45 | 33 / 31 / 36 | no clear category in the platform |

ICPAC within each EMI zone: mostly above normal 40–50% (West, North-central, Southeast); near normal 33–40% in South-central. Category agreement with the platform is about 41% within the compared area, which covers 22% of the national area. This is low because the platform shows a clear category over only a small part of the country.

## Step 9 — Review

When every checklist item holds:

```bat
python scripts\external_forecasts.py review --registry config\external_forecasts\fmam_2026.json --record icpac_mam_2026_rainfall --reviewer "Your name"
python scripts\external_forecasts.py review --registry config\external_forecasts\fmam_2026.json --record emi_belg_2026_outlook --reviewer "Your name"
```

If something is wrong, use `--reject --note "what is wrong"`, correct the record, and run step 7 again. Editing a record after review sends it back to review automatically.

## Step 10 — Rerun, build the site and check

```bat
python scripts\run_operational.py --config config\cycles\jan_2026_fmam.json --workflow products --compare-external
python scripts\build_site.py
python -m http.server 8000 --directory site
```

Open `http://localhost:8000/?cycle=fmam2026` and go to the Outlooks section, "Official outlook comparison — FMAM 2026". Check:
- **Key findings:** ICPAC agreement with its compared area; "EMI — whole zones".
- **Maps:** the platform map with the four EMI zones on the left, and EMI's official figure on the right.
- **EMI table:** official values against the platform over the whole zone. There are no arrow columns for Belg.
- **ICPAC table:** rows "Within zone …" plus the two areas.
- **Area selector:** switching to the FMAM R2 domain changes the findings, and labels each zone by its overlap with the domain.

## Step 11 — Publish

Add a release entry at the end of `config\site_releases.json`, and set the previous entry's `"commit"` to the commit that published it. Then run `python -m unittest discover -s tests`, then `git add`, `git commit` and `git push`. Or ask me to do this part.

## Troubleshooting

| Message | Meaning and fix |
|---|---|
| `... not listed at https://www.icpac.net/seasonal-forecast/?year=2026` | `index_url` lacks `&resource_type=27&region=1` |
| `Legend boxes found: N, expected M` | the `intervals_top_down` lists don't match the boxes; count them in the image |
| `Tick count differs from the template` | `x_ticks_deg` / `y_ticks_deg` have the wrong number of labels |
| `Zone digitization failed` | a `fill_rgb` is missing or not a list of three numbers |
| `zone X probabilities must ... sum to 1` | a transcription error in step 6 |
| `EMI: no matching product has a PDF yet` | EMI pages exist but carry no document; the saved snapshot stays in use |
| `comparison withheld (stale: ...)` when building the site | an input changed after the comparison; rerun step 7 |
