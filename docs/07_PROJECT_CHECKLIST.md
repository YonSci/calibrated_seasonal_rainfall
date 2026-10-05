# 07 — Project checklist

> **Status update (2026-10-05):** Stages 1–4 have been carried out. The current checklist and progress are in [36_PROJECT_STATUS_REVIEW.md](36_PROJECT_STATUS_REVIEW.md).

## Stage 1 — workspace and environment

- [ ] Install Python 3.11 x64 and VS Code Python extension.
- [ ] Select CMD terminal.
- [ ] Bootstrap into a fresh project folder or extract ZIP.
- [ ] Run setup_project.cmd successfully.
- [ ] Verify .venv interpreter and retain environment logs.

## Stage 2 — data and preparation

- [ ] Confirm JJAS versus JJA and initialization.
- [ ] Enter actual ECMWF folder and CHIRPS file paths.
- [ ] Confirm source system provenance and observed units.
- [ ] Inventory all configured years; resolve missing/error entries.
- [ ] Run synthetic tests successfully on the local environment.
- [ ] Prepare 1993 and review totals/date checks.
- [ ] Prepare 2017, 2025, and 2026 to check operational structure.
- [ ] Prepare full archive and retain QC results.
- [ ] Share inspection summary, inventory JSON, and preparation QC for review.

## Stage 3 — implement calibration (next development stage)

- [ ] Select common grid/remapping, valid domain, and bounds.
- [ ] Implement shared equal-year-weighted amount correction.
- [ ] Implement training-fold observed thresholds.
- [ ] Generate fold-isolated probability calibration examples.
- [ ] Implement regularized Dirichlet with nested year-wise tuning.
- [ ] Validate on untouched 2017–2025 seasons.
- [ ] Evaluate ensemble-size sensitivity.
- [ ] Fix the final configuration and criteria for deploying recalibration.

## Stage 4 — final application

- [ ] Refit eligible history through 2025 with documented weights.
- [ ] Apply to all valid 2026 members.
- [ ] Save corrected rainfall and final probabilities separately.
- [ ] Produce metadata-driven maps and verification report.
- [ ] Archive configuration, fitted parameters, and resolved environment.

No checkbox is pre-marked as completed on your computer.
