"""The site's data contract: site_data/, written by every build (docs/49).

Everything a page shows, as JSON, separate from any HTML, so a front end (planned: Astro) can be built from site_data/ and the
figures in site/assets/ alone, without the large outputs/ folder:

  site_data/site.json            schema version, current release, release history, sections, build time and code commit
  site_data/cycles.json          forecast cycles: the same data the current page's cycle selector uses
  site_data/data/*.json          per cycle: the official-outlook comparison and the historical diagnostics (paths as in cycles.json)
  site_data/files.json           every download linked from the site: path -> URL (release asset or site path), size
  site_data/sections.json        prose sections written by the build as HTML (methods and data)
  site_data/selection.json       the approach selected for each season, target and product, with its evidence (docs/50)
  site_data/method_summary.json  every method against the published approach, all seasons (method_summary.py, docs/50)
  site_data/bias/<cycle>.json    bias-correction benchmark: screening, confirmation, ratio-limit study, validation record,
                                 suggestion (docs/47)
  site_data/probcal/<cycle>.json probability and rainfall-distribution calibration: Phases 1-3 and the amount/range shadow (docs/48)
  site_data/leung_dirichlet/<cycle>.json  Leung–Dirichlet calibration against the published pipeline (docs/51)

Benchmark files keep their structure (documented in docs/47 and docs/48) but are slimmed: per-year series, per-cell values
and other long arrays are dropped (they remain in the full JSON downloads), leaving every summary score, test and decision.
"""
import json
import math
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'site_data'
SCHEMA_VERSION = 1
DROP = {'per_year', 'example_cell_quantiles', 'config_json', 'protocol'}   # long series and verbatim texts
MAX_LIST = 60                                                                 # longer numeric lists are per-cell or per-year


def slim(x):
    if isinstance(x, dict):
        return {k: slim(v) for k, v in x.items() if k not in DROP and not k.startswith('_')}
    if isinstance(x, list):
        if len(x) > MAX_LIST and all(isinstance(v, (int, float)) or v is None for v in x):
            return None
        return [slim(v) for v in x]
    return x


def finite(x):
    """Strict JSON: NaN and infinities become null (the structure is otherwise unchanged)."""
    if isinstance(x, dict):
        return {k: finite(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [finite(v) for v in x]
    return None if isinstance(x, float) and not math.isfinite(x) else x


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(finite(obj), ensure_ascii=False, indent=1, default=str, allow_nan=False) + '\n', encoding='utf-8', newline='\n')
    return path.stat().st_size


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).is_file() else None


def assets(site, rel):
    """Figure files of a section, relative to the site root."""
    d = site / rel
    return sorted(f.relative_to(site).as_posix() for f in d.rglob('*') if f.is_file()) if d.is_dir() else []


def bias_files(site):
    import site_bias
    out = {}
    recs = read(site_bias.BENCH / 'recommendations.json')
    for b in site_bias.load_all():
        project = read(ROOT / b['data']['config_contents']['project_config'])
        found = site_bias.findings(site_bias.View(b['data'], b['confirmation']))   # statements checked against the numbers
        out[b['name']] = dict(
            findings=[t for ok, t in found if ok and t], findings_withheld=sum(1 for ok, _ in found if not ok), findings_checked=len(found),
            initialization_month=project['initialization_month'], season=project['season']['name'],
            observations='CHIRPS v3.0 monthly totals, averaged from 0.05° to 0.25°' if project.get('chirps_temporal') == 'monthly'
            else 'CHIRPS v2.0 daily totals',
            benchmark=slim(b['data']), confirmation=slim(b['confirmation']),
            ratio_limits=slim(b['ratio']) if b['ratio'] else None,
            validation={str(y): slim(v) for y, v in b['validation'].items()},
            recommendation=next((c for c in (recs or {}).get('cycles', []) if c['name'] == b['name']), None),
            recommendation_rule=(recs or {}).get('rule_contents'), figures=f'assets/bias/{b["name"]}',
            figure_kinds=[dict(pattern=pat.format(year=b['data']['config_contents']['forecast_year'], t='{t}'),
                               label=lab.format(year=b['data']['config_contents']['forecast_year']), per_target=per)
                          for pat, lab, per in site_bias.FIGURES],
            assets=assets(site, f'assets/bias/{b["name"]}'),
            references={k: dict(text=v[0], doi=v[1]) for k, v in site_bias.REFERENCES.items()})
    return out


def probcal_files(site):
    import site_prob
    out = {}
    for b in site_prob.load_all():
        shadow = {str(y): {t: slim({k: v for k, v in r.items() if k != 'folder'}) for t, r in rows.items()}
                  for y, rows in b['shadow'].items()}
        out[b['name']] = dict(initialization_month=b['init'], season=b['season'], phase1=slim(b['data']),
                              phase2_binary=slim(b['binary']), phase2_distribution=slim(b['distribution']), phase3=slim(b['phase3']),
                              amount_shadow=shadow, shadow_config=read(ROOT / site_prob.SHADOW_CONFIG),
                              figures=f'assets/probcal/{b["name"]}', assets=assets(site, f'assets/probcal/{b["name"]}'),
                              plan=[dict(phase=ph, key=k, name=n, family=fam, output=o) for ph, k, n, fam, o in site_prob.PLAN],
                              references=[dict(html=t, url=u) for t, u in site_prob.REFERENCES])
    return out


