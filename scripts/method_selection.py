"""Select the approach for each season (cycle), target and product from the historical and validation evidence (docs/50).

Brings the benchmarks together under one rule (config/method_selection_rule.json, fixed in advance):
  bias correction       outputs/bias_correction_benchmark/recommendations.json (bias_recommend.py: the full-pipeline
                        confirmation and the independent validation seasons of every amount correction)
  probability stage     outputs/probability_calibration/<cycle>/benchmark.json (Phase 1) and phase2_binary/
  distribution models   outputs/probability_calibration/<cycle>/distribution/ (Phase 2) and phase3/; their independent
                        seasons from amount_shadow/<year>/ (dist_shadow.py runs a shadow for every candidate model)
  statistical downscaling  outputs/mos/<cycle>/benchmark.json (mos_benchmark.py: CCA, PCR; validation: its forecast year and the shadow seasons of mos_shadow.py)
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

import accept_results
import leung_dirichlet as ldc
import selection_tests as st

ROOT = Path(__file__).resolve().parents[1]
RULE = 'config/method_selection_rule.json'
OUT = ROOT / 'outputs/method_selection/selection.json'
CYCLES = ['jan_fmam', 'feb_fmam', 'may_jjas', 'sep_ondj']
FAMILY_LABEL = {'bias_correction': 'Bias correction (amount correction)', 'probability_phase1': 'Probability stage, Phase 1',
                'probability_phase2_binary': 'Probability stage, Phase 2 binary calibrators', 'distribution_phase2': 'Distribution model, Phase 2',
                'distribution_phase3': 'Distribution model, Phase 3', 'leung_dirichlet': 'Two-stage calibration (docs/51)', 'mos': 'Statistical downscaling (docs/53)',
                'distribution_neural': 'Neural network (docs/54)', 'distribution_neural_ext': 'Neural network, second stage (docs/54)',
                'distribution_neural_pooled': 'Neural network, pooled over the months (docs/54)',
                'distribution_neural_pooled2': 'Neural network, pooled, with EMOS or neighbourhood inputs (docs/54)',
                'distribution_neural_all': 'Neural network, pooled over all cycles (docs/54)',
                'distribution_stacking': 'Model combination: EMOS, quantile regression and the DRN (docs/54)'}
# Simplicity order of the practical tie rule (rule 'tie_rule'): fewer and more interpretable parameters first
SIMPLICITY = {'bias_correction': 1, 'probability_phase1': 1, 'probability_phase2_binary': 1, 'distribution_phase2': 2,
              'distribution_phase3': 4, 'leung_dirichlet': 4, 'mos': 4, 'distribution_neural': 5, 'distribution_neural_ext': 5,
              'distribution_neural_pooled': 5,
              # extensions of a network (the pooled DRN plus an EMOS base, neighbourhood inputs or the other cycles) and the
              # combination of models, which contains a network: one step more complex than the network they extend
              'distribution_neural_pooled2': 6, 'distribution_neural_all': 6, 'distribution_stacking': 6}
SIMPLER_METHOD = {'emos_csg': 2, 'quantile_regression': 3, 'extended_logistic': 3}     # within the Phase 2 distribution models


def simplicity(c):
    return SIMPLER_METHOD.get(c['method'], SIMPLICITY.get(c['family'], 9))


STAGE = {'bias_correction': 'amount correction', 'probability_phase1': 'probability stage', 'probability_phase2_binary': 'probability stage',
         'distribution_phase2': 'distribution model', 'distribution_phase3': 'distribution model', 'leung_dirichlet': 'Leung–Dirichlet calibration', 'mos': 'statistical downscaling',
         'distribution_neural': 'distribution model (neural network)', 'distribution_neural_ext': 'distribution model (neural network)',
         'distribution_neural_pooled': 'distribution model (neural network)', 'distribution_neural_pooled2': 'distribution model (neural network)',
         'distribution_neural_all': 'distribution model (neural network)', 'distribution_stacking': 'distribution model (combination)'}


def read(p):
    p = ROOT / p
    return json.loads(p.read_text(encoding='utf-8')) if p.is_file() else None


CORRECTION = 'holm'                                   # set from the rule's multiple_testing in main()
CORR_NAME = {'holm': 'Holm', 'benjamini_hochberg': 'Benjamini–Hochberg'}


def hist(test, decision=None):
    """The historical evidence of a test; `decision` is the rule's re-decision (selection_tests.decide)."""
    a, b, d = test['training'], test['test'], test['decision']
    return dict(training_difference=a['mean_difference'], years_better=a['years_better'], years=a['years'],
                holm_p=d.get('holm_p_family', d.get('holm_p')), test_difference=b['mean_difference'],
                p_adjusted=(decision or {}).get('p_adjusted', d.get('holm_p_family', d.get('holm_p'))),
                correction=(decision or {}).get('correction', 'holm'),
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
    """Candidates of one benchmark family: methods confirmed better under the rule's correction (score: 'rps' or 'crps'),
    adjusted across every method and target of the benchmark's family (SEL is its own family, as in the benchmark)."""
    out = []
    if not data:
        return out
    family_methods = [m for m in data['tests'] if m != 'SEL' and score in data['tests'][m]]
    dec = {**st.decide(data['tests'], family_methods, score, CORRECTION), **st.decide(data['tests'], ['SEL'], score, CORRECTION)}
    for k in keys:
        t = data['tests'].get(k, {}).get(score, {}).get(target)
        d = dec.get((k, target))
        if t and d and d['confirmed'] and (reference is None or t['decision'].get('reference', reference) == reference):
            out.append(dict(family=family, method=k, label=names(k), historical=hist(t, d), validation=None, status='candidate'))
    return out


def shadow_validation(cycle, model, target, minimum, score='crps'):
    """Independent seasons of a distribution model's shadow (dist_shadow.py) per scored year: amounts, its CRPS and the MVS
    ensemble's; probabilities, the RPS of its tercile probabilities and of the published probabilities."""
    ref = 'mvs_ensemble' if score == 'crps' else 'published'
    seasons = []
    for f in sorted((ROOT / f'outputs/probability_calibration/{cycle}/amount_shadow').glob(f'*/{model}__{target}.json')):
        r = json.loads(f.read_text(encoding='utf-8'))
        s = (r.get('scores') or {}).get(r.get('primary_region', 'ethiopia'), {})
        if r.get('observed') and score in s.get('shadow', {}) and score in s.get(ref, {}):
            seasons.append(dict(year=int(f.parent.name), method=s['shadow'][score], reference=s[ref][score]))
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


def mos_validation(cycle, mos, method, target, score, minimum):
    """Independent seasons of a statistical-downscaling method (docs/53): the benchmark's forecast year (2026) and every
    scored shadow season (mos_shadow.py, from 2027), one record per year."""
    seasons = {}
    v = (mos.get('validation') or {}).get(target)
    ref = 'incumbent' if score == 'rps' else 'mvs_ensemble'
    if v and method in v[score] and ref in v[score]:
        seasons[v['year']] = dict(year=v['year'], method=v[score][method], reference=v[score][ref])
    for f in sorted((ROOT / f'outputs/mos/{cycle}/shadow').glob(f'*/{method}__{target}.json')):
        r = json.loads(f.read_text(encoding='utf-8'))
        s = (r.get('scores') or {}).get(score)
        if r.get('observed') and s:
            seasons[int(r['forecast_year'])] = dict(year=int(r['forecast_year']), method=s['method'],
                                                    reference=s['published' if score == 'rps' else 'mvs_ensemble'])
    if not seasons:
        return None
    seasons = [seasons[y] for y in sorted(seasons)]
    return dict(seasons=seasons, mean_difference=float(np.mean([x['method'] - x['reference'] for x in seasons])), required=minimum)


def status_of(c, minimum):
    v = c.get('validation')
    if c['family'] == 'bias_correction' and c.get('status') in ('recommended', 'not_supported', 'candidate'):
        return c['status']                                               # bias_recommend.py applies the same validation rule
    if not v or len(v.get('seasons') or []) < minimum:
        return 'candidate'
    return 'recommended' if v['mean_difference'] <= 0 else 'not_supported'


def select(cands, level=None, margin=None):
    """The selected candidate: the best status, then the largest historical gain. Practical tie rule (rule 'tie_rule'): candidates
    of that status whose historical gain is within margin x level (level: the published approach's own historical score for
    the target and product) of the best are tied, and the simplest of them (SIMPLICITY) is selected; the tie is recorded."""
    order = {'recommended': 0, 'candidate': 1, 'not_supported': 2}
    usable = [c for c in cands if c['status'] != 'not_supported']
    if not usable:
        return None
    gain = lambda c: (c.get('historical') or {}).get('training_difference')          # noqa: E731
    best = sorted(usable, key=lambda c: (order[c['status']], gain(c) if gain(c) is not None else 0))[0]
    if not (margin and level and gain(best) is not None):
        return best
    tol = margin * level
    tied = [c for c in usable if c['status'] == best['status'] and gain(c) is not None and gain(c) - gain(best) <= tol]
    chosen = sorted(tied, key=lambda c: (simplicity(c), gain(c)))[0]
    if len(tied) > 1:
        chosen = dict(chosen, tie=dict(margin=margin, level=level, tolerance=tol, best=best['method'], best_gain=gain(best),
                                       tied=[dict(method=c['method'], family=c['family'], gain=gain(c), simplicity=simplicity(c)) for c in tied]))
    return chosen


def reference_level(cycle, target, score):
    """The published approach's own historical score for a target (training years, All Ethiopia): the MVS ensemble's CRPS or
    the published probabilities' RPS, from the Phase 2 distribution benchmark (the same folds and region as every family)."""
    d = read(f'outputs/probability_calibration/{cycle}/distribution/benchmark.json')
    try:
        m = d['targets'][target]['methods']['mvs_ensemble' if score == 'crps' else 'incumbent']['training'][d.get('primary_region', 'ethiopia')]
        return float(m[score])
    except (TypeError, KeyError):
        return None


def why(sel, product, target, ref_label, cands, unit):
    if sel is None:
        rejected = [c for c in cands if c['status'] == 'not_supported']
        base = f'No method is confirmed better than {ref_label} for {target} on the historical evidence'
        return base + (f'; {len(rejected)} confirmed method(s) were worse over the validation seasons.' if rejected else '.')
    h, v = sel.get('historical') or {}, sel.get('validation')
    txt = (f"{sel['label']} ({FAMILY_LABEL[sel['family']].lower()}) is confirmed better than {ref_label} for {target}: {unit} difference "
           f"{h.get('training_difference', float('nan')):+.4g} over the training years ({CORR_NAME.get(h.get('correction', 'holm'), 'Holm')} p {h.get('p_adjusted', h.get('holm_p', float('nan'))):.3g}; "
           f"{h.get('years_better', '?')} of {h.get('years', '?')} years better), {h.get('test_difference', float('nan')):+.4g} over the test years.")
    if v and v.get('seasons') and v.get('mean_difference') is not None:
        txt += f" Independent validation: {len(v['seasons'])} of {v['required']} season(s), mean difference {v['mean_difference']:+.4g}."
    elif v:
        txt += f" Independent validation: 0 of {v.get('required', 3)} seasons scored so far."
    else:
        txt += ' No independent validation season yet: a shadow forecast is needed before it can be recommended.'
    if sel.get('tie'):
        tie = sel['tie']
        tied = ', '.join(x['method'] for x in tie['tied'] if x['method'] != sel['method'])
        txt += (f" Tied within {100 * tie['margin']:g}% of the published score ({tie['tolerance']:.3g} {unit}) with {tied}: the simplest "
                f"is selected (practical tie rule; the largest gain was {tie['best']}).")
    others = [c for c in cands if (c['method'], c['family']) != (sel['method'], sel['family']) and c['status'] != 'not_supported']
    if others:
        txt += ' Also confirmed (one change at a time): ' + '; '.join(f"{c['label']} ({STAGE[c['family']]})" for c in others) + '.'
    return txt


def main():
    rule = read(RULE)
    global CORRECTION
    CORRECTION = rule.get('multiple_testing', 'holm')
    minimum = rule['validation']['minimum_seasons']
    recs = {c['name']: c for c in (read('outputs/bias_correction_benchmark/recommendations.json') or {}).get('cycles', [])}
    cycles = []
    for cy in CYCLES:
        base = f'outputs/probability_calibration/{cy}'
        p1, p2b = read(f'{base}/benchmark.json'), read(f'{base}/phase2_binary/benchmark.json')
        d2, d3 = (accept_results.read_accepted(f, cy) for f in ('distribution', 'phase3'))   # accepted results only
        # neural network (docs/54), accepted results only (scripts/accept_results.py): its decision models; the second stage
        # (SST inputs, neural correction of EMOS); one network for the months of the cycle
        dn, dx, dp = (accept_results.read_accepted(f, cy) for f in ('neural', 'neural_ext', 'neural_pooled'))
        dp2, dall, dst = (accept_results.read_accepted(f, cy) for f in ('neural_pooled2', 'neural_all', 'stacking'))
        ld = read(f'outputs/leung_dirichlet/{cy}/benchmark.json')
        mos = read(f'outputs/mos/{cy}/benchmark.json')
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
                for fam, d in (('distribution_phase2', d2), ('distribution_phase3', d3), ('distribution_neural', dn),
                               ('distribution_neural_ext', dx), ('distribution_neural_pooled', dp),
                               ('distribution_neural_pooled2', dp2), ('distribution_neural_all', dall), ('distribution_stacking', dst)):
                    if d:
                        cands += confirmed(d, fam, t, score, d['models'], lambda k, d=d: d['registry'][k]['name'],
                                           reference='incumbent' if score == 'rps' else 'mvs_ensemble')
                if ld:
                    # one method: the whole calibration for probabilities, its corrected amounts for amounts
                    key = 'ld_full' if score == 'rps' else 'leung_affine'
                    cands += confirmed(ld, 'leung_dirichlet', t, score, [key] if score in ld['tests'].get(key, {}) else [],
                                       lambda k: ldc.NAME, reference='incumbent' if score == 'rps' else 'mvs_ensemble')
                if mos:                                                  # statistical downscaling: CCA and PCR, both products
                    cands += confirmed(mos, 'mos', t, score, [k for k in mos['methods'] if score in mos['tests'].get(k, {})],
                                       lambda k: mos['labels'][k], reference='incumbent' if score == 'rps' else 'mvs_ensemble')
                for c in cands:
                    if c['family'].startswith('distribution'):          # amounts and, since drn-all-v1, probabilities
                        c['validation'] = shadow_validation(cy, c['method'], t, minimum, score)
                    if c['family'] == 'leung_dirichlet':
                        c['validation'] = leung_dirichlet_validation(ld, c['method'], t, score, minimum)
                    if c['family'] == 'mos':                                # the benchmark's forecast year and the shadow seasons
                        c['validation'] = mos_validation(cy, mos, c['method'], t, score, minimum)
                    c['status'] = status_of(c, minimum)
                margin = (rule.get('tie_rule') or {}).get('margin')
                sel = select(cands, reference_level(cy, t, score) if margin else None, margin)
                ref = spec['reference']['label']
                out['targets'][t][product] = dict(
                    product=spec['label'], reference=ref, status=sel['status'] if sel else 'keep',
                    selected=dict(family=sel['family'], family_label=FAMILY_LABEL[sel['family']], stage=STAGE[sel['family']], method=sel['method'],
                                  label=sel['label']) if sel else dict(family='published', label=ref, stage=None, method=None),
                    historical=sel.get('historical') if sel else None, validation=sel.get('validation') if sel else None,
                    alternatives=[dict(family=c['family'], family_label=FAMILY_LABEL[c['family']], method=c['method'], label=c['label'], status=c['status'],
                                       historical=c.get('historical')) for c in cands if not sel or c['method'] != sel['method'] or c['family'] != sel['family']],
                    tie=sel.get('tie') if sel else None,
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
