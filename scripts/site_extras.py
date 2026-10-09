"""Helpers for scripts/build_site.py: diagnostics export, comparison figures, PDF bulletin,
download-package metadata and the release archive. Everything is built from files the
pipeline already produced; nothing is refitted.
"""
import json
import re
import subprocess
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPO = 'https://github.com/YonSci/calibrated_seasonal_rainfall'
RAW = 'https://raw.githubusercontent.com/YonSci/calibrated_seasonal_rainfall'
CAT = ['below normal', 'near normal', 'above normal']
CAT_COLOURS = ['#eb6834', '#a9a7a0', '#1baf7a']
RELEASES = ROOT / 'config/site_releases.json'
CHANGE_TYPES = {
    'verification': 'New verification observations',
    'display': 'Display or explanatory-text change',
    'domain': 'Rainfall-domain presentation update',
    'analysis': 'New evidence or diagnostics (method unchanged)',
    'method': 'Change to the scientific method',
}


def rounded(x, d=4):
    if isinstance(x, float):
        return round(x, d)
    if isinstance(x, dict):
        return {k: rounded(v, d) for k, v in x.items()}
    if isinstance(x, list):
        return [rounded(v, d) for v in x]
    return x


# ---------------------------------------------------------------- historical diagnostics
def export_diagnostics(tag, cid, views, out):
    """Copy outputs/historical_diagnostics/<tag>_diagnostics.json (rounded) to site/data/; None if not generated."""
    src = ROOT / f'outputs/historical_diagnostics/{tag}_diagnostics.json'
    if not src.is_file():
        return None
    d = json.loads(src.read_text(encoding='utf-8'))
    keep = dict(created_utc=d['created_utc'], areas=[a for a in d['areas'] if a in dict(views)],
                targets=rounded(d['targets']), amount=rounded(d.get('amount', {})))
    rel = f'data/{cid}_diagnostics.json'
    (out / 'data').mkdir(parents=True, exist_ok=True)
    (out / rel).write_text(json.dumps(keep, separators=(',', ':')), encoding='utf-8', newline='')
    return rel


# ---------------------------------------------------------------- comparison figures
def comparison_images(folder):
    """Forecast | observed anomaly (same colour scale), and the same with the error map, from the cropped panels."""
    from PIL import Image
    names = ['verification_forecast_anomaly', 'verification_observed_anomaly', 'verification_error']
    if not all((folder / f'{n}.png').is_file() for n in names):
        return []
    ims = [Image.open(folder / f'{n}.png').convert('RGB') for n in names]
    for count, name in [(2, 'verification_comparison'), (3, 'verification_comparison_error')]:
        w, h = sum(i.width for i in ims[:count]), max(i.height for i in ims[:count])
        canvas = Image.new('RGB', (w, h), 'white')
        x = 0
        for im in ims[:count]:
            canvas.paste(im, (x, 0))
            x += im.width
        canvas.save(folder / f'{name}.png', optimize=True)
    for im in ims:
        im.close()
    return [['verification_comparison', 'Compare forecast and observed'],
            ['verification_comparison_error', 'Compare with error map']]


# ---------------------------------------------------------------- wording shared with the page
def signal(p):
    if not p or any(x is None for x in p):
        return -1, 'Not available'
    k = int(np.argmax(p))
    shift = p[k] - 1 / 3
    word = None if shift < .04 else 'Weak' if shift < .10 else 'Moderate' if shift < .20 else 'Strong'
    return (k, f'{word} tilt toward {CAT[k]}') if word else (-1, 'No clear tilt (close to climatology)')


def skill_word(h):
    if not h:
        return '—'
    if h['ci'][0] > 0:
        size = 'Small' if h['rpss'] < .03 else 'Modest' if h['rpss'] < .10 else 'Moderate'
        return f'{size} improvement over climatology (interval above zero)'
    return 'Small estimated improvement; skill uncertain' if h['rpss'] > 0 else 'No demonstrated improvement over climatology'


def sgn(x, d=0):
    if x is None:
        return '—'
    return f'{0:.{d}f}' if round(x, d) == 0 else f'{x:+.{d}f}'.replace('-', '−')


def area_history(t, view):
    own = t['history'].get(view)
    if own and own.get('training'):
        return own, False
    return t['history']['all_ethiopia'], view != 'all_ethiopia'


def interpretation(cyc, t, view):
    s = t['forecast'][view]['summary']
    p = s['mean_local_probabilities']
    k, _ = signal(p)
    label = dict(cyc['views'])[view]
    where = 'across Ethiopia' if view == 'all_ethiopia' else f'in the {label}'
    text = (f'The forecast leans toward {CAT[k]} rainfall {where}: averaged over the area, the local probability of '
            f'{CAT[k]} is {100 * p[k]:.0f}%, against about 33% for climatology.' if k >= 0 else
            f'The forecast is close to climatology {where}: no tercile stands out on average.')
    ref = s['mean_reference_mm']
    pct = f', {sgn(100 * s["mean_anomaly_mm"] / ref)}%' if ref else ''
    return text + (f' Mean forecast rainfall is {s["mean_rainfall_mm"]:.0f} mm against a {cyc["reference"]} average of '
                   f'{ref:.0f} mm ({sgn(s["mean_anomaly_mm"])} mm{pct}).')


# ---------------------------------------------------------------- PDF bulletin
def _image(ax, path, width=1100):
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert('RGB')
        im = im.resize((width, int(im.height * width / im.width)), Image.LANCZOS)
        ax.imshow(np.asarray(im))
    ax.axis('off')


def _wrap(fig, x, y, text, width, size=9.5, **kw):
    lines = textwrap.wrap(text, width)
    fig.text(x, y, '\n'.join(lines), fontsize=size, va='top', linespacing=1.35, **kw)
    return y - len(lines) * size * 1.35 / 72 / fig.get_figheight() - .008