def leung_dirichlet_files(site):
    """Leung–Dirichlet calibration compared with the published pipeline (scripts/leung_dirichlet_benchmark.py, docs/51);
    the display names come from scripts/leung_dirichlet.py, not from the saved results."""
    import leung_dirichlet as ldc
    import site_files
    by_hash = {v['sha256']: v['url'] for v in site_files.load_manifest()['assets'].values()}
    out = {}
    for f in sorted((ROOT / 'outputs/leung_dirichlet').glob('*/benchmark.json')):
        name = f.parent.name
        d = read(f)
        d.pop('protocol', None)
        files = []                                   # release-asset URL when uploaded, else the site path
        for src in [f] + sorted((f.parent / 'forecast').glob('*.nc')):
            local = f'downloads/leung_dirichlet/{name}/{src.name}'
            url = by_hash.get(site_files.sha256(src)) or (local if (site / local).is_file() else None)
            if url:
                files.append(url)
        out[name] = dict(slim(d), labels=ldc.LONG, short=ldc.SHORT, name=ldc.NAME, credit=ldc.CREDIT,
                         assets=assets(site, f'assets/leung_dirichlet/{name}'), downloads=files)
    return out


def downloads(site):
    """Every download link of the page: site path or release-asset URL, with its size when known."""
    import re
    import site_files
    page = (site / 'index.html').read_text(encoding='utf-8')
    manifest = {v['url']: v for v in site_files.load_manifest()['assets'].values()}
    labels = {h: re.sub(r'<[^>]+>', '', t).strip() for h, t in re.findall(r'<a href="([^"]+)"[^>]*>(.*?)</a>', page, re.S)}
    out = {}
    for href in sorted(set(re.findall(r'(?:href|src)(?:=|": ?)"((?:downloads/|https://github\.com/[^"]*/releases/download/)[^"#?]+)"', page))):
        local = site / href
        m = manifest.get(href)
        out[href] = dict(url=href, path=m['first_path'] if m else href, label=labels.get(href),
                         bytes=m['bytes'] if m else (local.stat().st_size if local.is_file() else None), sha256=m['sha256'] if m else None)
    return out


def sections_html(site):
    """Prose sections written by the build as HTML (methods and data), for pages that show them unchanged."""
    import re
    page = (site / 'index.html').read_text(encoding='utf-8')
    m = re.search(r'<section id="methods" class="wrap">(.*?)</section>', page, re.S)
    return dict(methods=m.group(1) if m else None)


def export(site, page_data, built, sha, release_id, releases, sections):
    """Write site_data/ from the built site and the result files; returns {file: bytes}."""
    if OUT.exists():
        shutil.rmtree(OUT)
    sizes = {}
    sizes['site.json'] = write(OUT / 'site.json', dict(
        schema_version=SCHEMA_VERSION, built_utc=built, code_commit=sha, release=release_id, releases=releases,
        change_types=__import__('site_extras').CHANGE_TYPES,
        sections=sections, assets='site/assets (figures and maps, paths relative to the site root)'))
    sizes['cycles.json'] = write(OUT / 'cycles.json', page_data)
    for f in sorted((site / 'data').glob('*.json')):          # per-cycle comparison and diagnostics, at the same relative paths
        sizes[f'data/{f.name}'] = write(OUT / 'data' / f.name, json.loads(f.read_text(encoding='utf-8')))
    sizes['files.json'] = write(OUT / 'files.json', downloads(site))
    sizes['sections.json'] = write(OUT / 'sections.json', sections_html(site))
    sel = read(ROOT / 'outputs/method_selection/selection.json')               # method selection (scripts/method_selection.py)
    if sel:
        sizes['selection.json'] = write(OUT / 'selection.json', sel)
    summary = read(ROOT / 'outputs/method_selection/summary.json')         # every method against the published approach
    if summary:
        summary.pop('protocol', None)
        sizes['method_summary.json'] = write(OUT / 'method_summary.json', summary)
    for name, obj in bias_files(site).items():
        sizes[f'bias/{name}.json'] = write(OUT / 'bias' / f'{name}.json', obj)
    for name, obj in probcal_files(site).items():
        sizes[f'probcal/{name}.json'] = write(OUT / 'probcal' / f'{name}.json', obj)
    for name, obj in leung_dirichlet_files(site).items():
        sizes[f'leung_dirichlet/{name}.json'] = write(OUT / 'leung_dirichlet' / f'{name}.json', obj)
    return sizes
