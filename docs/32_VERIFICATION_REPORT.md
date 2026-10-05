# Step 32 — Consolidated 2026 verification report

## Purpose

Complete the June–August assessment by combining country scores, the main
JJAS rainfall domain, individual rainfall regimes, regional limitations,
historical comparisons and the original verification maps.

The report is a **post-event verification addendum**. It preserves the frozen
forecasts and does not fit a revised calibration model. It does not alter
probabilities, rainfall amounts, eligibility masks or historical weights.

## What is already included

The `completed_report` folder contains a report generated from your actual
uploaded June–August country and regime summaries, your earlier historical
evidence, and your three verification map PNGs. No synthetic results are
included.

- `VERIFICATION_REPORT.html`: portable offline report with embedded maps.
- `VERIFICATION_REPORT.md`: editable Markdown version, with companion maps.
- `VERIFICATION_ADDENDUM.md`: concise notes to accompany the archived forecast
  bulletin or delivery package.
- `report_summary.json`: explicit target-completion status, source hashes and
  machine-readable performance notes.
- `maps/`: unchanged copies of the June, July and August verification maps.

The HTML can be opened directly in a browser and shared as one file. It does
not load images, scripts, fonts or analytics from external services. Use the
browser's Print command if a printed copy is needed; no separate PDF has been
generated or quality-checked in this update.

The delivered report checks consistency between the uploaded reports. It does
not claim that all source NetCDF files were re-opened here. The client script
below additionally checks the local frozen forecasts and Step 30 file hashes.

## 1. Install

Merge the update's `scripts`, `docs`, `tests`, and `completed_report` folders into:

```text
D:\calibrated_seasonal_rainfall
```

Keep the Step 30 and Step 31 scripts, including `followup_common.py` and
`verify2026_outputs.py`. No new Python dependencies are needed.

The `completed_report` folder supplies the ready-to-read report and the small
evidence snapshots used by the optional tests. Keep it if you intend to run
those tests. You do not need to replace your project's existing README.

The two new scripts are:

```text
scripts\build_verification_report.py
scripts\verification_report_core.py
```

## 2. Rebuild the report from your local results

In the VS Code **CMD** terminal:

```bat
cd /d D:\calibrated_seasonal_rainfall
.venv\Scripts\activate
python scripts\build_verification_report.py --targets Jun Jul Aug --regenerate
start "" "outputs\verification_report_2026\Jun_Jul_Aug\VERIFICATION_REPORT.html"
```

The script reads:

```text
outputs\verification_2026\frozen_forecasts\freeze_manifest.json
outputs\verification_2026\results\TARGET\verification_report.json
outputs\verification_2026\results\TARGET\verification_fields.nc
outputs\verification_2026\results\TARGET\verification_maps.png
outputs\verification_2026\observations\TARGET\chirps_2026_common.nc
outputs\verification_followup\regimes\Jun_Jul_Aug\regime_verification_summary.json
outputs\verification_followup\historical\historical_blend_review.json
```

Historical comparisons are optional: if the historical review is absent, that
section is explicitly marked unavailable. Existing maps are included when
present. A missing map does not remove its numerical verification results.

The script checks:

1. Frozen forecasts against their existing manifest, before and after report
   construction. Original forecast paths are also checked when available.
2. That the regime report references the same frozen assessment.
3. Current Step 30 report, field and observation hashes against the Step 31
   provenance, preventing mixed output generations.
4. Country/regime agreement, probability skill arithmetic and category-score
   identities.
5. That the disjoint regimes reconstruct the country scores with area weights.

`--regenerate` preserves an existing report folder in a timestamped backup.
All new outputs are under `outputs\verification_report_2026`; archived
forecasts and the original forecast delivery package are not overwritten.

## 3. How the regional annotations work

The report includes:

- Positive/negative corrected CRPSS relative to climatology.
- Positive/negative final RPSS relative to climatology.
- Whether blending improved or worsened RPS relative to corrected-smoothed
  probabilities on the same support.
- Corrected mean rainfall error and probability coverage.
- Categories with negative final Brier Skill Scores.

These are direct comparisons of observed 2026 scores. No new subjective
confidence classes are introduced. The annotations are not available at May
forecast issuance and must not be presented as forecast-time confidence.

Specific findings retained in the report include June R0 performance below
climatology, July R2's remaining rainfall overestimate, and August R3's
improvement after blending despite a small final overall probability skill.
The report also notes August R3's negative above-normal-category Brier Skill
Score, which is not visible from RPS alone.

## 4. September and JJAS completion

The official CHIRPS v2 archive was checked on 4 October 2026. It listed the
June, July and August daily monthly files, but not September:

https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/netcdf/p25/by_month/

The delivered report therefore marks September and JJAS as pending. It does
not manufacture a full-season score from the available months.

Recheck with the existing Step 31 command:

```bat
python scripts\complete_verification_2026.py --check
```

When ready to attempt completion:

```bat
python scripts\complete_verification_2026.py --run --regenerate
```

This command reports `WAITING` if all official monthly files are not confirmed
available. On successful completion it prepares all four months, verifies all
five targets and produces the corresponding regime summary. Data preparation
still has to pass the calendar, units, grid and historical-overlap checks.

Only **after that command reports successful verification of September and
JJAS**, build the complete report:

```bat
python scripts\build_verification_report.py --targets Jun Jul Aug Sep JJAS --regenerate
start "" "outputs\verification_report_2026\Jun_Jul_Aug_Sep_JJAS\VERIFICATION_REPORT.html"
```

There is no scheduled task or automatic retry. The existing frozen JJAS
forecast is verified directly against its complete observed seasonal total;
monthly scores or probabilities are never combined into a substitute.

## 5. Interpretation boundaries

- These are retrospective reconstructed forecasts, not evidence of an actual
  May 2026 operational issuance or an official EMI/ICPAC product.
- A positive skill percentage is a reduction in the stated score relative
  to climatology, not a forecast-accuracy percentage.
- The current method is amount correction, alpha=0.5 smoothing and a shared
  climatology blend; no experimental Dirichlet/local/regime mapping was
  adopted in the final product.
- One year cannot establish long-term reliability or significance. The
  spatial cells and monthly/JJAS targets are dependent.
- Amount and probability eligibility differ. Unscored cells are not normal
  conditions, and removing weak regions does not establish improvement.
- The historical and final 2026 fits use different training periods. The
  inspected 2026 outcomes cannot serve as an untouched test set for a new
  method developed in response to them.

## 6. Troubleshooting

| Message | Action |
|---|---|
| Missing `followup_common` or `verify2026_outputs` | Retain the Step 30/31 scripts in the same project `scripts` folder |
| Missing regime summary | Run `verify_2026_regimes.py` for the requested targets first |
| Step 30 inputs changed after Step 31 | Regenerate the corresponding regime summary, then rebuild the report |
| Wrong frozen assessment or changed forecast | Investigate the changed input; do not delete the manifest to bypass the check |
| Full-season files missing | Complete verification first; use June–August targets until then |
| Output already exists | Add `--regenerate` to retain a backup and rebuild |

For a nonstandard regime summary path, use `--regime-summary PATH`.

Optional test command:

```bat
python tests\test_verification_report.py
```

## 7. What remains

June–August reporting is complete. The remaining step for this forecast cycle
is observation availability and verification for September/JJAS. No further
calibration change is required to complete this assessment.
