r"""Turn comparison findings into sentences with deterministic rules, plus a review report.

Rules (no causes or skill claims are generated):
  both favour above            -> both outlooks favour wetter-than-normal conditions in the overlap
  above vs below               -> the outlooks disagree on the favoured rainfall category
  weak or tied signal          -> that source shows no clear category preference under its rule
  target windows differ        -> name the months that differ; spatial tendency only
  required product missing     -> state which comparison cannot be calculated and why

Every paragraph keeps its status (validated or draft) and evidence identifiers. Only
validated paragraphs are published on the site; the report shows drafts for review.

    python scripts\interpret_external_forecasts.py --comparison outputs\operational_2026_ondj\comparisons\comparison ^
        --sources outputs\operational_2026_ondj\comparisons\sources --out outputs\operational_2026_ondj\comparisons\interpretation
"""
import argparse
import html
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = {'below': 'below-normal', 'near': 'near-normal', 'above': 'above-normal', 'weak': 'no clear category', 'unknown': 'unknown'}
WET = {'above': 'wetter-than-normal', 'below': 'drier-than-normal', 'near': 'near-normal'}
ENGINE = 'rules v1'


def read_json(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def pct(x):
    return '—' if x is None else f'{100 * x:.0f}%'


def triple(p):
    return f'{pct(p["below"])} / {pct(p["near"])} / {pct(p["above"])}'


def window_sentence(f):
    lim = next((x for x in f['limitations'] if isinstance(x, dict) and x.get('code') == 'target_window_mismatch'), None)
    if not lim:
        return ''
    only_p = ', '.join(lim['only_platform']) or 'none'
    only_o = ', '.join(lim['only_official']) or 'none'
    return (f' The target periods differ: the official outlook covers {lim["official_months"][0]}–{lim["official_months"][-1]} and the '
            f'platform {lim["platform_months"][0]}–{lim["platform_months"][-1]} (only in the platform: {only_p}; only in the official '
            f'outlook: {only_o}). This compares spatial tendencies, not probabilities for the same seasonal event.')


def relationship_sentence(f, who):
    rel, pc, oc = f['relationship'], f['platform_category'], f['official_category']
    if rel == 'same_favoured_category':
        if pc in WET and pc != 'near':
            return f'Both outlooks favour {WET[pc]} conditions in {f["area_phrase"]}.'
        return f'Both outlooks favour near-normal rainfall in {f["area_phrase"]}.'
    if rel == 'opposing_favoured_categories':
        return (f'The platform favours {NAMES[pc]} rainfall in {f["area_phrase"]}, while the {who} outlook favours {NAMES[oc]} rainfall. '
                'This indicates disagreement in the favoured rainfall category.')
    if rel == 'near_versus_other':
        return (f'The platform favours {NAMES[pc]} and the {who} outlook {NAMES[oc]} rainfall in {f["area_phrase"]}; '
                'one of them points to near-normal conditions, so the two differ in emphasis rather than direction.')
    if rel == 'weak_signal':
        weak = 'The platform' if pc == 'weak' else f'The {who} outlook'
        return f'{weak} does not show a clear category preference in {f["area_phrase"]} under its applicable rule (leading probability below 40%).'
    return f'The relationship in {f["area_phrase"]} cannot be determined from the available information.'


def paragraphs(comparison, manifest):
    out = []
    who_of = {s['source_id']: s['provider'] for s in manifest['sources']}
    label_of = {s['source_id']: s.get('season_label') or s.get('label') or s['source_id'] for s in manifest['sources']}
    for f in comparison['findings']:
        who = who_of.get(f['source_id'], f['provider'])
        if f['kind'] == 'zone':
            nb = f.get('platform_neighbourhood') or {}
            f['area_phrase'] = f'the area EMI\'s arrow marks for zone {f["area"].split()[-1]}'
            text = relationship_sentence(f, who)
            mean = nb.get('mean_local_probabilities')
            text += (f' EMI prints below / near / above {triple(f["official_probabilities"])} for the zone; the platform\'s area mean of local '
                     f'probabilities within ±{nb.get("half_width_deg", 0.5)}° of the arrow tip is '
                     f'{" / ".join(pct(x) for x in mean) if mean else "not available"}.')
            text += (' An exact zone probability difference has not been calculated because the zone boundary is not published with '
                     'the figure (only an arrow locates it) and the EMI reference period is not stated.')
            text += window_sentence(f)
        else:
            n = f['numbers']
            where = f'the {f["area"]}' if f['area'] != 'All Ethiopia' else 'Ethiopia'
            f['area_phrase'] = f'the part of {where} where both show a favoured category'
            text = relationship_sentence(f, who) if f['relationship'] != 'unknown' else ''
            f['area_phrase'] = where
            ints = sorted(n['official_interval_shares'].items(), key=lambda kv: -kv[1])[:2]
            text += (f' Over {f["area_phrase"]}, the {who} map shows a favoured category on {pct(n["area_share_official_forecast_shown"])} '
                     f'of the area ({pct(n["area_share_official_no_forecast"])} is grey, without a forecast); it favours above normal on '
                     f'{pct(n["official_category_shares"]["above"])} of that, most often at {" and ".join(k.split(" ", 1)[1] + " " + NAMES[k.split(" ", 1)[0]] for k, _ in ints)}. '
                     f'The platform favours above normal on {pct(n["platform_category_shares"]["above"])} and below normal on '
                     f'{pct(n["platform_category_shares"]["below"])} of the area. ')
            if n['agreement_share_where_both_favoured'] is not None:
                text += (f'Where both show a favoured category ({pct(n["area_share_both_favoured"])} of the area), the categories agree on '
                         f'{pct(n["agreement_share_where_both_favoured"])} and are opposite (above vs below) on '
                         f'{pct(n["opposing_share_where_both_favoured"])}.')
            text += (' ICPAC publishes only the favoured category and its probability interval, so the platform\'s probabilities are '
                     'not differenced against it.') + window_sentence(f)
        out.append(dict(id=f['id'] + '_text', finding=f['id'], source_id=f['source_id'], area=f['area'], status=f['status'],
                        relationship=f['relationship'], text=' '.join(text.split()), evidence_ids=f['evidence_ids']))
    unavailable = [m for m in comparison['metrics'] if m['status'] == 'unavailable']
    reasons = {
        'rainfall_anomaly_difference': 'rainfall-anomaly differences, because no official rainfall-amount anomaly product was found in the checked ICPAC and EMI products',
        'forecast_accuracy': 'which forecast is more accurate, because that needs observations and a separate verification design (see Verification)',
        'zone_mean_probability': 'zone-mean platform probabilities for EMI zones, because the zone boundaries are not published with the figure',
        'same_event_probability_difference': 'same-event probability differences, because the target windows or spatial supports differ and ICPAC publishes only favoured-category intervals'}
    named = [reasons[k] for k in reasons if any(m['metric'] == k for m in unavailable)]
    if named:
        out.append(dict(id='not_calculated', finding=None, source_id=None, area=None, status='validated', relationship=None,
                        text='Not calculated: ' + '; '.join(named) + '.', evidence_ids=[]))
    pending = sorted({m['source_id'] for m in comparison['metrics'] if m['status'] == 'pending_review'})
    if pending:
        out.append(dict(id='pending_review', finding=None, source_id=None, area=None, status='validated', relationship=None,
                        text='Awaiting review: the values extracted from ' + ' and '.join(f'the {who_of.get(s, s)} {label_of.get(s, s)} outlook' for s in pending) +
                             ' have not yet been checked against the published figures by a person, so no comparison numbers are '
                             'published for them yet. The original figures are shown below.', evidence_ids=[]))
    return out


def evidence(comparison, manifest):
    ev = {}
    plat = comparison['platform']
    ev['platform_forecast_' + plat['target'].lower()] = dict(label=f'Platform {plat["label"]} forecast (native NetCDF, SHA-256 {plat["native_sha256"][:12]})',
                                                            file=plat['native_forecast'])
    for s in manifest['sources']:
        for e in s.get('evidence', []):
            ev[e['id']] = dict(label=f'{s["provider"]}: {e["caption"]}', file=f'../sources/{e["file"]}', url=s.get('requested_url'))
    for m in comparison['maps']:
        sid = m.rsplit('_', 1)[0]
        ev[f'{sid}_comparison_map'] = dict(label=f'Comparison map ({sid})', file=m)
    return ev


def report(path, comparison, manifest, paras, ev):
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
        imgs = ''.join(f'<figure><img src="../sources/{esc(e["file"])}" alt="{esc(e["caption"])}"><figcaption>{esc(e["caption"])}</figcaption></figure>'
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
    maps = ''.join(f'<figure><img src="{esc(m)}" alt="{esc(m)}"><figcaption>{esc(m)}</figcaption></figure>' for m in comparison['maps'])
    ps = ''.join(f'<p class="{esc(p["status"])}"><strong>[{esc(p["status"])}]</strong> {esc(p["text"])}'
                 + ('<br><span class="muted">Evidence: ' + ', '.join(esc(ev.get(i, {}).get('label', i)) for i in p['evidence_ids']) + '</span>'
                    if p['evidence_ids'] else '') + '</p>' for p in paras)
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Official outlook comparison</title><style>body{{font:15px/1.55 system-ui,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;color:#111}}
table{{border-collapse:collapse;width:100%;margin:8px 0}}th,td{{border-bottom:1px solid #ddd;padding:6px 8px;text-align:left;vertical-align:top}}th{{width:28%;color:#444}}
img{{max-width:100%}}figure{{margin:12px 0}}.muted{{color:#666;font-size:.9em}}.draft{{background:#fdf1d8;padding:8px}}code{{font-size:.85em;word-break:break-all}}
section{{border:1px solid #ddd;border-radius:8px;padding:12px 16px;margin:16px 0}}</style></head><body>
<h1>Official outlook comparison: {esc(comparison["platform"]["label"])}</h1>
<p class="muted">Generated {esc(datetime.now(timezone.utc).isoformat(timespec="seconds"))} by interpret_external_forecasts.py ({ENGINE}). Platform forecast: {esc(comparison["platform"]["native_forecast"])}.
Paragraphs marked [draft] use extraction records that a person has not yet checked; they are not published on the site.</p>
<h2>Interpretation</h2>{ps}<h2>Comparison maps</h2>{maps}{"".join(rows)}
<h2>Metrics and eligibility</h2><table><tr><th>Metric</th><th>Source / area</th><th>Status</th><th>Reason</th><th>Value (draft values shown for review)</th></tr>{"".join(draft_rows)}</table>
<h2>Notes</h2><ul>{"".join(f"<li>{esc(n)}</li>" for n in comparison["notes"])}</ul></body></html>'''
    path.write_text(page, encoding='utf-8', newline='')


def interpret(comparison_dir, sources_dir, out):
    comparison_dir, sources_dir, out = Path(comparison_dir), Path(sources_dir), Path(out)
    tmp = out.with_name(out.name + '_building')
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    comparison = read_json(comparison_dir / 'comparison.json')
    manifest = read_json(sources_dir / 'source_manifest.json')
    paras = paragraphs(comparison, manifest)
    ev = evidence(comparison, manifest)
    result = dict(created_utc=datetime.now(timezone.utc).isoformat(timespec='seconds'), engine=ENGINE, registry=comparison['registry'],
                  platform=comparison['platform'], paragraphs=paras, evidence=ev,
                  published_paragraphs=[p['id'] for p in paras if p['status'] == 'validated'])
    (tmp / 'interpretation.json').write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding='utf-8', newline='')
    # Report beside the comparison maps so relative image links work from comparisons/interpretation/.
    for m in comparison['maps']:
        shutil.copy2(comparison_dir / 'maps' / m, tmp / m)
    report(tmp / 'report.html', comparison, manifest, paras, ev)
    if out.exists():
        shutil.rmtree(out)
    tmp.replace(out)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--comparison', required=True)
    ap.add_argument('--sources', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    r = lambda p: Path(p) if Path(p).is_absolute() else ROOT / p
    res = interpret(r(a.comparison), r(a.sources), r(a.out))
    for p in res['paragraphs']:
        print(f'[{p["status"]}] {p["text"]}\n')


if __name__ == '__main__':
    main()
