"""Generate an evidence-based cycle-year verification report. No prediction or fitting code."""
import base64
import hashlib
import html
import json
import math
from pathlib import Path
import shutil
from cycle import CYCLE, YEAR, REF, REF_DASH, REF_YEARS, MEMBERS, REGIME, REGIME_YEARS, OVERLAP_YEAR, EVALUATION_STUDY

ORDER = ['Jun', 'Jul', 'Aug', 'Sep', 'JJAS']
LABELS = {'all_country': 'All Ethiopia', 'regime_0': 'R0: arid / marginal',
          'regime_1': 'R1: western unimodal', 'regime_2': 'R2: Belg–Kiremt rule',
          'regime_3': 'R3: Gu–Deyr rule', 'jjas_r12_rainfall_domain': 'JJAS R1+R2 rainfall domain'}
PROBS = ['raw_observed_thresholds', 'corrected_member_counts', 'corrected_smoothed', 'shared_blend', 'climatology']


def digest(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def eq(a, b, name):
    if a is None or b is None:
        if a != b:
            raise ValueError('Null/value mismatch: ' + name)
        return
    if isinstance(a, list):
        if not isinstance(b, list) or len(a) != len(b):
            raise ValueError('Array mismatch: ' + name)
        for x, y in zip(a, b):
            eq(x, y, name)
    elif not math.isfinite(float(a)) or not math.isfinite(float(b)) or not math.isclose(a, b, rel_tol=0, abs_tol=2e-6):
        raise ValueError('Inconsistent evidence: ' + name)


def ratio_skill(score, ref):
    return 1 - score / ref if ref > 0 else None


def validate(country, regimes, targets):
    if country.get('year') != YEAR or regimes.get('year') != YEAR:
        raise ValueError(f'Expected {YEAR} assessment')
    if len(set(targets)) != len(targets) or not set(targets) <= set(ORDER):
        raise ValueError('Invalid or duplicate targets')
    for source in [country, regimes]:
        names = [r['target'] for r in source['results']]
        if len(names) != len(set(names)) or set(names) != set(source['targets']) or not set(targets) <= set(names):
            raise ValueError('Targets missing, duplicated or inconsistent with report metadata')
    if regimes.get('classification_method') != 'github_refined_corrected_calendar_v1':
        raise ValueError('Unexpected regime definition')
    frozen = regimes['frozen_forecasts']['forecast_sha256']
    for target in targets:
        c = next(r for r in country['results'] if r['target'] == target)
        r = next(r for r in regimes['results'] if r['target'] == target)
        if c['year'] != YEAR or not r['provenance']['country_reproduction_passed']:
            raise ValueError('Country reproduction or evaluation year not verified')
        if c['forecast_sha256'] != frozen[target] or c['forecast_sha256'] != r['provenance']['forecast_sha256'] or c['observations_sha256'] != r['provenance']['observations_sha256']:
            raise ValueError('Mismatched forecast/observation generations')
        all_country = r['domains']['all_country']
        for key in ['amount_cells', 'probability_cells', 'amount_country_area_percent', 'probability_country_area_percent', 'observed_category_area_fractions']:
            eq(c[key], all_country[key], target + '/' + key)
        for family in ['amount', 'probability']:
            for method, metrics in all_country[family].items():
                for key, value in metrics.items():
                    eq(value, c[family][method][key], target + '/' + family + '/' + method + '/' + key)
        partitions = [r['domains']['regime_' + str(k)] for k in [-1, 0, 1, 2, 3, 4]]
        for key in ['domain_cells', 'amount_cells', 'probability_cells', 'domain_country_area_percent', 'amount_country_area_percent', 'probability_country_area_percent']:
            eq(sum(d[key] for d in partitions), all_country[key], 'regime partition/' + key)
        for domain, d in r['domains'].items():
            for family in ['amount', 'probability']:
                if not d[family]:
                    continue
                for method, metrics in d[family].items():
                    if family == 'amount':
                        eq(metrics['crpss'], ratio_skill(metrics['crps_mm'], d[family]['climatology']['crps_mm']), 'CRPSS')
                    else:
                        eq(metrics['rps'], metrics['brier_by_category'][0] + metrics['brier_by_category'][2], 'RPS identity')
                        eq(metrics['rpss'], ratio_skill(metrics['rps'], d[family]['climatology']['rps']), 'RPSS')
                        for bs, ref, bss in zip(metrics['brier_by_category'], d[family]['climatology']['brier_by_category'], metrics['bss_by_category']):
                            eq(bss, ratio_skill(bs, ref), 'BSS')
            if d['probability']:
                eq(d['blend_minus_smoothed_rps'], d['probability']['shared_blend']['rps'] - d['probability']['corrected_smoothed']['rps'], 'blend difference')
                eq(sum(d['observed_category_area_fractions']), 1, 'observed fractions')
                eq(sum(d['shared_mean_probabilities']), 1, 'probability sums')
        # Area-weight the disjoint regimes, never average their skill scores.
        for family, keys in [('amount', ['bias_mm', 'mae_mm', 'crps_mm']), ('probability', ['rps', 'log_loss'])]:
            area_key = family + '_country_area_percent'
            for method in all_country[family]:
                for key in keys:
                    value = sum(d[area_key] * d[family][method][key] for d in partitions if d[family]) / all_country[area_key]
                    eq(value, all_country[family][method][key], 'area-weighted reconstruction')


def performance_notes(regimes, targets):
    """Factual post-event annotations, not forecast confidence classes or masks."""
    notes = []
    for r in regimes['results']:
        if r['target'] not in targets:
            continue
        for domain in LABELS:
            d = r['domains'][domain]
            if not d['probability'] or not d['amount']:
                continue
            p = d['probability']['shared_blend']
            am = d['amount']['corrected']
            effect = d['blend_minus_smoothed_rps']
            def flag(value):
                return 'undefined_reference' if value is None else ('below_climatology' if value < 0 else ('above_climatology' if value > 0 else 'equal_to_climatology'))
            notes.append({'target': r['target'], 'domain': domain,
                          'amount_comparison': flag(am['crpss']), 'probability_comparison': flag(p['rpss']),
                          'corrected_crpss': am['crpss'], 'shared_rpss': p['rpss'],
                          'blend_effect': 'improved_RPS' if effect < 0 else ('worsened_RPS' if effect > 0 else 'unchanged_RPS'),
                          'blend_minus_smoothed_rps': effect, 'corrected_bias_mm': am['bias_mm'],
                          'amount_coverage_percent': d['amount_domain_area_percent'], 'probability_coverage_percent': d['probability_domain_area_percent'],
                          'negative_bss_categories': [cat for cat, value in zip(['below', 'near', 'above'], p['bss_by_category']) if value is not None and value < 0],
                          'interpretation': f'Descriptive result for this {YEAR} target only. Does not change forecast values, masks, weights or issuance-time confidence.'})
    return notes


def number(x, digits=2):
    return 'N/A' if x is None else f'{x:.{digits}f}'


def percent(x):
    return 'N/A' if x is None else f'{100*x:+.1f}%'


class Report:
    """Write the same report to Markdown and a portable HTML document."""
    def __init__(self):
        self.md = []
        self.web = []

    def heading(self, text, level=2):
        self.md += ['#' * level + ' ' + text, '']
        self.web.append(f'<h{level}>{html.escape(text)}</h{level}>')

    def paragraph(self, text, kind=''):
        self.md += [text, '']
        self.web.append(f'<p class="{kind}">{html.escape(text)}</p>')

    def table(self, headers, rows):
        self.md += ['| ' + ' | '.join(map(str, headers)) + ' |', '| ' + ' | '.join(['---'] * len(headers)) + ' |']
        self.md += ['| ' + ' | '.join(map(str, row)) + ' |' for row in rows]
        self.md.append('')
        cell = lambda value: html.escape(str(value))
        self.web.append('<div class="table-wrap"><table><thead><tr>' + ''.join('<th>' + cell(h) + '</th>' for h in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>' + cell(v) + '</td>' for v in row) + '</tr>' for row in rows) + '</tbody></table></div>')

    def picture(self, p, caption, root):
        relative = p.relative_to(root).as_posix()
        self.md += [f'![{caption}]({relative})', '']
        data = base64.b64encode(p.read_bytes()).decode('ascii')
        self.web.append('<figure><img alt="' + html.escape(caption, quote=True) + '" src="data:image/png;base64,' + data + '"><figcaption>' + html.escape(caption) + '</figcaption></figure>')

    def save(self, out):
        (out / 'VERIFICATION_REPORT.md').write_text('\n'.join(self.md), encoding='utf-8')
        css = '''body{margin:0;background:#edf2f5;color:#172b3a;font:16px/1.6 system-ui,Arial,sans-serif}main{max-width:1120px;margin:28px auto;padding:36px 42px;background:white;border-radius:14px}h1{font-size:32px;line-height:1.2;color:#123c55}h2{margin-top:36px;color:#155672;border-top:1px solid #dce5eb;padding-top:22px}h3{color:#315b6d}p{max-width:100ch}.status{background:#fff4d8;border-left:5px solid #b67716;padding:14px 18px}.note{background:#edf5f7;padding:14px 18px}.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;margin:18px 0;font-size:14px}th{background:#163f58;color:white;text-align:left}th,td{padding:10px 12px;border-bottom:1px solid #dce5eb}tbody tr:nth-child(even){background:#f2f6f8}td:not(:first-child){font-variant-numeric:tabular-nums}figure{margin:24px 0}img{max-width:100%;height:auto}figcaption{font-size:13px;color:#49616d}.footer{font-size:12px;color:#607582}@media(max-width:650px){main{margin:0;padding:20px;border-radius:0}h1{font-size:26px}}@media print{body{background:white}main{margin:0;padding:0;max-width:none}table{font-size:10px}h2,h3{break-after:avoid}tr,figure{break-inside:avoid}.table-wrap{overflow:visible}}'''
        page = f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Ethiopia {YEAR} rainfall forecast verification</title><style>' + css + '</style></head><body><main>' + '\n'.join(self.web) + '</main></body></html>'
        (out / 'VERIFICATION_REPORT.html').write_text(page, encoding='utf-8')


def export_report(country, regimes, history, targets, out, provenance, maps=None):
    validate(country, regimes, targets)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    evidence = out / 'evidence'
    evidence.mkdir(exist_ok=True)
    for filename, value in [('country_summary.json', country), ('regime_summary.json', regimes), ('historical_review.json', history)]:
        if value is not None:
            (evidence / filename).write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')
    targets = [t for t in ORDER if t in targets]
    missing = [t for t in ORDER if t not in targets]
    rows = {r['target']: r for r in regimes['results'] if r['target'] in targets}
    notes = performance_notes(regimes, targets)
    payload = {'year': YEAR, 'targets_verified': targets, 'targets_pending_in_report': missing,
               'full_JJAS_verified': 'JJAS' in targets, 'all_five_targets_verified': not missing,
               'forecast_changed': False, 'new_calibration_fitted': False,
               'assessment_type': f'Retrospective reconstruction; descriptive {YEAR} verification',
               'provenance': provenance, 'performance_notes': notes,
               'decision': 'Retain frozen shared-blend forecasts. Regional annotations are post-event verification findings, not forecast-time confidence labels or new masks. No automatic model switch.'}
    (out / 'report_summary.json').write_text(json.dumps(payload, indent=2, allow_nan=False), encoding='utf-8')
    r = Report()
    r.heading(f'Ethiopia rainfall forecast verification — {YEAR}', 1)
    r.paragraph(f'May initialization | ECMWF seasonal forecasts | CHIRPS v2 verification | Reference period {REF_DASH}')
    r.paragraph('Verified targets: ' + ', '.join(targets) + '. ' + ('Pending in this report: ' + ', '.join(missing) + '. No full-JJAS conclusion is inferred from monthly results.' if 'JJAS' in missing else 'JJAS is assessed directly against its complete seasonal observations; overlapping monthly and seasonal scores are not pooled.'), 'status')
    r.paragraph(f'This is a retrospective assessment of the reconstructed forecasts. It does not establish an actual May {YEAR} issuance, independent prospective validation, or an official EMI/ICPAC forecast. All results below concern the submitted verification evidence.', 'note')
    r.heading('Decision and principal findings')
    r.paragraph(payload['decision'])
    for target in targets:
        c = rows[target]['domains']['all_country']
        r.paragraph(f"{target}: corrected rainfall CRPSS {percent(c['amount']['corrected']['crpss'])}; final probability RPSS {percent(c['probability']['shared_blend']['rpss'])}; amount-mean error {c['amount']['corrected']['bias_mm']:+.2f} mm. Probability results cover {c['probability_domain_area_percent']:.1f}% of country grid area.")
    r.paragraph('Positive skill means a lower score than the stated climatological reference on the same support. It is not percentage forecast accuracy. Positive mean error means the forecast was wetter than observed, which can occur even when the forecast anomaly is below normal.')
    r.heading('Country results')
    r.table(['Target', 'Raw CRPS mm', 'Corrected CRPS mm', 'Climatology CRPS mm', 'Corrected CRPSS', 'Final RPSS'], [[t, *[number(rows[t]['domains']['all_country']['amount'][m]['crps_mm']) for m in ['raw', 'corrected', 'climatology']], percent(rows[t]['domains']['all_country']['amount']['corrected']['crpss']), percent(rows[t]['domains']['all_country']['probability']['shared_blend']['rpss'])] for t in targets])
    r.heading('Main JJAS rainfall domain')
    d0 = rows[targets[0]]['domains']['jjas_r12_rainfall_domain']
    r.paragraph(f"This fixed pre-{YEAR} domain contains {d0['domain_cells']} cells and {d0['domain_country_area_percent']:.1f}% of country grid area. It combines cleaned R1/R2 classes with the previously defined rainfall criteria. Monthly rows evaluate each month inside that domain; they are not a complete-JJAS assessment.")
    r.table(['Target', 'Amount CRPSS', 'Smoothed RPSS', 'Final RPSS', 'Mean error mm', 'Probability coverage'], [[t, percent(rows[t]['domains']['jjas_r12_rainfall_domain']['amount']['corrected']['crpss']), percent(rows[t]['domains']['jjas_r12_rainfall_domain']['probability']['corrected_smoothed']['rpss']), percent(rows[t]['domains']['jjas_r12_rainfall_domain']['probability']['shared_blend']['rpss']), number(rows[t]['domains']['jjas_r12_rainfall_domain']['amount']['corrected']['bias_mm']), number(rows[t]['domains']['jjas_r12_rainfall_domain']['probability_domain_area_percent'], 1) + '%'] for t in targets])
    r.heading('Regional performance notes')
    for target in targets:
        r.heading(target + f' {YEAR}', 3)
        table = []
        for domain in ['regime_0', 'regime_1', 'regime_2', 'regime_3']:
            d = rows[target]['domains'][domain]
            if not d['probability'] or not d['amount']:
                table.append([LABELS[domain], 'No score', 'No score', 'No score', 'N/A', 'No valid support'])
                continue
            effect = d['blend_minus_smoothed_rps']
            table.append([LABELS[domain], percent(d['amount']['corrected']['crpss']), percent(d['probability']['corrected_smoothed']['rpss']), percent(d['probability']['shared_blend']['rpss']), number(d['probability_domain_area_percent'], 1) + '%', 'Helped' if effect < 0 else ('Weakened' if effect > 0 else 'Unchanged')])
        r.table(['Regime', 'Amount CRPSS', 'Smoothed RPSS', 'Final RPSS', 'Probability coverage', 'Blend effect'], table)
    if 'Jun' in rows:
        d = rows['Jun']['domains']['regime_0']; a = d['amount']; p = d['probability']
        r.paragraph(f"June R0: raw, corrected and climatological CRPS are {a['raw']['crps_mm']:.2f}, {a['corrected']['crps_mm']:.2f} and {a['climatology']['crps_mm']:.2f} mm. Corrected mean rainfall is {d['corrected_mean_mm']:.2f} mm versus {d['observed_mean_mm']:.2f} mm observed. Final RPSS is {percent(p['shared_blend']['rpss'])}. Small climatological rainfall/error scales make percentage skill particularly sensitive here; report absolute scores alongside skill.")
    if 'Jul' in rows:
        d = rows['Jul']['domains']['regime_2']
        r.paragraph(f"July R2: corrected mean error is {d['amount']['corrected']['bias_mm']:+.2f} mm. Observed and forecast mean anomalies are {d['observed_mean_anomaly_mm']:.2f} and {d['forecast_mean_anomaly_mm']:.2f} mm. This documents a remaining error in the magnitude of the rainfall anomaly.")
    if 'Aug' in rows:
        d = rows['Aug']['domains']['regime_3']; p = d['probability']
        r.paragraph(f"August R3: smoothed RPSS is {percent(p['corrected_smoothed']['rpss'])}, versus {percent(p['shared_blend']['rpss'])} after blending. The final above-normal-category Brier Skill Score is {percent(p['shared_blend']['bss_by_category'][2])}. Overall RPS improvement therefore does not mean every category improved over climatology. Probability coverage is {d['probability_domain_area_percent']:.1f}% of R3 area.")
    r.paragraph('These labels describe the observed performance of these targets. They do not justify hiding weak regions, declaring confidence at issuance, applying a new mask, or replacing forecast values after observing outcomes.')
    r.heading('Historical context')
    if history is None:
        r.paragraph('Historical review was not supplied to this build. No historical ranking is inferred.')
    else:
        if history.get('classification_method') != regimes['classification_method']:
            raise ValueError('Historical/regime classification mismatch')
        hrows = []
        for h in history['reviews']:
            if h['target'] not in targets:
                continue
            g = h['domains']['all_country']['groups']['all']; p = g['probability']; delta = g['blend_minus_smooth']
            hrows.append([h['target'], h['mode'], len(g['years']), number(p['smooth']['rps'], 5), number(p['shared_blend']['rps'], 5), number(delta['mean'], 5)])
        r.table(['Target', 'Period', 'Years', 'Smoothed RPS', 'Shared RPS', 'Shared minus smoothed'], hrows)
        r.paragraph(f'Negative shared-minus-smoothed RPS favors blending. Historical training-period scores use nested year exclusion; operational-period scores use fits fixed on 1993–2016 and have already been inspected repeatedly. The final {YEAR} models were fitted on {REF_DASH}. These periods therefore do not test an identical fitted weight. Historical regime boundaries can also differ between folds.')
    r.heading('Methods and interpretation')
    for text in [
        f'Rainfall amounts: equal-year, cell-specific mean–variance bias correction. All {MEMBERS} operational members are retained. The ensemble and climatological reference are evaluated using empirical CRPS; their finite ensemble sizes are 51 and 33, respectively, without an iid/fair-ensemble adjustment.',
        'Probabilities: observed training-period terciles, member counts, alpha = 0.5 additive smoothing, then the selected shared climatology blend. The final product does not use the experimental Dirichlet, local or regime-specific probability mappings. Probability blending does not change the corrected rainfall members or amount CRPS.',
        'RPS is the sum of the first two cumulative-category squared errors. Brier scores are category-specific; log loss uses natural logarithms and the existing probability floor. Country and domain scores use grid-cell area weights on identical support across methods within each metric family.',
        'Amount and probability masks differ; unscored cells are not near-normal conditions. R0–R3 are the reconciled GitHub-derived climatological rules, not administrative boundaries or independently validated official EMI zones. No onset-detection gate is used.',
        f'One verification year cannot establish multi-year reliability or statistical significance. Spatial cells and overlapping months/JJAS are not independent evaluation samples. No pooled overall score is produced. The {YEAR} outcomes are now inspected evidence and must not be reused as an untouched test set.'
    ]:
        r.paragraph(text)
    r.heading('Verification maps')
    copied = []
    for target in targets:
        source = (maps or {}).get(target)
        if source and Path(source).is_file():
            dest = out / 'maps' / f'{target}_verification.png'; dest.parent.mkdir(exist_ok=True)
            shutil.copy2(source, dest)
            copied.append({'target': target, 'sha256': digest(dest)})
            r.picture(dest, target + f' {YEAR}: original native-grid verification map. Colour scales differ between months; use each legend. Gray excluded cells are not a near-normal forecast.', out)
    if not copied:
        r.paragraph('Map files were not supplied to this build. All numerical tables derive from the supplied verification reports.')
    r.heading('Completion and future work')
    r.paragraph('Retain the frozen forecasts and archive this report as a verification addendum. A future calibration revision needs a separate historical evaluation with all preprocessing and model selection inside year-based validation. This report does not fit or adopt a revised model.')
    if 'JJAS' in missing:
        r.paragraph('Complete September and JJAS only after the official CHIRPS v2 daily monthly observations pass the existing completeness and overlap checks. Then regenerate this report with all five targets. Until then, no full-JJAS verification result is available in this report.', 'status')
    r.heading('Evidence and reproducibility')
    r.paragraph(provenance['audit_scope'])
    for name, value in provenance.get('source_sha256', {}).items():
        r.paragraph(name + ': SHA-256 ' + value, 'footer')
    r.paragraph('Forecast identity is retained in report_summary.json. These hashes identify the input versions; they do not by themselves validate the scientific provenance of the original observations.', 'footer')
    r.save(out)
    payload['maps'] = copied
    (out / 'report_summary.json').write_text(json.dumps(payload, indent=2, allow_nan=False), encoding='utf-8')
    addendum = [f'# Verification addendum — {YEAR}', '', 'Post-event verification notes. Attach to the existing forecast package without revising its archived predictions.', '', 'Targets: ' + ', '.join(targets) + '.', 'Pending in this report: ' + (', '.join(missing) or 'none') + '.', '', payload['decision'], '']
    for n in notes:
        addendum.append(f"- {n['target']} / {LABELS[n['domain']]}: corrected CRPSS {percent(n['corrected_crpss'])}; final RPSS {percent(n['shared_rpss'])}; blend {n['blend_effect']}; probability coverage {n['probability_coverage_percent']:.1f}%.")
    addendum += ['', 'These are single-year descriptive findings; they are not forecast-time confidence grades. See VERIFICATION_REPORT.html for context, exceptions and historical comparisons.']
    (out / 'VERIFICATION_ADDENDUM.md').write_text('\n'.join(addendum) + '\n', encoding='utf-8')
    return payload
