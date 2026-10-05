"""Review existing nested historical predictions, without fitting or choosing weights."""
import argparse
import csv
import sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from followup_common import *
from verify2026_outputs import staged_output


def annual_rows(report, domain):
    result = []
    for row in report['years']:
        d = row['domains'][domain]
        if not d['probability']:
            continue
        metrics = {m: d['probability'][m] for m in METHODS}
        for v in metrics.values():
            if not np.isfinite([v['rps'], v['log_loss'], *v['brier_by_category']]).all():
                raise ValueError('Non-finite historical probability score')
            if not np.isclose(v['rps'], v['brier_by_category'][0] + v['brier_by_category'][2], atol=1e-10, rtol=0):
                raise ValueError('Historical RPS/Brier identity failed')
            if v['cells'] != d['probability_cells']:
                raise ValueError('Historical methods have different evaluation support')
        am = d['amount']
        anomaly = -float(am['climatology']['bias_mm']) if am else None
        state = 'unknown' if anomaly is None else ('below_mean' if anomaly < -1e-6 else ('above_mean' if anomaly > 1e-6 else 'at_mean'))
        weight = next(w['shared'] for w in report['weights'] if w['target_year'] == row['year'])
        result.append({'year': row['year'], 'training_years': row['training_years'],
                       'observed_area_mean_anomaly_mm': anomaly, 'year_group': state,
                       'probability_cells': d['probability_cells'], 'amount_cells': d['amount_cells'],
                       'probability_country_area_fraction': d['probability_country_area_fraction'],
                       'amount_country_area_fraction': d['amount_country_area_fraction'],
                       'shared_climatology_weight': weight, 'probability': metrics, 'amount': am,
                       'blend_minus_smooth_rps': metrics['shared_blend']['rps'] - metrics['smooth']['rps']})
    return result


def summarize(rows):
    if not rows:
        return {'years': [], 'probability': {}, 'amount': {}, 'blend_minus_smooth': paired_summary([])}
    p = {m: {k: np.mean([r['probability'][m][k] for r in rows], axis=0).tolist()
             for k in ['rps', 'log_loss', 'brier_by_category']} for m in METHODS}
    for v in p.values():
        v['rpss'] = skill(v['rps'], p['climatology']['rps'])
        v['bss_by_category'] = [skill(x, y) for x, y in zip(v['brier_by_category'], p['climatology']['brier_by_category'])]
    ar = [r for r in rows if r['amount']]
    am = {}
    if ar:
        for m in ['raw', 'corrected', 'climatology']:
            am[m] = {k: float(np.mean([r['amount'][m][k] for r in ar])) for k in ['crps_mm', 'bias_mm', 'mse_mm2']}
            am[m]['rmse_mm'] = float(np.sqrt(am[m]['mse_mm2']))
        for v in am.values():
            v['crpss'] = skill(v['crps_mm'], am['climatology']['crps_mm'])
    return {'years': [r['year'] for r in rows], 'probability': p, 'amount': am,
            'mean_probability_country_area_fraction': float(np.mean([r['probability_country_area_fraction'] for r in rows])),
            'blend_minus_smooth': paired_summary([r['blend_minus_smooth_rps'] for r in rows])}


def validate_report(report, target, mode):
    expected = list(range(1993, 2017)) if mode == 'training' else list(range(2017, 2026))
    if report['target'] != target or report['mode'] != mode or report['evaluation_years'] != expected:
        raise ValueError('Historical period/target mismatch')
    if [r['year'] for r in report['years']] != expected:
        raise ValueError('Historical annual rows are missing, duplicated or out of order')
    if [w['target_year'] for w in report['weights']] != expected:
        raise ValueError('Missing or duplicated shared-weight records')
    for row in report['years']:
        train = [y for y in range(1993, 2017) if y != row['year']]
        if row['training_years'] != train:
            raise ValueError('Held-out year leakage or unexpected training baseline')
    # Reproduce the previously reported equal-year means before making new summaries.
    for domain in report['equal_year_summary']:
        rows = annual_rows(report, domain)
        if rows:
            actual = summarize(rows)['probability']
            for m in METHODS:
                for k in ['rps', 'log_loss', 'brier_by_category']:
                    if not np.allclose(actual[m][k], report['equal_year_summary'][domain]['probability'][m][k], atol=1e-10, rtol=0):
                        raise ValueError('Annual scores do not reproduce historical summary')


