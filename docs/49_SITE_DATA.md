# Site data contract and downloads

The results site has outgrown one generated page: `site/index.html` is 1.3 MB of HTML built by string concatenation in
`scripts/build_site.py`, `site_bias.py` and `site_prob.py`, and until release 2026-10-14.3 every data download was committed
with the site (181 MB of `site/`, and the git history grew with every build). This document describes the two steps taken so
far and the planned migration.

## 1. Downloads as GitHub release assets (`scripts/site_files.py`)

Data downloads (NetCDF, JSON, PDF, CSV; not HTML pages) of at least 100 kB are uploaded to one GitHub release, tag
[`site-files`](https://github.com/YonSci/calibrated_seasonal_rainfall/releases/tag/site-files), and the page, its data
files and the downloads listing link there; the files are removed from `site/`.

* **Content-addressed.** The asset name is `<first 16 hex digits of the SHA-256>-<path with / replaced by .>`. An asset never
  changes once uploaded, so every link published in any release keeps working, and unchanged files are never uploaded twice.
* **Manifest.** `config/site_files.json` lists every uploaded asset (SHA-256, size, first site path, URL). An entry is added
  only after a successful upload; when the build can reach GitHub, entries missing from the release are not linked.
* **Safe by default.** A file whose asset is not uploaded yet stays in `site/downloads/` and is linked locally, so a build
  never breaks the site.

```
python scripts/build_site.py --upload-files     # build, upload new download files, link them
python scripts/build_site.py                     # build; link files already uploaded, keep the others local
python scripts/build_site.py --keep-downloads    # every download local (previous behaviour)
```

The first upload (2026-10-13) moved 82 files, 183.5 MB, out of the site. The bulletins carry the build time, so each build
uploads new bulletin PDFs (about 0.3 MB each). The existing git history (605 MB) is unchanged: archived releases load their
files from it, so it is not rewritten.

## 2. The data contract (`scripts/site_data.py` → `site_data/`)

Every build also writes, separately from any HTML, the data the page shows:

| File | Content |
| --- | --- |
| `site_data/site.json` | schema version, current release, release history (`config/site_releases.json`), the page's sections, build time and code commit |
| `site_data/cycles.json` | the forecast cycles: exactly the data the current page's cycle selector uses (outlooks, maps, verification, downloads) |
| `site_data/files.json` | every download linked from the page: URL (release asset or site path), size, SHA-256 |
| `site_data/bias/<cycle>.json` | bias-correction benchmark (docs/47): screening, confirmation, MVS ratio-limit study, validation record, suggestion |
| `site_data/probcal/<cycle>.json` | probability and rainfall-distribution calibration (docs/48): Phases 1–3 and the amount/range shadow |

Benchmark files keep the structure of their full JSON outputs (documented in docs/47 and docs/48) but are slimmed: per-year
series (`per_year`), per-cell and other long numeric arrays, internal fields (`_…`) and verbatim protocol texts are dropped;
every summary score, test, decision and fitted parameter remains. The full files stay available as downloads. Figures and
maps are in `site/assets/` (paths in the data are relative to the site root). About 15 MB in all (indented, so changes between
releases diff and compress well; 2 MB compressed), committed with each release so that a front end can be built without the
large `outputs/` folder.

`schema_version` (now 1) is raised whenever a field a page reads is renamed or removed.

## 3. The Astro front end (`web/`)

The new pages are built with [Astro](https://astro.build) 7.3.5 (Node ≥ 22.12) from `site_data/` alone; figures and maps are
linked from `site/assets/`. They are served under `/next/` next to the current page while the migration runs, and updated
automatically: every build of the results refreshes `site_data/`, and the Pages workflow (`.github/workflows/pages.yml`)
rebuilds the Astro pages from it on each push, so new results (a new phase, a new verified season) appear without page edits.
The built pages are not committed (`site/next/` is ignored). If the Astro build fails, the workflow still publishes the
current site.

| Page | Content | Source |
| --- | --- | --- |
| `/next/` | the current outlook first (latest cycle, its domain, the season: headline, probabilities, map, amount, signal, skill), every target as a small map, what's new, other cycles, research | `site.json`, `cycles.json` |
| `/next/outlooks/` | every forecast cycle | `cycles.json` |
| `/next/outlooks/<cycle>/<area>/<target>/` | outlook (answer first), all targets as small maps with previous/next, map viewer, side panel: links to this target's verification and skill, the official outlooks, the cycle record | `cycles.json` |
| `/next/outlooks/<cycle>/<area>/<target>/verification/` | forecast vs observed chart and the verification narratives (selected target first) | `cycles.json` |
| `/next/outlooks/<cycle>/<area>/<target>/skill/` | historical skill, the verification explorer (both periods), regions | `cycles.json`, `data/<cycle>_diagnostics.json` |
| `/next/outlooks/<cycle>/<area>/official/` | official-outlook comparison (season) | `data/<cycle>_comparison.json` |
| `/next/probability-calibration/` | plan, definitions, cycles, references | `probcal/<cycle>.json` |
| `/next/probability-calibration/<cycle>/` | summary: what each phase tested and what was confirmed better, the shadow status | `probcal/<cycle>.json` |
| `/next/probability-calibration/<cycle>/{phase-1,phase-2,phase-3,shadow,downloads}/` | one sub-page per phase, the amount/range shadow, downloads | `probcal/<cycle>.json` |
| `/next/bias-correction/` | the benchmark and its cycles | `bias/<cycle>.json` |
| `/next/bias-correction/<cycle>/` | summary: what the evidence supports and the suggested method | `bias/<cycle>.json` |
| `/next/bias-correction/<cycle>/{interpretation,methods,screening,confirmation,ratio-limits,shadow,figures,downloads}/` | interpretation and caveats; data, methods and designs; screening (one region at a time, statistics, diagnostics); confirmation; ratio-limit study; shadow and validation; figure browser; files, provenance and references | `bias/<cycle>.json` |
| `/next/research/amount-shadow/` | the amount and range shadow of every cycle | `probcal/<cycle>.json` |
| `/next/downloads/` | every data file with size and SHA-256 | `files.json` |
| `/next/releases/` | change log, archived releases | `site.json` |

Navigation: the site menu puts the forecast first (Outlook, Verification, Skill), then Research and About menus and
Downloads. On forecast pages a context bar under the menu (breadcrumbs; cycle, area and target; section tabs Outlook and
maps · Official outlooks · Verification · Historical skill) stays with the page; changing a choice keeps the others and the
section. Research pages have the same kind of bar: breadcrumbs, the cycle (staying on the same sub-page) and the sub-pages
as tabs, with previous/next links at the bottom and, on wide screens, an "On this page" list of the headings. The addresses of release 2026-10-14.5 (`/<cycle>/<area>/verification/` and `/history/`) forward to the season's
pages.

Pages only display what the Python build decided: every ✓, confirmation and interpretation statement comes from the data
(the bias-correction interpretation statements are computed by `site_bias.findings` and exported as text). The benchmark
pages are checked number by number against the current page: every signed score of a cycle, collected over its summary and
sub-pages, is identical (582–641 values per bias-correction cycle, 169–206 per probability-calibration cycle). The outlook pages carry the current page's rendering code, ported to
build time; for every cycle, area and target the text of each section (outlook, targets, comparison, record, verification,
historical skill, regions and the explorer in both periods) was compared with the current page rendered in a browser.

Preview locally (Git Bash needs `MSYS_NO_PATHCONV=1` so the base path is not rewritten):

```
cd web && npm ci
MSYS_NO_PATHCONV=1 ASTRO_BASE=/next/ ASTRO_OUT=../site/next npm run build
cd ../site && python -m http.server 8765        # then open http://127.0.0.1:8765/next/
```

## 4. Next steps

1. ✓ Forecast outlooks, maps, verification and historical performance (one page per cycle, area and target).
2. Rainfall domains, methods and the cycle download packages.
3. Make the Astro pages the site root, and retire the HTML generation in `build_site.py`, `site_bias.py` and `site_prob.py`;
   the Python build keeps producing the results, figures, downloads and `site_data/`.

A server back end is not planned: everything shown is precomputed. Should on-demand queries be needed (e.g. a time series at
a clicked point), FastAPI with xarray over the NetCDF outputs fits the existing stack.

## 5. Operations: scoring each season as observations arrive

`scripts/watch_observations.py` runs daily (Windows scheduled task `SeasonalRainfall\WatchObservations`, 07:00, while the user is
logged on). For each cycle in `config/observation_watch.json` it asks the operational runner which targets have CHIRPS
published (read-only preflight); when a target becomes ready that was not ready before, it runs the verification workflow
for that cycle (observations, scores, report, views, the official-outlook comparison when the cycle enables it, the
bias-correction validation of every method and the amount/range shadow) and then the bias-correction suggestions. It never
publishes: rebuild the site (`python scripts/build_site.py --upload-files`), add a release entry and push to publish the new
scores. State and history: `outputs/observation_watch/status.json` and `watch.log`; a failed run is retried at the next check.
Remove a cycle from the watch list once every target is verified, and add new cycle files as they start.

```
python scripts/watch_observations.py --check     # what would be scored now
schtasks /Query /TN "SeasonalRainfall\WatchObservations"
schtasks /Delete /TN "SeasonalRainfall\WatchObservations" /F    # stop the daily check
```