def bulletin_pdf(cyc, out_pdf, built, site):
    """Three-page A4 bulletin for the cycle's rainfall domain: outlook, evidence and record, monthly maps."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    view = cyc['domain_view']
    area = dict(cyc['views'])[view]
    season = cyc['targets'][0]
    s = season['forecast'][view]['summary']
    p = s['mean_local_probabilities']
    ink, muted, amber = '#0b0b0b', '#52514e', '#8a5a00'
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(out_pdf) as pdf:
        # ---- page 1: outlook
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.text(.07, .955, f'{season["label"]} rainfall outlook', fontsize=20, weight='bold', color=ink)
        fig.text(.07, .932, f'ECMWF SEAS5 initialized 1 {cyc["init"]} {cyc["init_date"][:4]} · calibrated with CHIRPS v2.0 · {area}',
                 fontsize=9.5, color=muted)
        fig.text(.07, .912, 'Research reconstruction — not an official EMI or ICPAC forecast', fontsize=9, color=amber, weight='bold')
        y = _wrap(fig, .07, .89, interpretation(cyc, season, view), 98, 10.5, color=ink)
        ax = fig.add_axes([.07, y - .03, .86, .022])
        left = 0
        for i, v in enumerate(p):
            ax.barh(0, v, left=left, color=CAT_COLOURS[i], height=1, edgecolor='white', linewidth=1.5)
            left += v
        ax.set_xlim(0, 1)
        ax.axis('off')
        fig.text(.07, y - .05, '      '.join(f'{c.capitalize()} {100 * v:.0f}%' for c, v in zip(CAT, p)), fontsize=9, color=ink,
                 weight='bold')
        y -= .07
        y = _wrap(fig, .07, y, 'Average local probability: each grid cell has its own tercile probabilities; these are their '
                  f'averages over the {s["probability_domain_area_percent"]:.0f}% of the area that has probabilities, not the '
                  'probability that the area-total rainfall falls in a category.', 110, 8, color=muted)
        h, fallback = area_history(season, view)
        tr = h['training']
        k, sig_text = signal(p)
        y = _wrap(fig, .07, y, f'Forecast signal: {sig_text} (largest area-average probability compared with a one-third '
                  'reference; based on probabilities only).', 110, 8.5, color=ink)
        y = _wrap(fig, .07, y, f'Historical skill ({"All Ethiopia" if fallback else area}): {skill_word(tr)}. Probability skill '
                  f'(RPSS) {sgn(tr["rpss"], 3)}, cross-validated {tr["first"]}–{tr["last"]}, 95% interval {sgn(tr["ci"][0], 3)} to '
                  f'{sgn(tr["ci"][1], 3)}; better than climatology in {tr["better"]} of {tr["years"]} years. A strong signal is not '
                  'a confidence rating.', 110, 8.5, color=ink)
        ax = fig.add_axes([.04, .04, .92, y - .06])
        _image(ax, site / season['forecast'][view]['folder'] / 'tercile_outlook.png')
        ax.set_anchor('N')
        fig.text(.5, .025, f'Built {built} · {REPO}', ha='center', fontsize=7, color=muted)
        pdf.savefig(fig)
        plt.close(fig)

        # ---- page 2: targets, evidence, record
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.text(.07, .955, 'All targets, evidence and record', fontsize=15, weight='bold', color=ink)
        fig.text(.07, .935, f'{cyc["option"]} · {area}', fontsize=9, color=muted)

        def tab(top, rows, cols, widths, height):
            ax = fig.add_axes([.07, top - height, .86, height])
            ax.axis('off')
            tb = ax.table(cellText=rows, colLabels=cols, colWidths=widths, loc='upper left', cellLoc='left')
            tb.auto_set_font_size(False)
            tb.set_fontsize(7)
            tb.scale(1, 1.35)
            for (r, _), cell in tb.get_celld().items():
                cell.set_edgecolor('#e1e0dc')
                if r == 0:
                    cell.set_facecolor('#e6f1ed')
                    cell.set_text_props(weight='bold')
            return top - height - .035

        rows = []
        for t in cyc['targets']:
            v = t['forecast'][view]['summary']
            rows.append([t['label'], ' / '.join('—' if z is None else f'{100 * z:.0f}%' for z in v['mean_local_probabilities']),
                         f'{v["probability_domain_area_percent"]:.0f}%', f'{sgn(v["mean_anomaly_mm"])} mm',
                         textwrap.shorten(t['status']['text'].replace('Awaiting CHIRPS observations: ', 'Awaiting CHIRPS: ')
                                          .replace(' in the checked CHIRPS listing', '').replace(' (last checked', ' (checked'), 70, placeholder=' …')])
        y = tab(.915, rows, ['Target', 'Below/near/above', 'Coverage', 'Anomaly', 'Verification status'],
                [.11, .15, .1, .08, .56], .0205 * (len(rows) + 1))
        fig.text(.07, y + .012, 'Historical skill, cross-validated (probability skill, RPSS, with whole-year 95% interval)', fontsize=9,
                 weight='bold', color=ink)
        rows = []
        for t in cyc['targets']:
            hh, _ = area_history(t, view)
            r = hh['training']
            rows.append([t['id'], f'{sgn(r["rpss"], 3)} ({sgn(r["ci"][0], 3)} to {sgn(r["ci"][1], 3)})', f'{r["better"]}/{r["years"]}',
                         f'{r.get("holm_p", float("nan")):.3f}', skill_word(r)])
        y = tab(y - .005, rows, ['Target', 'RPSS (95% interval)', 'Yrs better', 'Holm p', 'In words'],
                [.07, .22, .09, .11, .51], .0205 * (len(rows) + 1))
        done = [t for t in cyc['targets'] if t['verification'].get(view)]
        fig.text(.07, y + .012, 'Verification against CHIRPS (single season or month)', fontsize=9, weight='bold', color=ink)
        if done:
            rows = []
            for t in done:
                v = t['verification'][view]['summary']
                rows.append([t['label'], sgn(v['probability']['shared_blend']['rpss'], 3), sgn(v['amount']['corrected']['crpss'], 3),
                             f'{sgn(v["amount"]["corrected"]["bias_mm"], 1)} mm', f'{sgn(v["forecast_mean_anomaly_mm"])} / {sgn(v["observed_mean_anomaly_mm"])} mm',
                             ' / '.join(f'{100 * z:.0f}%' for z in v['observed_category_area_fractions'])])
            y = tab(y - .005, rows, ['Target', 'RPSS', 'CRPSS', 'Bias', 'Forecast / observed anomaly', 'Observed below/near/above'],
                    [.12, .1, .1, .12, .26, .3], .0205 * (len(rows) + 1))
        else:
            y = _wrap(fig, .07, y - .01, 'No target has been verified yet.', 110, 8.5, color=muted) - .02
        fig.text(.07, y + .012, 'Cycle record', fontsize=9, weight='bold', color=ink)
        y -= .005
        for k_, v_ in cyc['meta']:
            y = _wrap(fig, .07, y, f'{k_}: {v_}', 118, 7.8, color=ink)
        y = _wrap(fig, .07, y - .01, 'How to read: terciles split the reference-period rainfall into three equally likely parts. '
                  'Climatology assigns about one-third to each (the observed tercile frequencies of the training years). Skill '
                  'scores are decimals: +0.05 means a 5% lower score than climatology. RPSS refers to the blended probabilities; '
                  'CRPSS and bias to the amount-corrected ensemble.', 118, 7.8, color=muted)
        _wrap(fig, .07, y - .005, 'Limitations: few evaluation years and single verification seasons give wide uncertainty; '
              'the 0.25° maps repeat ~1° model information; the rainfall domain is for display and summaries only.', 118, 7.8,
              color=muted)
        pdf.savefig(fig)
        plt.close(fig)

        # ---- page 3: monthly tercile maps
        months = [t for t in cyc['targets'] if t['kind'] == 'month']
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.text(.07, .955, 'Monthly tercile outlooks', fontsize=15, weight='bold', color=ink)
        fig.text(.07, .935, f'{cyc["option"]} · {area}', fontsize=9, color=muted)
        for i, t in enumerate(months[:4]):
            r, c = divmod(i, 2)
            ax = fig.add_axes([.01 + c * .49, .52 - r * .42, .48, .4])
            _image(ax, site / t['forecast'][view]['folder'] / 'tercile_outlook.png', 900)
            ax.set_anchor('N')
        pdf.savefig(fig)
        plt.close(fig)


# ---------------------------------------------------------------- package metadata
def package_readme(cyc, built, release_id):
    view = cyc['domain_view']
    season = cyc['targets'][0]
    lines = [
        f'{cyc["option"]} - forecast and evidence package',
        '=' * 60,
        '',
        'Research reconstruction; not an official EMI or ICPAC forecast.',
        f'Built {built} (site release {release_id}) from {REPO}',
        '',
        'What this forecast is',
        '---------------------',
        textwrap.fill(interpretation(cyc, season, view), 90),
        '',
        *[f'{k}: {v}' for k, v in cyc['meta']],
        f'Rainfall domain: {cyc["definition"]}',
        '',
        'Contents',
        '--------',
        'bulletin.pdf            Outlook, interpretation, evidence, record and monthly maps',
        'summary.csv             Every target and area: probabilities, amounts, coverage, status, verification scores',
        'metadata.json           Initialization, target dates, reference period, method version, freeze status, files',
        'maps/forecast/...       PNG maps per target and area: tercile, total, anomaly (mm and %)',
        'maps/verification/...   Verification panels, comparison figures and the six-panel figure (verified targets)',
        'reports/                Verification reports (HTML), where verification exists',
        'data/                   Forecast NetCDF files per target (0.25 deg; corrected ensemble, probabilities)',
        '',
        'How to read',
        '-----------',
        textwrap.fill('Terciles split the reference-period CHIRPS rainfall into three equally likely parts; climatology '
                      'assigns about one-third to each (the observed tercile frequencies of the training years). Area '
                      'probabilities are averages of grid-cell probabilities, not probabilities of the area-total rainfall. '
                      'Skill scores are decimals: +0.05 means a 5% lower score than climatology. RPSS refers to the blended '
                      'probabilities, CRPSS and bias to the amount-corrected ensemble.', 90),
        '',
        'Sources and attribution',
        '-----------------------',
        'Contains modified Copernicus Climate Change Service information (ECMWF SEAS5, system 51).',
        'CHIRPS v2.0: Climate Hazards Center, UC Santa Barbara.',
    ]
    return '\n'.join(lines) + '\n'


def package_metadata(cyc, built, release_id, sha, files):
    return dict(cycle=cyc['label'], initialization=cyc['init_date'], initialization_month=cyc['init'],
                built_utc=built, release=release_id, code_version=sha, repository=REPO,
                record={k: v for k, v in cyc['meta']}, rainfall_domain=dict(view=cyc['domain_view'], definition=cyc['definition']),
                reference_period=cyc['reference'],
                targets=[dict(target=t['label'], start=t['start'], end=t['end'], status=t['status'],
                              verified_areas=sorted(t['verification'])) for t in cyc['targets']],
                files=[f for _, f in files], status='research reconstruction; not an official EMI or ICPAC forecast')


# ---------------------------------------------------------------- release archive
def load_releases():
    return json.loads(RELEASES.read_text(encoding='utf-8')) if RELEASES.is_file() else []


def _git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, check=True).stdout


def _site_data(page):
    m = re.search(r'<script id="(?:site-data|entries)" type="application/json">(.*?)</script>', page, re.S)
    return json.loads(m.group(1).replace('<\\/', '</')) if m else None


def differences(old, new):
    """Short list of what changed between an archived page's data and the current data."""
    if not old or 'cycles' not in old:
        return ['Earlier page format (before the cycle selector); open both pages to compare.']
    out = []
    oc = {c['id']: c for c in old['cycles']}
    for c in new['cycles']:
        o = oc.get(c['id'])
        if not o:
            out.append(f'{c["label"]}: cycle added.')
            continue
        ot = {t['id']: t for t in o['targets']}
        for t in c['targets']:
            x = ot.get(t['id'])
            if not x:
                continue
            if x['status']['text'] != t['status']['text']:
                out.append(f'{t["label"]}: status "{x["status"]["text"]}" → "{t["status"]["text"]}".')
            added = sorted(set(t['verification']) - set(x['verification']))
            if added:
                out.append(f'{t["label"]}: verification added ({", ".join(dict(c["views"]).get(v, v) for v in added)}).')
            for v in t['forecast']:
                a, b = x['forecast'].get(v, {}).get('summary'), t['forecast'][v]['summary']
                if a and max(abs((p or 0) - (q or 0)) for p, q in zip(a['mean_local_probabilities'], b['mean_local_probabilities'])) > .005:
                    out.append(f'{t["label"]} ({dict(c["views"]).get(v, v)}): forecast probabilities changed.')
        if any(v not in dict(o['views']) for v in dict(c['views'])):
            out.append(f'{c["label"]}: rainfall-domain view changed.')
    return out or ['Forecast numbers, statuses and verification are unchanged; differences are in presentation only.']


