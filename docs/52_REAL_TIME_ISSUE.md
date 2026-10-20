# Real-time issue from 2027: forecasts frozen and published before their seasons

Until 2026 every cycle on the platform is a **research reconstruction**: made after its initialization date, recalibrated
with CHIRPS v3.0 when observations of the target period were already available. From 2027 each forecast is **issued in
real time**: produced as soon as SEAS5 for the initialization is available, frozen, and published before its target period,
so that anyone can check it existed, unchanged, before its outcome.

## 1. The issue step

After the forecast files exist (docs/40 section 2, steps 1–9, for the forecast year only):

    set CALIBRATION_CYCLE=config\cycles\jan_2027_fmam.json
    python scripts\issue_forecast.py --check        # report only
    python scripts\issue_forecast.py                # freeze, issue record, local tag forecast-<site_id>
    python scripts\issue_forecast.py --publish      # push the tag, create the public GitHub release

`issue_forecast.py` refuses when:
- every target period has already started;
- observations of a target month are already in the project;
- a forecast file is missing;
- code or configuration have uncommitted changes.

It never overwrites an issue. It runs the existing freeze (`prepare_verification_2026.py --freeze-only`) and checks the
manifest against the forecast files. It then writes `<verification_root>/frozen_forecasts/issue_record.json`, which holds:
- the issue time;
- the commit;
- the SHA-256 of each forecast file and of the manifest;
- the members used;
- for each target, whether it was issued before its own period started.

`--publish` checks the files are still the issued ones, pushes the tag and creates the GitHub release. The release holds
the forecast NetCDF files, the manifest and the record. GitHub stamps the release with its creation time: that is the
independent evidence of when the forecast existed.

**Targets already under way.** A target whose period has begun when the forecast is issued is issued *in season*, and is
labelled as such. A February-initialized FMAM forecast is the usual case: SEAS5 for 1 February appears around the 5th–13th,
so February and the FMAM season are issued in season, while March, April and May are issued before their periods. No
observation of any target period may be in the project at issue time.

## 2. What the platform says

`scripts/forecast_issue.py` (`issue_status`) reads the issue record and supplies every statement about a cycle's status:
- the "Publication status" and "Forecast record" lines of the status panel;
- the outlook badge;
- the map footers;
- the PDF bulletin, the package README and the metadata.

There are three cases:

| Issue record | Wording |
| --- | --- |
| none, or issued after every target period began | *Research reconstruction · not an official EMI or ICPAC forecast* |
| issued before the whole target period | *Forecast issued <date>, before the season · not an official EMI or ICPAC forecast* |
| issued with some targets already under way | *Forecast issued <date> (in season for <targets>) · not an official EMI or ICPAC forecast* |

Site-wide texts state what is true of both: no cycle is an official EMI or ICPAC forecast; cycles before 2027 are research
reconstructions.

## 3. Reminders

The daily check (`watch_observations.py`, cycles listed in `issue_cycles` of `config/observation_watch.json`) logs:
- from the 13th of the initialization month until the last target period starts: that the forecast is due, and how many days
  are left;
- issued but not yet published: a reminder to publish;
- once every target period has started without an issue: a missed issue.

It does not download, run or issue anything itself.

Issue windows for 2027, with SEAS5 on CDS by about the 13th:

| Cycle | Due from | Season starts | Margin |
| --- | --- | --- | --- |
| FMAM, January | 13 Jan | 1 Feb | about 2.5 weeks |
| FMAM, February | 13 Feb | 1 Feb (March 1 Mar) | in season for February and FMAM |
| JJAS, May | 13 May | 1 Jun | about 2.5 weeks |
| ONDJ, September | 13 Sep | 1 Oct | about 2.5 weeks |

## 4. Forecast members from 2027

From 2027 the forecasts use the **first 25 SEAS5 members** (member numbers 0–24, the same numbering as the 25-member
hindcasts), set by `member_policy` in the 2027 cycle files (`{"from_year": 2027, "use_first": 25}`):
- the full 51-member file is still downloaded and inventoried (`Cycle.archive_members`);
- `prepare_seasonal.py` keeps the first 25 members and records it (`member_subset` attribute);
- every later step (loader, verification checks, smoothing formula, freeze) therefore sees one consistent 25-member
  ensemble (`Cycle.members`).

Earlier years are unchanged: 25 members until 2016 and 51 for 2017–2026, as fitted and evaluated. The model initialization
line on the site states "the first 25 of 51, as the hindcasts".

## 5. Dry season on the tercile maps

Cells with too little reference rainfall for tercile limits (mostly the dry season, such as January in the east and the
west) have no tercile probabilities. The tercile maps now show them in their own colour, labelled
**Dry season: no tercile forecast**; previously they were grey, labelled "Ineligible in view". The amount maps are unchanged.

## 6. The 2027 cycle files

`config/cycles/`:
- `jan_2027_fmam.json`, `feb_2027_fmam.json` and `may_2027.json`: reference 1993–2026;
- `sep_2027_ondj.json`: reference 1993–2025, since the ONDJ 2026/27 season ends in January 2027.

Each has `member_policy`. The external comparison is switched off until the 2027 official outlooks are registered.
Prerequisites before each run, as in docs/40 section 5:
- 2026 CHIRPS added with `extend_observations.py`;
- the new model year in `archive_years` of the project configuration.

**Project configurations for 2027.** Each 2027 cycle has its own project configuration (`config/fmam/project_2027.json`,
`config/fmam_feb/project_2027.json`, `config/project_2027.json`, `config/ondj/project_2027.json`): the 2026 one with
`archive_years` to 2027 and `observation_years` to the end of the reference period (2026; ONDJ 2025). The 2026
configurations stay as they were, so the 2026 cycles and the benchmarks that fingerprint them are unchanged.

## 7. Readiness check

    python scripts/check_readiness.py                 # every cycle of issue_cycles (config/observation_watch.json)

Checks everything that can be checked before the initialization's SEAS5 exists, and says what to do and by when:
configuration (project years against the cycle, member policy, masks), inputs (SEAS5 raw files and processed files of the
reference years, the last reference year's CHIRPS with the command that adds it, SEAS5 SST), leakage (no forecast-year
CHIRPS in the project), shadows (amount, bias-correction validation, statistical downscaling), the issue window (SEAS5 on the
CDS from the 13th of the initialization month, the first target period, targets issued in season) and the tools (CDS
credentials, GitHub CLI login, disk space, a clean working tree). Nothing is downloaded or changed; the result is in
`outputs/readiness/readiness.json`.

**State on 2026-10-20:** no defects. The 2026 FMAM (January and February) and JJAS observations were added to the training
archive with `extend_observations.py` (checks passed: grids, missing-cell patterns, months summing to the season). Left:
the ONDJ 2025 observations for the September 2027 cycle (`prepare_seasonal.py --years 2025` with the 2027 ONDJ project
configuration, then the regrid and monthly steps; done when that cycle is prepared, since the regrid also rewrites the
SEAS5 2025 files the ONDJ benchmarks fingerprint), and, for each cycle, the run and issue in its window.
