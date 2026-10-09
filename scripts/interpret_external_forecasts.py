r"""Turn comparison findings into a summary, a table and sentences with deterministic rules,
plus a review report.

Rules (no causes or skill claims are generated):
  spatial agreement drives the opening   all / predominant with localized disagreement / substantial
                                         disagreement / mostly different categories
  both favour above                      -> wetter-than-normal conditions in the specified overlap
  above vs below                         -> the outlooks disagree on the favoured rainfall category
  weak or tied signal                    -> that source shows no clear category preference under its rule
  target windows differ                  -> name the months that differ; spatial tendency only
  required product missing               -> state which comparison cannot be calculated and why

Agreement percentages always carry their denominator (the compared area). Shares near the
ends are written ">99%" / "<1%"; probability triples are rounded so they add up to 100.

Every item keeps its status (validated or draft) and evidence identifiers. Only validated
items are published on the site; the report shows drafts for review.

    python scripts\interpret_external_forecasts.py --comparison outputs\operational_2026_ondj\comparisons\comparison ^
        --sources outputs\operational_2026_ondj\comparisons\sources --out outputs\operational_2026_ondj\comparisons\interpretation
"""
import argparse
import html
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = {'below': 'below-normal', 'near': 'near-normal', 'above': 'above-normal', 'weak': 'no clear category', 'unknown': 'unknown'}
SHORT = {'below': 'below normal', 'near': 'near normal', 'above': 'above normal', 'weak': 'no clear category', 'unknown': 'unknown'}
WET = {'above': 'wetter-than-normal', 'below': 'drier-than-normal', 'near': 'near-normal'}
RELATION = {'same_favoured_category': 'Same category', 'opposing_favoured_categories': 'Opposing categories',
            'near_versus_other': 'Near normal vs other', 'weak_signal': 'No clear category in one source', 'unknown': 'Unknown'}
GREY = 'no forecast category shown (the legend does not explain the grey areas)'
ENGINE = 'rules v2'


