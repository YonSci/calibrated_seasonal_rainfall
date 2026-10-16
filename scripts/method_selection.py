"""Select the approach for each season (cycle), target and product from the historical and validation evidence (docs/50).

Brings the benchmarks together under one rule (config/method_selection_rule.json, fixed in advance):
  bias correction       outputs/bias_correction_benchmark/recommendations.json (bias_recommend.py: the full-pipeline
                        confirmation and the independent validation seasons of every amount correction)
  probability stage     outputs/probability_calibration/<cycle>/benchmark.json (Phase 1) and phase2_binary/
  distribution models   outputs/probability_calibration/<cycle>/distribution/ (Phase 2) and phase3/; their independent
                        seasons from amount_shadow/<year>/ (dist_shadow.py runs a shadow for every candidate model)
  Leung–Dirichlet       outputs/leung_dirichlet/<cycle>/benchmark.json (leung_dirichlet_benchmark.py; its validation season is the
                        cycle's forecast year once observed, scored by the same run)
Products: the published tercile probabilities (RPS against MVS + climatology blend) and rainfall amounts (CRPS against the
MVS ensemble). A method is a candidate only if its benchmark confirms it better than the published reference (Holm across
its family, not worse over the test years); validation seasons then decide between candidate, recommended and not
supported. One change at a time: candidates of different families were not tested together.

A selection is the approach the evidence supports; it never changes the published forecast.

  python scripts/method_selection.py      ->  outputs/method_selection/selection.json
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import leung_dirichlet as ldc

ROOT = Path(__file__).resolve().parents[1]
RULE = 'config/method_selection_rule.json'
OUT = ROOT / 'outputs/method_selection/selection.json'
CYCLES = ['jan_fmam', 'feb_fmam', 'may_jjas', 'sep_ondj']
FAMILY_LABEL = {'bias_correction': 'Bias correction (amount correction)', 'probability_phase1': 'Probability stage, Phase 1',
                'probability_phase2_binary': 'Probability stage, Phase 2 binary calibrators', 'distribution_phase2': 'Distribution model, Phase 2',
                'distribution_phase3': 'Distribution model, Phase 3', 'leung_dirichlet': 'Leung–Dirichlet calibration (docs/51)'}
STAGE = {'bias_correction': 'amount correction', 'probability_phase1': 'probability stage', 'probability_phase2_binary': 'probability stage',
         'distribution_phase2': 'distribution model', 'distribution_phase3': 'distribution model', 'leung_dirichlet': 'Leung–Dirichlet calibration'}


def read(p):
    p = ROOT / p
    return json.loads(p.read_text(encoding='utf-8')) if p.is_file() else None


def hist(test):
    a, b, d = test['training'], test['test'], test['decision']
    return dict(training_difference=a['mean_difference'], years_better=a['years_better'], years=a['years'],
                holm_p=d.get('holm_p_family', d.get('holm_p')), test_difference=b['mean_difference'],
                test_years_better=b['years_better'], test_years=b['years'])


def bias_candidates(rec, target, product):
    """Bias-correction candidates for a target and product, with their validation record (bias_recommend.py)."""
    if not rec:
        return []
    e = rec['targets'].get(target, {}).get(product)
    if not e or e['status'] == 'keep':
        return []
    out = [dict(family='bias_correction', method=e['method'], label=e['method_label'], historical=e['historical'],
                validation=e.get('validation'), status=e['status'], chosen_by=e.get('chosen_by'))]
    for a in e.get('alternatives', []):                                   # other confirmed corrections (no own validation summary)
        out.append(dict(family='bias_correction', method=a.get('method', a['label']), label=a['label'], historical=a.get('historical'),
                        validation=None, status='candidate'))
    return out


def confirmed(data, family, target, score, keys, names, reference=None):
    """Candidates of one probability/distribution family: methods its benchmark confirms better (score: 'rps' or 'crps')."""
    out = []
    if not data:
        return out
    for k in keys:
        t = data['tests'].get(k, {}).get(score, {}).get(target)
        if t and t['decision']['confirmed'] and (reference is None or t['decision'].get('reference', reference) == reference):
            out.append(dict(family=family, method=k, label=names(k), historical=hist(t), validation=None, status='candidate'))
    return out


def shadow_validation(cycle, model, target, minimum):
    """Independent seasons of a distribution model's amount shadow (dist_shadow.py): its CRPS and the MVS ensemble's per scored year."""
    seasons = []
    for f in sorted((ROOT / f'outputs/probability_calibration/{cycle}/amount_shadow').glob(f'*/{model}__{target}.json')):
        r = json.loads(f.read_text(encoding='utf-8'))
        s = (r.get('scores') or {}).get(r.get('primary_region', 'ethiopia'), {})
        if r.get('observed') and 'crps' in s.get('shadow', {}) and 'crps' in s.get('mvs_ensemble', {}):
            seasons.append(dict(year=int(f.parent.name), method=s['shadow']['crps'], reference=s['mvs_ensemble']['crps']))
    if not seasons:
        return None
    return dict(seasons=seasons, mean_difference=float(np.mean([x['method'] - x['reference'] for x in seasons])), required=minimum)


def leung_dirichlet_validation(ld, method, target, score, minimum):
    """The Leung–Dirichlet benchmark's forecast year, once observed: the method's score and the published reference's."""
    v = (ld.get('validation') or {}).get(target)
    ref = 'incumbent' if score == 'rps' else 'mvs_ensemble'
    if not v or method not in v[score] or ref not in v[score]:
        return None
    seasons = [dict(year=v['year'], method=v[score][method], reference=v[score][ref])]
    return dict(seasons=seasons, mean_difference=float(seasons[0]['method'] - seasons[0]['reference']), required=minimum)