def _has(sha, path):
    try:
        _git('cat-file', '-e', f'{sha}:{path}')
        return True
    except subprocess.CalledProcessError:
        return False


def comparison_differences(sha, out, current):
    """What changed in the published official-outlook comparisons since a release commit."""
    lines = []
    for c in current['cycles']:
        rel = c.get('comparison')
        if not rel or not (out / rel).is_file():
            continue
        new = json.loads((out / rel).read_text(encoding='utf-8'))
        old = json.loads(_git('show', f'{sha}:site/{rel}').decode('utf-8')) if _has(sha, f'site/{rel}') else None
        count = lambda d: len([p for p in d.get('paragraphs', []) if p.get('finding')])
        if old is None:
            lines.append(f'{c["label"]}: comparison with official outlooks added ({count(new)} published findings).')
            continue
        if count(old) != count(new):
            lines.append(f'{c["label"]}: published comparison findings {count(old)} → {count(new)}.')
        ost = {s['id']: s['extraction']['status'] for s in old.get('sources', [])}
        for s in new.get('sources', []):
            if ost.get(s['id']) != s['extraction']['status']:
                lines.append(f'{c["label"]}: {s["provider"]} extraction {ost.get(s["id"], "absent")} → {s["extraction"]["status"]}.')
        if count(old) == count(new) and [p['text'] for p in old.get('paragraphs', [])] != [p['text'] for p in new.get('paragraphs', [])]:
            lines.append(f'{c["label"]}: comparison wording or numbers changed.')
        if new.get('stale') and not old.get('stale'):
            lines.append(f'{c["label"]}: comparison withheld because its inputs changed.')
    return lines


