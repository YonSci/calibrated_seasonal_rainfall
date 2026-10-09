"""Build the static GitHub Pages site (site/) from the project's result files.

Every number on the page is read from outputs/ files; maps are copied from each
cycle's presentation layers. One page serves every rendered forecast cycle: a
cycle selector updates the outlook, maps, verification, historical evidence,
status and downloads. Rerun after results change:

    python scripts\\build_site.py                 (checks the CHIRPS archive listing online)
    python scripts\\build_site.py --offline       (observation availability shown as "not checked")
"""
import argparse
import calendar
import csv
import html
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from cycle import load_cycle, target_window          # noqa: E402
from significance import paired_summary              # noqa: E402
import site_extras as extras                          # noqa: E402

OUT = ROOT / 'site'
REPO = 'https://github.com/YonSci/calibrated_seasonal_rainfall'
CHIRPS_LISTING = 'https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/netcdf/p25/by_month/'
CYCLE_FILES = ['config/operational.json', *sorted(str(p.relative_to(ROOT)) for p in (ROOT / 'config/cycles').glob('*.json'))]
INCLUDE_BACKTESTS = False      # --include-backtests (scratch builds only)
PRODUCTS = [('tercile_outlook', 'Tercile probabilities'), ('rainfall_total_mm', 'Total rainfall'),
            ('rainfall_anomaly_mm', 'Anomaly (mm)'), ('rainfall_anomaly_percent', 'Anomaly (%)')]
JJAS_TARGETS = ['JJAS', 'Jun', 'Jul', 'Aug', 'Sep']
esc = html.escape


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding='utf-8-sig'))


def signed(x, d=3):
    """Signed decimal with a typographic minus (no sign on a rounded zero)."""
    return f'{0:.{d}f}' if round(x, d) == 0 else f'{x:+.{d}f}'.replace('-', '−')


def table(head, rows, caption='', cls=''):
    h = ''.join(f'<th scope="col">{c}</th>' for c in head)
    b = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in rows)
    cap = f'<caption>{caption}</caption>' if caption else ''
    return f'<div class="table-wrap"><table class="{cls}">{cap}<thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>'


def skill_cell(v, ci=None):
    cls = 'pos' if v > 0 else 'neg'
    text = f'<span class="{cls}">{signed(v)}</span>'
    if ci:
        text += f' <span class="ci">({signed(ci[0])} to {signed(ci[1])})</span>'
    return text


def day(d):
    return f'{d.day} {d:%b %Y}'


def iso_day(s):
    """'2026-10-04T18:35:59+00:00' -> '4 Oct 2026'."""
    return day(datetime.fromisoformat(s.replace('Z', '+00:00')))


def git_sha():
    try:
        return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return 'unknown'


def chirps_published(offline):
    """(year, month) pairs in the official CHIRPS v2.0 p25 by_month listing; None when not checked."""
    if offline:
        return None
    try:
        with urllib.request.urlopen(CHIRPS_LISTING, timeout=30) as r:
            text = r.read().decode('utf-8', 'replace')
    except Exception as exc:
        print('CHIRPS listing not checked:', exc)
        return None
    return {(int(y), int(m)) for y, m in re.findall(r'chirps-v2\.0\.(\d{4})\.(\d{2})\.days_p25\.nc', text)}


def months_between(start, end):
    y, m, out = start.year, start.month, []
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def cycle_entries(c):
    """Forecast (and, after run_operational.py, verification) entries of a cycle's output folder."""
    out = c.root('output_root')
    gallery = out / 'index.html'
    if gallery.is_file():          # runner gallery: forecast and verification views
        found = re.search(r'<script id="data" type="application/json">(.*?)</script>',
                          gallery.read_text(encoding='utf-8'), re.S)
        if found:
            return [dict(e, folder=e['folder'].replace('\\', '/')) for e in json.loads(found.group(1))]
    listing = out / 'entries.json'
    return json.loads(listing.read_text(encoding='utf-8'))['entries'] if listing.is_file() else []


def year_skill(path, draws=5000, seed=20261005):
    """RPSS of the final method against climatology with a whole-year bootstrap interval."""
    if not path.is_file():
        return None
    r = json.loads(path.read_text(encoding='utf-8'))
    b = np.array([y['metrics']['shared_blend']['rps'] for y in r['years']])
    c = np.array([y['metrics']['climatology']['rps'] for y in r['years']])
    idx = np.random.default_rng(seed).integers(0, len(b), (draws, len(b)))
    boot = 1 - b[idx].sum(1) / c[idx].sum(1)
    ps = paired_summary(b, c)
    return dict(rpss=float(1 - b.sum() / c.sum()), ci=[float(np.quantile(boot, .025)), float(np.quantile(boot, .975))],
                better=ps['years_better'], years=ps['years'], p=ps['p_improvement'],
                first=r['target_years'][0], last=r['target_years'][-1])


def area_skill(r, national):
    """Regional-skill record (regional_skill.py) in the year_skill format; None if not scored."""
    if not r or 'rpss_blend' not in r or national is None:
        return None
    return dict(rpss=r['rpss_blend'], ci=r['rpss_blend_95'], better=r['years_blend_better'], years=r['years'],
                p=r['p_blend_better_than_climatology'], first=national['first'], last=national['last'],
                coverage=r.get('probability_coverage'))


def add_holm(targets):
    """Holm-adjusted p (over the cycle's targets) for each area's cross-validated score."""
    from significance import holm
    for area in {a for t in targets for a in t['history']}:
        ps = {t['id']: t['history'][area]['training']['p'] for t in targets
              if area in t['history'] and t['history'][area]['training']}
        for k, v in holm(ps).items():
            next(t for t in targets if t['id'] == k)['history'][area]['training']['holm_p'] = v


# Panels of the six-panel verification figure (presentation_layers.verification_maps: 15.6 x 10.6 in at
# 180 dpi, subplots_adjust left=.055 right=.97 top=.84 bottom=.14 wspace=.24 hspace=.29), row-major.
PANELS = [('verification_observed_anomaly', 'Observed anomaly'), ('verification_forecast_anomaly', 'Forecast anomaly'),
          ('verification_error', 'Forecast minus observed'), ('verification_observed_tercile', 'Observed tercile'),
          ('verification_rps_difference', 'Probability score vs climatology'),
          ('verification_crps', 'Rainfall amount score (CRPS)')]
PANEL_SIZE = (2808, 1908)


def panel_layout_ok(src):
    from PIL import Image
    with Image.open(src) as im:
        return im.size == PANEL_SIZE


def crop_panels(src, folder):
    """Cut the six panels out of the composite verification figure; [] if its layout is not the expected one."""
    from PIL import Image
    with Image.open(src) as im:
        if im.size != PANEL_SIZE:
            print(f'{src}: unexpected size {im.size}; panels not split')
            return []
        W, H = im.size
        left, right, top, bottom, ws, hs = .055, .97, .84, .14, .24, .29
        w, h = (right - left) / (3 + 2 * ws), (top - bottom) / (2 + hs)
        folder.mkdir(parents=True, exist_ok=True)
        for i, (name, _) in enumerate(PANELS):
            r, c = divmod(i, 3)
            x0, y1 = left + c * w * (1 + ws), top - r * h * (1 + hs)
            box = (x0 - .045, 1 - (y1 + .04), x0 + w + .02, 1 - (y1 - h - .04))
            im.crop(tuple(int(v * s) for v, s in zip(box, (W, H, W, H)))).save(folder / f'{name}.png', optimize=True)
    return [list(p) for p in PANELS]


def domain_text(c, entries_json):
    if 'domain_definition' in entries_json:
        return entries_json['domain_definition'], entries_json.get('domain_note', '')
    summary = c.root('output_root') / f'presentation/forecast/{c.season_name}/presentation_summary.json'
    if summary.is_file():
        s = json.loads(summary.read_text(encoding='utf-8'))
        return s['domain_definition'], s.get('domain_note', '')
    with xr.open_dataset(c.root('season_domain_mask')) as m:
        return m.attrs['domain_definition'], ''


def ref_label(c, crosses):
    if crosses:
        return f'{c.ref_first}/{(c.ref_first + 1) % 100:02d}–{c.ref_last}/{(c.ref_last + 1) % 100:02d}'
    return c.reference_dash


def target_status(window, verified, processed, published, today):
    start, end = window
    months = months_between(start, end)
    if verified:
        return dict(code='published', text='Verification published')
    if today < start:
        return dict(code='not_started', text=f'Target period starts {day(start)}')
    if today <= end:
        return dict(code='ongoing', text=f'Target period ongoing (ends {day(end)})')
    if published is None:
        return dict(code='not_checked', text='Observation availability not checked')
    missing = [ym for ym in months if ym not in published]
    if missing:
        names = ', '.join(f'{calendar.month_abbr[m]} {y}' for y, m in missing)
        return dict(code='awaiting', text=f'Awaiting CHIRPS observations: {names} file not found in the checked '
                                          f'CHIRPS listing (last checked {day(today)})')
    if not processed:
        return dict(code='processing', text='CHIRPS observations published; awaiting processing')
    return dict(code='ready', text='Observations processed; verification not yet run')


def build_cycle(cfg_path, published, today, sha):
    """Everything the page shows for one cycle, plus the files to copy."""
    c = load_cycle(ROOT / cfg_path)
    out_root, season = c.root('output_root'), c.season_name
    raw = cycle_entries(c)
    if not raw:
        return None
    cid = f'{season.lower()}{c.year}'
    listing = out_root / 'entries.json'
    ej = json.loads(listing.read_text(encoding='utf-8')) if listing.is_file() else {}
    definition, note = domain_text(c, ej)
    s_start, s_end = target_window(season, c)
    crosses = s_start.year != s_end.year
    views = list(dict.fromkeys((e['view'], e['label']) for e in raw))
    domain_view = next((v for v, _ in views if v != 'all_ethiopia'), views[0][0])
    vroot = c.root('verification_root')
    processed = {m for m in c.targets if m != season and any((vroot / 'observations' / m).glob('chirps_*_common.nc'))}
    copies, targets = [], []
    reg_file = ROOT / f'outputs/regional_skill/{c.tag}_regional_skill.json'
    regional = json.loads(reg_file.read_text(encoding='utf-8')) if reg_file.is_file() else {}
    for t in [season, *[x for x in c.targets if x != season]]:
        window = target_window(t, c)
        item = dict(id=t, label=c.target_label(t), kind='season' if t == season else 'month',
                    start=window[0].isoformat(), end=window[1].isoformat(), forecast={}, verification={})
        for e in raw:
            if e['target'] != t:
                continue
            folder = f'assets/maps/{cid}/' + e['folder'].removeprefix('presentation/')
            images = [list(i) for i in e['images']]
            copies += [(out_root / e['folder'] / f'{name}.png', OUT / folder / f'{name}.png') for name, _ in images]
            composite = out_root / e['folder'] / 'verification_maps.png'
            if e['kind'] == 'verification' and composite.is_file() and panel_layout_ok(composite):
                images = ([['verification_comparison', 'Compare forecast and observed'],
                           ['verification_comparison_error', 'Compare with error map']]
                          + [list(x) for x in PANELS] + [['verification_maps', 'All six panels']])
                copies.append((composite, OUT / folder))          # a folder destination: split into panels
            item[e['kind']][e['view']] = dict(summary=e['summary'], folder=folder, images=images)
        months_ok = processed >= ({t} if t != season else set(c.targets) - {season})
        item['status'] = target_status(window, bool(item['verification']), months_ok, published, today)
        # Historical skill per area: all Ethiopia and the cycle's rainfall domain (regional_skill.py --cycle).
        national = {mode: year_skill(ROOT / f'outputs/local_calibration/{c.tag}_{t}/{mode}/local_comparison_summary.json')
                    for mode in ('training', 'operational')}
        item['history'] = {'all_ethiopia': national}
        if t in regional.get('targets', {}):
            item['history'][domain_view] = {mode: area_skill(regional['targets'][t][mode].get('season_domain'), national[mode])
                                            for mode in ('training', 'operational')}
        nc = c.forecast_file(c.root('forecast_root'), t)
        if nc.is_file():
            item['netcdf'] = f'downloads/data/{cid}/{t}_forecast_{c.year}.nc'
            copies.append((nc, OUT / item['netcdf']))
        blend = c.forecast_dir(c.root('forecast_root'), t) / 'blend_parameters.json'
        item['lambda'] = json.loads(blend.read_text(encoding='utf-8'))['climatology_weight'] if blend.is_file() else None
        targets.append(item)
    add_holm(targets)
    regions = {}
    if regional:
        names = dict(ethiopia='All Ethiopia', R0_arid_marginal='R0 arid / marginal', R1_western_unimodal='R1 western unimodal',
                     R2_belg_kiremt='R2 Belg–Kiremt', R3_gu_deyr='R3 Gu–Deyr', season_domain=regional.get('domain_label'))
        regions = dict(label=regional.get('domain_label'), rows=[
            [names.get(r, r), {t['id']: area_skill(regional['targets'][t['id']]['training'].get(r), t['history']['all_ethiopia']['training'])
                               for t in targets if t['id'] in regional['targets']}] for r in regional['regions']])

    # ---------- status panel (cycle metadata)
    freeze = vroot / 'frozen_forecasts/freeze_manifest.json'
    state = out_root / 'state/latest_run.json'
    verified = [x['label'] for x in targets if x['verification']]
    if freeze.is_file():
        stamp = json.loads(freeze.read_text(encoding='utf-8'))['created_utc']
        when = ('after the target period ended, ' if datetime.fromisoformat(stamp).date() > s_end
                else 'after the target period began, ' if datetime.fromisoformat(stamp).date() >= s_start else '')
        frozen = f'Frozen {iso_day(stamp)} ({when}before this project downloaded its observations; SHA-256 manifest)'
    else:
        made = iso_day(ej['created_utc']) if 'created_utc' in ej else 'date not recorded'
        frozen = f'Generated {made}; not yet frozen for verification (freeze before observations are used)'
    obs_months = sorted((target_window(m, c)[0].year, list(calendar.month_abbr).index(m)) for m in processed)
    if obs_months:
        y, m = obs_months[-1]
        obs_text = f'{calendar.month_name[m]} {y} ({", ".join(calendar.month_abbr[mm] for _, mm in obs_months)})'
    else:
        obs_text = 'None yet'
    last_run = 'Not run'
    if verified and state.is_file():
        last_run = iso_day(json.loads(state.read_text(encoding='utf-8'))['finished_utc'])
    if published is None:
        archive = 'Not checked at build time'
    else:
        latest = max(published)
        gaps = [f'{calendar.month_abbr[m]} {y}' for y, m in months_between(date(latest[0] - 1, 1, 1), date(*latest, 1))
                if (y, m) not in published]
        archive = (f'Official CHIRPS v2.0 p25 by_month listing checked {day(today)}: monthly files through '
                   f'{calendar.month_abbr[latest[1]]} {latest[0]}'
                   + (f'; {", ".join(gaps)} file not found' if gaps else ''))
    lam = next((x['lambda'] for x in targets if x['kind'] == 'season'), None)
    meta = [
        ['Model initialization', f'1 {c.init_month_name} {c.year} · ECMWF SEAS5 (system 51), {c.members(c.year)} members'],
        ['Target period', f'{day(s_start)} – {day(s_end)}'],
        ['Forecast record', frozen],
        ['Publication status', 'Research reconstruction: produced after the initialization date with the published '
                               'method; not an official EMI or ICPAC forecast'],
        ['Reference period', f'CHIRPS v2.0 {season} {ref_label(c, crosses)} ({len(c.reference_years)} seasons)'],
        ['Observations processed through', obs_text],
        ['CHIRPS archive', archive],
        ['Verification last run', last_run],
        ['Method / version', f'Shared climatology blend (λ = {lam:.2f} for {season}) · code {sha}' if lam is not None
                             else f'Shared climatology blend · code {sha}'],
    ]

    # ---------- downloads
    downloads = [dict(label=f'Bulletin, {c.target_label(season)} (PDF)', href=f'downloads/{cid}_bulletin.pdf',
                      note='Outlook, interpretation, evidence, cycle record, limitations and monthly maps (3 pages)'),
                 dict(label=f'Summary table, {c.target_label(season)} (CSV)', href=f'downloads/{cid}_summary.csv',
                      note='Every target and view: probabilities, amounts, coverage, status and verification scores'),
                 dict(label='Metadata (JSON)', href=f'downloads/{cid}_metadata.json',
                      note='Initialization, target dates, reference period, method version, freeze status and file list')]
    for report in sorted((out_root / 'reports').glob('*/VERIFICATION_REPORT.html')):
        if '_backup_' in report.parent.name:
            continue
        name = f'downloads/{cid}_verification_report_{report.parent.name}.html'
        copies.append((report, OUT / name))
        downloads.append(dict(label=f'Verification report, {report.parent.name.replace("_", ", ")} (HTML)', href=name,
                              note='Self-contained report with maps and tables'))
    bulletin = ROOT / f'outputs/forecast_delivery/{c.tag}_{c.year}/BULLETIN.md'
    if bulletin.is_file():
        copies.append((bulletin, OUT / f'downloads/{cid}_bulletin.md'))
        downloads.append(dict(label='Original forecast bulletin (Markdown)', href=f'downloads/{cid}_bulletin.md',
                              note='Text bulletin issued with the frozen forecast'))
    data = dict(id=cid, cfg=cfg_path, tag=c.tag, season=season, label=c.target_label(season), init=c.init_month_name,
                option=f'{c.target_label(season)} — {c.init_month_name} initialization',
                init_date=date(c.year, c.init_month, 1).isoformat(), views=views, domain_view=domain_view,
                definition=definition, note=note, reference=ref_label(c, crosses), targets=targets, meta=meta, regions=regions,
                downloads=downloads)
    return data, copies


