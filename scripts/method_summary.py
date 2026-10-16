"""Which bias-correction and probability-calibration methods are better than the published approach, across every season and
target, from the historical benchmarks and the independent validation seasons (docs/50, section "Summary across seasons").

For every method and product (tercile probabilities: RPS against the published MVS + climatology blend; rainfall amounts:
CRPS against the MVS-corrected ensemble), over all targets of all seasons with a benchmark:
  confirmed     targets where the benchmark confirms it better (Holm p < 0.05 within its family, not worse over the test years)
  training      targets where it is better on average over 1993-2016 (leave one year out), whatever the significance
  test          targets where it is better on average over the test years (2017 onward)
  validation    independent seasons scored after the benchmark (forecast years with CHIRPS): seasons better / scored
Counts are comparable across targets; the differences themselves are in each benchmark.

  python scripts/method_summary.py      ->  outputs/method_selection/summary.json and summary.md
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import leung_dirichlet as ldc

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/method_selection'
CYCLES = ['jan_fmam', 'feb_fmam', 'may_jjas', 'sep_ondj']
SEASON = dict(jan_fmam='FMAM (Jan)', feb_fmam='FMAM (Feb)', may_jjas='JJAS (May)', sep_ondj='ONDJ (Sep)')
REGION = 'ethiopia'
PRODUCTS = dict(probabilities='rps', amounts='crps')
LD_LABEL = dict(ldc.SHORT, ld_full='Leung–Dirichlet as uploaded (Leung + counts + Dirichlet)',
                iad_on_mvs='MVS + Dirichlet (the Dirichlet alone)', leung_blend='Leung + published blend (Leung alone)')


def read(p):
    p = ROOT / p
    return json.loads(p.read_text(encoding='utf-8')) if p.is_file() else None


def row(store, family, method, label, product):
    key = (family, method, product)
    return store.setdefault(key, dict(family=family, method=method, label=label, product=product, targets=0, confirmed=[],
                                      training_better=0, test_better=0, test_scored=0, validation_better=0, validation_scored=0,
                                      seasons=set()))


def add_test(r, cycle, target, t):
    """One target's test record (paired_summary for training and test, and the decision)."""
    r['targets'] += 1
    r['seasons'].add(cycle)
    if t['decision']['confirmed']:
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
        for m in [m for m in conf['family'] if m != ref]:
            for product, sc in PRODUCTS.items():
                r = row(store, 'Bias correction', m, label(m), product)
                for target, t in conf['tests'][m][sc].items():
                    add_test(r, cy, target, t)
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
                for m in [m for m in d['methods'] if m != d['incumbent']]:
                    r = row(store, family, m, d['registry'][m]['name'], 'probabilities')
                    for target, t in d['tests'][m]['rps'].items():
                        add_test(r, cy, target, t)
        for rel, family in (('distribution/benchmark.json', 'Distribution model (Phase 2)'), ('phase3/benchmark.json', 'Distribution model (Phase 3)')):
            d = read(f'{base}/{rel}')
            if not d:
                continue
            for m in d['models']:
                for product, sc in PRODUCTS.items():
                    if sc not in d['tests'].get(m, {}):
                        continue
                    r = row(store, family, m, d['registry'][m]['name'], product)
                    for target, t in d['tests'][m][sc].items():
                        add_test(r, cy, target, t)
                        for f in sorted((ROOT / base / 'amount_shadow').glob(f'*/{m}__{target}.json')):    # shadow seasons
                            s = (read(f).get('scores') or {}).get(REGION, {}) if read(f).get('observed') else {}
                            if product == 'probabilities':
                                add_validation(r, s.get('shadow', {}).get('rps'), s.get('published', {}).get('rps'))
                            else:
                                add_validation(r, s.get('shadow', {}).get('crps'), s.get('mvs_ensemble', {}).get('crps'))
        g = read(f'outputs/leung_dirichlet/{cy}/benchmark.json')
        if g:
            for m in g['methods']:
                for product, sc in PRODUCTS.items():
                    if sc not in g['tests'].get(m, {}):
                        continue
                    r = row(store, 'Leung–Dirichlet (docs/51)', m, LD_LABEL.get(m, m), product)
                    for target, t in g['tests'][m][sc].items():
                        add_test(r, cy, target, t)
                        v = (g.get('validation') or {}).get(target)
                        if v:
                            ref = 'incumbent' if sc == 'rps' else 'mvs_ensemble'
                            add_validation(r, v[sc].get(m), v[sc].get(ref))


def table(rows, product):
    rows = sorted([r for r in rows if r['product'] == product],
                  key=lambda r: (-len(r['confirmed']), -r['training_better'] / max(r['targets'], 1), -r['test_better'] / max(r['test_scored'], 1)))
    ref = 'MVS + climatology blend (RPS)' if product == 'probabilities' else 'MVS-corrected ensemble (CRPS)'
    lines = [f'| Method | Family | Seasons | Confirmed better | Better 1993–2016 | Better 2017+ | Better in validation (2026) |',
             '| --- | --- | --- | --- | --- | --- | --- |']
    for r in rows:
        conf = f"**{len(r['confirmed'])}** ({', '.join(r['confirmed'])})" if r['confirmed'] else '0'
        val = f"{r['validation_better']} of {r['validation_scored']}" if r['validation_scored'] else '—'
        lines.append(f"| {r['label']} | {r['family']} | {len(r['seasons'])} | {conf} | {r['training_better']} of {r['targets']} | "
                     f"{r['test_better']} of {r['test_scored']} | {val} |")
    return f'Reference: {ref}.\n\n' + '\n'.join(lines)


def main():
    store = {}
    bias(store)
    probability(store)
    rows = [dict(r, seasons=sorted(r['seasons'])) for r in store.values()]
    data = dict(created_utc=datetime.now(timezone.utc).isoformat(), region=REGION, protocol=__doc__.strip(), rows=rows)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'summary.json').write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    md = ['# Methods against the published approach, all seasons', '',
          f'Generated {data["created_utc"][:10]} by scripts/method_summary.py (region: All Ethiopia). Counts are targets '
          '(5 per season: the months and the season). Validation: targets of the independent seasons scored after the benchmark '
          '(2026 so far: FMAM from January and February, JJAS from May; ONDJ not yet observed).', '',
          '## Tercile probabilities', '', table(rows, 'probabilities'), '', '## Rainfall amounts', '', table(rows, 'amounts'), '']
    (OUT / 'summary.md').write_text('\n'.join(md), encoding='utf-8')
    print('\n'.join(md))


if __name__ == '__main__':
    main()