def build_releases(out, current_data, esc):
    """site/releases/: archived pages (exact published page per release commit) and the change log."""
    releases = load_releases()
    if not releases:
        return None
    base_dir = out / 'releases'
    base_dir.mkdir(parents=True, exist_ok=True)
    cards = []
    for r in reversed(releases):
        link, diff = '../index.html', []
        if r.get('commit'):
            sha = _git('rev-parse', r['commit']).decode().strip()
            page = _git('show', f'{sha}:site/index.html').decode('utf-8')
            raw = f'{RAW}/{sha}/site/'
            folder = base_dir / r['id']
            folder.mkdir(exist_ok=True)
            for name in ('site.js', 'style.css'):
                (folder / name).write_bytes(_git('show', f'{sha}:site/assets/{name}'))
            page = page.replace('assets/style.css', 'style.css').replace('assets/site.js', 'site.js')
            # Assets and downloads come from the release commit; the page's data files are copied next to it
            # (with their own asset links pointed at the commit) so the archived script loads them unchanged.
            page = re.sub(r'(["\'(])(assets/|downloads/)', lambda m: m.group(1) + raw + m.group(2), page)
            names = _git('ls-tree', '--name-only', f'{sha}:site/data').decode().split() if _has(sha, 'site/data') else []
            for name in names:
                text = _git('show', f'{sha}:site/data/{name}').decode('utf-8')
                text = re.sub(r'"(assets/|downloads/)', lambda m: '"' + raw + m.group(1), text)
                (folder / 'data').mkdir(exist_ok=True)
                (folder / 'data' / name).write_text(text, encoding='utf-8', newline='')
            banner = (f'<div style="background:#fdf1d8;color:#5c3d00;padding:10px 16px;font:14px/1.5 system-ui,sans-serif;'
                      f'border-bottom:1px solid #e2b25c">Archived release <strong>{esc(r["id"])}</strong> ({esc(r["date"])}): '
                      f'the page as published then (code {sha[:7]}). <a href="../../index.html">Current release</a> · '
                      f'<a href="../index.html">Change log</a></div>')
            page = page.replace('<body>', '<body>' + banner, 1)
            (folder / 'index.html').write_text(page, encoding='utf-8', newline='')
            link = f'{r["id"]}/index.html'
            diff = differences(_site_data(_git('show', f'{sha}:site/index.html').decode('utf-8')), current_data)
            extra = comparison_differences(sha, out, current_data)
            if extra:
                diff = [d for d in diff if not d.startswith('Forecast numbers, statuses and verification are unchanged')] + extra
        badges = ''.join(f'<span class="status ready">{esc(CHANGE_TYPES.get(c["type"], c["type"]))}</span> ' for c in r['changes'])
        items = ''.join(f'<li><strong>{esc(CHANGE_TYPES.get(c["type"], c["type"]))}:</strong> {esc(c["text"])}</li>' for c in r['changes'])
        files = f'{REPO}/tree/{r["commit"]}/site' if r.get('commit') else f'{REPO}/tree/main/site'
        dif = ('<p><strong>Differences from the current release</strong></p><ul>' + ''.join(f'<li>{esc(d)}</li>' for d in diff) + '</ul>'
               if r.get('commit') else '<p><strong>This is the current release.</strong></p>')
        cards.append(f'<section class="box"><h2>Release {esc(r["id"])} <span class="caveat">· {esc(r["date"])}</span></h2>'
                     f'<p>{esc(r["title"])}</p><p>{badges}</p><ul>{items}</ul><p class="caveat">Cycles: {esc(", ".join(r.get("cycles", [])))}</p>'
                     f'{dif}<p><a href="{link}">Open this release</a> · <a href="{files}">Files at this release (GitHub)</a></p></section>')
    types = ''.join(f'<li><strong>{esc(v)}</strong> ({esc(k)})</li>' for k, v in CHANGE_TYPES.items())
    (base_dir / 'index.html').write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Release archive</title><link rel="stylesheet" href="../assets/style.css"></head><body><main class="wrap">'
        '<h1>Release archive and change log</h1><p><a href="../index.html">Back to the current outlooks</a></p>'
        '<p>Each release is the site as published at one commit. Archived releases open the exact page published then; its maps '
        'and files are served from that commit in the repository.</p>'
        f'<details><summary>Change types</summary><ul>{types}</ul></details>{"".join(cards)}'
        '<p class="caveat">Research reconstructions; not official EMI or ICPAC forecasts.</p></main></body></html>\n',
        encoding='utf-8', newline='')
    return releases[-1]['id']



