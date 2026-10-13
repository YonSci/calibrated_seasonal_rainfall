"""Suggest a bias-correction method for every cycle, target and product from the evidence (docs/47).

Applies the rule in config/bias_correction/recommendation_rule.json — fixed before the validation seasons are scored —
to two kinds of evidence:
  historical  the benchmark confirmation against CHIRPS (outer leave-one-year-out over the training years, full pipeline,
              Holm across every declared method and target, no harm over the test years) and its selection-aware choice;
  validation  independent seasons scored after the benchmark (bias_validation.py: <benchmark>/validation/<year>/*.json).
Statuses: keep (no candidate), candidate (confirmed; validation seasons still being collected), recommended (confirmed
and not worse over at least the minimum number of validation seasons), not_supported (worse over them).
A suggestion never changes the published forecast; it informs a decision.

  python scripts/bias_recommend.py
Output: outputs/bias_correction_benchmark/recommendations.json
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def read(p):
    return json.loads((ROOT / p).read_text(encoding='utf-8'))


def validation_seasons(folder, method, ref, target, score, region):
    """Independent seasons (forecast years) where both the method and the reference have been scored for the target."""
    out = []
    for year_dir in sorted((folder / 'validation').glob('[0-9]*')):
        fm, fr = year_dir / f'{method}__{target}.json', year_dir / f'{ref}__{target}.json'
        if fm.is_file() and fr.is_file():
            a, b = json.loads(fm.read_text(encoding='utf-8')), json.loads(fr.read_text(encoding='utf-8'))
            if a.get('observed') and b.get('observed'):
                out.append(dict(year=int(year_dir.name), method=a['scores'][region][score], reference=b['scores'][region][score]))
    return out


def recommend(bench_path, rule):
    bench = read(bench_path)
    folder = ROOT / bench['output_root']
    conf = json.loads((folder / 'confirmation/confirmation.json').read_text(encoding='utf-8'))
    ref, family = conf['reference'], conf['family']
    region = rule['validation']['region']
    minimum = rule['validation']['minimum_seasons']
    names =json.loads((folder / 'benchmark.json').read_text(encoding='utf-8'))['methods']
    label = lambda m: names.get(m, {}).get('label', m).replace(' (operational)', '')
    out = dict(benchmark=bench_path, name=bench['name'], reference=ref, reference_label=label(ref), targets={},
               confirmation_commit=conf['provenance']['commit'])
    for t in conf['targets']:
        out['targets'][t] = {}
        for product, spec in rule['products'].items():
            sc = spec['score']
            tests = conf['tests']
            cands = [m for m in family if m != ref and tests[m][sc][t]['decision']['confirmed']]
            train_mean = lambda m: float(np.mean(conf['targets'][t]['methods'][m]['training'][region]['per_year'][sc]))
            entry = dict(product=spec['label'])
            if not cands:
                entry.update(status='keep', method=ref, method_label=label(ref), alternatives=[],
                             why=f'No method is confirmed better than {label(ref)} for {t} on the historical evidence.')
            else:
                chosen = conf['targets'][t]['selection'][spec['selection']]['chosen_test']
                pick = chosen if chosen in cands else min(cands, key=train_mean)
                d = tests[pick][sc][t]
                seasons = validation_seasons(folder, pick, ref, t, sc, region)
                diff = float(np.mean([s['method'] - s['reference'] for s in seasons])) if seasons else None
                if len(seasons) >= minimum:
                    status = 'recommended' if diff <= 0 else 'not_supported'
                else:
                    status = 'candidate'
                entry.update(
                    status=status, method=pick, method_label=label(pick),
                    chosen_by=('selection-aware procedure (training years only)' if pick == chosen else 'best training score among candidates'),
                    alternatives=[dict(method=m, label=label(m), holm_p=tests[m][sc][t]['decision']['holm_p_family']) for m in cands if m != pick],
                    historical=dict(training_difference=d['training']['mean_difference'], holm_p=d['decision']['holm_p_family'],
                                    years_better=d['training']['years_better'], years=d['training']['years'],
                                    test_difference=d['test']['mean_difference'], test_years_better=d['test']['years_better'],
                                    test_years=d['test']['years']),
                    validation=dict(seasons=seasons, mean_difference=diff, required=minimum),
                    why=(f"{label(pick)} is confirmed better than {label(ref)} for {t} ({spec['unit']} difference "
                         f"{d['training']['mean_difference']:+.4g} over the training years, Holm p {d['decision']['holm_p_family']:.3g}; "
                         f"{d['test']['mean_difference']:+.4g} over the test years). Independent validation: {len(seasons)} of {minimum} "
                         f"season(s)" + (f", mean difference {diff:+.4g}" if seasons else '') + '.'))
            out['targets'][t][product] = entry
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--rule', default='config/bias_correction/recommendation_rule.json')
    a = p.parse_args()
    rule = read(a.rule)
    result = dict(created_utc=datetime.now(timezone.utc).isoformat(), rule=a.rule, rule_contents=rule,
                  cycles=[recommend(b, rule) for b in rule['benchmarks']])
    path = ROOT / 'outputs/bias_correction_benchmark/recommendations.json'
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    for c in result['cycles']:
        for t, prods in c['targets'].items():
            for prod, e in prods.items():
                if e['status'] != 'keep':
                    print(f"{c['name']:9s} {t:5s} {prod:13s} {e['status']:13s} {e['method_label']}  (validation {len(e['validation']['seasons'])}/{e['validation']['required']})")
    print('Saved:', path)


if __name__ == '__main__':
    main()
