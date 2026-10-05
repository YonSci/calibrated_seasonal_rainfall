# 05 — Quality safeguards and acceptance gates

> **Status update (2026-10-05):** gates marked "Planned" below are now implemented (regridding, leakage-safe folds, probability checks, 2017–2025 validation, freeze manifests). The physical land/ocean mask is still open. See [36_PROJECT_STATUS_REVIEW.md](36_PROJECT_STATUS_REVIEW.md).

| Gate | Pass criterion | Current support |
| --- | --- | --- |
| Environment | Imports, pip consistency, executable in project venv | Setup/check scripts |
| Provenance | Source system and download history documented | Manual; counts do not prove SEAS5 |
| Metadata | Explicit variable/dimension/unit contract | Inspect/prepare |
| Time | First +24h, all intervals daily, correct start labels | Prepare |
| Accumulations | No significant negative increments; seasonal sum telescopes | Prepare |
| Completeness | Full season per valid member/pixel | Prepare |
| Ensemble | Actual 25/51 counts, no fake member padding | Inspect/prepare |
| Grid | Confirmed bounds, remapping and mask | Planned |
| Leakage | All fitted statistics excluded from held-out seasons | Planned |
| Probabilities | Finite, bounded, sum one; valid-member denominator | Planned |
| Validation | Independent-year scores against baselines | Planned |
| Final labels | Correct init/season/reference/system/member count | Planned |

The inspection checks one sample accumulation series; full spatial checking happens in preparation. CHIRPS spatial NaNs are preserved. Do not fill missing daily rainfall with zero. For dry locations, degenerate terciles require a documented mask or rule in the later calibration stage.

Reports record source paths and configuration. Original input files are read-only by convention: scripts never call a write operation on them. Derived per-year NetCDFs are written through temporary files and replaced only after successful serialization. Do not run multiple preparation commands for the same output year concurrently.

A conservative-grid implementation should verify valid-data coverage as well as area weights; regridding across missing pixels must not manufacture complete observational seasons.

Member count changes affect probability granularity and sampling noise. The final modeling decision must follow held-out-year evaluation, not visual agreement with a preferred map.

Before production, retain a source-file inventory with file sizes and checksums, dataset provenance, resolved dependencies, config, Git commit if applicable, and run identifiers. Checksumming multi-GB originals is intentionally not done automatically by this first lightweight inventory.
