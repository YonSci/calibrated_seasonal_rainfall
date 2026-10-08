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
            page = re.sub(r'(["\'(])(assets/|downloads/|data/)', lambda m: m.group(1) + raw + m.group(2), page)
            banner = (f'<div style="background:#fdf1d8;color:#5c3d00;padding:10px 16px;font:14px/1.5 system-ui,sans-serif;'
                      f'border-bottom:1px solid #e2b25c">Archived release <strong>{esc(r["id"])}</strong> ({esc(r["date"])}): '
                      f'the page as published then (code {sha[:7]}). <a href="../../index.html">Current release</a> · '
                      f'<a href="../index.html">Change log</a></div>')
            page = page.replace('<body>', '<body>' + banner + f'<script>window.SITE_BASE={json.dumps(raw)}</script>', 1)
            (folder / 'index.html').write_text(page, encoding='utf-8', newline='')
            link = f'{r["id"]}/index.html'
            diff = differences(_site_data(_git('show', f'{sha}:site/index.html').decode('utf-8')), current_data)
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
