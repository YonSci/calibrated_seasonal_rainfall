"""The site's data contract: site_data/, written by every build (docs/49).

Everything a page shows, as JSON, separate from any HTML, so a front end (planned: Astro) can be built from site_data/ and the
figures in site/assets/ alone, without the large outputs/ folder:

  site_data/site.json            schema version, current release, release history, sections, build time and code commit
  site_data/cycles.json          forecast cycles: the same data the current page's cycle selector uses
  site_data/data/*.json          per cycle: the official-outlook comparison and the historical diagnostics (paths as in cycles.json)
  site_data/files.json           every download linked from the site: path -> URL (release asset or site path), size
  site_data/bias/<cycle>.json    bias-correction benchmark: screening, confirmation, ratio-limit study, validation record,
                                 suggestion (docs/47)
  site_data/probcal/<cycle>.json probability and rainfall-distribution calibration: Phases 1-3 and the amount/range shadow (docs/48)

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
    for name, obj in bias_files(site).items():
        sizes[f'bias/{name}.json'] = write(OUT / 'bias' / f'{name}.json', obj)
    for name, obj in probcal_files(site).items():
        sizes[f'probcal/{name}.json'] = write(OUT / 'probcal' / f'{name}.json', obj)
    return sizes