def status_of(c, minimum):
    v = c.get('validation')
    if c['family'] == 'bias_correction' and c.get('status') in ('recommended', 'not_supported', 'candidate'):
        return c['status']                                               # bias_recommend.py applies the same validation rule
    if not v or len(v.get('seasons') or []) < minimum:
        return 'candidate'
    return 'recommended' if v['mean_difference'] <= 0 else 'not_supported'


def select(cands):
    order = {'recommended': 0, 'candidate': 1, 'not_supported': 2}
    usable = [c for c in cands if c['status'] != 'not_supported']
    if not usable:
        return None
    return sorted(usable, key=lambda c: (order[c['status']], (c.get('historical') or {}).get('training_difference', 0)))[0]


def why(sel, product, target, ref_label, cands, unit):
    if sel is None:
        rejected = [c for c in cands if c['status'] == 'not_supported']
        base = f'No method is confirmed better than {ref_label} for {target} on the historical evidence'
        return base + (f'; {len(rejected)} confirmed method(s) were worse over the validation seasons.' if rejected else '.')
    h, v = sel.get('historical') or {}, sel.get('validation')
    txt = (f"{sel['label']} ({FAMILY_LABEL[sel['family']].lower()}) is confirmed better than {ref_label} for {target}: {unit} difference "
           f"{h.get('training_difference', float('nan')):+.4g} over the training years (Holm p {h.get('holm_p', float('nan')):.3g}; "
           f"{h.get('years_better', '?')} of {h.get('years', '?')} years better), {h.get('test_difference', float('nan')):+.4g} over the test years.")
    if v and v.get('seasons') and v.get('mean_difference') is not None:
        txt += f" Independent validation: {len(v['seasons'])} of {v['required']} season(s), mean difference {v['mean_difference']:+.4g}."
    elif v:
        txt += f" Independent validation: 0 of {v.get('required', 3)} seasons scored so far."
    else:
        txt += ' No independent validation season yet: a shadow forecast is needed before it can be recommended.'
    others = [c for c in cands if c is not sel and c['status'] != 'not_supported']
    if others:
        txt += ' Also confirmed (one change at a time): ' + '; '.join(f"{c['label']} ({STAGE[c['family']]})" for c in others) + '.'
    return txt


