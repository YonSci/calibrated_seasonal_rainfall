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

## 3. Planned migration

1. ✓ Downloads as release assets.
2. ✓ Data contract.
3. **Astro front end** (static site generator; React components only where a page is interactive: cycle selector, maps,
   sortable tables), one page per topic: each cycle's outlook, verification, bias correction, probability calibration,
   domains, methods, releases. Built from `site_data/` and `site/assets/`, deployed to GitHub Pages by the existing workflow.
4. Retire the HTML generation in `build_site.py`, `site_bias.py` and `site_prob.py`; the Python build keeps producing the
   results, figures, downloads and `site_data/`.

A server back end is not planned: everything shown is precomputed. Should on-demand queries be needed (e.g. a time series at
a clicked point), FastAPI with xarray over the NetCDF outputs fits the existing stack.