# ---------------------------------------------------------------- official outlook comparison
def _current_inputs(cycle, registry_path):
    """Recompute what a saved comparison depends on, from the files as they are now."""
    import sys
    sys.path.insert(0, str(ROOT / 'scripts'))
    import external_forecasts as ef
    from compare_external_forecasts import input_fingerprint
    ext = cycle.raw['external_comparison']
    registry = ef.load_registry(registry_path)
    season = cycle.season_name
    vr = cycle.root('verification_root')
    frozen = vr / f'frozen_forecasts/{cycle.tag}_{season}/forecast_{cycle.year}.nc'
    native = frozen if (vr / 'frozen_forecasts/freeze_manifest.json').is_file() else cycle.forecast_file(cycle.root('forecast_root'), season)
    mask = cycle.root('regime_mask') if season == 'JJAS' else cycle.root('season_domain_mask')
    current_path = ef.cache_dir(registry, ext['cache_root']) / 'current.json'
    current = json.loads(current_path.read_text(encoding='utf-8')) if current_path.is_file() else {}
    sources = {}
    for sid, cur in current.items():
        rec, _ = ef.extraction_record(registry, sid)
        status, _ = ef.extraction_check(rec, cur['sha256'])
        sources[sid] = dict(sha256=cur['sha256'], extraction_status=status, content_sha256=rec and ef.content_sha256(rec))
    minimum = cycle.raw['display']['minimum_leading_probability']      # the favoured-category rule
    return input_fingerprint(native, mask, registry, sources, minimum), registry, ef.cache_dir(registry, ext['cache_root'])


def _stale_reasons(saved, now):
    names = dict(native_sha256='the platform forecast', domain_mask_sha256='the rainfall-domain mask', registry_sha256='the source registry',
                 minimum_leading_probability='the favoured-category threshold')
    out = [names[k] for k in names if (saved or {}).get(k) != now.get(k)]
    old, new = (saved or {}).get('sources', {}), now.get('sources', {})
    for sid in sorted(set(old) | set(new)):
        a, b = old.get(sid, {}), new.get(sid, {})
        if a.get('sha256') != b.get('sha256'):
            out.append(f'the official product {sid}')
        elif (a.get('extraction_status'), a.get('content_sha256')) != (b.get('extraction_status'), b.get('content_sha256')):
            out.append(f'the extraction record of {sid}')
    return out


def saved_output_consistency(manifest, comparison, interp):
    """The three saved stage outputs must describe the same inputs (matters when outputs are restored or copied)."""
    from compare_external_forecasts import manifest_states
    out = []
    if manifest_states(manifest) != (comparison.get('inputs') or {}).get('sources'):
        out.append('the saved source manifest (it differs from the sources the comparison used)')
    if interp.get('inputs') != comparison.get('inputs'):
        out.append('the interpretation (made from a different comparison)')
    return out


def _refresh_state(r, extraction_status):
    if not r:
        return dict(state='not_checked', text='Not checked online in this build; saved product shown')
    day = r['checked_utc'][:10]
    if r.get('status') == 'failed':
        return dict(state='refresh_failed', text=f'Refresh failed on {day}; saved product shown', checked_utc=r['checked_utc'])
    if r.get('changed') and extraction_status != 'validated':
        return dict(state='new_awaiting_review', text=f'New product found on {day}; awaiting extraction review', checked_utc=r['checked_utc'])
    skipped = [s['title'] for s in r.get('skipped_candidates') or []]
    return dict(state='checked', text=f'Checked {day}: ' + ('unchanged' if not r.get('changed') else 'new product, reviewed')
                + (f'; a matching page without a document yet was skipped ({"; ".join(skipped)})' if skipped else ''),
                checked_utc=r['checked_utc'])