def package_files(cyc):
    """Everything in a cycle's ZIP package: (path on the site, path inside the archive)."""
    cid = cyc['id']
    files = [(f'downloads/{cid}_README.txt', 'README.txt'), (f'downloads/{cid}_metadata.json', 'metadata.json'),
             (f'downloads/{cid}_summary.csv', 'summary.csv'), (f'downloads/{cid}_bulletin.pdf', 'bulletin.pdf')]
    for d in cyc['downloads']:
        if '_comparison' in d['href']:
            continue                                      # added below with the comparison folder
        if d['href'].endswith('.html'):
            files.append((d['href'], 'reports/' + d['href'].split('/')[-1].removeprefix(f'{cid}_')))
        elif d['href'].endswith('.md'):
            files.append((d['href'], 'original_bulletin.md'))
    for t in cyc['targets']:
        for kind in ('forecast', 'verification'):
            for view, e in t[kind].items():
                files += [(f'{e["folder"]}/{name}.png', f'maps/{kind}/{t["id"]}/{view}/{name}.png') for name, _ in e['images']]
        if t.get('netcdf'):
            files.append((t['netcdf'], 'data/' + t['netcdf'].split('/')[-1]))
    files += [tuple(x) for x in cyc.get('comparison_package', [])]
    return [[a, b] for a, b in files if (OUT / a).is_file() or a.endswith(('README.txt', 'metadata.json'))]


def write_csv(cyc):
    path = OUT / f'downloads/{cyc["id"]}_summary.csv'
    path.parent.mkdir(parents=True, exist_ok=True)
    labels = dict(cyc['views'])
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['cycle', 'initialization', 'target', 'target_start', 'target_end', 'view', 'prob_below', 'prob_near',
                    'prob_above', 'forecast_mean_mm', 'reference_mean_mm', 'anomaly_mm', 'anomaly_percent',
                    'probability_coverage_percent', 'amount_coverage_percent', 'status', 'rpss_blended_probabilities',
                    'crpss_corrected_amounts', 'bias_mm', 'observed_below', 'observed_near', 'observed_above',
                    'observed_anomaly_mm', 'forecast_anomaly_mm'])
        for t in cyc['targets']:
            for view, label in cyc['views']:
                s = t['forecast'].get(view, {}).get('summary')
                if not s:
                    continue
                v = t['verification'].get(view, {}).get('summary')
                p = [None if x is None else round(x, 4) for x in s['mean_local_probabilities']]
                ref = s['mean_reference_mm']
                row = [cyc['label'], cyc['init_date'], t['label'], t['start'], t['end'], labels[view], *p,
                       round(s['mean_rainfall_mm'], 1), round(ref, 1), round(s['mean_anomaly_mm'], 1),
                       round(100 * s['mean_anomaly_mm'] / ref, 1) if ref else '',
                       round(s['probability_domain_area_percent'], 1), round(s['amount_domain_area_percent'], 1),
                       t['status']['text']]
                if v:
                    row += [round(v['probability']['shared_blend']['rpss'], 4), round(v['amount']['corrected']['crpss'], 4),
                            round(v['amount']['corrected']['bias_mm'], 1),
                            *[round(x, 4) for x in v['observed_category_area_fractions']],
                            round(v['observed_mean_anomaly_mm'], 1), round(v['forecast_mean_anomaly_mm'], 1)]
                w.writerow(row)


def jjas_evidence():
    """May-initialized JJAS diagnostics shown in the methods section (computed only for that cycle)."""
    return dict(gates=load('outputs/decision_gates/decision_gates.json')['gates'],
                ens=load('outputs/ensemble_checks/ensemble_checks.json')['targets'],
                mono=load('outputs/monthly_consistency/monthly_consistency.json'),
                clip=load('outputs/clipping_analysis/amount_correction_alternatives.json')['targets'],
                raw=load('outputs/verification/init05_JJAS/Ethiopia/verification_summary.json')['summary'])


def page(cycles, default, ev, built, sha, release_id='unreleased'):
    gates, ens, mono, clip, raw = (ev[k] for k in ('gates', 'ens', 'mono', 'clip', 'raw'))
    raw_rpss = raw.get('raw_rps_skill')

    gate_names = [('ethiopia_lambda_vs_current', 'Fit the blend weight on Ethiopia only'),
                  ('sqrt_vs_current', 'Square-root amount correction (probabilities)'),
                  ('no_blend_vs_current', 'Remove the climatology blend'),
                  ('climatology_vs_current', 'Plain climatology')]
    gate_rows = []
    for fam, label in gate_names:
        g = gates[fam]
        tr = [g[t]['training']['mean_difference'] for t in JJAS_TARGETS]
        op = [g[t]['operational']['mean_difference'] for t in JJAS_TARGETS]
        adopted = [t for t in JJAS_TARGETS if g[t]['decision']['adopt']]
        gate_rows.append([label, f'{signed(min(tr), 4)} to {signed(max(tr), 4)}', f'{signed(min(op), 4)} to {signed(max(op), 4)}',
                          'Adopted: ' + ', '.join(adopted) if adopted else 'Not adopted'])
    sq = [clip[t]['training_loyo_1993_2016'] for t in JJAS_TARGETS]
    dq = [s['sqrt_affine']['crps'] - s['affine']['crps'] for s in sq]
    gate_rows.append(['Square-root amount correction (amounts, CRPS in mm)', f'{signed(min(dq), 2)} to {signed(max(dq), 2)}',
                      'lower in all targets', 'Passes for all targets; candidate for the next cycle'])
    gate = table(['Candidate change', 'Score change 1993–2016', 'Score change 2017–2025', 'Decision'], gate_rows,
                 'Method changes tested with whole-year significance gates (May-initialized JJAS targets; negative = better)')

    ens_rows = [[t, f'{ens[t]["ensemble_size"]["rps_51"]:.4f}', f'{ens[t]["ensemble_size"]["rps_25_mean"]:.4f}',
                 f'{ens[t]["system_consistency"]["spread_error_ratio_hindcast"]:.2f} → {ens[t]["system_consistency"]["spread_error_ratio_operational"]:.2f}']
                for t in JJAS_TARGETS]
    ens_t = table(['Target', 'RPS, 51 members', 'RPS, 25-member subsets (mean)', 'Spread / error (hindcast → 2017–2025)'], ens_rows,
                  'Ensemble-size check, May-initialized JJAS targets, 2017–2025 (lower RPS is better)', 'compact')
    mc = mono['frozen_2026']

    steps = [
        ('Download', 'ECMWF SEAS5 (system 51) daily accumulated precipitation from the Copernicus CDS for the initialization month, 1993 to the forecast year.', 'download_seasonal_forecasts_daily_c3s.py'),
        ('Inspect', 'Inventory every year: initialization, lead times, member counts and accumulation increments (GRIB packing tolerance 0.2 mm).', 'inspect_inputs.py'),
        ('Prepare', 'De-accumulate to daily totals, sum the season and each month; CHIRPS on the same dates.', 'prepare_seasonal.py · run_monthly.py'),
        ('Regrid', 'Each 1° model cell is copied into its 4×4 block of 0.25° CHIRPS cells (no interpolation).', 'regrid_seasonal.py'),
        ('Calibrate', 'Per-cell amount correction, smoothed tercile counts and one climatology-blend weight per target.', 'final_shared_blend.py'),
        ('Evaluate', 'Nested cross-validation 1993–2016; exploratory fixed-fit scores for later years; whole-year significance tests.', 'local_blend.py · decision_gates.py'),
        ('Deliver', 'Maps, summaries and an offline gallery; forecasts frozen with SHA-256 hashes before observations are used.', 'run_operational.py · build_season_products.py'),
        ('Verify', 'Official CHIRPS v2.0 monthly files, checked against the archive where they overlap, scored per month and season.', 'prepare_verification_2026.py · verify_frozen_2026.py'),
    ]
    flow = ''.join(f'<li class="step"><span class="step-n">{i}</span><div><h4>{a}</h4><p>{b}</p><code>{c}</code></div></li>'
                   for i, (a, b, c) in enumerate(steps, 1))

    options = ''.join(f'<option value="{c["id"]}"{" selected" if c["id"] == default else ""}>{esc(c["option"])}</option>'
                      for c in cycles)
    # Static fallback: each cycle's season outlook in its rainfall domain.
    rows = []
    for c in cycles:
        t = c['targets'][0]
        s = t['forecast'][c['domain_view']]['summary']
        p = s['mean_local_probabilities']
        rows.append([esc(c['option']), esc(dict(c['views'])[c['domain_view']]),
                     ' / '.join('—' if x is None else f'{100 * x:.0f}%' for x in p),
                     f'{signed(s["mean_anomaly_mm"], 0)} mm', esc(t['status']['text'])])
    fallback = table(['Cycle', 'Rainfall domain', 'Average local probability below / near / above', 'Forecast anomaly',
                      'Season status'], rows, 'Season outlooks of every cycle (scripts are off, so only this summary is shown)')
    data_json = json.dumps(dict(cycles=cycles, default=default, products=PRODUCTS)).replace('</', '<\\/')
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ethiopia Seasonal Rainfall</title>
<meta name="description" content="Calibrated ECMWF SEAS5 seasonal rainfall outlooks for Ethiopia (FMAM, JJAS, ONDJ), with maps, verification against CHIRPS and historical skill.">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<a class="skip" href="#outlooks">Skip to the outlook</a>
<header class="top">
  <div class="wrap nav">
    <a class="brand" href="#top">Ethiopia Seasonal Rainfall</a>
    <nav aria-label="Sections"><a href="#outlooks">Outlooks</a><a href="#official">Compare outlooks</a><a href="#maps">Maps</a><a href="#verification">Verification</a><a href="#history">Historical performance</a><a href="#methods">Methods &amp; data</a><a href="#downloads">Downloads</a></nav>
  </div>
  <div class="cyclebar">
    <div class="wrap pickers">
      <label>Forecast cycle <select id="cycle">{options}</select></label>
      <label>Area <select id="view"></select></label>
      <span class="research">Research reconstruction · not an official EMI or ICPAC forecast</span>
    </div>
  </div>
</header>
<main id="top">
<noscript><section class="wrap"><p class="notice">This page needs JavaScript for the cycle selector and maps. The summary below lists each cycle's season outlook; reports and tables are listed on the <a href="downloads/index.html">downloads page</a> and the <a href="{REPO}">repository</a>.</p>{fallback}</section></noscript>

<section id="outlooks" class="wrap">
  <p class="eyebrow" id="ol-eyebrow"></p>
  <h1 id="ol-title">Seasonal rainfall outlook</h1>
  <p class="research-inline">Research reconstruction · not an official forecast</p>
  <div id="ol-live" aria-live="polite" class="sr-only"></div>
  <div class="targets" role="group" aria-label="Target period" id="ol-targets"></div>
  <div class="glance">
    <div class="glance-text">
      <p class="lead" id="ol-lead"></p>
      <div class="box">
        <h3>Average local probability</h3>
        <div id="ol-prob"></div>
        <p class="caveat" id="ol-prob-note"></p>
      </div>
      <div class="box">
        <h3>Rainfall amount</h3>
        <div id="ol-amount"></div>
      </div>
      <div class="pair">
        <div class="box"><h3>Forecast signal</h3><div id="ol-signal"></div></div>
        <div class="box"><h3 id="ol-skill-title">Historical skill</h3><div id="ol-skill"></div></div>
      </div>
      <p class="caveat">Signal strength describes how far this forecast's probabilities depart from climatology. Historical skill describes how forecasts made the same way scored in past years. A strong signal is not a confidence rating.</p>
    </div>
    <figure class="glance-map" id="ol-map"></figure>
  </div>
  <h2 class="h3">All targets in this cycle</h2>
  <div id="ol-table"></div>
  <h2 class="h3" id="official">Official outlook comparison</h2>
  <div id="cmp-body" aria-live="polite"></div>
  <details class="panel-details" open>
    <summary>Cycle status and record</summary>
    <div id="ol-meta"></div>
  </details>
</section>

<section id="maps" class="wrap">
  <h2>Maps</h2>
  <div class="map-controls">
    <label>Target <select id="mp-target"></select></label>
    <div class="seg" role="group" aria-label="Product" id="mp-kind"></div>
  </div>
  <div class="tabs" role="group" aria-label="Map type" id="mp-tabs"></div>
  <div id="mp-toggle"></div>
  <div class="map-actions" id="mp-actions">
    <button type="button" id="mp-copy">Copy link to this view</button>
    <a id="mp-open" target="_blank" rel="noopener">Open full-size</a>
    <a id="mp-download" download>Download PNG</a>
    <span id="mp-copied" class="caveat" aria-live="polite"></span>
  </div>
  <figure class="map-figure" id="mp-figure"></figure>
  <div class="grid2">
    <div class="box"><h3>How to read this map</h3><div id="mp-help"></div></div>
    <div class="box"><h3>Grey, white and blank areas</h3>
      <p><strong>Light grey</strong>: outside the selected area. <strong>Dark grey</strong>: inside the area but without values, for example cells where reference-period rainfall is too small for tercile categories, or (percent maps) below 10&nbsp;mm. <strong>White</strong> on tercile maps: no category reaches 40%, or two categories tie. Sea cells have no CHIRPS data.</p>
      <p><strong>Smoothing and resolution.</strong> Maps are drawn on a 12× finer display grid with light Gaussian smoothing (σ = 0.6 grid cells); all numbers on this page use the original 0.25° grid. The model's own resolution is about 1°: each model cell covers 4×4 grid cells, so detail within a 1° box comes from local CHIRPS rainfall statistics used in the amount correction, not from the model.</p>
    </div>
  </div>