def review_evidence(evidence, targets, modes):
    reviews = []
    for target in targets:
        for mode in modes:
            found = [e for e in evidence['experiments'] if (e['method'], e['target'], e['mode']) == (METHOD, target, mode)]
            if len(found) != 1:
                raise ValueError(f'Expected one {METHOD} {target} {mode} record. Re-run collect_regime_experiments.py and pass --evidence outputs/all_regime_experiments.json')
            report = found[0]['report']
            validate_report(report, target, mode)
            domains = {}
            for domain in report['equal_year_summary']:
                rows = annual_rows(report, domain)
                groups = {'all': summarize(rows)}
                for group in ['below_mean', 'above_mean', 'at_mean', 'unknown']:
                    groups[group] = summarize([r for r in rows if r['year_group'] == group])
                domains[domain] = {'annual': rows, 'groups': groups}
            reviews.append({'target': target, 'mode': mode, 'domains': domains})
    return {'created_utc': now(), 'classification_method': METHOD, 'reviews': reviews,
            'selected_forecast_changed': False,
            'group_definition': 'Within each domain/year, observed area-mean anomaly equals minus the reported climatology mean error, using that fold\'s amount support and baseline. Negative = below_mean; positive = above_mean. These are NOT rainfall tercile categories or nationally declared drought years. This outcome-based split is descriptive, never a forecast-time selector.',
            'evaluation': 'Training 1993-2016: existing nested leave-one-year-out fits. Operational 2017-2025: existing fits fixed on 1993-2016, repeatedly inspected and exploratory. Neither is a refit on 1993-2025. Preserve 2026 separately.',
            'regimes': 'Historical domains use training-fold-only classification. R0-R3 are climatological rules, not administrative regions or independently validated official EMI zones. seasonally_relevant is the original threshold-only domain, not the cleaned GitHub R1+R2 mask.',
            'weighting': 'Equal years; area weights within each year/domain. Amount and probability supports differ. Regime labels/support may vary across folds.',
            'decision': 'No automatic winner, new weights or adoption. Negative blend-minus-smooth means blending helps. Conditional groups and bootstrap intervals are descriptive; many comparisons are being inspected.'}


def write_outputs(result, out):
    write(out / 'historical_blend_review.json', result)
    with (out / 'annual_blend_scores.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['target', 'mode', 'domain', 'year', 'year_group', 'observed_anomaly_mm', 'probability_cells', 'country_area_fraction', 'climatology_weight', 'smooth_RPS', 'shared_RPS', 'climatology_RPS', 'shared_minus_smooth_RPS'])
        for r in result['reviews']:
            for domain, d in r['domains'].items():
                for row in d['annual']:
                    writer.writerow([r['target'], r['mode'], domain, row['year'], row['year_group'], row['observed_area_mean_anomaly_mm'], row['probability_cells'], row['probability_country_area_fraction'], row['shared_climatology_weight'], *[row['probability'][m]['rps'] for m in ['smooth', 'shared_blend', 'climatology']], row['blend_minus_smooth_rps']])
    lines = ['# Historical blend review', '', result['evaluation'], '', result['group_definition'], '',
             'Lower RPS is better. Negative shared-minus-smooth favors blending. Scores below use the country domain.', '',
             '| Target | Period | Group | Years | Smooth RPS | Shared RPS | Difference |',
             '|---|---|---|---:|---:|---:|---:|']
    for r in result['reviews']:
        for group in ['all', 'below_mean', 'above_mean']:
            g = r['domains']['all_country']['groups'][group]
            if g['years']:
                p = g['probability']
                lines.append(f"| {r['target']} | {r['mode']} | {group} | {len(g['years'])} | {p['smooth']['rps']:.5f} | {p['shared_blend']['rps']:.5f} | {g['blend_minus_smooth']['mean']:+.5f} |")
    lines += ['', 'See JSON for domain-specific metrics, category Brier scores, log loss, amount scores, year lists, coverage and descriptive intervals.', '', result['regimes'], '', result['decision']]
    (out / 'HISTORICAL_BLEND_REVIEW.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    fig, axes = plt.subplots(len(result['reviews']), 1, figsize=(11, 2.5 * len(result['reviews'])), squeeze=False, layout='constrained')
    for ax, r in zip(axes.flat, result['reviews']):
        rows = r['domains']['all_country']['annual']
        ax.bar([v['year'] for v in rows], [v['blend_minus_smooth_rps'] for v in rows], color=['#b77625' if v['year_group'] == 'below_mean' else '#278d86' for v in rows])
        ax.axhline(0, color='black', lw=.8)
        ax.set(title=f"{r['target']} | {r['mode']} | brown: below-mean year; teal: above-mean year", ylabel='Shared − smooth RPS', xlabel='Year')
    fig.savefig(out / 'annual_blend_difference.png', dpi=140)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--evidence', default='evidence/followup_all_regime_experiments.json')
    ap.add_argument('--targets', nargs='+', choices=TARGETS, default=TARGETS)
    ap.add_argument('--modes', nargs='+', choices=['training', 'operational'], default=['training', 'operational'])
    ap.add_argument('--verification-root', default='outputs/verification_2026')
    ap.add_argument('--output', default='outputs/verification_followup/historical')
    ap.add_argument('--with-fields', action='store_true', help='Also check original NetCDF predictions and make descriptive reliability plots.')
    ap.add_argument('--input-root', default='outputs/regime_calibration_github')
    ap.add_argument('--regenerate', action='store_true')
    a = ap.parse_args()
    try:
        root, out, evidence = path(a.verification_root), path(a.output), path(a.evidence)
        protect_output(out, [root, evidence, path(a.input_root)])
        snapshot = freeze_snapshot(root)
        result = review_evidence(read(evidence), list(dict.fromkeys(a.targets)), list(dict.fromkeys(a.modes)))
        result.update(source_sha256=sha(evidence), frozen_forecasts=snapshot)
        with staged_output(out, a.regenerate) as stage:
            if a.with_fields:
                from followup_reliability import review_fields
                result['field_diagnostics'] = review_fields(result, path(a.input_root), stage)
            unchanged(root, snapshot)
            write_outputs(result, stage)
        print('Historical review ready:', out, flush=True)
    except (ValueError, KeyError, OSError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    main()