def export_comparison(cycle, cid, out):
    """Publish a cycle's official-outlook comparison: validated content only, and only while the saved
    results still match the current forecast, sources, extraction records, registry and mask."""
    import shutil
    ext = cycle.raw.get('external_comparison')
    if not ext:
        return None
    base = ROOT / ext['output_root']
    files = [base / 'sources/source_manifest.json', base / 'comparison/comparison.json', base / 'interpretation/interpretation.json']
    if not all(f.is_file() for f in files):
        return None
    manifest, comparison, interp = (json.loads(f.read_text(encoding='utf-8')) for f in files)
    now_inputs, registry, cache = _current_inputs(cycle, ROOT / ext['registry'])
    stale = _stale_reasons(comparison.get('inputs'), now_inputs) + saved_output_consistency(manifest, comparison, interp)
    status_path = cache / 'refresh_status.json'
    refresh = json.loads(status_path.read_text(encoding='utf-8')) if status_path.is_file() else {}
    assets = out / 'assets/external' / cid
    assets.mkdir(parents=True, exist_ok=True)
    season = cycle.season_name
    sources, public = [], {}
    for s in manifest['sources']:
        x = s.get('extraction', {})
        figures = []
        for e in s.get('evidence', []):
            src = base / 'sources' / e['file']
            shutil.copy2(src, assets / src.name)
            figures.append(dict(id=e['id'], file=f'assets/external/{cid}/{src.name}', caption=e['caption']))
            public[e['id']] = f'assets/external/{cid}/{src.name}'
        sources.append(dict(id=s['source_id'], provider=s['provider'], product=s.get('product'), representation=s.get('representation'),
                            label=s.get('label'), season_label=s.get('season_label'), target_start=s.get('target_start'),
                            target_end=s.get('target_end'), issue_date=s.get('issue_date'), initialization=s.get('initialization'),
                            reference_period=s.get('reference_period'), retrieved_utc=s.get('retrieved_utc'), sha256=s.get('sha256'),
                            page=s.get('requested_url'), download=s.get('download_url'), narrative=s.get('narrative', []),
                            extraction=dict(status=x.get('status'), method=x.get('method'), review=x.get('review'), note=x.get('note')),
                            refresh=_refresh_state(refresh.get(s['source_id']), x.get('status')), figures=figures))
    validated = {s['id'] for s in sources if s['extraction']['status'] == 'validated'}
    layers = [dict(id=l['id'], provider=l.get('provider'), status=l['status'], note=l.get('note'), citation=l.get('citation'), doi=l.get('doi'),
                   url=l.get('url'), license_note=l.get('license_note'), review=l.get('review'), region_names=l.get('region_names'))
              for l in manifest.get('reference_layers', [])]
    regions_ok = any(l['status'] == 'validated' for l in layers)
    maps = []
    if not stale:
        for m in comparison['maps']:
            sid = next((v for v in validated if m.startswith(v)), None)
            if sid and 'regions' in m and not regions_ok:
                sid = None                              # the region map also needs the reviewed region layer
            if sid:                                     # comparison maps only for reviewed extractions
                shutil.copy2(base / 'comparison/maps' / m, assets / m)
                maps.append(dict(source_id=sid, file=f'assets/external/{cid}/{m}', name=m))
    # Evidence identifiers -> public links (internal repository paths are never published as links).
    nc = f'downloads/data/{cid}/{season}_forecast_{cycle.year}.nc'
    evidence = {}
    for k, e in interp['evidence'].items():
        kind = e.get('kind')
        if kind == 'platform':
            links = [dict(label='Platform map', href=f'assets/maps/{cid}/forecast/{season}/' + '{view}/tercile_outlook.png'),
                     dict(label='Platform data (NetCDF)', href=nc)]
        elif kind == 'official_figure':
            links = [dict(label='Official figure', href=public.get(k)),
                     dict(label='Original PDF page' if '#page=' in (e.get('url') or '') else 'Original file', href=e.get('url'))]
        elif kind == 'comparison_map':
            m = next((m for m in maps if m['name'] == e.get('map')), None)
            links = [dict(label='Comparison map', href=m['file'])] if m else []
        elif kind == 'source_record':
            links = [dict(label='Source record', href=f'downloads/{cid}_comparison_sources.json')]
        else:
            links = []
        evidence[k] = dict(label=e['label'], kind=kind, links=[l for l in links if l['href']])
    # Published rows never carry draft columns (e.g. zone means before the region layer is reviewed).
    clean = lambda i: {k: v for k, v in i.items() if not k.endswith('_draft')}
    keep = (lambda items: [clean(i) for i in items if i['status'] == 'validated']) if not stale else (lambda items: [])
    metrics = [dict(metric=m['metric'], source_id=m.get('source_id'), where=m.get('zone') or m.get('area'), status=m['status'],
                    reason=m.get('reason'), basis=m.get('basis'), value=m.get('value') if m['status'] == 'available' and not stale else None)
               for m in comparison['metrics']]
    rerun = (f'python scripts\\run_operational.py --config {Path(cycle.path).resolve().relative_to(ROOT)} --workflow products --compare-external'
             + (' --refresh-external' if any('official product' in r for r in stale) else ''))
    data = dict(platform=comparison['platform'], sources=sources, maps=maps, metrics=metrics, summary=keep(interp.get('summary', [])),
                emi_table=keep(interp.get('emi_table', [])), icpac_table=keep(interp.get('icpac_table', [])),
                paragraphs=keep(interp['paragraphs']), evidence=evidence,
                notes=comparison['notes'], stale=stale, rerun=rerun, created_utc=interp['created_utc'], engine=interp['engine'],
                reference_layers=layers)
    rel = f'data/{cid}_comparison.json'
    (out / 'data').mkdir(parents=True, exist_ok=True)
    (out / rel).write_text(json.dumps(rounded(data), separators=(',', ':'), ensure_ascii=False), encoding='utf-8', newline='')
    # Downloads: comparison data, source records with review metadata, and a readable report.
    dl = out / 'downloads'
    dl.mkdir(parents=True, exist_ok=True)
    records = {}
    ex_dir = Path(registry['extractions_dir'])
    ex_dir = ex_dir if ex_dir.is_absolute() else ROOT / ex_dir
    for s in registry['sources']:
        p = ex_dir / f'{s["id"]}.json'
        if p.is_file():
            records[s['id']] = json.loads(p.read_text(encoding='utf-8'))
    (dl / f'{cid}_comparison.json').write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding='utf-8', newline='')
    (dl / f'{cid}_comparison_sources.json').write_text(
        json.dumps(dict(sources=manifest['sources'], extraction_records=records, anomaly_products_checked=manifest.get('anomaly_products_checked')),
                   indent=1, ensure_ascii=False), encoding='utf-8', newline='')
    downloads = [dict(label='Comparison with official outlooks (JSON)', href=f'downloads/{cid}_comparison.json',
                      note='Published findings, tables, metrics with their status and reasons, sources and evidence links'),
                 dict(label='Official outlook sources and extraction reviews (JSON)', href=f'downloads/{cid}_comparison_sources.json',
                      note='Source pages, download links, file hashes, retrieval times and the reviewed extraction records')]
    package = [[f'downloads/{cid}_comparison.json', 'comparison/comparison.json'],
               [f'downloads/{cid}_comparison_sources.json', 'comparison/sources_and_reviews.json']]
    # Public reports are rendered from the same filtered data as the page (the full operational report
    # with draft values stays internal): one with site paths, one with the ZIP package's paths.
    package += [[f['file'], 'comparison/figures/' + Path(f['file']).name] for s in sources for f in s['figures']]
    package += [[m['file'], 'comparison/figures/' + m['name']] for m in maps]
    (dl / f'{cid}_comparison_report.html').write_text(public_report(data, f'../assets/external/{cid}/'), encoding='utf-8', newline='')
    packaged = public_report(data, 'figures/')
    in_zip = {z for _, z in package}
    missing = [s for s in local_images(packaged) if 'comparison/' + s not in in_zip]
    if missing:
        raise ValueError(f'Packaged comparison report refers to files missing from the package: {missing}')
    (dl / f'{cid}_comparison_report_package.html').write_text(packaged, encoding='utf-8', newline='')
    downloads.insert(0, dict(label='Comparison with official outlooks (report, HTML)', href=f'downloads/{cid}_comparison_report.html',
                             note='Key findings, maps, tables, interpretation, sources and review status (reviewed content only)'))
    package.append([f'downloads/{cid}_comparison_report_package.html', 'comparison/report.html'])
    return dict(rel=rel, downloads=downloads, package=package, stale=stale)