</section>

<section id="verification" class="wrap">
  <h2>Verification</h2>
  <p>Frozen forecasts compared with official CHIRPS v2.0 observations once a target period is complete. Each result is one season or month, so it shows what happened this time, not long-term reliability.</p>
  <div id="vf-body" aria-live="polite"></div>
</section>

<section id="history" class="wrap">
  <h2>Historical performance</h2>
  <p>How forecasts made with the same method scored in past years against climatology (the observed frequency of each tercile in the training years, about one-third each). The main number is the <strong>cross-validated 1993–2016</strong> score: each year is forecast with parameters fitted without that year. Later years are <strong>exploratory</strong>: they were seen while the method was chosen.</p>
  <div id="hs-body"></div>
  <h3>Historical verification explorer</h3>
  <p class="caveat">The evidence behind the scores above, for the selected cycle, target and area. Choose the evaluation period; all diagnostics use the blended probabilities against climatology.</p>
  <div class="map-controls">
    <label>Target <select id="dg-target"></select></label>
    <div class="seg" role="group" aria-label="Evaluation period" id="dg-period"></div>
  </div>
  <div id="dg-body" aria-live="polite"></div>
  <h3>Historical performance by rainfall region</h3>
  <div id="hs-regions"></div>
</section>

<section id="methods" class="wrap">
  <h2>Methods &amp; data</h2>
  <div class="grid2">
    <div>
      <h3>In brief</h3>
      <p>Each cycle starts from the ECMWF SEAS5 seasonal ensemble issued on the 1st of the initialization month. For every 0.25° grid cell in Ethiopia the forecast rainfall is corrected toward the CHIRPS observed mean and variability, then turned into tercile probabilities (below, near or above normal relative to the cycle's CHIRPS reference period). The probabilities are finally blended with climatology using one weight per target, chosen to give the best past scores. Climatology assigns approximately one-third probability to each tercile; the calculations use the observed category frequencies of the training reference period.</p>
      <p>Probabilities and amounts are produced separately: the <strong>probability skill (RPSS)</strong> on this site refers to the blended probabilities, and the <strong>rainfall amount skill (CRPSS)</strong> to the amount-corrected ensemble.</p>
      <p>The <strong>raw benchmark</strong> is the uncorrected model: raw ECMWF members counted against each cell's CHIRPS tercile limits, with no correction, smoothing or blend.{f" For May-initialized JJAS over 2017–2025 it scores RPSS {signed(raw_rpss, 2)}, far below climatology, which is why calibration is needed." if raw_rpss is not None else ""}</p>
    </div>
    <div>
      <h3>Data</h3>
      {table(['Source', 'Details'], [
          ['ECMWF SEAS5', 'Copernicus CDS <code>seasonal-original-single-levels</code>, system 51, total precipitation, 1993 to the forecast year; 25 members to 2016, 51 from 2017; 1° grid'],
          ['CHIRPS v2.0', '0.25° daily rainfall; archive 1993–2025; verification months from the official monthly files, checked against the archive where they overlap'],
          ['Areas', 'All Ethiopia (1,484 cells) and one rainfall domain per season, built from rainfall regimes: FMAM R2 (Belg), JJAS R1+R2, ONDJ R3 (Deyr). The domains are for display and summaries only; calibration uses every cell.'],
      ], 'Data sources', 'compact')}
    </div>
  </div>
  <details><summary>Workflow (eight scripted stages)</summary><ol class="flow">{flow}</ol>
    <p class="caveat">Every stage is a script in <a href="{REPO}/tree/main/scripts"><code>scripts/</code></a>; documents in <a href="{REPO}/tree/main/docs"><code>docs/</code></a> record each step, issue and decision (runbook: docs/38; per-season guides: docs/40).</p></details>
  <details><summary>Equations</summary>
    <ol>
      <li><strong>Amount correction</strong> per cell, equal weight per year: <code>x̂ = max(0, μ<sub>obs</sub> + r·(x − μ<sub>model</sub>))</code>, <code>r = clip(σ<sub>obs</sub>/σ<sub>model</sub>, 0.5, 2)</code></li>
      <li><strong>Tercile probabilities</strong> from the corrected members against CHIRPS tercile limits, smoothed: <code>(n + 0.5)/(M + 1.5)</code></li>
      <li><strong>Climatology blend</strong>: <code>p<sub>final</sub> = (1 − λ)·p<sub>model</sub> + λ·p<sub>climatology</sub></code>, with one λ per target fitted on leave-one-year-out RPS.<br>
        <code>p<sub>climatology</sub></code> is, for each grid cell, the observed frequency of each tercile in the training reference years (about one-third each; it differs slightly because of sample size, category limits and ties).</li>
      <li><strong>Skill score</strong>: <code>RPSS = 1 − RPS<sub>forecast</sub> / RPS<sub>climatology</sub></code>; RPSS +0.05 means a 5% lower ranked probability score than climatology. CRPSS is the same for rainfall amounts.</li>
    </ol></details>
  <details><summary>How the method was chosen</summary>
    <p>A change is adopted only if it improves the cross-validated 1993–2016 scores (Holm-adjusted p &lt; 0.05 over the five JJAS targets) and does not worsen 2017–2025. Also evaluated and not adopted: regularized Dirichlet recalibration and per-cell or regime-specific blend weights.</p>
    {gate}</details>
  <details><summary>Ensemble size and spread</summary>
    {ens_t}
    <p class="caveat">Calibration parameters are fitted mostly on 25-member hindcasts and applied to 51-member forecasts. In 2017–2025 the 51-member forecasts scored about the same as, or slightly better than, 25-member subsets, so the transfer did not degrade scores in the years tested; this does not show it is neutral in every year or region. The corrected ensemble is under-dispersive (spread smaller than error), which the climatology blend partly offsets. Monthly and seasonal outlooks are calibrated separately: for JJAS 2026 over all Ethiopia the corrected monthly means sum to {mc["sum_of_monthly_corrected_means_mm"]:.0f} mm against {mc["jjas_corrected_mean_mm"]:.0f} mm for the season ({signed(mc["difference_mm"], 1)} mm).</p></details>
  <details><summary>Quality control</summary>
    <ul>
      <li>Every forecast file is inventoried; re-downloaded years were bit-identical, confirming SEAS5 system 51.</li>
      <li>Small negative daily increments (≤ 0.15 mm) are GRIB packing rounding; tolerated up to 0.2 mm and clipped, and the seasonal sum is checked.</li>
      <li>CHIRPS sea cells (223) are always missing; no partial season enters any fit.</li>
      <li>Verification observations are compared with the archive in the overlap year (tolerance 0.0001 mm/day) before use.</li>
    </ul></details>
  <details><summary>Limitations</summary>
    <ul>
      <li>Few evaluation years and single verification seasons give wide uncertainty; regional and monthly results are noisy.</li>
      <li>The later evaluation years were inspected during method development; the cleanest evidence is the cross-validated 1993–2016 score.</li>
      <li>The 0.25° maps repeat 1° model information; they add no dynamical detail.</li>
      <li>All cycles are research reconstructions produced after their initialization dates, not official EMI or ICPAC forecasts.</li>
    </ul></details>
  <details><summary>Reproduce</summary>
  <pre><code>git clone {REPO}.git
python -m venv .venv &amp;&amp; .venv\\Scripts\\activate &amp;&amp; pip install -r requirements.txt
set CALIBRATION_CYCLE=config\\cycles\\sep_2026_ondj.json
python scripts\\run_operational.py --config config\\cycles\\sep_2026_ondj.json --workflow all
python scripts\\build_site.py</code></pre>
  <p>Raw ECMWF and CHIRPS data are not stored in the repository. Step-by-step guides: <a href="{REPO}/blob/main/docs/40_SEASON_RUN_GUIDES.md">docs/40</a>; project status: <a href="{REPO}/blob/main/docs/36_PROJECT_STATUS_REVIEW.md">docs/36</a>.</p></details>
</section>

<section id="downloads" class="wrap">
  <h2>Downloads</h2>
  <div class="box"><h3>Complete package</h3>
    <p>One ZIP file with the PDF bulletin, summary CSV, metadata, README, every map (forecast and verification), verification reports and the forecast NetCDF files for the selected cycle.</p>
    <p><button type="button" id="dl-package">Download package (ZIP)</button> <span id="dl-progress" class="caveat" aria-live="polite"></span></p>
  </div>
  <div id="dl-body"></div>
  <p><a href="releases/index.html">Release archive and change log</a>: earlier published versions and what changed.</p>
  <p class="caveat">Individual maps: use <em>Download PNG</em> in the map viewer. Code, documentation and notebooks: <a href="{REPO}">GitHub repository</a>.</p>
</section>
</main>
<footer class="wrap foot">Release {release_id} · built {built} from the project's result files by <code>scripts/build_site.py</code> (code {sha}) · <a href="releases/index.html">Release archive and change log</a></footer>
<script id="site-data" type="application/json">{data_json}</script>
<script src="assets/site.js"></script>
</body>
</html>
'''


CSS = r'''
:root{--bg:#f7f7f5;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#6b6a66;--line:#e1e0dc;--accent:#1f6f5c;--accent-soft:#e6f1ed;
--fc:#2a78d6;--obs:#3d3c39;--below:#eb6834;--near:#a9a7a0;--above:#1baf7a;--pos:#1f6f5c;--neg:#b03a24;
--good:#1f7a4a;--good-bg:#e5f3ea;--warn:#8a5a00;--warn-bg:#fdf1d8;--info:#2a5d9f;--info-bg:#e7eff9;--plain-bg:#efeeea;--code:#efeeea}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#121211;--surface:#1b1b1a;--ink:#f1f0ec;--ink2:#c3c1bb;--muted:#a3a19b;--line:#33322f;
--accent:#6fc7ad;--accent-soft:#1d2b27;--fc:#5b9be6;--obs:#d9d7d0;--below:#f07d4f;--near:#8a8882;--above:#2cc58d;--pos:#7fd3b8;--neg:#f0907c;
--good:#7fd3a0;--good-bg:#1c2c22;--warn:#f0c46b;--warn-bg:#2d2414;--info:#8fb8f0;--info-bg:#18243a;--plain-bg:#262624;--code:#262624}}
:root[data-theme="dark"]{--bg:#121211;--surface:#1b1b1a;--ink:#f1f0ec;--ink2:#c3c1bb;--muted:#a3a19b;--line:#33322f;
--accent:#6fc7ad;--accent-soft:#1d2b27;--fc:#5b9be6;--obs:#d9d7d0;--below:#f07d4f;--near:#8a8882;--above:#2cc58d;--pos:#7fd3b8;--neg:#f0907c;
--good:#7fd3a0;--good-bg:#1c2c22;--warn:#f0c46b;--warn-bg:#2d2414;--info:#8fb8f0;--info-bg:#18243a;--plain-bg:#262624;--code:#262624}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:140px}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 Inter,system-ui,sans-serif}
a{color:var(--accent)}code,pre{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:.85em}
code{background:var(--code);padding:.1em .35em;border-radius:4px;overflow-wrap:anywhere}
pre{background:var(--code);padding:16px;border-radius:8px;overflow-x:auto}pre code{background:none;padding:0}
.wrap{max-width:1160px;margin:0 auto;padding:0 16px}
.skip{position:absolute;left:-9999px}.skip:focus{left:16px;top:8px;z-index:20;background:var(--surface);padding:8px 12px;border-radius:6px}
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.top{position:sticky;top:0;z-index:10;background:color-mix(in srgb,var(--bg) 92%,transparent);backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
.nav{display:flex;align-items:center;justify-content:space-between;gap:8px 20px;min-height:52px;flex-wrap:wrap}
.brand{font-weight:700;text-decoration:none;color:var(--ink);white-space:nowrap}
nav{display:flex;gap:18px;overflow-x:auto;white-space:nowrap;scrollbar-width:none}nav a{text-decoration:none;color:var(--ink2);font-size:.92rem;padding:4px 0}nav a:hover{color:var(--accent)}
.cyclebar{border-top:1px solid var(--line)}
.pickers{display:flex;flex-wrap:wrap;align-items:center;gap:8px 18px;padding-top:8px;padding-bottom:8px}
.pickers label,.map-controls label{display:flex;align-items:center;gap:8px;font-size:.88rem;color:var(--ink2);font-weight:500}
select,button,.map-actions a{font:inherit;font-size:.95rem;color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:6px 10px}
select{max-width:100%}select:focus-visible,button:focus-visible,a:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.research{font-size:.8rem;color:var(--warn);background:var(--warn-bg);padding:3px 10px;border-radius:999px}
section{padding:36px 0 8px}h1{font-size:clamp(1.7rem,3.6vw,2.5rem);line-height:1.15;margin:.15em 0 .3em}
h2,.h3{font-size:1.5rem;margin:0 0 .5em}.h3{font-size:1.15rem;margin-top:1.6em}h3{font-size:1.02rem;margin:0 0 .5em}h4{margin:0 0 .2em;font-size:.98rem}
.eyebrow{color:var(--accent);font-weight:600;margin:0}.lead{font-size:1.08rem;margin:0 0 14px}
.notice{background:var(--warn-bg);border-left:4px solid var(--warn);padding:12px 16px;border-radius:6px}
.targets{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 18px}
.chip{font-size:.9rem;border-radius:999px;padding:5px 14px;cursor:pointer}
.chip[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:var(--surface)}
.glance{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.05fr);gap:24px;align-items:start}
.glance>*,.grid2>*,.pair>*{min-width:0}
.box{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:12px}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px}.pair .box{margin-bottom:0}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:24px}
@media (max-width:900px){.glance,.grid2{grid-template-columns:1fr}}
@media (max-width:560px){.pair{grid-template-columns:1fr}.top{position:static}html{scroll-padding-top:8px}.research{display:none}}
.probbar{display:flex;gap:2px;height:26px;border-radius:6px;overflow:hidden;margin:4px 0 8px}
.probbar span{display:block;height:100%}.probbar span:first-child{border-radius:6px 0 0 6px}.probbar span:last-child{border-radius:0 6px 6px 0}
.problegend{display:flex;flex-wrap:wrap;gap:4px 18px;font-size:.92rem}.problegend b{font-variant-numeric:tabular-nums}
.sw{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.amount{display:grid;grid-template-columns:repeat(3,auto);gap:4px 18px;justify-content:start;font-variant-numeric:tabular-nums}
.amount div span{display:block;font-size:.8rem;color:var(--muted)}.amount div b{font-size:1.15rem}
.big{font-size:1.15rem;font-weight:700}
.caveat{color:var(--muted);font-size:.88rem}
figure{margin:0;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:10px}
figure img{width:100%;height:auto;display:block;border-radius:6px;background:#fff}figcaption{color:var(--ink2);font-size:.85rem;padding-top:6px}
.img-error{padding:40px 16px;text-align:center;color:var(--muted)}
.unavailable{padding:32px 16px;text-align:center;background:var(--warn-bg);border-radius:8px}.unavailable button{cursor:pointer;margin-top:4px}
.research-inline{display:none;font-size:.8rem;color:var(--warn);background:var(--warn-bg);padding:2px 10px;border-radius:999px;margin:0 0 6px}
@media (max-width:560px){.research-inline{display:inline-block}}   /* after the base rule so it wins on phones */
@media (max-width:560px){.pickers label,.map-controls label{flex-direction:column;align-items:stretch;gap:2px;width:100%}.pickers select,.map-controls select{width:100%}.hbar{grid-template-columns:110px 1fr 40px}.meta{font-size:.88rem}}
[hidden]{display:none!important}
.table-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--surface);margin:10px 0}
table{border-collapse:collapse;width:100%;font-size:.9rem}caption{text-align:left;padding:10px 12px 4px;color:var(--ink2);font-size:.85rem;caption-side:top}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
th{background:var(--accent-soft);font-weight:600}tbody tr:last-child td{border-bottom:none}table.compact td,table.compact th{padding:6px 10px}
td{font-variant-numeric:tabular-nums}.pos{color:var(--pos)}.neg{color:var(--neg)}.ci{color:var(--muted);font-size:.85em;white-space:nowrap}
tr.current td{background:color-mix(in srgb,var(--accent-soft) 60%,transparent)}
.linkbtn{background:none;border:none;padding:0;color:var(--accent);text-decoration:underline;cursor:pointer;font-size:inherit}
.status{display:inline-flex;align-items:center;gap:6px;font-size:.82rem;padding:2px 10px;border-radius:999px;background:var(--plain-bg);color:var(--ink2);white-space:normal}
.status::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor;flex:none}
.status.published{background:var(--good-bg);color:var(--good)}.status.published::before{content:"✓";width:auto;height:auto;background:none}
.status.awaiting,.status.processing,.status.ready{background:var(--warn-bg);color:var(--warn)}
.status.ongoing,.status.not_started{background:var(--info-bg);color:var(--info)}
.meta{display:grid;grid-template-columns:max-content 1fr;gap:6px 18px;margin:8px 0;font-size:.92rem}.meta dt{color:var(--ink2);font-weight:600}.meta dd{margin:0}
@media (max-width:560px){.meta{grid-template-columns:1fr}.meta dd{margin-bottom:6px}}
details{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:10px 16px;margin:10px 0}
summary{cursor:pointer;font-weight:600}details[open] summary{margin-bottom:8px}
.panel-details{margin-top:18px}
.map-controls{display:flex;flex-wrap:wrap;gap:10px 20px;align-items:center;margin-bottom:10px}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.seg button{border:none;border-radius:0;border-right:1px solid var(--line)}.seg button:last-child{border-right:none}
.seg button[aria-pressed="true"],.tab[aria-pressed="true"]{background:var(--accent);color:var(--surface)}
.seg button:disabled{color:var(--muted);cursor:not-allowed}
.tabs{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 10px}.tab{border-radius:999px;padding:5px 14px;cursor:pointer;font-size:.9rem}
.map-actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:10px}
.map-actions a{text-decoration:none;display:inline-block}.map-actions button{cursor:pointer}
.map-figure{max-width:900px}.map-figure.wide{max-width:none}
.chart{width:100%;max-width:720px;height:auto;display:block}.chart text{fill:var(--ink2);font:13px Inter,system-ui,sans-serif}
.chart .val{fill:var(--ink);font-weight:600}.chart .axis{stroke:var(--line)}.chart .zero{stroke:var(--ink2)}
.legend{display:flex;flex-wrap:wrap;gap:4px 18px;font-size:.9rem;margin:4px 0}
.scope{font-size:.95rem;margin:4px 0 8px}.cmp-pair{display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start;margin:12px 0}
.cmp-pair figure{margin:0}@media (max-width:860px){.cmp-pair{grid-template-columns:1fr}}.nowrap{white-space:nowrap}.cmp-square{max-width:640px}.findings{margin:0;padding-left:20px}.findings li{margin:6px 0}
.evlinks{display:block;font-size:.85rem;color:var(--muted)}.evlinks a{white-space:nowrap}
.quote{margin:8px 0;padding:8px 12px;border-left:3px solid var(--line);color:var(--ink2);font-size:.92rem}
.chart.rel{max-width:340px}.check{display:inline-flex;gap:8px;align-items:center;font-size:.92rem;margin:0 0 10px}
.hbars{display:grid;gap:6px;margin:8px 0 12px}.hbar{display:grid;grid-template-columns:150px 1fr 48px;gap:8px;align-items:center;font-size:.88rem}
.hbar div{background:var(--plain-bg);border-radius:4px;height:14px;overflow:hidden}.hbar i{display:block;height:100%;background:var(--fc);border-radius:0 4px 4px 0}
.hbar b{text-align:right;font-variant-numeric:tabular-nums}
.vcard h3{margin-bottom:.3em}.qa{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
@media (max-width:900px){.qa{grid-template-columns:1fr}}
.qa h4{color:var(--ink2);font-size:.85rem;text-transform:uppercase;letter-spacing:.03em}.qa ul{margin:0;padding-left:18px}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin-top:12px}
.metric{border-top:1px solid var(--line);padding-top:8px}.metric span{display:block;font-size:.8rem;color:var(--muted)}.metric b{font-size:1.05rem}
.flow{list-style:none;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px}
.step{display:flex;gap:10px;border:1px solid var(--line);border-radius:10px;padding:10px}.step>div{min-width:0}.step p{margin:0 0 .4em;color:var(--ink2);font-size:.9rem}
.step-n{flex:none;width:26px;height:26px;border-radius:50%;background:var(--accent-soft);color:var(--accent);display:grid;place-items:center;font-weight:700;font-size:.85rem}
.dl{list-style:none;padding:0;margin:0}.dl li{padding:10px 0;border-bottom:1px solid var(--line)}.dl li:last-child{border-bottom:none}.dl li>span:not(.status){display:block;color:var(--muted);font-size:.85rem}
.foot{color:var(--muted);font-size:.85rem;padding:32px 16px 48px;border-top:1px solid var(--line);margin-top:40px}
'''


JS = r'''
(() => {
  const D = JSON.parse(document.getElementById('site-data').textContent);
  const $ = id => document.getElementById(id);
  const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const CAT = ['below normal', 'near normal', 'above normal'];
  const CATV = ['--below', '--near', '--above'];
  const ok = x => x !== null && x !== undefined && !Number.isNaN(x);
  const fx = (x, d = 0) => ok(x) ? Number(x).toFixed(d).replace('-', '−') : '—';
  const sg = (x, d = 0) => !ok(x) ? '—' : Number(Math.abs(x).toFixed(d)) === 0 ? (0).toFixed(d) : (x > 0 ? '+' : '−') + Math.abs(x).toFixed(d);
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const dt = s => { const [y, m, d] = s.split('-').map(Number); return d + ' ' + MON[m - 1] + ' ' + y; };
  const pc = (x, d = 0) => ok(x) ? (100 * x).toFixed(d) + '%' : '—';
  // Shares near the ends are not rounded to 'all' or 'none'; agreement shares keep one decimal.
  const share = x => !ok(x) ? '—' : (x >= 0.995 && x < 1) ? '>99%' : (x > 0 && x < 0.005) ? '<1%' : (100 * x).toFixed(0) + '%';
  const share1 = x => !ok(x) ? '—' : x >= 0.99995 ? '100%' : (100 * x).toFixed(1) + '%';
  const PRODUCTS = D.products;
  const HELP = {
    tercile_outlook: '<p>Colour shows the <strong>most likely tercile</strong> at each place, shaded by its probability: yellow–red for below normal, cyan for near normal, green for above normal. Terciles split the reference-period rainfall into three equally likely parts, so climatology is about 33% each. Places where no category reaches 40% are left white.</p>',
    rainfall_total_mm: '<p>The <strong>corrected ensemble-mean rainfall</strong> for the target period in mm. It is the average of the bias-corrected members, not a probability.</p>',
    rainfall_anomaly_mm: '<p>The <strong>difference in mm</strong> between the corrected ensemble mean and the reference-period CHIRPS average. Red–orange: drier than average; green: wetter.</p>',
    rainfall_anomaly_percent: '<p>The same anomaly as a <strong>percentage of the reference average</strong>. Hidden where the reference rainfall is below 10 mm, where percentages exaggerate small amounts.</p>',
    verification_maps: '<p>All six panels in one figure (also available separately): observed anomaly, forecast anomaly, forecast minus observed, the observed tercile at each cell, the probability score difference against climatology and the rainfall amount score.</p>',
    verification_comparison: '<p><strong>Forecast anomaly (left) and observed anomaly (right)</strong> for the same target and area, cut from one figure: same map extent, units (mm), reference period and colour scale. Brown: drier than average; green: wetter.</p>',
    verification_comparison_error: '<p><strong>Forecast anomaly, observed anomaly and forecast minus observed</strong>. The first two share one colour scale; in the error map red means the forecast was too wet and blue too dry.</p>',
    verification_observed_anomaly: '<p><strong>Observed rainfall anomaly</strong> (CHIRPS minus the reference average, mm). Brown: drier than average; green: wetter. Same colour scale as the forecast anomaly panel.</p>',
    verification_forecast_anomaly: '<p><strong>Forecast anomaly</strong> of the frozen corrected ensemble mean (mm), on the same colour scale as the observed anomaly so the two can be compared directly.</p>',
    verification_error: '<p><strong>Forecast minus observed</strong> rainfall (mm). Red: the forecast was too wet; blue: too dry.</p>',
    verification_observed_tercile: '<p>The <strong>observed tercile</strong> at each grid cell (below, near or above normal) relative to the reference period. Cells are not smoothed or filled from neighbours.</p>',
    verification_rps_difference: '<p><strong>Probability score difference</strong>: RPS of the forecast minus RPS of climatology at each cell. Blue (negative) favours the forecast; red favours climatology.</p>',
    verification_crps: '<p><strong>Rainfall amount score</strong> (CRPS of the corrected ensemble, mm). Lower is better; it grows with the size of the error and with rainfall amounts.</p>'
  };
  let S = {};
  const cyc = () => D.cycles.find(c => c.id === S.cycle);
  const tgt = () => cyc().targets.find(t => t.id === S.target);
  const viewLabel = v => (cyc().views.find(x => x[0] === v) || [v, v])[1];

  function init() {
    const q = new URLSearchParams(location.search);
    const c = D.cycles.find(x => x.id === q.get('cycle')) || D.cycles.find(x => x.id === D.default);
    S.cycle = c.id;
    S.target = c.targets.some(t => t.id === q.get('target')) ? q.get('target') : c.targets[0].id;
    S.view = c.views.some(v => v[0] === q.get('view')) ? q.get('view') : c.domain_view;
    S.kind = q.get('kind') === 'verification' ? 'verification' : 'forecast';
    S.product = q.get('product') || 'tercile_outlook';
    S.period = q.get('period') === 'operational' ? 'operational' : 'training';
  }
  function sync() {
    const q = new URLSearchParams({cycle: S.cycle, target: S.target, view: S.view, kind: S.kind, product: S.product, period: S.period});
    history.replaceState(null, '', location.pathname + '?' + q + location.hash);
  }

  function status(st) { return '<span class="status ' + st.code + '">' + esc(st.text) + '</span>'; }
  function signal(p) {
    if (!p || p.some(x => !ok(x))) return {text: 'Not available', cat: -1, shift: 0};
    const k = p.indexOf(Math.max(...p)), shift = p[k] - 1 / 3;
    const word = shift < 0.04 ? null : shift < 0.10 ? 'Weak' : shift < 0.20 ? 'Moderate' : 'Strong';
    return {cat: word ? k : -1, shift, text: word ? word + ' tilt toward ' + CAT[k] : 'No clear tilt (close to climatology)'};
  }
  // Verbal skill labels carry the uncertainty: an interval that includes zero is not an established gain.
  function skillWord(h) {
    if (!h) return '—';
    if (h.ci[0] > 0) return (h.rpss < 0.03 ? 'Small' : h.rpss < 0.10 ? 'Modest' : 'Moderate') + ' improvement over climatology (interval above zero)';
    if (h.rpss > 0) return 'Small estimated improvement; skill uncertain';
    return 'No demonstrated improvement over climatology';
  }
  function holmText(h, n) {
    if (!h || !ok(h.holm_p)) return '';
    return 'One-target p = ' + h.p.toFixed(3) + '; adjusted for testing ' + n + ' targets (Holm), p = ' + h.holm_p.toFixed(3) + (h.holm_p < 0.05 ? ' (still significant).' : ' (not significant after adjustment).');
  }
  // Historical skill for the selected area; falls back to all Ethiopia with an explicit label.
  function areaHistory(t) {
    const own = t.history[S.view];
    if (own && own.training) return {h: own, area: viewLabel(S.view), fallback: false};
    return {h: t.history.all_ethiopia, area: 'All Ethiopia', fallback: S.view !== 'all_ethiopia'};
  }
  function rpssText(r) { return sg(r, 3) + ' (' + Math.abs(100 * r).toFixed(1) + '% ' + (r >= 0 ? 'lower' : 'higher') + ' score than climatology)'; }
  function img(e, name, cap, alt) {
    const src = e.folder + '/' + name + '.png';
    return '<a href="' + src + '" target="_blank" rel="noopener"><img src="' + src + '" alt="' + esc(alt) +
      '" onerror="this.parentNode.outerHTML=\'<p class=img-error>Map image could not be loaded. Try Open full-size or the Downloads section.</p>\'"></a>' +
      '<figcaption>' + esc(cap) + '</figcaption>';
  }

  // ---------- outlook
  function renderOutlook() {
    const c = cyc(), t = tgt(), f = t.forecast[S.view];
    $('ol-eyebrow').textContent = c.init + ' initialization · ECMWF SEAS5 calibrated with CHIRPS · ' + viewLabel(S.view);
    $('ol-title').textContent = t.label + ' rainfall outlook';
    $('ol-targets').innerHTML = c.targets.map(x => '<button type="button" class="chip" aria-pressed="' + (x.id === S.target) +
      '" data-t="' + x.id + '">' + esc(x.label) + '</button>').join('');
    if (!f) { $('ol-lead').textContent = 'No forecast is available for this view.'; return; }
    const s = f.summary, p = s.mean_local_probabilities, sig = signal(p);
    const ref = s.mean_reference_mm, anomPct = ref ? 100 * s.mean_anomaly_mm / ref : null;
    const where = S.view === 'all_ethiopia' ? 'across Ethiopia' : 'in the ' + viewLabel(S.view);
    let lead = sig.cat >= 0
      ? 'The forecast leans toward <strong>' + CAT[sig.cat] + '</strong> rainfall ' + esc(where) + ': averaged over the area, the local probability of ' + CAT[sig.cat] + ' is <strong>' + pc(p[sig.cat]) + '</strong>, against about 33% for climatology.'
      : 'The forecast is <strong>close to climatology</strong> ' + esc(where) + ': no tercile stands out on average.';
    lead += ' Mean forecast rainfall is ' + fx(s.mean_rainfall_mm) + ' mm against a ' + c.reference + ' average of ' + fx(ref) + ' mm (' + sg(s.mean_anomaly_mm) + ' mm' + (ok(anomPct) ? ', ' + sg(anomPct) + '%' : '') + ').';
    $('ol-lead').innerHTML = lead;
    $('ol-live').textContent = t.label + ', ' + viewLabel(S.view) + ': ' + sig.text + '.';
    $('ol-prob').innerHTML = (p.every(ok)
      ? '<div class="probbar" role="img" aria-label="Below normal ' + pc(p[0]) + ', near normal ' + pc(p[1]) + ', above normal ' + pc(p[2]) + '">' +
        p.map((x, i) => '<span style="width:' + (100 * x).toFixed(1) + '%;background:var(' + CATV[i] + ')"></span>').join('') + '</div>' : '') +
      '<div class="problegend">' + p.map((x, i) => '<span><i class="sw" style="background:var(' + CATV[i] + ')"></i>' + CAT[i][0].toUpperCase() + CAT[i].slice(1) + ' <b>' + pc(x) + '</b></span>').join('') + '</div>';
    $('ol-prob-note').textContent = 'Each grid cell has its own tercile probabilities; these are their averages over the ' +
      fx(s.probability_domain_area_percent) + '% of the area that has probabilities. They are not the probability that the area-total rainfall falls in a category.';
    $('ol-amount').innerHTML = '<div class="amount"><div><span>Forecast mean</span><b>' + fx(s.mean_rainfall_mm) + ' mm</b></div>' +
      '<div><span>' + c.reference + ' average</span><b>' + fx(ref) + ' mm</b></div><div><span>Anomaly</span><b>' + sg(s.mean_anomaly_mm) + ' mm' +
      (ok(anomPct) ? ' (' + sg(anomPct) + '%)' : '') + '</b></div></div><p class="caveat">Amounts cover ' + fx(s.amount_domain_area_percent) +
      '% of the area. They come from the amount-corrected ensemble, calibrated separately from the probabilities, so the two can differ slightly.</p>';
    $('ol-signal').innerHTML = '<p class="big">' + sig.text + '</p><p class="caveat">Largest area-average probability ' + (p.every(ok) ? pc(Math.max(...p)) : '—') +
      ', compared with a one-third reference. The local climatological probabilities (observed tercile frequencies in the training years) are close to, but not exactly, one-third. Based on probabilities only.</p>';
    const A = areaHistory(t), h = A.h.training;
    $('ol-skill-title').textContent = 'Historical skill — ' + A.area;
    $('ol-skill').innerHTML = h ? '<p class="big">' + skillWord(h) + '</p><p class="caveat">Probability skill (RPSS) ' + sg(h.rpss, 3) +
      ' for ' + esc(t.id) + ', cross-validated ' + h.first + '–' + h.last + ' (95% interval ' + sg(h.ci[0], 3) + ' to ' + sg(h.ci[1], 3) + '); better than climatology in ' + h.better + ' of ' + h.years + ' years. ' +
      holmText(h, c.targets.length) + ' <a href="#history">Details</a></p>' +
      (A.fallback ? '<p class="caveat">Historical skill for the selected rainfall domain has not yet been evaluated.</p>' : '')
      : '<p>Not computed for this target.</p>';
    const e = t.forecast[S.view];
    $('ol-map').innerHTML = img(e, 'tercile_outlook', 'Tercile probabilities, ' + t.label + ', ' + viewLabel(S.view) + '. Open the map viewer below for other products.',
      'Map of ' + t.label + ' tercile probabilities for ' + viewLabel(S.view));
    // targets table
    $('ol-table').innerHTML = '<div class="table-wrap"><table><caption>' + esc(c.label) + ' targets, ' + esc(viewLabel(S.view)) +
      '. Probabilities are average local probabilities.</caption><thead><tr><th scope="col">Target</th><th scope="col">Period</th><th scope="col">Below / near / above</th><th scope="col">Probability coverage</th><th scope="col">Anomaly</th><th scope="col">Verification status</th></tr></thead><tbody>' +
      c.targets.map(x => { const v = (x.forecast[S.view] || {}).summary; return '<tr' + (x.id === S.target ? ' class="current"' : '') + '><td><button type="button" class="linkbtn" data-t="' + x.id + '">' + esc(x.label) + '</button></td><td>' + dt(x.start) + ' – ' + dt(x.end) + '</td><td>' +
        (v ? v.mean_local_probabilities.map(z => pc(z)).join(' / ') : '—') + '</td><td>' + (v ? fx(v.probability_domain_area_percent) + '% of area' : '—') + '</td><td>' + (v ? sg(v.mean_anomaly_mm) + ' mm' : '—') + '</td><td>' + status(x.status) + '</td></tr>'; }).join('') +
      '</tbody></table></div><p class="caveat">Probability coverage is the share of the area with tercile probabilities; averages are over that share only. Cells with very little reference-period rainfall have no terciles.</p>';
    $('ol-meta').innerHTML = '<dl class="meta">' + c.meta.map(r => '<dt>' + esc(r[0]) + '</dt><dd>' + esc(r[1]) + '</dd>').join('') +
      '<dt>Rainfall domain</dt><dd>' + esc(c.definition) + (c.note ? ' ' + esc(c.note) : '') + '</dd></dl>';
  }

  // ---------- maps
  function renderMaps() {
    const c = cyc(), t = tgt();
    $('mp-target').innerHTML = c.targets.map(x => '<option value="' + x.id + '"' + (x.id === S.target ? ' selected' : '') + '>' + esc(x.label) + '</option>').join('');
    const hasV = !!t.verification[S.view];
    $('mp-kind').innerHTML = '<button type="button" data-k="forecast" aria-pressed="' + (S.kind === 'forecast') + '">Forecast</button>' +
      '<button type="button" data-k="verification" aria-pressed="' + (S.kind === 'verification') + '">Verification' + (hasV ? '' : ' (not available)') + '</button>';
    const e = S.kind === 'forecast' ? t.forecast[S.view] : t.verification[S.view];
    const prods = S.kind === 'forecast' ? PRODUCTS : (e ? e.images : []);
    if (prods.length && !prods.some(p => p[0] === S.product)) S.product = prods[0][0];
    const cmp = S.product === 'verification_comparison' || S.product === 'verification_comparison_error';
    $('mp-tabs').innerHTML = prods.filter(p => p[0] !== 'verification_comparison_error').map(p => '<button type="button" class="tab" data-p="' + p[0] + '" aria-pressed="' +
      (p[0] === S.product || (cmp && p[0] === 'verification_comparison')) + '">' + esc(p[1]) + '</button>').join('');
    $('mp-toggle').innerHTML = cmp && prods.some(p => p[0] === 'verification_comparison_error')
      ? '<label class="check"><input type="checkbox" id="mp-error"' + (S.product === 'verification_comparison_error' ? ' checked' : '') + '> Show error map (forecast minus observed)</label>' : '';
    const fig = $('mp-figure');
    fig.classList.toggle('wide', S.kind === 'verification' && (S.product === 'verification_maps' || cmp));
    $('mp-actions').hidden = !e;
    if (!e) {
      fig.innerHTML = '<div class="unavailable" role="status"><p><strong>' + esc(t.label) + ' ' + (S.kind === 'verification' ? 'verification' : 'forecast') + ' is unavailable.</strong> ' + esc(t.status.text) + '.</p>' +
        (S.kind === 'verification' ? '<button type="button" data-k="forecast">View the ' + esc(t.label) + ' forecast</button>' : '') + '</div>';
      $('mp-help').innerHTML = '<p>Verification maps appear once the target period is complete and its CHIRPS observations have been processed.</p>';
      return;
    }
    const pname = prods.find(p => p[0] === S.product)[1];
    const cap = t.label + ' · ' + viewLabel(S.view) + ' · ' + pname + ' · ' + c.init + ' initialization';
    fig.innerHTML = img(e, S.product, cap, (S.kind === 'forecast' ? 'Forecast map: ' : 'Verification map: ') + cap);
    const src = e.folder + '/' + S.product + '.png';
    const slug = s => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    $('mp-open').href = src;
    $('mp-download').href = src;
    $('mp-open').textContent = cmp ? 'Open full-size comparison' : 'Open full-size';
    $('mp-download').textContent = cmp ? 'Download comparison figure' : 'Download PNG';
    $('mp-download').setAttribute('download', ['ethiopia-rainfall', slug(t.label), slug(c.init) + '-init', slug(viewLabel(S.view)), slug(pname)].join('_') + '.png');
    $('mp-help').innerHTML = (HELP[S.product] || '') + '<p class="caveat">Reference period: CHIRPS ' + c.reference + '.</p>';
  }

  // ---------- verification
  function chart(rows) {
    const W = 640, H = 250, L = 46, R = 10, T = 18, B = 34;
    const vals = rows.flatMap(r => [r.f, r.o]), mx = Math.max(5, ...vals.map(Math.abs));
    const step = [1, 2, 5, 10, 20, 25, 50, 100, 200].find(s => mx / s <= 4) || 500, top = Math.ceil(Math.max(0, ...vals) / step) * step, bot = Math.floor(Math.min(0, ...vals) / step) * step;
    const y = v => T + (top - v) / (top - bot || 1) * (H - T - B);
    const gw = (W - L - R) / rows.length, bw = Math.min(46, gw / 3.2);
    let g = '';
    for (let v = bot; v <= top + 1e-9; v += step) g += '<line class="axis" x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v) + '" y2="' + y(v) + '"/><text x="' + (L - 6) + '" y="' + (y(v) + 4) + '" text-anchor="end">' + sg(v).replace('+0', '0') + '</text>';
    g += '<line class="zero" x1="' + L + '" x2="' + (W - R) + '" y1="' + y(0) + '" y2="' + y(0) + '"/>';
    rows.forEach((r, i) => {
      const cx = L + gw * (i + .5);
      [[r.f, 'var(--fc)', 'Forecast', -1], [r.o, 'var(--obs)', 'Observed', 1]].forEach(([v, col, name, side]) => {
        const x = cx + (side < 0 ? -bw - 1 : 1), y0 = y(Math.max(v, 0)), h = Math.max(1, Math.abs(y(v) - y(0)));
        const rad = Math.min(4, h / 2), up = v >= 0;
        const d = up ? 'M' + x + ',' + (y0 + h) + 'V' + (y0 + rad) + 'q0,-' + rad + ' ' + rad + ',-' + rad + 'H' + (x + bw - rad) + 'q' + rad + ',0 ' + rad + ',' + rad + 'V' + (y0 + h) + 'Z'
          : 'M' + x + ',' + y0 + 'V' + (y0 + h - rad) + 'q0,' + rad + ' ' + rad + ',' + rad + 'H' + (x + bw - rad) + 'q' + rad + ',0 ' + rad + ',-' + rad + 'V' + y0 + 'Z';
        g += '<path d="' + d + '" fill="' + col + '"><title>' + esc(r.label) + ' ' + name.toLowerCase() + ' anomaly: ' + sg(v, 1) + ' mm</title></path>';
        g += '<text class="val" x="' + (x + bw / 2) + '" y="' + (up ? y(v) - 5 : y(v) + 14) + '" text-anchor="middle">' + sg(v) + '</text>';
      });
      g += '<text x="' + cx + '" y="' + (H - 10) + '" text-anchor="middle">' + esc(r.label) + '</text>';
    });
    return '<div class="legend"><span><i class="sw" style="background:var(--fc)"></i>Forecast anomaly</span><span><i class="sw" style="background:var(--obs)"></i>Observed anomaly</span></div>' +
      '<svg class="chart" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Forecast versus observed rainfall anomaly (mm): ' +
      esc(rows.map(r => r.label + ' forecast ' + sg(r.f) + ', observed ' + sg(r.o)).join('; ')) + '">' + g + '</svg>';
  }
  function narrative(t, s) {
    const ref = s.observed_mean_mm - s.observed_mean_anomaly_mm, o = s.observed_mean_anomaly_mm, f = s.forecast_mean_anomaly_mm;
    const obsCat = s.observed_category_area_fractions, k = obsCat.indexOf(Math.max(...obsCat));
    const fp = s.shared_mean_probabilities, fk = fp.indexOf(Math.max(...fp));
    const pb = s.probability.shared_blend, ac = s.amount.corrected;
    const happened = ['Rainfall was <strong>' + (o >= 0 ? 'wetter' : 'drier') + '</strong> than the reference average by ' + fx(Math.abs(o)) + ' mm' + (ref > 0 ? ' (' + sg(100 * o / ref) + '%)' : '') + ', averaged over the assessed area.',
      pc(obsCat[k]) + ' of the assessed area fell in the <strong>' + CAT[k] + '</strong> tercile.'];
    const got = [], miss = [];
    const small = Math.max(2, 0.03 * Math.abs(ref));            // anomalies below this are "near average"
    const word = o >= 0 ? 'surplus' : 'deficit', cond = o >= 0 ? 'wet' : 'dry';
    const bias = ac.bias_mm, big = x => '<strong>' + x + '</strong>';
    // The signed rainfall error is always reported; larger discrepancies are emphasised.
    const err = 'Forecast rainfall was ' + fx(Math.abs(bias), 1) + ' mm ' + (bias >= 0 ? 'higher' : 'lower') + ' than observed, averaged over the assessed area.';
    const errBig = Math.abs(bias) >= Math.max(5, 0.1 * Math.abs(ref));
    if (Math.abs(o) < small) {
      got.push('Observed rainfall was close to average (' + sg(o) + ' mm); the forecast anomaly was ' + sg(f) + ' mm.');
      miss.push(errBig ? big(err) : err);
    } else if (Math.abs(f) < small) {
      miss.push('The forecast mean was close to average (' + sg(f) + ' mm), so it gave little indication of the observed ' + cond + ' anomaly (' + sg(o) + ' mm).');
      miss.push(errBig ? big(err) : err);
    } else if (Math.sign(f) === Math.sign(o)) {
      got.push('The forecast captured the ' + cond + ' conditions (' + sg(f) + ' mm forecast, ' + sg(o) + ' mm observed).');
      const r = Math.abs(f) / Math.abs(o), off = Math.round(100 * Math.abs(1 - r));
      const size = r < 1 ? 'It underestimated the rainfall ' + word + ' by about ' + off + '%.' : 'It overestimated the rainfall ' + word + ' by about ' + off + '%.';
      const line = err + ' ' + (off >= 10 ? size : 'The size of the anomaly was close to the observed one.');
      miss.push(off >= 30 || errBig ? big(line) : line);
    } else {
      miss.push(big('The forecast anomaly had the wrong sign (' + sg(f) + ' mm forecast, ' + sg(o) + ' mm observed).'));
      miss.push(err);
    }
    if (fk === k && fp[fk] - 1 / 3 >= 0.02) got.push('The highest average probability (' + pc(fp[fk]) + ') was on the observed ' + CAT[k] + ' category.');
    else if (fp[fk] - 1 / 3 >= 0.02) miss.push('Probabilities favoured ' + CAT[fk] + ' (' + pc(fp[fk]) + ') while most of the area was ' + CAT[k] + '.');
    else miss.push('Probabilities stayed close to climatology (largest ' + pc(fp[fk]) + ').');
    (pb.rpss > 0 ? got : miss).push('Probabilities scored ' + (pb.rpss > 0 ? 'better' : 'worse') + ' than climatology (RPSS ' + sg(pb.rpss, 3) + ').');
    (ac.crpss > 0 ? got : miss).push('Rainfall amounts scored ' + (ac.crpss > 0 ? 'better' : 'worse') + ' than climatology (CRPSS ' + sg(ac.crpss, 3) + ').');
    const li = a => a.length ? '<ul>' + a.map(x => '<li>' + x + '</li>').join('') + '</ul>' : '<p class="caveat">None of the checked aspects (sign of the anomaly, leading category, scores against climatology).</p>';
    const raw = (s.probability.raw_observed_thresholds || {}).rpss;
    return '<div class="box vcard"><h3>' + esc(t.label) + '</h3><div class="qa"><div><h4>What happened?</h4>' + li(happened) + '</div><div><h4>What did the forecast capture?</h4>' + li(got) +
      '</div><div><h4>What did it miss?</h4>' + li(miss) + '</div></div><div class="metrics">' +
      '<div class="metric"><span>Probability skill (RPSS)</span><b>' + rpssText(pb.rpss) + '</b></div>' +
      '<div class="metric"><span>Rainfall amount skill (CRPSS)</span><b>' + rpssText(ac.crpss) + '</b></div>' +
      '<div class="metric"><span>Average rainfall error (bias, positive = too wet)</span><b>' + sg(ac.bias_mm, 1) + ' mm</b></div>' +
      '<div class="metric"><span>Observed category distribution (of the assessed area)</span><b>' + obsCat.map(x => pc(x)).join(' / ') + '</b> <span>below / near / above</span></div>' +
      '<div class="metric"><span>Assessed area (share of the selected area)</span><b>' + fx(s.probability_domain_area_percent) + '% probabilities · ' + fx(s.amount_domain_area_percent) + '% amounts</b></div>' +
      (ok(raw) ? '<div class="metric"><span>Raw benchmark (uncorrected model) RPSS</span><b>' + sg(raw, 3) + '</b></div>' : '') +
      '</div></div>';
  }
  function renderVerification() {
    const c = cyc(), done = c.targets.filter(t => t.verification[S.view]);
    let h = '';
    if (!done.length) h += '<p class="notice">No target of ' + esc(c.label) + ' has been verified yet.</p>';
    else {
      const ordered = [...done.filter(t => t.kind === 'month'), ...done.filter(t => t.kind === 'season')];
      const rows = ordered.map(t => ({label: t.label, f: t.verification[S.view].summary.forecast_mean_anomaly_mm, o: t.verification[S.view].summary.observed_mean_anomaly_mm}));
      h += '<div class="box"><h3>Forecast vs observed rainfall anomaly, ' + esc(viewLabel(S.view)) + ' (mm)</h3>' + chart(rows) +
        '<p class="caveat">Area-mean anomalies against the ' + c.reference + ' CHIRPS average. Probability skill (RPSS) refers to the blended probabilities; rainfall amount skill (CRPSS) and bias to the amount-corrected ensemble. Skill scores are decimals: +0.193 means a 19.3% lower score than climatology.</p></div>';
      h += ordered.map(t => narrative(t, t.verification[S.view].summary)).join('');
    }
    const pending = c.targets.filter(t => !t.verification[S.view]);
    if (pending.length) h += '<div class="box"><h3>Not yet verified</h3><ul class="dl">' + pending.map(t => '<li><strong>' + esc(t.label) + '</strong> ' + status(t.status) + '</li>').join('') + '</ul></div>';
    $('vf-body').innerHTML = h;
  }

  // ---------- history
  function renderHistory() {
    const c = cyc();
    const cell = (r, main = true) => r ? '<' + (main ? 'strong' : 'span') + ' class="' + (r.rpss > 0 ? 'pos' : 'neg') + '">' + sg(r.rpss, 3) + '</' + (main ? 'strong' : 'span') + '> <span class="ci">(' + sg(r.ci[0], 3) + ' to ' + sg(r.ci[1], 3) + ')</span>' : '—';
    const yrs = r => r ? r.better + ' of ' + r.years : '—';
    const H = t => areaHistory(t), area = H(c.targets[0]).area;
    const tr = H(c.targets[0]).h.training, op = H(c.targets[0]).h.operational;
    const sig = c.targets.filter(t => (H(t).h.training || {}).holm_p < 0.05).map(t => t.id);
    $('hs-body').innerHTML = '<div class="table-wrap"><table><caption>' + esc(c.label) + ' (' + esc(c.init) + ' initialization), ' + esc(area) + ': probability skill (RPSS) of the final method against climatology, with whole-year 95% intervals' +
      (H(c.targets[0]).fallback ? '. Historical skill for the selected rainfall domain has not yet been evaluated.' : '') + '</caption><thead><tr>' +
      '<th scope="col">Target</th><th scope="col">Cross-validated ' + tr.first + '–' + tr.last + ' (main)</th><th scope="col">Years better</th><th scope="col">p (one target / Holm)</th><th scope="col">In words</th>' +
      '<th scope="col">Exploratory ' + (op ? op.first + '–' + op.last : '') + '</th><th scope="col">Years better</th><th scope="col">Blend weight λ</th></tr></thead><tbody>' +
      c.targets.map(t => { const h = H(t).h; return '<tr' + (t.id === S.target ? ' class="current"' : '') + '><td>' + esc(t.id) + '</td><td>' + cell(h.training) + '</td><td>' + yrs(h.training) + '</td><td>' +
        (h.training ? h.training.p.toFixed(3) + ' / ' + (ok(h.training.holm_p) ? h.training.holm_p.toFixed(3) : '—') : '—') + '</td><td>' + skillWord(h.training) + '</td><td>' + cell(h.operational, false) + '</td><td>' + yrs(h.operational) + '</td><td>' + (ok(t.lambda) ? t.lambda.toFixed(2) : '—') + '</td></tr>'; }).join('') +
      '</tbody></table></div><p class="caveat">RPSS +0.05 means a 5% lower ranked probability score than climatology. Each interval and one-target p-value describes that target alone. Because ' + c.targets.length +
      ' targets are examined, the Holm-adjusted p is the stricter test: ' + (sig.length ? sig.join(', ') + ' remain' + (sig.length === 1 ? 's' : '') + ' significant after adjustment.' : 'no target remains significant after adjustment.') +
      ' Gains are modest and the intervals are wide; an interval that includes zero means the gain is not established. λ is the weight given to climatology in the blend (higher = closer to climatology).</p>';
    const R = c.regions;
    $('hs-regions').innerHTML = !R || !R.rows ? '<p class="caveat">Regional skill has not been computed for this cycle.</p>' :
      '<div class="table-wrap"><table class="compact"><caption>' + esc(c.label) + ': probability skill (RPSS) by rainfall region, cross-validated ' + tr.first + '–' + tr.last + ', with whole-year 95% intervals and years better than climatology</caption><thead><tr><th scope="col">Region</th>' +
      c.targets.map(t => '<th scope="col">' + esc(t.id) + '</th>').join('') + '</tr></thead><tbody>' +
      R.rows.map(([name, v]) => '<tr><td>' + esc(name) + '</td>' + c.targets.map(t => { const r = v[t.id]; return '<td>' + (r ? cell(r, false) + ' <span class="ci">' + r.better + '/' + r.years + ' yrs</span>' : '<span class="ci">too little coverage</span>') + '</td>'; }).join('') + '</tr>').join('') +
      '</tbody></table></div><p class="caveat">Positive values mean lower RPS than climatology. Intervals resample whole years; regions are the fixed 1993–2025 rainfall regimes, and the last row is this cycle\'s rainfall domain. Regional results are noisier than national ones.</p>';
  }

  // ---------- historical verification explorer (data/<cycle>_diagnostics.json, loaded on demand)
  const siteURL = path => new URL(path, window.SITE_BASE || document.baseURI).href;
  const DIAG = {};
  function loadDiag(c) {
    if (!c.diagnostics) return Promise.resolve(null);
    if (!DIAG[c.id]) DIAG[c.id] = fetch(siteURL(c.diagnostics)).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });
    return DIAG[c.id];
  }
  function yearChart(rows) {
    const W = 640, H = 220, L = 46, R = 8, T = 16, B = 30, ys = rows.filter(r => ok(r.rpss));
    const vals = ys.map(r => r.rpss), mx = Math.max(0.05, ...vals.map(Math.abs));
    const step = [0.02, 0.05, 0.1, 0.2, 0.5].find(s => mx / s <= 3) || 1, top = Math.ceil(Math.max(0, ...vals) / step) * step, bot = Math.floor(Math.min(0, ...vals) / step) * step;
    const y = v => T + (top - v) / (top - bot || 1) * (H - T - B), gw = (W - L - R) / rows.length, bw = Math.max(3, gw - 3);
    const hi = vals.indexOf(Math.max(...vals)), lo = vals.indexOf(Math.min(...vals));
    let g = '';
    for (let v = bot; v <= top + 1e-9; v += step) g += '<line class="axis" x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v) + '" y2="' + y(v) + '"/><text x="' + (L - 6) + '" y="' + (y(v) + 4) + '" text-anchor="end">' + sg(v, 2) + '</text>';
    g += '<line class="zero" x1="' + L + '" x2="' + (W - R) + '" y1="' + y(0) + '" y2="' + y(0) + '"/>';
    ys.forEach((r, i) => {
      const x = L + gw * rows.indexOf(r) + 1.5, v = r.rpss, up = v >= 0, top0 = y(Math.max(v, 0)), h = Math.max(1, Math.abs(y(v) - y(0)));
      g += '<rect x="' + x + '" y="' + top0 + '" width="' + bw + '" height="' + h + '" rx="2" fill="var(' + (up ? '--fc' : '--neg') + ')"><title>' + r.year + ': RPSS ' + sg(v, 3) +
        ' (forecast RPS ' + r.rps_blend.toFixed(3) + ', climatology ' + r.rps_climatology.toFixed(3) + '; ' + r.cells + ' cells)</title></rect>';
      if (i === hi || i === lo) g += '<text class="val" x="' + (x + bw / 2) + '" y="' + (up ? y(v) - 4 : y(v) + 13) + '" text-anchor="middle">' + r.year + '</text>';
      if (r.year % 4 === 1) g += '<text x="' + (x + bw / 2) + '" y="' + (H - 10) + '" text-anchor="middle">' + r.year + '</text>';
    });
    return '<svg class="chart" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Probability skill by year: ' + esc(ys.map(r => r.year + ' ' + sg(r.rpss, 3)).join(', ')) + '">' + g + '</svg>';
  }
  function reliabilityChart(rel, minCount) {
    const S0 = 300, M = 40, P = S0 - M - 10, x = v => M + v * P, y = v => 10 + (1 - v) * P;
    let g = '<rect x="' + M + '" y="10" width="' + P + '" height="' + P + '" fill="none" class="axis" stroke="var(--line)"/>';
    for (let v = 0; v <= 1.0001; v += 0.2) g += '<text x="' + x(v) + '" y="' + (S0 - 14) + '" text-anchor="middle">' + v.toFixed(1) + '</text><text x="' + (M - 6) + '" y="' + (y(v) + 4) + '" text-anchor="end">' + v.toFixed(1) + '</text>';
    g += '<line x1="' + x(0) + '" y1="' + y(0) + '" x2="' + x(1) + '" y2="' + y(1) + '" stroke="var(--ink2)" stroke-dasharray="4 4"/>';
    // Bins with few cell-years are shown as open points and not joined: their observed frequency is unstable.
    rel.forEach((rows, k) => {
      const pts = rows.filter(r => r.count >= minCount).map(r => x(r.forecast).toFixed(1) + ',' + y(r.observed).toFixed(1)).join(' ');
      g += '<polyline points="' + pts + '" fill="none" stroke="var(' + CATV[k] + ')" stroke-width="2"/>';
      rows.forEach(r => { const full = r.count >= minCount;
        g += '<circle cx="' + x(r.forecast) + '" cy="' + y(r.observed) + '" r="' + (full ? 4.5 : 3.5) + '" fill="' + (full ? 'var(' + CATV[k] + ')' : 'var(--surface)') +
          '" stroke="' + (full ? 'var(--surface)' : 'var(' + CATV[k] + ')') + '" stroke-width="' + (full ? 2 : 1.5) + '"><title>' + CAT[k] + ': forecast ' + pc(r.forecast) + ', observed ' + pc(r.observed) + ' (' + r.count + ' cell-years' + (full ? '' : ', too few to judge') + ')</title></circle>'; });
    });
    g += '<text x="' + (M + P / 2) + '" y="' + (S0) + '" text-anchor="middle">Forecast probability</text>';
    return '<svg class="chart rel" viewBox="0 0 ' + S0 + ' ' + (S0 + 6) + '" role="img" aria-label="Reliability diagram: observed frequency against forecast probability for each tercile">' + g + '</svg>';
  }
  function renderDiag() {
    const c = cyc(), t = tgt();
    $('dg-target').innerHTML = c.targets.map(x => '<option value="' + x.id + '"' + (x.id === S.target ? ' selected' : '') + '>' + esc(x.label) + '</option>').join('');
    $('dg-period').innerHTML = [['training', 'Cross-validated'], ['operational', 'Exploratory']].map(([k, l]) => '<button type="button" data-period="' + k + '" aria-pressed="' + (S.period === k) + '">' + l + '</button>').join('');
    const body = $('dg-body');
    if (!c.diagnostics) { body.innerHTML = '<p class="notice">Historical diagnostics have not been generated for this cycle (run scripts/historical_diagnostics.py).</p>'; return; }
    body.innerHTML = '<p class="caveat">Loading diagnostics…</p>';
    const want = [c.id, S.target, S.view, S.period].join('|');
    loadDiag(c).then(D2 => {
      if ([cyc().id, S.target, S.view, S.period].join('|') !== want) return;     // selection changed meanwhile
      const area = D2.areas.includes(S.view) ? S.view : 'all_ethiopia';
      const d = ((D2.targets[t.id] || {})[S.period] || {})[area];
      if (!d) { body.innerHTML = '<p class="notice">No ' + (S.period === 'training' ? 'cross-validated' : 'exploratory') + ' diagnostics for ' + esc(t.label) + ' in this area.</p>'; return; }
      const better = d.per_year.filter(r => r.rpss > 0).length;
      const worst = d.per_year.filter(r => ok(r.rpss)).sort((a, b) => a.rpss - b.rpss).slice(0, 3);
      const head = '<dl class="meta"><dt>Evaluation</dt><dd>' + (S.period === 'training' ? 'Cross-validated (nested leave-one-year-out), ' : 'Exploratory: parameters fitted on 1993–2016 applied to later years, which were seen during method selection, ') + d.first + '–' + d.last + '</dd>' +
        '<dt>Benchmark</dt><dd>Climatology: observed tercile frequencies of the training years (about one-third each)</dd>' +
        '<dt>Area</dt><dd>' + esc(area === S.view ? viewLabel(S.view) : 'All Ethiopia (the selected domain has no diagnostics)') + '; probabilities on ' + pc(d.coverage) + ' of it on average</dd>' +
        '<dt>Sample</dt><dd>' + d.years + ' years, ' + d.cell_years.toLocaleString('en') + ' cell-years. Cells within a year are spatially correlated, so the independent sample is closer to one value per year.</dd></dl>';
      const bs = d.brier, cats = [0, 1, 2];
      const brier = '<div class="table-wrap"><table class="compact"><caption>Category Brier scores (lower is better) and Brier skill against climatology</caption><thead><tr><th scope="col">Category</th><th scope="col">Forecast</th><th scope="col">Climatology</th><th scope="col">Brier skill</th></tr></thead><tbody>' +
        cats.map(k => '<tr><td><i class="sw" style="background:var(' + CATV[k] + ')"></i>' + CAT[k] + '</td><td>' + bs.blend[k].toFixed(4) + '</td><td>' + bs.climatology[k].toFixed(4) + '</td><td class="' + (bs.bss[k] > 0 ? 'pos' : 'neg') + '">' + sg(bs.bss[k], 3) + '</td></tr>').join('') + '</tbody></table></div>';
      const hist = '<div class="hbars">' + d.histogram.map(h => '<div class="hbar"><span>' + esc(h.label) + '</span><div><i style="width:' + (100 * h.share).toFixed(1) + '%"></i></div><b>' + pc(h.share) + '</b></div>').join('') + '</div>';
      const relTable = '<details><summary>Reliability table (forecast bins, observed frequency, counts)</summary><div class="table-wrap"><table class="compact"><thead><tr><th scope="col">Category</th><th scope="col">Bin</th><th scope="col">Mean forecast</th><th scope="col">Observed frequency</th><th scope="col">Cell-years</th></tr></thead><tbody>' +
        d.reliability.flatMap((rows, k) => rows.map(r => '<tr><td>' + CAT[k] + '</td><td>' + pc(r.bin[0]) + '–' + pc(r.bin[1]) + '</td><td>' + pc(r.forecast) + '</td><td>' + pc(r.observed) + '</td><td>' + r.count.toLocaleString('en') + '</td></tr>')).join('') + '</tbody></table></div></details>';
      const am = ((D2.amount || {})[t.id] || {})[area];
      const amount = am ? '<div class="table-wrap"><table class="compact"><caption>Rainfall amounts, ' + esc(am.period) + '</caption><tbody>' +
          '<tr><td>Rainfall amount skill (CRPSS)</td><td>' + sg(am.crpss, 3) + '</td></tr><tr><td>CRPS, corrected / climatology</td><td>' + am.corrected_crps_mm.toFixed(1) + ' / ' + am.climatology_crps_mm.toFixed(1) + ' mm</td></tr>' +
          '<tr><td>Average rainfall error, corrected (raw model)</td><td>' + sg(am.corrected_bias_mm, 1) + ' mm (' + sg(am.raw_bias_mm, 1) + ' mm)</td></tr><tr><td>RMSE, corrected / climatology</td><td>' + am.corrected_rmse_mm.toFixed(1) + ' / ' + am.climatology_rmse_mm.toFixed(1) + ' mm</td></tr></tbody></table></div>'
        : '<p class="caveat">Historical rainfall-amount diagnostics (CRPS, CRPSS and amount errors) have not been generated for ' + esc(t.label) + ' in this area and period; this needs a separate cross-validated amount evaluation. Single-season amount scores are in the Verification section.</p>';
      body.innerHTML = head +
        '<div class="box"><h4>Performance by year</h4><p class="caveat">Probability skill (RPSS) of each year; better than climatology in ' + better + ' of ' + d.years + ' years. Weakest years: ' + worst.map(r => r.year + ' (' + sg(r.rpss, 3) + ')').join(', ') + '.</p>' +
        '<div class="legend"><span><i class="sw" style="background:var(--fc)"></i>Better than climatology</span><span><i class="sw" style="background:var(--neg)"></i>Worse</span></div>' + yearChart(d.per_year) + '</div>' +
        '<div class="grid2"><div class="box"><h4>Reliability</h4><div class="legend">' + cats.map(k => '<span><i class="sw" style="background:var(' + CATV[k] + ')"></i>' + CAT[k] + '</span>').join('') + '</div>' + reliabilityChart(d.reliability, Math.max(50, Math.round(0.005 * d.cell_years))) +
        '<p class="caveat">Points on the dashed diagonal are reliable: events forecast with probability p happen p of the time. Points flatter than the diagonal mean over-confident probabilities. Open points have fewer than ' + Math.max(50, Math.round(0.005 * d.cell_years)) + ' cell-years (0.5% of the sample, at least 50) and are not joined. Hover a point for its count.</p>' + relTable + '</div>' +
        '<div class="box"><h4>How strong are the signals?</h4><p class="caveat">Share of cell-years by the leading tercile probability.</p>' + hist + brier + '</div></div>' +
        '<div class="box"><h4>Rainfall amounts</h4>' + amount + '</div>';
    }).catch(() => { body.innerHTML = '<p class="notice">The diagnostics file could not be loaded. Try reloading the page.</p>'; });
  }

  // ---------- comparison with official outlooks (data/<cycle>_comparison.json; validated content only)
  const CMP = {};
  const METRIC = {display_official_probabilities: 'Official probabilities shown', favoured_category_relationship: 'Favoured-category relationship',
    zone_mean_probability: 'Platform mean over the official zone', same_event_probability_difference: 'Probability difference for the same event',
    mapped_category_agreement: 'Mapped category agreement', rainfall_anomaly_difference: 'Rainfall anomaly difference', forecast_accuracy: 'Which forecast is more accurate'};
  const REASON = {transcription_awaiting_review: 'transcribed values await review against the published figure',
    transcription_and_anchor_awaiting_review: 'transcribed values and locations await review', digitization_awaiting_review: 'digitized map awaits review',
    zone_geometry_requires_alignment: 'the zone boundary is not published with the figure', official_reference_period_unknown: 'the official reference period is not stated',
    target_window_mismatch: 'the target periods differ', official_publishes_only_favoured_category_interval: 'only the favoured category and its interval are published',
    official_amount_anomaly_not_found_in_checked_products: 'no official rainfall-amount anomaly product was found in the checked products'};
  const plainReason = r => !r ? '' : r.split(';').map(x => x.trim()).map(x => x.startsWith('out_of_scope') ? 'needs observations and a separate verification design (see Verification)' : (REASON[x] || x.replace(/_/g, ' '))).join('; ');
  function renderComparison() {
    const c = cyc(), body = $('cmp-body'), head = $('official');
    const season = c.targets.find(t => t.kind === 'season') || c.targets[0];
    head.textContent = 'Official outlook comparison — ' + season.label;
    if (!c.comparison) { body.innerHTML = '<p class="caveat">No comparison with official outlooks is configured for this cycle.</p>'; return; }
    body.innerHTML = '<p class="caveat">Loading…</p>';
    if (!CMP[c.id]) CMP[c.id] = fetch(siteURL(c.comparison)).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });
    const want = [c.id, S.target, S.view].join('|');
    CMP[c.id].then(X => {
      if ([cyc().id, S.target, S.view].join('|') !== want) return;
      const ev = X.evidence || {};
      const areaKey = S.view === 'all_ethiopia' ? 'all_ethiopia' : 'season_domain';
      const areaName = viewLabel(S.view), otherName = areaKey === 'all_ethiopia' ? 'Rainfall-domain context' : 'National context';
      const href = p => esc(siteURL(p));
      // Evidence maps follow the finding's own scope (a national-context finding links the national map).
      const scopeView = key => key === 'season_domain' ? c.domain_view : key === 'all_ethiopia' ? 'all_ethiopia' : S.view;
      const links = (ids, sid, view = S.view) => {
        const seen = new Set(), out = [];
        [...ids, ...(sid ? [sid + '_record'] : [])].forEach(i => ((ev[i] || {}).links || []).forEach(l => {
          const map = l.href.includes('{view}'), url = l.href.replace('{view}', view);
          const label = map ? l.label + ' (' + (view === 'all_ethiopia' ? 'All Ethiopia' : 'domain') + ')' : l.label;
          if (!seen.has(url)) { seen.add(url); out.push('<a href="' + href(url) + '" target="_blank" rel="noopener">' + esc(label) + '</a>'); }
        }));
        return out.length ? '<span class="evlinks">Evidence: ' + out.join(' · ') + '</span>' : '';
      };
      const overlap = x => !ok(x) ? '' : x <= 0 ? 'Outside the domain (national context)' : x >= 1 ? 'Entire sample in the domain' :
        'Partly overlaps the domain — ' + (100 * x).toFixed(0) + '% of sample cells';
      const item = i => '<li><strong>' + esc(i.title) + '.</strong> ' + esc(i.text) + links(i.evidence_ids, i.source_id, scopeView(i.area_key)) + '</li>';
      let h = '<p class="scope"><strong>Season:</strong> ' + esc(season.label) + ' (' + dt(season.start) + ' – ' + dt(season.end) + ') · <strong>Area:</strong> ' + esc(areaName) + '</p>';
      if (S.target !== season.id) h += '<p class="notice">This comparison covers the full ' + esc(season.id) + ' season. A separate ' + esc(tgt().label) + ' comparison is not available.</p>';
      if (X.stale.length) h += '<p class="notice"><strong>Comparison withheld.</strong> The saved comparison no longer matches the current ' + esc(X.stale.join(', ')) +
        '. Its findings are not shown until it is regenerated: <code>' + esc(X.rerun) + '</code></p>';
      h += '<p class="caveat">Official outlooks from ICPAC and the Ethiopian Meteorology Institute (EMI), compared with this platform\'s forecast. The comparison describes agreement between outlooks, not which is more accurate, and uses only values a person has checked against the published figures.</p>';
      // 1. key findings for the selected area; the rest as context
      const mine = X.summary.filter(i => i.area_key === areaKey || i.area_key === 'any');
      const ctx = X.summary.filter(i => i.area_key !== areaKey && i.area_key !== 'any');
      if (mine.length) h += '<div class="box"><h3>Key findings — ' + esc(areaName) + '</h3><ul class="findings">' + mine.map(item).join('') + '</ul></div>';
      // 2. maps
      const cap = {icpac: 'Platform ' + season.label + ' vs ICPAC (left to right: platform favoured category, ICPAC favoured category, agreement). Periods differ; see the findings.',
                   emi: 'Platform ' + season.label + ' favoured category with EMI zone values at their arrow tips; boxes show the sampled ±0.5° neighbourhoods.'};
      // The EMI comparison map is shown next to EMI's own official figure (the zones as EMI published them).
      const emiFig = X.sources.filter(s => s.provider === 'EMI').flatMap(s => s.figures)[0];
      const fig = (file, alt, caption) => '<figure><a href="' + href(file) + '" target="_blank" rel="noopener"><img loading="lazy" src="' + href(file) +
        '" alt="' + esc(alt) + '"></a><figcaption>' + esc(caption) + '</figcaption></figure>';
      // Right-hand panel: the EMI zones as regions (reviewed digitization) or, until then, EMI's own figure.
      const regionMap = X.maps.find(m => m.name.includes('regions'));
      const layer = (X.reference_layers || [])[0];
      const right = regionMap
        ? fig(regionMap.file, 'EMI homogeneous rainfall regions with the Bega 2026/27 values', 'EMI zones as homogeneous rainfall regions, with the values EMI printed for Bega 2026/27. Regions redrawn after ' +
              (layer ? layer.citation.split(' (figure')[0] : 'Korecha and Sorteberg (2013)') + '; region layout as published in 2013. EMI\'s own figure is under Sources.')
        : (emiFig ? fig(emiFig.file, 'EMI official figure', 'EMI official figure (as published): ' + emiFig.caption + '. EMI publishes zone values with arrows; no zone boundaries are given.') : '');
      if (X.maps.length) h += X.maps.filter(m => !m.name.includes('regions')).map(m => m.name.includes('anchors')
        ? '<div class="cmp-pair">' + fig(m.file, 'Platform map with EMI zone values', cap.emi) + right + '</div>'
        : '<figure class="map-figure wide"><a href="' + href(m.file) + '" target="_blank" rel="noopener"><img loading="lazy" src="' + href(m.file) +
          '" alt="Comparison map"></a><figcaption>' + esc(cap.icpac) + '</figcaption></figure>').join('');
      // 3. compact tables
      const agree = X.metrics.filter(m => m.metric === 'mapped_category_agreement' && m.value);
      if (agree.length) h += '<div class="table-wrap"><table class="compact"><caption>ICPAC category agreement (only where both outlooks show a favoured category)</caption><thead><tr><th scope="col">Area</th><th scope="col">Compared area (share of the analysed area)</th><th scope="col">Category agreement within it</th><th scope="col">Opposite categories within it</th></tr></thead><tbody>' +
        agree.map(m => { const v = m.value, here = (areaKey === 'all_ethiopia') === (m.where === 'All Ethiopia');
          return '<tr' + (here ? ' class="current"' : '') + '><td>' + esc(m.where) + (here ? '' : ' <span class="caveat">(' + otherName.toLowerCase() + ')</span>') + '</td><td>' + share(v.area_share_both_favoured) + '</td><td>' +
            share1(v.agreement_share_where_both_favoured) + '</td><td>' + share1(v.opposing_share_where_both_favoured) + '</td></tr>'; }).join('') + '</tbody></table></div>';
      if (X.emi_table.length) {
        const rows = areaKey === 'all_ethiopia' ? X.emi_table : [...X.emi_table].sort((a, b) => b.domain_share - a.domain_share);
        const hasZone = rows.some(r => r.zone_mean), hasArrow = rows.some(r => r.platform !== '—');
        h += '<div class="table-wrap"><table class="compact"><caption>EMI zones: printed values and the platform (below / near / above)</caption><thead><tr><th scope="col">Location</th><th scope="col">Official</th>' +
          (hasZone ? '<th scope="col">Platform over the whole zone</th>' : '') + (hasArrow ? '<th scope="col">Platform near the arrow (±0.5°)</th><th scope="col">Relationship near the arrow</th>' : '') + '<th scope="col">Evidence</th></tr></thead><tbody>' +
          rows.map(r => { const mapView = areaKey === 'season_domain' && r.domain_share >= 1 ? c.domain_view : 'all_ethiopia';
            const zoneCell = hasZone ? '<td>' + (r.zone_mean ? '<span class="nowrap">' + esc(r.zone_mean) + '</span><br><span class="caveat">' + esc(r.zone_relationship) +
              (r.zone_name ? ' · ' + esc(r.zone_name) + ' region' : '') + (areaKey === 'season_domain' && ok(r.zone_domain_share) && r.zone_domain_share < 1 ? ' · ' + (100 * r.zone_domain_share).toFixed(0) + '% of the zone in the domain' : '') + '</span>' : '—') + '</td>' : '';
            return '<tr' + (r.relationship_code === 'opposing_favoured_categories' ? ' class="current"' : '') + '><td>Zone ' + esc(r.zone) +
              (areaKey === 'all_ethiopia' ? '' : '<br><span class="caveat">' + (hasArrow ? overlap(r.domain_share) + ' (arrow sample)' : overlap(r.zone_domain_share)) + '</span>') + '</td><td class="nowrap">' + esc(r.official) + '</td>' + zoneCell + (hasArrow ? '<td class="nowrap">' + esc(r.platform) +
              '</td><td>' + esc(r.relationship) + (r.stable === false ? ' <span class="caveat">(sensitive to location)</span>' : '') + '</td>' : '') + '<td>' + links(r.evidence_ids, null, mapView).replace('Evidence: ', '') + '</td></tr>'; }).join('') +
          '</tbody></table></div><p class="caveat">Platform values are area means of local probabilities. ' + (hasZone ? '"Whole zone" uses EMI\'s homogeneous rainfall regions as published in 2013 (assumed unchanged for 2026/27); ' : '') + '"near the arrow" uses the ±0.5° sample around each arrow tip, also where it only partly overlaps the domain. Percentages are rounded to add up to 100%.</p>';
      }
      const icpacSrc = X.sources.find(s => s.provider === 'ICPAC');
      const icpacPeriod = icpacSrc ? dt(icpacSrc.target_start) + ' – ' + dt(icpacSrc.target_end) : 'its own period';
      if ((X.icpac_table || []).length) {
        const samples = X.icpac_table.filter(r => r.kind === 'sample'), arows = X.icpac_table.filter(r => r.kind === 'area');
        const ordered = [...(areaKey === 'all_ethiopia' ? samples : [...samples].sort((a, b) => b.domain_share - a.domain_share)),
                         ...arows.filter(r => r.area_key === areaKey), ...arows.filter(r => r.area_key !== areaKey)];
        h += '<div class="table-wrap"><table class="compact"><caption>ICPAC: printed favoured category and interval vs the platform (below / near / above)</caption><thead><tr><th scope="col">Location</th><th scope="col">ICPAC (favoured category, printed interval)</th><th scope="col">Platform</th><th scope="col">Relationship</th><th scope="col">Evidence</th></tr></thead><tbody>' +
          ordered.map(r => { const mapView = r.kind === 'area' ? (r.area_key === 'season_domain' ? c.domain_view : 'all_ethiopia')
                                             : (areaKey === 'season_domain' && r.domain_share >= 1 ? c.domain_view : 'all_ethiopia');
            const where = r.kind === 'sample' ? (areaKey === 'all_ethiopia' ? '' : '<br><span class="caveat">' + overlap(r.domain_share) + '</span>')
                                              : (r.area_key === areaKey ? '<br><span class="caveat">selected area</span>' : '<br><span class="caveat">' + otherName.toLowerCase() + '</span>');
            return '<tr' + (r.relationship_code === 'opposing_favoured_categories' ? ' class="current"' : '') + '><td>' + esc(r.location) + where + '</td><td>' + esc(r.official) +
              (r.official_note ? '<br><span class="caveat">' + esc(r.official_note) + '</span>' : '') + '</td><td class="nowrap">' + esc(r.platform) + '</td><td>' + esc(r.relationship) +
              '</td><td>' + links(r.evidence_ids, null, mapView).replace('Evidence: ', '') + '</td></tr>'; }).join('') +
          '</tbody></table></div><p class="caveat">ICPAC publishes only the favoured category and its probability interval (the other two categories are not published), for ' + icpacPeriod + '; the platform covers ' + dt(X.platform.target_start) + ' – ' + dt(X.platform.target_end) + ', so the two are compared as tendencies, not as the same event. Locations are the EMI arrow-tip boxes or the digitized EMI zones; platform values are area means of local probabilities over each location or area.</p>';
      }
      if (ctx.length) h += '<details><summary>' + otherName + '</summary><ul class="findings">' + ctx.map(item).join('') + '</ul></details>';
      // 4. detailed interpretation
      if (X.paragraphs.length) {
        const order = p => (p.area_key === areaKey ? 0 : p.area_key === 'zone' ? 1 : p.area_key === 'any' ? 3 : 2);
        h += '<details><summary>Detailed interpretation</summary>' + [...X.paragraphs].sort((a, b) => order(a) - order(b)).map(p =>
          '<p>' + (p.area_key !== 'zone' && p.area_key !== 'any' && p.area_key !== areaKey ? '<span class="caveat">' + otherName + ':</span> ' : '') + esc(p.text) + links(p.evidence_ids, null, scopeView(p.area_key === 'zone' ? 'all_ethiopia' : p.area_key)) + '</p>').join('') + '</details>';
      }
      // 5. sources, extraction review and methods
      const st = s => s === 'validated' ? '<span class="status published">Extraction reviewed</span>' : '<span class="status awaiting">Extraction awaiting review</span>';
      const chk = r => '<span class="status ' + ({checked: 'published', new_awaiting_review: 'awaiting', refresh_failed: 'awaiting'}[r.state] || 'not_started') + '">' + esc(r.text) + '</span>';
      h += '<details><summary>Sources, extraction review and methods</summary><div class="grid2">' + X.sources.map(s => {
        const same = s.target_start === X.platform.target_start && s.target_end === X.platform.target_end;
        const rv = s.extraction.review;
        return '<div class="box"><h3>' + esc(s.provider) + ': ' + esc(s.season_label || s.label) + '</h3><p>' + st(s.extraction.status) + ' ' + chk(s.refresh) + '</p>' +
          '<dl class="meta"><dt>Product</dt><dd>' + esc(s.label) + '</dd><dt>Target period</dt><dd>' + dt(s.target_start) + ' – ' + dt(s.target_end) +
          (same ? '' : ' <strong>(differs from this forecast: ' + dt(X.platform.target_start) + ' – ' + dt(X.platform.target_end) + ')</strong>') + '</dd>' +
          '<dt>Issue date</dt><dd>' + esc(s.issue_date || 'not stated by the provider') + '</dd><dt>Reference period</dt><dd>' + esc(s.reference_period || 'not stated') + '</dd>' +
          '<dt>Retrieved</dt><dd>' + esc((s.retrieved_utc || '').slice(0, 10)) + ' · content hash ' + esc((s.sha256 || '').slice(0, 12)) + '</dd>' +
          (rv ? '<dt>Review</dt><dd>' + esc(rv.decision) + ' by ' + esc(rv.reviewer) + ', ' + esc((rv.reviewed_utc || '').slice(0, 10)) + '</dd>' : '') +
          (s.extraction.note ? '<dt>Note</dt><dd>' + esc(s.extraction.note) + '</dd>' : '') +
          '<dt>Source</dt><dd><a href="' + esc(s.page) + '" rel="noopener">product page</a> · <a href="' + esc(s.download) + '" rel="noopener">original file</a></dd></dl>' +
          (s.narrative.length ? '<blockquote class="quote">' + s.narrative.map(n => esc(n.text)).join('<br>') + '<br><span class="caveat">— ' + esc(s.provider) + ', ' + esc(s.narrative[0].locator) + '</span></blockquote>' : '') +
          s.figures.map(f => '<figure><a href="' + href(f.file) + '" target="_blank" rel="noopener"><img loading="lazy" src="' + href(f.file) + '" alt="' + esc(f.caption) + '"></a><figcaption>' + esc(f.caption) + ' (original figure)</figcaption></figure>').join('') + '</div>';
      }).join('') + '</div><div class="table-wrap"><table class="compact"><caption>What is compared, and what is not</caption><thead><tr><th scope="col">Comparison</th><th scope="col">Where</th><th scope="col">Status</th><th scope="col">Why</th></tr></thead><tbody>' +
        X.metrics.map(m => '<tr><td>' + esc(METRIC[m.metric] || m.metric) + '</td><td>' + esc(m.where ? (String(m.where).length < 5 ? 'EMI zone ' + m.where : m.where) : '—') + '</td><td>' +
          esc(m.status.replace(/_/g, ' ')) + '</td><td>' + esc(plainReason(m.reason) || (m.basis || '').replace(/_/g, ' ')) + '</td></tr>').join('') + '</tbody></table></div>' +
        '<ul class="caveat">' + X.notes.map(n => '<li>' + esc(n) + '</li>').join('') + '</ul></details>';
      body.innerHTML = h;
    }).catch(() => { body.innerHTML = '<p class="notice">The comparison file could not be loaded.</p>'; });
  }

  // ---------- one-click package (files are zipped in the browser)
  function loadZip() {
    if (window.JSZip) return Promise.resolve(window.JSZip);
    const urls = ['https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js', 'https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js'];
    const tryLoad = i => new Promise((res, rej) => { const sc = document.createElement('script'); sc.src = urls[i];
      sc.onload = () => res(window.JSZip); sc.onerror = () => (i + 1 < urls.length ? tryLoad(i + 1).then(res, rej) : rej(new Error('ZIP library could not be loaded')));
      document.head.appendChild(sc); });
    return tryLoad(0);
  }
  async function downloadPackage() {
    const c = cyc(), btn = $('dl-package'), prog = $('dl-progress');
    btn.disabled = true;
    try {
      const Z = await loadZip(), zip = new Z(), root = 'ethiopia-rainfall_' + c.id + '_package/';
      let n = 0;
      for (const [src, dest] of c.package) {
        prog.textContent = 'Adding file ' + (++n) + ' of ' + c.package.length + '…';
        const r = await fetch(siteURL(src));
        if (!r.ok) throw new Error(src + ' (' + r.status + ')');
        zip.file(root + dest, await r.arrayBuffer());
      }
      prog.textContent = 'Compressing…';
      const blob = await zip.generateAsync({type: 'blob'});
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = 'ethiopia-rainfall_' + c.id + '_package.zip';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 10000);
      prog.textContent = 'Package ready (' + (blob.size / 1e6).toFixed(1) + ' MB, ' + c.package.length + ' files).';
    } catch (err) {
      prog.textContent = 'The package could not be built: ' + err.message + '. The individual files below are still available.';
    } finally { btn.disabled = false; }
  }

  function renderDownloads() {
    const c = cyc();
    $('dl-package').textContent = 'Download package (ZIP): ' + c.label + ', ' + c.package.length + ' files';
    $('dl-body').innerHTML = '<div class="box"><h3>' + esc(c.option) + ' — individual files</h3><ul class="dl">' + c.downloads.map(d => '<li><a href="' + d.href + '" download>' + esc(d.label) + '</a><span>' + esc(d.note) + '</span></li>').join('') + '</ul></div>' +
      '<details><summary>Other cycles</summary><ul class="dl">' + D.cycles.filter(x => x.id !== c.id).flatMap(x => x.downloads.map(d => '<li><a href="' + d.href + '" download>' + esc(d.label) + '</a><span>' + esc(x.option) + '</span></li>')).join('') + '</ul></details>';
  }

  // Re-rendering replaces controls; keep keyboard focus on the equivalent control.
  function focusKey() {
    const a = document.activeElement;
    if (!a || a === document.body) return null;
    if (a.id) return '#' + a.id;
    for (const k of ['t', 'k', 'p', 'period']) if (a.dataset && a.dataset[k]) { const box = a.closest('[id]'); return (box ? '#' + box.id + ' ' : '') + '[data-' + k + '="' + a.dataset[k] + '"]'; }
    return null;
  }
  function renderAll() {
    const key = focusKey();
    renderParts();
    if (key) {
      // A control that disappears (e.g. the forecast button in an unavailable-verification message) hands focus to
      // the persistent control with the same action (#mp-kind).
      const el = document.querySelector(key) || document.querySelector('#mp-kind ' + key.replace(/^#[^ ]+ /, ''));
      if (el && el !== document.activeElement) el.focus({preventScroll: true});
    }
  }
  function renderParts() {
    const c = cyc();
    $('cycle').value = c.id;
    $('view').innerHTML = c.views.map(v => '<option value="' + v[0] + '"' + (v[0] === S.view ? ' selected' : '') + '>' + esc(v[1]) + '</option>').join('');
    renderOutlook(); renderMaps(); renderVerification(); renderHistory(); renderDiag(); renderComparison(); renderDownloads(); sync();
  }

  // Anchor offset follows the real height of the sticky header (wrapped controls included).
  const header = document.querySelector('.top');
  const offset = () => { const sticky = getComputedStyle(header).position === 'sticky';
    document.documentElement.style.scrollPaddingTop = (sticky ? header.offsetHeight + 12 : 8) + 'px'; };
  if (window.ResizeObserver) new ResizeObserver(offset).observe(header);
  window.addEventListener('resize', offset);
  offset();

  init();
  $('cycle').addEventListener('change', e => { const c = D.cycles.find(x => x.id === e.target.value); S.cycle = c.id; S.target = c.targets[0].id; S.view = c.domain_view; renderAll(); });
  $('view').addEventListener('change', e => { S.view = e.target.value; renderAll(); });
  $('mp-target').addEventListener('change', e => { S.target = e.target.value; renderAll(); });
  $('dg-target').addEventListener('change', e => { S.target = e.target.value; renderAll(); });
  document.addEventListener('change', e => { if (e.target.id === 'mp-error') { S.product = e.target.checked ? 'verification_comparison_error' : 'verification_comparison'; renderAll(); } });
  $('dl-package').addEventListener('click', downloadPackage);
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-t],[data-k],[data-p],[data-period]');
    if (!b) return;
    if (b.dataset.period) S.period = b.dataset.period;
    if (b.dataset.t) S.target = b.dataset.t;
    if (b.dataset.k) S.kind = b.dataset.k;
    if (b.dataset.p) S.product = b.dataset.p;
    renderAll();
  });
  $('mp-copy').addEventListener('click', () => {
    const url = location.href.split('#')[0] + '#maps';
    const done = () => { $('mp-copied').textContent = 'Link copied.'; setTimeout(() => { $('mp-copied').textContent = ''; }, 2500); };
    if (navigator.clipboard) navigator.clipboard.writeText(url).then(done, () => { $('mp-copied').textContent = url; });
    else $('mp-copied').textContent = url;
  });
  renderAll();
})();
'''


def main():
    global OUT, INCLUDE_BACKTESTS
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', help='Write the site elsewhere (default: site/)')
    ap.add_argument('--include-backtests', action='store_true', help='Also show backtest cycles (scratch builds only)')
    ap.add_argument('--offline', action='store_true', help='Do not query the CHIRPS archive listing')
    a = ap.parse_args()
    if a.out:
        OUT = Path(a.out).resolve()
    INCLUDE_BACKTESTS = a.include_backtests
    today, sha = date.today(), git_sha()
    published = chirps_published(a.offline)
    cycles, copies = [], []
    for cfg in CYCLE_FILES:
        if 'backtest' in cfg and not INCLUDE_BACKTESTS:
            continue
        try:
            built = build_cycle(cfg, published, today, sha)
        except (KeyError, FileNotFoundError, ValueError) as exc:
            print(f'Skipped {cfg}: {exc}')
            continue
        if built:
            cycles.append(built[0])
            copies += built[1]
    cycles.sort(key=lambda c: c['init_date'])
    default = cycles[-1]['id']                     # latest initialization
    OUT.mkdir(parents=True, exist_ok=True)
    for sub in ('assets', 'downloads', 'data', 'releases'):
        if (OUT / sub).exists():
            shutil.rmtree(OUT / sub)
    for src, dest in copies:
        if src.suffix == '.png' and dest.suffix == '':
            crop_panels(src, dest)
            extras.comparison_images(dest)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    built = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    releases = extras.load_releases()
    release_id = releases[-1]['id'] if releases else 'unreleased'
    for c in cycles:
        write_csv(c)
        c['diagnostics'] = extras.export_diagnostics(c['tag'], c['id'], c['views'], OUT)
        exported = extras.export_comparison(load_cycle(ROOT / c['cfg']), c['id'], OUT)
        c['comparison'] = exported and exported['rel']
        if exported:
            c['downloads'] += exported['downloads']
            c['comparison_package'] = exported['package']
            if exported['stale']:
                print(f'{c["id"]}: comparison withheld (stale: {", ".join(exported["stale"])})')
        extras.bulletin_pdf(c, OUT / f'downloads/{c["id"]}_bulletin.pdf', built, OUT)
        c['package'] = package_files(c)
        meta = extras.package_metadata(c, built, release_id, sha, c['package'])
        (OUT / f'downloads/{c["id"]}_metadata.json').write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding='utf-8', newline='')
        (OUT / f'downloads/{c["id"]}_README.txt').write_text(extras.package_readme(c, built, release_id), encoding='utf-8', newline='')
    # Plain listing of every download (the no-JavaScript fallback links here).
    items = ''.join(f'<h2>{esc(c["option"])}</h2><ul>' + ''.join(
        f'<li><a href="{esc(d["href"].removeprefix("downloads/"))}">{esc(d["label"])}</a> — {esc(d["note"])}</li>' for d in c['downloads'])
        + '</ul>' for c in cycles)
    (OUT / 'downloads/index.html').write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Ethiopia Seasonal Rainfall downloads</title><link rel="stylesheet" href="../assets/style.css"></head>'
        f'<body><main class="wrap"><h1>Downloads</h1><p><a href="../index.html">Back to the outlooks</a></p>{items}'
        '<p class="caveat">Research reconstructions; not official EMI or ICPAC forecasts.</p></main></body></html>\n',
        encoding='utf-8', newline='')
    (OUT / 'assets/site.js').write_text(JS.strip() + '\n', encoding='utf-8', newline='')
    (OUT / 'assets/style.css').write_text(CSS.strip() + '\n', encoding='utf-8', newline='')
    extras.build_releases(OUT, dict(cycles=cycles), esc)
    (OUT / 'index.html').write_text(page(cycles, default, jjas_evidence(), built, sha, release_id), encoding='utf-8', newline='')
    (OUT / '.nojekyll').write_text('', encoding='utf-8')
    size = sum(f.stat().st_size for f in OUT.rglob('*') if f.is_file())
    print(f'Site written to {OUT}: {len(cycles)} cycles ({", ".join(c["label"] for c in cycles)}), default {default}, '
          f'CHIRPS listing {"checked" if published else "not checked"}, {size / 1e6:.1f} MB')


if __name__ == '__main__':
    main()