def read_json(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def share(x):
    """Percentage without rounding 'almost all' to 'all' (or 'a little' to 'none')."""
    if x is None:
        return '—'
    if 0.995 <= x < 1:
        return '>99%'
    if 0 < x < 0.005:
        return '<1%'
    return f'{100 * x:.0f}%'


def share1(x):
    """One decimal for agreement shares and ranges (100% only when exact)."""
    if x is None:
        return '—'
    return '100%' if x >= 0.99995 else f'{100 * x:.1f}%'


def rounded_triple(values):
    """Integer percentages that add up to 100 (largest remainder); stored values are untouched."""
    raw = [100 * v for v in values]
    base = [int(r) for r in raw]
    for i in sorted(range(len(raw)), key=lambda i: raw[i] - base[i], reverse=True)[:100 - sum(base)]:
        base[i] += 1
    return base


def triple(p):
    """below / near / above from a dict or a list in that order."""
    vals = [p['below'], p['near'], p['above']] if isinstance(p, dict) else list(p)
    return ' / '.join(f'{v}%' for v in rounded_triple(vals))


def and_join(items):
    items = list(items)
    return items[0] if len(items) == 1 else ', '.join(items[:-1]) + ' and ' + items[-1]


def window_sentence(f):
    lim = next((x for x in f['limitations'] if isinstance(x, dict) and x.get('code') == 'target_window_mismatch'), None)
    if not lim:
        return ''
    return (f' The official outlook covers {lim["official_months"][0]}–{lim["official_months"][-1]} and the platform '
            f'{lim["platform_months"][0]}–{lim["platform_months"][-1]} ({", ".join(lim["only_platform"]) or "no month"} only in the platform), '
            'so this compares spatial tendencies, not probabilities for the same seasonal event.')


def area_opening(n, where):
    """Opening sentence driven by spatial agreement, not by the majority categories alone."""
    ag, maj = n['agreement_share_where_both_favoured'], n.get('overlap_majority') or {}
    om, pm = maj.get('official'), maj.get('platform')
    if ag is None:
        return f'The two outlooks never both show a favoured category in {where}.'
    if ag >= 0.9999:
        return f'Both outlooks favour {SHORT[om]} rainfall throughout the part of {where} where both show a favoured category.'
    if ag >= 0.9 and om == pm:
        return (f'{NAMES[om].capitalize()} rainfall is the predominant tendency in both outlooks over their shared displayed area in {where}, '
                'with localized disagreement.')
    if ag >= 0.6 and om == pm:
        return (f'{NAMES[om].capitalize()} rainfall is the most common favoured category in both outlooks in {where}, but they disagree '
                f'over a substantial part of their shared displayed area.')
    return f'The outlooks favour different categories over much of their shared displayed area in {where}.'


def agreement_clause(n, area_word):
    return (f'category agreement of {share1(n["agreement_share_where_both_favoured"])} within the compared area, which covers '
            f'{share(n["area_share_both_favoured"])} of the analysed {area_word}')


def summary_items(comparison, manifest):
    """Two or three key findings per area, each with its scope; used first on the site."""
    out = []
    zones = [f for f in comparison['findings'] if f['kind'] == 'zone']
    for f in [f for f in comparison['findings'] if f['kind'] == 'area']:
        n = f['numbers']
        area_word = 'national area' if f['area_key'] == 'all_ethiopia' else 'domain'
        lim = next((x for x in f['limitations'] if isinstance(x, dict) and x.get('code') == 'target_window_mismatch'), None)
        period = f'{lim["official_months"][0]}–{lim["official_months"][-1]} vs {lim["platform_months"][0]}–{lim["platform_months"][-1]}' if lim else 'same period'
        maj = (n.get('overlap_majority') or {}).get('official')
        text = f'{agreement_clause(n, area_word).capitalize()}. '
        if maj and maj == (n.get('overlap_majority') or {}).get('platform'):
            text += f'Predominant category in both: {SHORT[maj]}. '
        if lim:
            text += f'Periods differ ({period}).'
        out.append(dict(id=f['id'] + '_summary', area_key=f['area_key'], source_id=f['source_id'], status=f['status'],
                        title=f'{f["provider"]} — {f["area"]}', text=text.strip(), evidence_ids=f['evidence_ids'],
                        scope=dict(compared_area_share=n['area_share_both_favoured'], period=period)))
    arrows = [z for z in zones if z.get('platform_neighbourhood')]
    if arrows:
        zones_all, zones = zones, arrows
        status = 'validated' if all(z['status'] == 'validated' for z in zones) else 'draft'
        ids = sorted({i for z in zones for i in z['evidence_ids']})
        for key in ('all_ethiopia', 'season_domain'):
            dshare = lambda z: (z.get('platform_neighbourhood') or {}).get('domain_share', 0)
            inside = [z for z in zones if key == 'all_ethiopia' or dshare(z) > 0]
            partial = [z for z in inside if key == 'season_domain' and dshare(z) < 1]
            opp = [z for z in inside if z['relationship'] == 'opposing_favoured_categories']
            same = [z for z in inside if z['relationship'] == 'same_favoured_category']
            name = lambda zs: and_join(z['area'].split()[-1] for z in zs)
            parts = []
            if opp:
                parts.append(f'Opposing categories near the arrow{"s" if len(opp) > 1 else ""} of zone{"s" if len(opp) > 1 else ""} {name(opp)}: '
                             + '; '.join(f'platform {SHORT[z["platform_category"]]}, EMI {SHORT[z["official_category"]]}' for z in opp) + '.')
            if same:
                cats = {z['official_category'] for z in same}
                parts.append(f'Both favour {SHORT[cats.pop()] if len(cats) == 1 else "the same category"} near the arrows of zone'
                             f'{"s" if len(same) > 1 else ""} {name(same)}.')
            others = [z for z in inside if z not in opp and z not in same]
            if others:
                parts.append(' '.join(f'Zone {z["area"].split()[-1]}: {RELATION[z["relationship"]].lower()}.' for z in others))
            if partial:
                parts.append(f'The sample{"s" if len(partial) > 1 else ""} near zone{"s" if len(partial) > 1 else ""} {name(partial)} only partly '
                             f'overlap{"" if len(partial) > 1 else "s"} the domain ({and_join(f"{100 * dshare(z):.0f}%" for z in partial)} of sample cells); '
                             'the values describe the whole sample.')
            if not inside:
                parts.append('No EMI sample overlaps this area; see the national context.')
            out.append(dict(id=f'emi_zones_{key}_summary', area_key=key, source_id=zones[0]['source_id'], status=status,
                            title='EMI — sampled neighbourhoods near the zone arrows' + (' in the domain' if key == 'season_domain' else ''),
                            text=' '.join(parts) + ' Sampled neighbourhoods (±0.5°), not complete EMI zones.', evidence_ids=ids,
                            scope=dict(zones=[z['area'].split()[-1] for z in inside])))
    zones = [f for f in comparison['findings'] if f['kind'] == 'zone']
    zm = [z for z in zones if (z.get('zone_mean') or {}).get('mean_local_probabilities')]
    if zm:
        status = 'validated' if all(z['zone_mean']['status'] == 'validated' for z in zm) else 'draft'
        for key in ('all_ethiopia', 'season_domain'):
            inside = [z for z in zm if key == 'all_ethiopia' or z['zone_mean']['domain_share'] > 0]
            if not inside:
                continue
            parts = []
            for z in inside:
                m, n = z['zone_mean'], z['area'].split()[-1]
                rel = m['relationship']
                verb = {'same_favoured_category': f'both favour {SHORT[z["official_category"]]}',
                        'opposing_favoured_categories': f'opposing: platform {SHORT[favoured_name(m)]}, EMI {SHORT[z["official_category"]]}',
                        'weak_signal': 'no clear category in one source', 'near_versus_other': 'near normal vs other'}.get(rel, 'unknown')
                part = f'zone {n}' + (f' ({m["region_name"]})' if m.get('region_name') else '') + f': {verb}, platform {triple(m["mean_local_probabilities"])}'
                if key == 'season_domain' and m['domain_share'] < 1:
                    part += f' over the whole zone ({100 * m["domain_share"]:.0f}% of it in the domain)'
                parts.append(part)
            basis = zm[0]['zone_mean'].get('basis') or ''
            boundary = ('EMI homogeneous rainfall regions as published in 2013 (Korecha and Sorteberg), assumed unchanged'
                        if 'regions' in basis else 'the zone polygons digitized from the EMI figure (georeferenced by fitting the country outline)')
            out.append(dict(id=f'emi_whole_zones_{key}_summary', area_key=key, source_id=zones[0]['source_id'], status=status,
                            title='EMI — whole zones' + (' (rainfall regions)' if 'regions' in basis else ''),
                            text='Platform area mean of local probabilities over each EMI zone, below / near / above: ' + '; '.join(parts) +
                                 f'. Zone boundaries: {boundary}.',
                            evidence_ids=sorted({i for z in inside for i in z['evidence_ids']}), scope=dict(zones=[z['area'].split()[-1] for z in inside])))
    robust = robustness(comparison)
    if robust:
        out.append(robust)
    return out


def favoured_name(m):
    p = m['mean_local_probabilities']
    k = max(range(3), key=lambda i: p[i])
    return ('below', 'near', 'above')[k] if p[k] >= 0.4 else 'weak'


def robustness(comparison):
    """A bounded sensitivity statement (not a confidence interval)."""
    zones = [f for f in comparison['findings'] if f['kind'] == 'zone' and f.get('sensitivity')]
    areas = [f for f in comparison['findings'] if f['kind'] == 'area' and (f['numbers'].get('registration_sensitivity') or {}).get('agreement_range')]
    if not zones and not areas:
        return None
    parts = []
    if zones:
        stable = [z for z in zones if z['sensitivity']['stable']]
        n = zones[0]['sensitivity']['tested']
        if len(stable) == len(zones):
            parts.append(f'The EMI category relationships are stable under the tested location and neighbourhood changes '
                         f'({n} variants per zone: half-widths 0.25–1.0°, arrow-tip shifts up to ±0.5°).')
        else:
            parts.append('The EMI category relationship changes under the tested location and neighbourhood changes for zone'
                         f'{"s" if len(zones) - len(stable) > 1 else ""} ' + ', '.join(z['area'].split()[-1] for z in zones if z not in stable)
                         + '; treat those results as uncertain.')
    for f in areas:
        r = f['numbers']['registration_sensitivity']
        main = f['numbers']['agreement_share_where_both_favoured']
        lo, hi = min(r['agreement_range'][0], main), max(r['agreement_range'][1], main)
        span = (f'at {share1(lo)}' if share1(lo) == share1(hi) else f'between {share1(lo)} and {share1(hi)}')
        parts.append(f'With the ICPAC map as digitized and shifted by one source pixel in each direction, the {f["area"]} '
                     f'category agreement stays {span}.')
    parts.append('These are bounded sensitivity checks of the extraction, not statistical confidence intervals; exact EMI zone comparisons remain unavailable.')
    status = 'validated' if all(f['status'] == 'validated' for f in zones + areas) else 'draft'
    return dict(id='robustness_summary', area_key='any', source_id=None, status=status, title='Robustness of the extraction',
                text=' '.join(parts), evidence_ids=[], scope={})


def interval_text(key):
    """'above 70-80%' -> 'Above normal 70–80%'."""
    if not key:
        return 'no forecast category shown'
    c, iv = key.split(' ', 1)
    return f'{SHORT[c].capitalize()} {iv.replace("-", "–")}'


def icpac_table(comparison):
    """ICPAC's printed favoured category and interval vs the platform, at the sampled locations and per area."""
    rows = []
    for f in [f for f in comparison['findings'] if f['kind'] == 'icpac_sample']:
        main = interval_text(f['official_main_interval'])
        extra = []
        if f['official_main_interval'] and f['official_interval_shares'][f['official_main_interval']] < 0.995:
            extra.append(f'{share(f["official_interval_shares"][f["official_main_interval"]])} of shown cells; also '
                         + ', '.join(f'{interval_text(k)} ({share(v)})' for k, v in sorted(f['official_interval_shares'].items(), key=lambda kv: -kv[1])
                                     if k != f['official_main_interval']))
        if f['official_no_forecast_share'] > 0.005:
            extra.append(f'{share(f["official_no_forecast_share"])} of the sample grey (no forecast category shown)')
        rows.append(dict(id=f['id'], kind='sample', status=f['status'], location=f['area'].replace('EMI zone', 'zone'), zone=f['zone'],
                         official=main, official_note='; '.join(extra),
                         platform=triple(f['platform_mean_local_probabilities']) if f['platform_mean_local_probabilities'] else '—',
                         relationship=('Not comparable: ICPAC shows no forecast category here' if f['official_category'] == 'unknown'
                                       else RELATION[f['relationship']]), relationship_code=f['relationship'],
                         domain_share=f['domain_share'], area_key=None, evidence_ids=f['evidence_ids']))
    for f in [f for f in comparison['findings'] if f['kind'] == 'area']:
        n = f['numbers']
        top = max(n['official_interval_shares'].items(), key=lambda kv: kv[1])[0] if n['official_interval_shares'] else None
        rows.append(dict(id=f['id'] + '_row', kind='area', status=f['status'], location=f['area'], zone=None,
                         official=f'{SHORT[f["official_category"]].capitalize()} (most often {interval_text(top).split(" ", 2)[-1]})'
                                  if top and f['official_category'] in SHORT else '—',
                         official_note=f'shown on {share(n["area_share_official_forecast_shown"])} of the area; '
                                       f'{share(n["area_share_official_no_forecast"])} grey (no forecast category shown)',
                         platform=triple(n['platform_mean_local_probabilities']) if n.get('platform_mean_local_probabilities') else '—',
                         relationship=RELATION[f['relationship']] + ' (where both show a category)', relationship_code=f['relationship'],
                         domain_share=None, area_key=f['area_key'], evidence_ids=f['evidence_ids']))
    return rows


def emi_table(comparison):
    rows = []
    for f in [f for f in comparison['findings'] if f['kind'] == 'zone']:
        nb = f.get('platform_neighbourhood') or {}
        rows.append(dict(id=f['id'], status=f['status'], zone=f['area'].split()[-1], official=triple(f['official_probabilities']),
                         platform=triple(nb['mean_local_probabilities']) if nb.get('mean_local_probabilities') else '—',
                         relationship=RELATION[f['relationship']] if nb else '—', relationship_code=f['relationship'] if nb else None,
                         domain_share=nb.get('domain_share'), center=nb.get('center'),
                         stable=(f.get('sensitivity') or {}).get('stable'), evidence_ids=f['evidence_ids'],
                         **zone_columns(f.get('zone_mean'))))
    return rows


def zone_columns(zm):
    """Platform mean over the whole zone (digitized EMI rainfall region); draft values kept apart."""
    if not zm:
        return {}
    t = triple(zm['mean_local_probabilities'])
    ok = zm.get('status') == 'validated'
    return dict(zone_name=zm.get('region_name'), zone_domain_share=zm.get('domain_share'), zone_cells=zm.get('cells'),
                zone_mean=t if ok else None, zone_relationship=RELATION[zm['relationship']] if ok else None,
                zone_relationship_code=zm['relationship'] if ok else None,
                zone_mean_draft=None if ok else t, zone_relationship_draft=None if ok else RELATION[zm['relationship']])


def paragraphs(comparison, manifest):
    """Detailed interpretation: one paragraph per finding, shared limitations stated once."""
    out = []
    who_of = {s['source_id']: s['provider'] for s in manifest['sources']}
    label_of = {s['source_id']: s.get('season_label') or s.get('label') or s['source_id'] for s in manifest['sources']}
    zones = [f for f in comparison['findings'] if f['kind'] == 'zone']
    for f in zones:
        nb = f.get('platform_neighbourhood') or {}
        zm = f.get('zone_mean') or {}
        if nb:
            rel, pcat = f['relationship'], f['platform_category']
            place = f'near the arrow of EMI zone {f["area"].split()[-1]}'
        elif zm.get('status') == 'validated':
            rel = zm['relationship']
            pcat = favoured_name(zm)
            place = f'over EMI zone {f["area"].split()[-1]}'
        else:
            continue                                  # nothing publishable for this zone yet
        if rel == 'same_favoured_category':
            lead = (f'Both outlooks favour {WET.get(pcat, NAMES[pcat])} conditions {place}.')
        elif rel == 'opposing_favoured_categories':
            lead = (f'The platform favours {NAMES[pcat]} rainfall {place}, while the EMI outlook favours '
                    f'{NAMES[f["official_category"]]} rainfall. This indicates disagreement in the favoured rainfall category.')
        elif rel == 'weak_signal':
            weak = 'The platform' if pcat == 'weak' else 'The EMI outlook'
            lead = f'{weak} does not show a unique favoured category {place} under its applicable rule.'
        else:
            lead = f'The platform favours {NAMES[pcat]} and the EMI outlook {NAMES[f["official_category"]]} rainfall {place}.'
        text = lead + f' EMI prints {triple(f["official_probabilities"])} (below / near / above)'
        if nb.get('mean_local_probabilities'):
            text += f'; the platform\'s area mean of local probabilities in the sampled neighbourhood is {triple(nb["mean_local_probabilities"])}.'
        else:
            text += '.'
        if zm.get('status') == 'validated':           # never mix draft zone means into a published paragraph
            where = f'the EMI {zm["region_name"]} rainfall region' if zm.get('region_name') else 'as digitized from the EMI figure'
            text += (f' Over the whole zone ({where}), the platform area mean is '
                     f'{triple(zm["mean_local_probabilities"])}: {RELATION[zm["relationship"]].lower()}.')
        out.append(dict(id=f['id'] + '_text', finding=f['id'], source_id=f['source_id'], area=f['area'], area_key='zone',
                        status=f['status'], relationship=rel, text=text, evidence_ids=f['evidence_ids']))
    if zones:
        if any(z.get('platform_neighbourhood') for z in zones):
            limit = ('For every EMI zone, the platform value near the arrow is the area mean of local probabilities within ±0.5° of the arrow tip, '
                     'not the complete EMI zone: the figure publishes no zone boundaries and no reference period, so exact zone '
                     'probability differences are not calculated.')
        else:
            limit = ('The EMI zones were digitized from the figure\'s fill colours and placed by fitting the country outline, so their '
                     'boundaries are approximate; the figure states no reference period, so probability differences are not calculated.')
        out.append(dict(id='emi_shared_limitation', finding=None, source_id=zones[0]['source_id'], area=None, area_key='zone',
                        status='validated' if all(z['status'] == 'validated' for z in zones) else 'draft', relationship=None,
                        text=limit + window_sentence(zones[0]), evidence_ids=[]))
    for f in [f for f in comparison['findings'] if f['kind'] == 'area']:
        n = f['numbers']
        where = 'Ethiopia' if f['area_key'] == 'all_ethiopia' else f'the {f["area"]}'
        area_word = 'national area' if f['area_key'] == 'all_ethiopia' else 'domain'
        ints = sorted(n['official_interval_shares'].items(), key=lambda kv: -kv[1])[:2]
        opp = n['opposing_share_where_both_favoured']
        text = (area_opening(n, where) + f' ICPAC shows a favoured category on {share(n["area_share_official_forecast_shown"])} of {where} and '
                f'{GREY} on {share(n["area_share_official_no_forecast"])}; where it shows one it favours above normal on '
                f'{share(n["official_category_shares"]["above"])}, most often at {" and ".join(k.split(" ", 1)[1] for k, _ in ints)}. '
                f'The platform favours above normal on {share(n["platform_category_shares"]["above"])} and below normal on '
                f'{share(n["platform_category_shares"]["below"])} of {where}. '
                + (f'There is {agreement_clause(n, area_word)}' + (f'; opposite categories (above vs below) on {share(opp)} of the compared area.' if opp else '.')
                   if n['agreement_share_where_both_favoured'] is not None else '')
                + ' ICPAC publishes only the favoured category and its probability interval, so probabilities are not differenced.'
                + window_sentence(f))
        out.append(dict(id=f['id'] + '_text', finding=f['id'], source_id=f['source_id'], area=f['area'], area_key=f['area_key'],
                        status=f['status'], relationship=f['relationship'], text=' '.join(text.split()), evidence_ids=f['evidence_ids']))
    unavailable = [m for m in comparison['metrics'] if m['status'] == 'unavailable']
    reasons = {
        'rainfall_anomaly_difference': 'rainfall-anomaly differences, because no official rainfall-amount anomaly product was found in the checked ICPAC and EMI products',
        'forecast_accuracy': 'which forecast is more accurate, because that needs observations and a separate verification design (see Verification)',
        'zone_mean_probability': 'zone-mean platform probabilities for EMI zones, because the zone boundaries are not published with the figure',
        'same_event_probability_difference': 'same-event probability differences, because the target windows or spatial supports differ and ICPAC publishes only favoured-category intervals'}
    named = [reasons[k] for k in reasons if any(m['metric'] == k for m in unavailable)]
    if named:
        out.append(dict(id='not_calculated', finding=None, source_id=None, area=None, area_key='any', status='validated', relationship=None,
                        text='Not calculated: ' + '; '.join(named) + '.', evidence_ids=[]))
    pending = sorted({m['source_id'] for m in comparison['metrics'] if m['status'] == 'pending_review'})
    if pending:
        out.append(dict(id='pending_review', finding=None, source_id=None, area=None, area_key='any', status='validated', relationship=None,
                        text='Awaiting review: the values extracted from ' + ' and '.join(f'the {who_of.get(s, s)} {label_of.get(s, s)} outlook' for s in pending) +
                             ' have not yet been checked against the published figures by a person, so no comparison numbers are '
                             'published for them yet. The original figures are shown below.', evidence_ids=[]))
    return out


def evidence(comparison, manifest):
    """Evidence identifiers -> labels and repository-relative files (the site maps them to public URLs)."""
    ev = {}
    plat = comparison['platform']
    ev['platform_forecast_' + plat['target'].lower()] = dict(kind='platform', label=f'Platform {plat["label"]} forecast data (NetCDF)',
                                                            file=plat['native_forecast'], sha256=plat['native_sha256'])
    for s in manifest['sources']:
        for e in s.get('evidence', []):
            url = s.get('download_url')
            if e.get('pdf_page') and url:
                url = f'{url}#page={e["pdf_page"]}'
            ev[e['id']] = dict(kind='official_figure', label=f'{s["provider"]} figure: {e["caption"]}', preview=e['file'], url=url,
                               page=s.get('requested_url'), source_id=s['source_id'])
        ev[s['source_id'] + '_record'] = dict(kind='source_record', label=f'{s["provider"]} source record', source_id=s['source_id'])
    for m in comparison['maps']:
        sid = m.rsplit('_', 1)[0]
        ev[f'{sid}_comparison_map'] = dict(kind='comparison_map', label='Comparison map', map=m, source_id=sid)
    return ev


def report(path, comparison, manifest, items, table, paras, ev, image_prefix='', itable=()):
    esc = html.escape
    rows = []
    for s in manifest['sources']:
        x = s.get('extraction', {})
        meta = [('Provider / product', f'{s["provider"]} · {s.get("product")} · {s.get("representation")}'), ('Label', s.get('label')),
                ('Target period', f'{s.get("target_start")} to {s.get("target_end")}'), ('Issue date', s.get('issue_date') or 'not stated by the provider'),
                ('Initialization', s.get('initialization') or 'not stated'), ('Reference period', s.get('reference_period') or 'not stated'),
                ('Retrieved', s.get('retrieved_utc')), ('HTTP Last-Modified (not the issue date)', s.get('http_last_modified') or '—'),
                ('Source page', s.get('requested_url')), ('Download', s.get('download_url')), ('SHA-256', s.get('sha256')),
                ('Extraction', f'{x.get("status")} · {x.get("method")} · record {x.get("record")}' + (f' · {x["note"]}' if x.get('note') else '')),
                ('Review', json.dumps(x.get('review')) if x.get('review') else 'not reviewed')]
        imgs = ''.join(f'<figure><img src="{image_prefix}../sources/{esc(e["file"])}" alt="{esc(e["caption"])}"><figcaption>{esc(e["caption"])}</figcaption></figure>'
                       for e in s.get('evidence', []))
        checks = ''.join(f'<li>{esc(c)}</li>' for c in (x.get('checks_for_reviewer') or []))
        narrative = ''.join(f'<li>{esc(n["text"])} <span class="muted">({esc(n["locator"])})</span></li>' for n in s.get('narrative', []))
        cmd = (f'python scripts\\external_forecasts.py review --registry config\\external_forecasts\\{comparison["registry"]}.json '
               f'--record {s["source_id"]} --reviewer "Your name"')
        rows.append(f'<section><h2>{esc(s["provider"])}: {esc(s.get("label") or s["source_id"])}</h2><table>' +
                    ''.join(f'<tr><th>{esc(k)}</th><td>{esc(str(v))}</td></tr>' for k, v in meta) + '</table>' +
                    (f'<h3>Provider text</h3><ul>{narrative}</ul>' if narrative else '') + imgs +
                    (f'<h3>Reviewer checklist</h3><ol>{checks}</ol><p>After checking every item against the figure: <code>{esc(cmd)}</code> '
                     f'(add <code>--reject --note "…"</code> if anything is wrong).</p>' if x.get('status') != 'validated' else '') + '</section>')
    draft_rows = []
    for m in comparison['metrics']:
        val = m.get('value') if m.get('value') is not None else m.get('draft_value')
        draft_rows.append(f'<tr><td>{esc(m["metric"])}</td><td>{esc(m.get("source_id") or "")} {esc(str(m.get("zone") or m.get("area") or ""))}</td>'
                          f'<td>{esc(m["status"])}</td><td>{esc(m.get("reason") or "")}</td>'
                          f'<td><code>{esc(json.dumps(val, ensure_ascii=False)[:400]) if val is not None else ""}</code></td></tr>')
    tag = lambda st: f'<strong>[{esc(st)}]</strong> ' if st != 'validated' else ''
    summary = ''.join(f'<li>{tag(i["status"])}<strong>{esc(i["title"])}.</strong> {esc(i["text"])}</li>' for i in items)
    zone_rows = ''.join(f'<tr><td>{tag(r["status"])}Zone {esc(r["zone"])}</td><td>{esc(r["official"])}</td><td>{esc(r["platform"])}</td>'
                        f'<td>{esc(r["relationship"])}</td><td>{share(r["domain_share"])}</td></tr>' for r in table)
    maps = ''.join(f'<figure><img src="{esc(m)}" alt="{esc(m)}"><figcaption>{esc(m)}</figcaption></figure>' for m in comparison['maps'])
    ps = ''.join(f'<p class="{esc(p["status"])}">{tag(p["status"])}{esc(p["text"])}</p>' for p in paras)
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Official outlook comparison</title><style>body{{font:15px/1.55 system-ui,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;color:#111}}
table{{border-collapse:collapse;width:100%;margin:8px 0}}th,td{{border-bottom:1px solid #ddd;padding:6px 8px;text-align:left;vertical-align:top}}
img{{max-width:100%}}figure{{margin:12px 0}}.muted{{color:#666;font-size:.9em}}.draft{{background:#fdf1d8;padding:8px}}code{{font-size:.85em;word-break:break-all}}
section{{border:1px solid #ddd;border-radius:8px;padding:12px 16px;margin:16px 0}}</style></head><body>
<h1>Official outlook comparison: {esc(comparison["platform"]["label"])}</h1>
<p class="muted">Generated {esc(datetime.now(timezone.utc).isoformat(timespec="seconds"))} by interpret_external_forecasts.py ({ENGINE}). Platform forecast: {esc(comparison["platform"]["native_forecast"])}
(SHA-256 {esc(comparison["platform"]["native_sha256"][:12])}). Items marked [draft] use extraction records not yet checked by a person and are not published.</p>
<h2>Key findings</h2><ul>{summary}</ul><h2>Comparison maps</h2>{maps}
<h2>EMI zones: official values and sampled platform neighbourhoods</h2><table><tr><th>Location</th><th>Official below / near / above</th>
<th>Platform neighbourhood below / near / above</th><th>Relationship</th><th>Share of sample in the domain</th></tr>{zone_rows}</table>
<p class="muted">Platform values: area mean of local probabilities within ±0.5° of each arrow tip, not the complete EMI zone. Rounded to add up to 100%.</p>
<h2>ICPAC: printed favoured category and interval vs the platform</h2><table><tr><th>Location</th><th>ICPAC (favoured category, printed interval)</th>
<th>Platform below / near / above</th><th>Relationship</th></tr>{"".join(f'<tr><td>{tag(r["status"])}{esc(r["location"])}</td><td>{esc(r["official"])}<br><span class="muted">{esc(r["official_note"])}</span></td><td>{esc(r["platform"])}</td><td>{esc(r["relationship"])}</td></tr>' for r in itable)}</table>
<p class="muted">ICPAC publishes only the favoured category and its probability interval (the other two categories are not published), for its own target period; see the source details for the dates of each product.</p>
<h2>Detailed interpretation</h2>{ps}{"".join(rows)}
<h2>Metrics and eligibility</h2><table><tr><th>Metric</th><th>Source / area</th><th>Status</th><th>Reason</th><th>Value (draft values shown for review)</th></tr>{"".join(draft_rows)}</table>
<h2>Notes</h2><ul>{"".join(f"<li>{esc(n)}</li>" for n in comparison["notes"])}</ul></body></html>'''
    path.write_text(page, encoding='utf-8', newline='')


def interpret(comparison_dir, sources_dir, out):
    import external_forecasts as ef
    comparison_dir, sources_dir, out = Path(comparison_dir), Path(sources_dir), Path(out)
    tmp = ef.staging(out)
    comparison = read_json(comparison_dir / 'comparison.json')
    manifest = read_json(sources_dir / 'source_manifest.json')
    items, table, itable = summary_items(comparison, manifest), emi_table(comparison), icpac_table(comparison)
    paras = paragraphs(comparison, manifest)
    ev = evidence(comparison, manifest)
    result = dict(created_utc=datetime.now(timezone.utc).isoformat(timespec='seconds'), engine=ENGINE, registry=comparison['registry'],
                  platform=comparison['platform'], inputs=comparison.get('inputs'), summary=items, emi_table=table, icpac_table=itable,
                  paragraphs=paras, evidence=ev, published_paragraphs=[p['id'] for p in paras if p['status'] == 'validated'])
    (tmp / 'interpretation.json').write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding='utf-8', newline='')
    # Report beside the comparison maps so relative image links work from comparisons/interpretation/.
    for m in comparison['maps']:
        shutil.copy2(comparison_dir / 'maps' / m, tmp / m)
    report(tmp / 'report.html', comparison, manifest, items, table, paras, ev, itable=itable)
    ef.publish(tmp, out)
    return result


def main():
    import sys
    sys.path.insert(0, str(ROOT / 'scripts'))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--comparison', required=True)
    ap.add_argument('--sources', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    r = lambda p: Path(p) if Path(p).is_absolute() else ROOT / p
    res = interpret(r(a.comparison), r(a.sources), r(a.out))
    for i in res['summary']:
        print(f'[{i["status"]}] {i["title"]}: {i["text"]}\n')


if __name__ == '__main__':
    main()