def main():
    rule = read(RULE)
    minimum = rule['validation']['minimum_seasons']
    recs = {c['name']: c for c in (read('outputs/bias_correction_benchmark/recommendations.json') or {}).get('cycles', [])}
    cycles = []
    for cy in CYCLES:
        base = f'outputs/probability_calibration/{cy}'
        p1, p2b, d2, d3 = read(f'{base}/benchmark.json'), read(f'{base}/phase2_binary/benchmark.json'), read(f'{base}/distribution/benchmark.json'), read(f'{base}/phase3/benchmark.json')
        ld = read(f'outputs/leung_dirichlet/{cy}/benchmark.json')
        rec = recs.get(cy)
        if not (p1 or rec):
            continue
        bench = read(f'config/bias_correction/{cy}.json') or {}
        found = list((p1 or {}).get('targets') or rec['targets'])
        targets = [t for t in bench.get('targets', []) if t in found] + [t for t in found if t not in bench.get('targets', [])]   # calendar order
        out = dict(name=cy, targets={})
        for t in targets:
            out['targets'][t] = {}
            for product, spec in rule['products'].items():
                score = 'rps' if product == 'probabilities' else 'crps'
                cands = bias_candidates(rec, t, product)
                if product == 'probabilities':
                    if p1:
                        cands += confirmed(p1, 'probability_phase1', t, 'rps', [m for m in p1['methods'] if m != p1['incumbent']], lambda k: p1['registry'][k]['name'])
                    if p2b:
                        cands += confirmed(p2b, 'probability_phase2_binary', t, 'rps', [m for m in p2b['methods'] if m != p2b['incumbent']], lambda k: p2b['registry'][k]['name'])
                for fam, d in (('distribution_phase2', d2), ('distribution_phase3', d3)):
                    if d:
                        cands += confirmed(d, fam, t, score, d['models'], lambda k, d=d: d['registry'][k]['name'],
                                           reference='incumbent' if score == 'rps' else 'mvs_ensemble')
                if ld:
                    cands += confirmed(ld, 'leung_dirichlet', t, score, [k for k in ld['methods'] if score in ld['tests'].get(k, {})],
                                       lambda k: ldc.LONG.get(k, k), reference='incumbent' if score == 'rps' else 'mvs_ensemble')
                for c in cands:
                    if c['family'].startswith('distribution') and product == 'amounts':
                        c['validation'] = shadow_validation(cy, c['method'], t, minimum)
                    if c['family'] == 'leung_dirichlet':
                        c['validation'] = leung_dirichlet_validation(ld, c['method'], t, score, minimum)
                    c['status'] = status_of(c, minimum)
                sel = select(cands)
                ref = spec['reference']['label']
                out['targets'][t][product] = dict(
                    product=spec['label'], reference=ref, status=sel['status'] if sel else 'keep',
                    selected=dict(family=sel['family'], family_label=FAMILY_LABEL[sel['family']], stage=STAGE[sel['family']], method=sel['method'],
                                  label=sel['label']) if sel else dict(family='published', label=ref, stage=None, method=None),
                    historical=sel.get('historical') if sel else None, validation=sel.get('validation') if sel else None,
                    alternatives=[dict(family=c['family'], family_label=FAMILY_LABEL[c['family']], method=c['method'], label=c['label'], status=c['status'],
                                       historical=c.get('historical')) for c in cands if c is not sel],
                    why=why(sel, product, t, ref, cands, 'RPS' if score == 'rps' else 'CRPS (mm)'))
        cycles.append(out)
    data = dict(created_utc=datetime.now(timezone.utc).isoformat(), rule=RULE, rule_contents=rule, cycles=cycles)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    for c in cycles:
        for t, prods in c['targets'].items():
            for p, e in prods.items():
                if e['status'] != 'keep':
                    print(f"{c['name']} {t} {p}: {e['status']} — {e['selected']['label']} ({e['selected']['family_label']})")
    print(f'Saved {OUT.relative_to(ROOT)}: {sum(len(c["targets"]) for c in cycles)} targets in {len(cycles)} cycles')


if __name__ == '__main__':
    main()