# ---------------------------------------------------------------- public comparison report
def overlap_label(share, domain='the domain'):
    """How an EMI sample (±0.5° box) relates to the rainfall domain; the probabilities describe the whole box."""
    if share is None:
        return ''
    if share <= 0:
        return f'Outside {domain}'
    if share >= 1:
        return f'Entire sample in {domain}'
    return f'Partly overlaps {domain} — {100 * share:.0f}% of sample cells'


def _pct(x, one=False):
    if x is None:
        return '—'
    if one:
        return '100%' if x >= 0.99995 else f'{100 * x:.1f}%'
    return '>99%' if 0.995 <= x < 1 else '<1%' if 0 < x < 0.005 else f'{100 * x:.0f}%'


def public_report(data, prefix):
    """Readable comparison report from the published (reviewed, current) data only.

    prefix: where the figures are relative to the report ('../assets/external/<cid>/' on the
    site, 'figures/' inside the ZIP package).
    """
    import html as _html
    esc = _html.escape
    plat = data['platform']
    areas = plat.get('areas', {})
    dom = areas.get('season_domain', 'rainfall domain')
    name = lambda f: f.rsplit('/', 1)[-1]
    parts = [f'<h1>Official outlook comparison — {esc(plat["label"])}</h1>',
             f'<p class="muted">Season {esc(plat["target_start"])} to {esc(plat["target_end"])} · areas: All Ethiopia and the {esc(dom)} · '
             f'built from reviewed extractions only ({esc(data["engine"])}, {esc(data["created_utc"][:10])}). Research reconstruction; not an '
             'official EMI or ICPAC forecast. The comparison describes agreement between outlooks, not which is more accurate.</p>']
    if data['stale']:
        parts.append(f'<p class="warn"><strong>Comparison withheld.</strong> The saved comparison no longer matches the current '
                     f'{esc(", ".join(data["stale"]))}. Regenerate with <code>{esc(data["rerun"])}</code>.</p>')
    groups = [('all_ethiopia', 'All Ethiopia'), ('season_domain', dom), ('any', 'Robustness of the extraction')]
    for key, title in groups:
        items = [i for i in data['summary'] if i['area_key'] == key]
        if items:
            parts.append(f'<h2>Key findings — {esc(title)}</h2><ul>' +
                         ''.join(f'<li><strong>{esc(i["title"])}.</strong> {esc(i["text"])}</li>' for i in items) + '</ul>')
    if data['maps']:
        emi_fig = next((f for s in data['sources'] if s['provider'] == 'EMI' for f in s['figures']), None)
        region = next((m for m in data['maps'] if 'regions' in m['file']), None)
        cite = next((l['citation'] for l in data.get('reference_layers', []) if l.get('citation')), '')
        if region:                                    # reviewed region layer: zones as regions with EMI's values
            right = (f'<figure><img src="{esc(prefix + name(region["file"]))}" alt="EMI rainfall regions"><figcaption>EMI zones as homogeneous '
                     f'rainfall regions with the Bega 2026/27 printed values; regions redrawn after {esc(cite.split(" (figure")[0])} '
                     '(layout as published in 2013).</figcaption></figure>')
        elif emi_fig:
            right = (f'<figure><img src="{esc(prefix + name(emi_fig["file"]))}" alt="EMI official figure">'
                     f'<figcaption>EMI official figure: {esc(emi_fig["caption"])}</figcaption></figure>')
        else:
            right = ''
        out = []
        for m in [m for m in data['maps'] if 'regions' not in m['file']]:
            fig = f'<figure><img src="{esc(prefix + name(m["file"]))}" alt="Comparison map"><figcaption>{esc(name(m["file"]))}</figcaption></figure>'
            if 'anchors' in m['file'] and right:
                fig = '<div class="pair">' + fig + right + '</div>'
            out.append(fig)
        parts.append('<h2>Comparison maps</h2>' + ''.join(out))
    agree = [m for m in data['metrics'] if m['metric'] == 'mapped_category_agreement' and m['value']]
    if agree:
        parts.append('<h2>ICPAC category agreement</h2><p class="muted">Only where both outlooks show a favoured category.</p><table>'
                     '<tr><th>Area</th><th>Compared area (share of the analysed area)</th><th>Agreement within it</th><th>Opposite within it</th></tr>' +
                     ''.join(f'<tr><td>{esc(m["where"])}</td><td>{_pct(m["value"]["area_share_both_favoured"])}</td>'
                             f'<td>{_pct(m["value"]["agreement_share_where_both_favoured"], True)}</td>'
                             f'<td>{_pct(m["value"]["opposing_share_where_both_favoured"], True)}</td></tr>' for m in agree) + '</table>')
    if data['emi_table']:
        zone = any(r.get('zone_mean') for r in data['emi_table'])
        parts.append('<h2>EMI zones: printed values and the platform</h2><table><tr><th>Zone</th><th>Official below / near / above</th>'
                     + ('<th>Platform over the whole zone (region)</th>' if zone else '') +
                     f'<th>Platform near the arrow (±0.5°)</th><th>Relationship near the arrow</th><th>Arrow sample vs the {esc(dom)}</th></tr>' +
                     ''.join(f'<tr><td>Zone {esc(r["zone"])}</td><td>{esc(r["official"])}</td>'
                             + (f'<td>{esc(r.get("zone_mean") or "—")}<br><span class="muted">{esc(r.get("zone_relationship") or "")}</span></td>' if zone else '')
                             + f'<td>{esc(r["platform"])}</td><td>{esc(r["relationship"])}</td><td>{esc(overlap_label(r.get("domain_share")))}</td></tr>'
                             for r in data['emi_table']) +
                     '</table><p class="muted">Platform values are area means of local probabilities: over the whole zone (EMI homogeneous rainfall '
                     'region as published in 2013, assumed unchanged) where reviewed, and over the ±0.5° sample around each arrow tip. '
                     'Percentages are rounded to add up to 100%.</p>')
    if data.get('icpac_table'):
        parts.append('<h2>ICPAC: printed favoured category and interval vs the platform</h2><table><tr><th>Location</th>'
                     '<th>ICPAC (favoured category, printed interval)</th><th>Platform below / near / above</th><th>Relationship</th></tr>' +
                     ''.join(f'<tr><td>{esc(r["location"])}' + (f'<br><span class="muted">{esc(overlap_label(r["domain_share"]))}</span>' if r.get('domain_share') is not None else '')
                             + f'</td><td>{esc(r["official"])}' + (f'<br><span class="muted">{esc(r["official_note"])}</span>' if r['official_note'] else '')
                             + f'</td><td>{esc(r["platform"])}</td><td>{esc(r["relationship"])}</td></tr>' for r in data['icpac_table']) +
                     '</table><p class="muted">ICPAC publishes only the favoured category and its probability interval (the other two categories are not '
                     'published), for October–December; the platform covers October–January. Sample locations are the EMI arrow-tip boxes; '
                     'platform values are area means of local probabilities over each sample or area.</p>')
    if data['paragraphs']:
        parts.append('<h2>Detailed interpretation</h2>' + ''.join(f'<p>{esc(p["text"])}</p>' for p in data['paragraphs']))
    for s in data['sources']:
        rv = s['extraction'].get('review') or {}
        rows = [('Product', s['label']), ('Target period', f'{s["target_start"]} to {s["target_end"]}'),
                ('Issue date', s.get('issue_date') or 'not stated by the provider'), ('Reference period', s.get('reference_period') or 'not stated'),
                ('Retrieved', (s.get('retrieved_utc') or '')[:10]), ('Latest check', s['refresh']['text']),
                ('Content hash (SHA-256)', s.get('sha256')), ('Extraction', s['extraction'].get('status')),
                ('Review', f'{rv.get("decision")} by {rv.get("reviewer")}, {(rv.get("reviewed_utc") or "")[:10]}' if rv else 'not reviewed'),
                ('Source page', s.get('page')), ('Original file', s.get('download'))]
        parts.append(f'<h2>Source: {esc(s["provider"])} — {esc(s.get("season_label") or s["label"])}</h2><table>' +
                     ''.join(f'<tr><th>{esc(k)}</th><td>{esc(str(v))}</td></tr>' for k, v in rows) + '</table>' +
                     (('<blockquote>' + '<br>'.join(esc(n['text']) for n in s['narrative']) + f'<br><span class="muted">— {esc(s["provider"])}</span></blockquote>')
                      if s['narrative'] else '') +
                     ''.join(f'<figure><img src="{esc(prefix + name(f["file"]))}" alt="{esc(f["caption"])}"><figcaption>{esc(f["caption"])} '
                             '(original figure)</figcaption></figure>' for f in s['figures']))
    parts.append('<h2>What is compared, and what is not</h2><table><tr><th>Comparison</th><th>Where</th><th>Status</th><th>Reason</th></tr>' +
                 ''.join(f'<tr><td>{esc(m["metric"].replace("_", " "))}</td><td>{esc(str(m.get("where") or "—"))}</td>'
                         f'<td>{esc(m["status"].replace("_", " "))}</td><td>{esc((m.get("reason") or m.get("basis") or "").replace("_", " "))}</td></tr>'
                         for m in data['metrics']) + '</table>')
    parts.append('<h2>Notes</h2><ul>' + ''.join(f'<li>{esc(n)}</li>' for n in data['notes']) + '</ul>')
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>Official outlook comparison — {esc(plat["label"])}</title><style>body{{font:15px/1.55 system-ui,sans-serif;max-width:1100px;'
            'margin:24px auto;padding:0 16px;color:#111}table{border-collapse:collapse;width:100%;margin:8px 0}th,td{border-bottom:1px solid #ddd;'
            'padding:6px 8px;text-align:left;vertical-align:top}img{max-width:100%}figure{margin:12px 0}.muted{color:#555;font-size:.92em}'
            '.warn{background:#fdf1d8;padding:10px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px;align-items:start}blockquote{border-left:3px solid #ccc;margin:8px 0;padding:4px 12px;color:#333}</style></head><body>'
            + ''.join(parts) + '</body></html>\n')


def local_images(page):
    """Relative image references of an HTML page."""
    return [s for s in re.findall(r'<img[^>]+src="([^"]+)"', page) if not re.match(r'^(?:[a-z]+:)?//', s) and not s.startswith('data:')]
