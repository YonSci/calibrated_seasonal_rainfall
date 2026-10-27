"""Which bias-correction and probability-calibration methods are better than the published approach, across every season and
target, from the historical benchmarks and the independent validation seasons (docs/50, section "Summary across seasons").

For every method and product (tercile probabilities: RPS against the published MVS + climatology blend; rainfall amounts:
CRPS against the MVS-corrected ensemble), over all targets of all seasons with a benchmark:
  confirmed     targets where it is confirmed better under the selection rule's correction (Benjamini-Hochberg since
                2026-10-17, Holm before) within its benchmark family, p < 0.05, and not worse over the test years
  training      targets where it is better on average over 1993-2016 (leave one year out), whatever the significance
  test          targets where it is better on average over the test years (2017 onward)
  validation    independent seasons scored after the benchmark (forecast years with CHIRPS): seasons better / scored
Counts are comparable across targets; the differences themselves are in each benchmark.

Further evidence from the same out-of-sample scores, no refitting (docs/50, section "More statistical power"):
  33 years      each target's 1993-2016 leave-one-year-out years joined with its 2017+ test years (fitted on 1993-2016), so
                every year 1993-2025 is scored out of sample: a paired whole-year sign-flip test over all of them
  pooled        per year, the method's skill difference from the reference ((score - reference) / climatology score) averaged
                over all its targets of all seasons; one sign-flip test over the years for the method
  adjustments   Holm (family-wise error) and Benjamini-Hochberg (false discovery rate) across every method of a product, for
                the pooled tests and for the 33-year target tests. The selection rule (docs/50) uses Benjamini-Hochberg within
                each benchmark family (decided 2026-10-17); these are sensitivity analyses.

  python scripts/method_summary.py      ->  outputs/method_selection/summary.json and summary.md
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import accept_results
import leung_dirichlet as ldc
import selection_tests as st
from significance import paired_summary, sign_flip_p, holm

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/method_selection'
CYCLES = ['jan_fmam', 'feb_fmam', 'may_jjas', 'sep_ondj']
SEASON = dict(jan_fmam='FMAM (Jan)', feb_fmam='FMAM (Feb)', may_jjas='JJAS (May)', sep_ondj='ONDJ (Sep)')
REGION = 'ethiopia'
PRODUCTS = dict(probabilities='rps', amounts='crps')
# The Leung–Dirichlet calibration counts as one method: the whole calibration for tercile probabilities and its corrected
# amounts for rainfall amounts (its stage-by-stage variants stay on its own page, docs/51).
LD_METHOD = dict(probabilities='ld_full', amounts='leung_affine')
# Plain categories for the overview, with the benchmark families they gather
CATEGORY = {'Bias correction': 'Bias correction', 'Probability stage (Phase 1)': 'Probability calibration',
            'Probability stage (Phase 2)': 'Probability calibration', 'Distribution model (Phase 2)': 'Rainfall-distribution model',
            'Distribution model (Phase 3)': 'Rainfall-distribution model', 'Two-stage calibration': 'Two-stage calibration',
            'Statistical downscaling (MOS)': 'Statistical downscaling', 'Neural network (DRN)': 'Neural network',
            'Model combination': 'Model combination'}
ALPHA = 0.05


def bh(pvalues):
    """Benjamini-Hochberg adjusted p-values (false discovery rate)."""
    keys = sorted(pvalues, key=lambda k: pvalues[k])
    m, adjusted, running = len(keys), {}, 1.0
    for i in range(m - 1, -1, -1):
        running = min(running, pvalues[keys[i]] * m / (i + 1))
        adjusted[keys[i]] = min(1.0, running)
    return adjusted


def add_series(r, cycle, target, mres, rres, sc):
    """The per-year scores of a method and its reference over both designs (training LOYO years, then test years)."""
    years, m, ref, clim, n_train = [], [], [], [], 0
    for design in ('training', 'test'):
        a, b = (mres.get(design) or {}).get(REGION), (rres.get(design) or {}).get(REGION)
        if not a or not b or sc not in a['per_year']:
            continue
        ya, yb = list(dict.fromkeys(a['years'])), list(dict.fromkeys(b['years']))    # a method scored twice a year lists it twice
        if ya != yb or len(ya) != len(a['per_year'][sc]):
            raise ValueError(f'year mismatch {cycle} {target} {design}')
        years += ya; m += a['per_year'][sc]; ref += b['per_year'][sc]; clim += a['per_year'][sc + '_clim']
        n_train = len(ya) if design == 'training' else n_train
    if years:
        r.setdefault('series', []).append(dict(cycle=cycle, target=target, years=years, m=m, ref=ref, clim=clim, n_train=n_train))


def read(p):
    p = ROOT / p
    return json.loads(p.read_text(encoding='utf-8')) if p.is_file() else None


def row(store, family, method, label, product):
    key = (family, method, product)
    return store.setdefault(key, dict(family=family, method=method, label=label, product=product, targets=0, confirmed=[],
                                      training_better=0, test_better=0, test_scored=0, validation_better=0, validation_scored=0,
                                      seasons=set()))


CORRECTION = read('config/method_selection_rule.json').get('multiple_testing', 'holm')


def decisions(tests, score, family=None):
    """The rule's decisions for one benchmark and score, {(method, target): decision}, within the benchmark's family
    (by default every method with the score except SEL, which is its own family, as in the benchmarks)."""
    family = family if family is not None else [m for m in tests if m != 'SEL' and score in tests[m]]
    return {**st.decide(tests, family, score, CORRECTION), **st.decide(tests, ['SEL'], score, CORRECTION)}


def add_test(r, cycle, target, t, decision):
    """One target's test record (paired_summary for training and test) and the rule's decision."""
    r['targets'] += 1
    r['seasons'].add(cycle)
    r.setdefault('by_target', {})[f'{SEASON[cycle]} {target}'] = dict(
        cycle=cycle, target=target, confirmed=bool(decision['confirmed']), p_adjusted=decision.get('p_adjusted'),
        years_better=t['training']['years_better'], years=t['training']['years'],
        test_better=t['test']['years_better'] if t.get('test') else None, test_years=t['test']['years'] if t.get('test') else None)
    if decision['confirmed']:
        r['confirmed'].append(f'{SEASON[cycle]} {target}')
    r['training_better'] += t['training']['mean_difference'] < 0
    if t.get('test') and t['test'].get('years'):
        r['test_scored'] += 1
        r['test_better'] += t['test']['mean_difference'] < 0


def add_validation(r, method_score, reference_score):
    if method_score is None or reference_score is None:
        return
    r['validation_scored'] += 1
    r['validation_better'] += method_score < reference_score


def bias(store):
    """Amount corrections (docs/47): the full pipeline for probabilities, the corrected ensemble for amounts."""
    for cy in CYCLES:
        conf = read(f'outputs/bias_correction_benchmark/{cy}/confirmation/confirmation.json')
        bench = read(f'outputs/bias_correction_benchmark/{cy}/benchmark.json')
        if not conf:
            continue
        ref = conf['reference']
        label = lambda m: bench['methods'].get(m, {}).get('label', m).replace(' (operational)', '')
        fam = [m for m in conf['family'] if m != ref]
        dec = {sc: decisions(conf['tests'], sc, fam) for sc in PRODUCTS.values()}
        for m in fam:
            for product, sc in PRODUCTS.items():
                r = row(store, 'Bias correction', m, label(m), product)
                for target, t in conf['tests'][m][sc].items():
                    add_test(r, cy, target, t, dec[sc][(m, target)])
                    add_series(r, cy, target, conf['targets'][target]['methods'][m], conf['targets'][target]['methods'][ref], sc)
                    for year_dir in sorted((ROOT / f'outputs/bias_correction_benchmark/{cy}/validation').glob('[0-9]*')):
                        a, b = read(year_dir / f'{m}__{target}.json'), read(year_dir / f'{ref}__{target}.json')
                        if a and b and a.get('observed') and b.get('observed'):
                            add_validation(r, a['scores'][REGION][sc], b['scores'][REGION][sc])


def probability(store):
    """Probability stage (Phases 1 and 2 binary), distribution models (Phases 2 and 3) and the Leung–Dirichlet calibration (docs/48, 51)."""
    for cy in CYCLES:
        base = f'outputs/probability_calibration/{cy}'
        for rel, family in (('benchmark.json', 'Probability stage (Phase 1)'), ('phase2_binary/benchmark.json', 'Probability stage (Phase 2)')):
            d = read(f'{base}/{rel}')
            if d:
                dec = decisions(d['tests'], 'rps')
                for m in [m for m in d['methods'] if m != d['incumbent']]:
                    r = row(store, family, m, d['registry'][m]['name'], 'probabilities')
                    for target, t in d['tests'][m]['rps'].items():
                        add_test(r, cy, target, t, dec[(m, target)])
                        add_series(r, cy, target, d['targets'][target]['methods'][m], d['targets'][target]['methods'][d['incumbent']], 'rps')
        for rel, family in (('distribution/benchmark.json', 'Distribution model (Phase 2)'), ('phase3/benchmark.json', 'Distribution model (Phase 3)'),
                            ('neural/benchmark.json', 'Neural network (DRN)'),           # neural: its decision models only (docs/54)
                            ('neural_ext/benchmark.json', 'Neural network (DRN)'), ('neural_pooled/benchmark.json', 'Neural network (DRN)'),
                            ('neural_pooled2/benchmark.json', 'Neural network (DRN)'), ('neural_all/benchmark.json', 'Neural network (DRN)'),
                            ('neural_fmam_ondj/benchmark.json', 'Neural network (DRN)'),
                            ('stacking/benchmark.json', 'Model combination')):
            fam = rel.split('/')[0]
            d = accept_results.read_accepted(fam, cy) if fam in accept_results.GATED else read(f'{base}/{rel}')   # neural: accepted only
            if not d:
                continue
            dec = {sc: decisions(d['tests'], sc) for sc in PRODUCTS.values()}
            for m in d['models']:
                for product, sc in PRODUCTS.items():
                    if sc not in d['tests'].get(m, {}):
                        continue
                    r = row(store, family, m, d['registry'][m]['name'], product)
                    for target, t in d['tests'][m][sc].items():
                        add_test(r, cy, target, t, dec[sc][(m, target)])
                        add_series(r, cy, target, d['targets'][target]['methods'][m],
                                   d['targets'][target]['methods']['incumbent' if sc == 'rps' else 'mvs_ensemble'], sc)
                        for f in sorted((ROOT / base / 'amount_shadow').glob(f'*/{m}__{target}.json')):    # shadow seasons
                            s = (read(f).get('scores') or {}).get(REGION, {}) if read(f).get('observed') else {}
                            if product == 'probabilities':
                                add_validation(r, s.get('shadow', {}).get('rps'), s.get('published', {}).get('rps'))
                            else:
                                add_validation(r, s.get('shadow', {}).get('crps'), s.get('mvs_ensemble', {}).get('crps'))
        g = read(f'outputs/leung_dirichlet/{cy}/benchmark.json')
        if g:
            for product, sc in PRODUCTS.items():
                m = LD_METHOD[product]
                if sc in g['tests'].get(m, {}):
                    r = row(store, 'Two-stage calibration', 'leung_dirichlet', ldc.NAME, product)
                    dec = decisions(g['tests'], sc)
                    for target, t in g['tests'][m][sc].items():
                        add_test(r, cy, target, t, dec[(m, target)])
                        ref = 'incumbent' if sc == 'rps' else 'mvs_ensemble'
                        add_series(r, cy, target, g['targets'][target]['methods'][m], g['targets'][target]['methods'][ref], sc)
                        v = (g.get('validation') or {}).get(target)
                        if v:
                            add_validation(r, v[sc].get(m), v[sc].get(ref))
        g = read(f'outputs/mos/{cy}/benchmark.json')                   # statistical downscaling (docs/53)
        if g:
            for m in g['methods']:
                for product, sc in PRODUCTS.items():
                    if sc not in g['tests'].get(m, {}):
                        continue
                    r = row(store, 'Statistical downscaling (MOS)', m, g['labels'][m], product)
                    ref = 'incumbent' if sc == 'rps' else 'mvs_ensemble'
                    dec = decisions(g['tests'], sc)
                    for target, t in g['tests'][m][sc].items():
                        add_test(r, cy, target, t, dec[(m, target)])
                        add_series(r, cy, target, g['targets'][target]['methods'][m], g['targets'][target]['methods'][ref], sc)
                        v = (g.get('validation') or {}).get(target)
                        if v and m in v[sc] and ref in v[sc]:
                            add_validation(r, v[sc][m], v[sc][ref])
                        for f in sorted((ROOT / f'outputs/mos/{cy}/shadow').glob(f'*/{m}__{target}.json')):   # shadow seasons
                            s = (read(f) or {}).get('scores') or {}
                            if read(f).get('observed') and sc in s and (not v or int(read(f)['forecast_year']) != v.get('year')):
                                add_validation(r, s[sc]['method'], s[sc]['published' if sc == 'rps' else 'mvs_ensemble'])


def evidence(rows):
    """33-year target tests and pooled tests per method, with Holm and Benjamini-Hochberg across the methods of a product."""
    for product in PRODUCTS:
        prod = [r for r in rows if r['product'] == product and r.get('series')]
        target_p, pooled_p = {}, {}
        for i, r in enumerate(prod):
            per_year = {}
            r['oos33'] = dict(targets=0, better=0, tests={})
            for s in r['series']:
                ps = paired_summary(s['m'], s['ref'])
                r['oos33']['targets'] += 1
                r['oos33']['better'] += ps['mean_difference'] < 0
                key = (i, f"{SEASON[s['cycle']]} {s['target']}")
                target_p[key] = ps['p_improvement']
                r['oos33']['tests'][key[1]] = dict(years=ps['years'], mean_difference=ps['mean_difference'], p=ps['p_improvement'],
                                                   years_better=ps['years_better'])
                for y, a, b, c in zip(s['years'], s['m'], s['ref'], s['clim']):
                    if c > 0:
                        per_year.setdefault(y, []).append((a - b) / c)       # negative: better than the reference
            years = sorted(per_year)
            d = np.array([np.mean(per_year[y]) for y in years])
            pooled_p[i] = sign_flip_p(d)
            r['pooled'] = dict(years=len(years), first=years[0], last=years[-1], skill_gain=float(-d.mean()),
                               years_better=int((d < 0).sum()), p=float(pooled_p[i]))
        for name, adjust in (('holm', holm), ('bh', bh)):
            a = adjust(pooled_p)
            for i, r in enumerate(prod):
                r['pooled'][f'p_{name}'] = float(a[i])
                r['pooled'][f'better_{name}'] = bool(r['pooled']['skill_gain'] > 0 and a[i] < ALPHA)
            a = adjust(target_p)
            for (i, label), p in a.items():
                t = prod[i]['oos33']['tests'][label]
                t[f'p_{name}'] = float(p)
                if t['mean_difference'] < 0 and p < ALPHA:
                    prod[i]['oos33'].setdefault(f'confirmed_{name}', []).append(label)
        for r in prod:
            r['oos33'].setdefault('confirmed_holm', [])
            r['oos33'].setdefault('confirmed_bh', [])
            r['oos33']['tests'] = {k: v for k, v in r['oos33']['tests'].items()}


def table(rows, product):
    rows = sorted([r for r in rows if r['product'] == product],
                  key=lambda r: (-len(r['confirmed']), -r['training_better'] / max(r['targets'], 1), -r['test_better'] / max(r['test_scored'], 1)))
    ref = 'MVS + climatology blend (RPS)' if product == 'probabilities' else 'MVS-corrected ensemble (CRPS)'
    lines = [f'| Method | Category | Seasons | Confirmed better | Better 1993–2016 | Better 2017+ | Better in validation (2026) |',
             '| --- | --- | --- | --- | --- | --- | --- |']
    for r in rows:
        conf = f"**{len(r['confirmed'])}** ({', '.join(r['confirmed'])})" if r['confirmed'] else '0'
        val = f"{r['validation_better']} of {r['validation_scored']}" if r['validation_scored'] else '—'
        lines.append(f"| {r['label']} | {r['category']} | {len(r['seasons'])} | {conf} | {r['training_better']} of {r['targets']} | "
                     f"{r['test_better']} of {r['test_scored']} | {val} |")
    return f'Reference: {ref}.\n\n' + '\n'.join(lines)


def main():
    store = {}
    bias(store)
    probability(store)
    evidence(list(store.values()))
    order = []                                               # the targets in cycle and season order (the method explorer's columns)
    for r in store.values():                                 # per target: skill gain against the published approach, share of climatology
        for sr in r.get('series', []):
            key = f"{SEASON[sr['cycle']]} {sr['target']}"
            g = [(ref - m) / c for m, ref, c in zip(sr['m'], sr['ref'], sr['clim']) if c]
            n = sr['n_train']
            cell = r.setdefault('by_target', {}).setdefault(key, dict(cycle=sr['cycle'], target=sr['target']))
            cell.update(gain_training=float(np.mean(g[:n])) if g[:n] else None, gain_test=float(np.mean(g[n:])) if g[n:] else None)
            if (sr['cycle'], sr['target']) not in order:
                order.append((sr['cycle'], sr['target']))
    targets = {c: cfg.get('targets', []) for c in CYCLES for cfg in [read(f'config/bias_correction/{c}.json') or {}]}
    order.sort(key=lambda ct: (CYCLES.index(ct[0]), targets[ct[0]].index(ct[1]) if ct[1] in targets[ct[0]] else 99))
    rows = [dict({k: v for k, v in r.items() if k != 'series'}, seasons=sorted(r['seasons']), category=CATEGORY[r['family']]) for r in store.values()]
    categories = {}                                          # methods per category, each counted once over both products
    for r in rows:
        categories.setdefault(r['category'], set()).add(r['method'])
    categories = {k: len(v) for k, v in sorted(categories.items(), key=lambda kv: list(CATEGORY.values()).index(kv[0]))}
    data = dict(created_utc=datetime.now(timezone.utc).isoformat(), region=REGION, protocol=__doc__.strip(),
                categories=categories, methods=sum(categories.values()), multiple_testing=CORRECTION,
                target_order=[dict(key=f'{SEASON[c]} {t}', cycle=c, season=SEASON[c], target=t) for c, t in order], rows=rows)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'summary.json').write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    md = ['# Methods against the published approach, all seasons', '',
          f'Generated {data["created_utc"][:10]} by scripts/method_summary.py (region: All Ethiopia). Counts are targets '
          '(5 per season: the months and the season). Validation: targets of the independent seasons scored after the benchmark '
          '(2026 so far: FMAM from January and February, JJAS from May; ONDJ not yet observed).', '',
          f'{data["methods"]} methods: ' + ', '.join(f'{k.lower()} {n}' for k, n in categories.items()) + '.', '',
          '## Tercile probabilities', '', table(rows, 'probabilities'), '', '## Rainfall amounts', '', table(rows, 'amounts'), '']
    (OUT / 'summary.md').write_text('\n'.join(md), encoding='utf-8')
    print('\n'.join(md))


if __name__ == '__main__':
    main()
