"""The site's data contract: site_data/, written by every build (docs/49).

Everything a page shows, as JSON, separate from any HTML, so a front end (planned: Astro) can be built from site_data/ and the
figures in site/assets/ alone, without the large outputs/ folder:

  site_data/site.json            schema version, current release, release history, sections, build time and code commit
  site_data/cycles.json          forecast cycles: the same data the current page's cycle selector uses
  site_data/files.json           every download linked from the site: path -> URL (release asset or site path), size
  site_data/bias/<cycle>.json    bias-correction benchmark: screening, confirmation, ratio-limit study, validation record,
                                 suggestion (docs/47)
  site_data/probcal/<cycle>.json probability and rainfall-distribution calibration: Phases 1-3 and the amount/range shadow (docs/48)

Benchmark files keep their structure (documented in docs/47 and docs/48) but are slimmed: per-year series, per-cell values
and other long arrays are dropped (they remain in the full JSON downloads), leaving every summary score, test and decision.
"""
import json
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


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str) + '\n', encoding='utf-8', newline='\n')
    return path.stat().st_size


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).is_file() else None


def bias_files():
    import site_bias
    out = {}
    recs = read(site_bias.BENCH / 'recommendations.json')
    for b in site_bias.load_all():
        out[b['name']] = dict(
            benchmark=slim(b['data']), confirmation=slim(b['confirmation']),
            ratio_limits=slim(b['ratio']) if b['ratio'] else None,
            validation={str(y): slim(v) for y, v in b['validation'].items()},
            recommendation=next((c for c in (recs or {}).get('cycles', []) if c['name'] == b['name']), None),
            recommendation_rule=(recs or {}).get('rule_contents'), figures=f'assets/bias/{b["name"]}')
    return out


def probcal_files():
    import site_prob
    out = {}
    for b in site_prob.load_all():
        shadow = {str(y): {t: slim({k: v for k, v in r.items() if k != 'folder'}) for t, r in rows.items()}
                  for y, rows in b['shadow'].items()}
        out[b['name']] = dict(initialization_month=b['init'], season=b['season'], phase1=slim(b['data']),
                              phase2_binary=slim(b['binary']), phase2_distribution=slim(b['distribution']), phase3=slim(b['phase3']),
                              amount_shadow=shadow, shadow_config=read(ROOT / site_prob.SHADOW_CONFIG),
                              figures=f'assets/probcal/{b["name"]}')
    return out


def downloads(site):
    """Every download link of the page: site path or release-asset URL, with its size when known."""
    import re
    import site_files
    page = (site / 'index.html').read_text(encoding='utf-8')
    manifest = {v['url']: v for v in site_files.load_manifest()['assets'].values()}
    out = {}
    for href in sorted(set(re.findall(r'(?:href|src)(?:=|": ?)"((?:downloads/|https://github\.com/[^"]*/releases/download/)[^"#?]+)"', page))):
        local = site / href
        out[href] = dict(url=href, bytes=manifest[href]['bytes'] if href in manifest else (local.stat().st_size if local.is_file() else None),
                         sha256=manifest[href]['sha256'] if href in manifest else None)
    return out


def export(site, page_data, built, sha, release_id, releases, sections):
    """Write site_data/ from the built site and the result files; returns {file: bytes}."""
    if OUT.exists():
        shutil.rmtree(OUT)
    sizes = {}
    sizes['site.json'] = write(OUT / 'site.json', dict(
        schema_version=SCHEMA_VERSION, built_utc=built, code_commit=sha, release=release_id, releases=releases,
        sections=sections, assets='site/assets (figures and maps, paths relative to the site root)'))
    sizes['cycles.json'] = write(OUT / 'cycles.json', page_data)
    sizes['files.json'] = write(OUT / 'files.json', downloads(site))
    for name, obj in bias_files().items():
        sizes[f'bias/{name}.json'] = write(OUT / 'bias' / f'{name}.json', obj)
    for name, obj in probcal_files().items():
        sizes[f'probcal/{name}.json'] = write(OUT / 'probcal' / f'{name}.json', obj)
    return sizes
