"""Stratify cycle-year verification by the fixed descriptive Ethiopian climate regimes (cycle.py)."""
import argparse
import csv
import sys
import numpy as np
import xarray as xr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from followup_common import *
from verify2026_outputs import staged_output
from verify2026_common import check_forecast
from cycle import CYCLE, YEAR, REF, REF_DASH, REF_YEARS, MEMBERS, REGIME, REGIME_YEARS, OVERLAP_YEAR, EVALUATION_STUDY

from cycle import SEASON, DOMAIN_VIEW, resolve
PROB_METHODS = ['raw_observed_thresholds', 'corrected_member_counts', 'corrected_smoothed', 'shared_blend', 'climatology']


def make_domains(mask, reference):
    same_grid(mask, reference)
    if mask.attrs.get('method') != METHOD or read_years(mask.attrs.get('training_years', '[]')) != REGIME_YEARS:
        raise ValueError(f'Use the corrected GitHub reconciliation mask fitted on {REGIME}, not a different classification or baseline.')
    if not np.array_equal(mask.region_mask.values, reference.country_mask.values):
        raise ValueError('Regime and verification country masks differ')
    country = reference.country_mask.values == 1
    codes = mask.github_regime_cleaned.transpose('lat', 'lon').values
    if not np.isin(codes[country], [-1, 0, 1, 2, 3, 4]).all():
        raise ValueError('Unexpected regime code inside country')
    if SEASON == 'JJAS':
        rainfall = mask.github_jjas_r12_rainfall_cleaned.transpose('lat', 'lon').values
        if not np.isin(rainfall, [0, 1]).all():
            raise ValueError('JJAS rainfall mask must be binary')
        if np.any((rainfall == 1) & (~country | ~np.isin(codes, [1, 2]))):
            raise ValueError('Cleaned JJAS R1/R2 mask is inconsistent with cleaned regime codes')
    else:
        rainfall = season_domain(reference)
    domains = {'all_country': country}
    domains.update({'regime_' + str(k): country & (codes == k) for k in [-1, 0, 1, 2, 3, 4]})
    domains[DOMAIN_VIEW] = country & (rainfall == 1)
    domains['outside_' + DOMAIN_VIEW] = country & (rainfall == 0)
    return domains


def season_domain(reference):
    """Season rainfall domain of a non-JJAS cycle (build_season_domain.py --method regime)."""
    p = resolve(CYCLE.raw['season_domain_mask'])
    with xr.open_dataset(p) as ds:
        m = ds.load()
    same_grid(m, reference)
    if m.attrs.get('season') != SEASON:
        raise ValueError(f'Season domain mask {p} is not for {SEASON}')
    return (m.season_domain.transpose('lat', 'lon').values == 1).astype(int)


def domain_label():
    if SEASON == 'JJAS':
        return 'JJAS R1+R2 domain'
    with xr.open_dataset(resolve(CYCLE.raw['season_domain_mask'])) as ds:
        return ds.attrs.get('view_label', f'{SEASON} rainfall domain')


def read_years(value):
    import json
    return json.loads(value)


def summarize_domain(d, domain):
    w = area(d)
    country = d.country_mask.values == 1
    av = domain & (d.amount_support.values == 1)
    pv = domain & (d.probability_support.values == 1)
    if np.any(pv & ~av):
        raise ValueError('Probability support exceeds amount support')
    denom = float(w[domain].sum())
    def avg(z, support):
        z = np.asarray(z, float)
        if not np.isfinite(z[support]).all():
            raise ValueError('Missing score on declared verification support')
        return float(np.average(z[support], weights=w[support]))
    result = {'domain_cells': int(domain.sum()), 'domain_country_area_percent': float(100 * denom / w[country].sum()),
              'amount_cells': int(av.sum()), 'probability_cells': int(pv.sum()),
              'amount_domain_area_percent': float(100 * w[av].sum() / denom) if denom else None,
              'probability_domain_area_percent': float(100 * w[pv].sum() / denom) if denom else None,
              'amount_country_area_percent': float(100 * w[av].sum() / w[country].sum()),
              'probability_country_area_percent': float(100 * w[pv].sum() / w[country].sum()),
              'amount': {}, 'probability': {}, 'observed_category_area_fractions': None}
    if av.any():
        for method in ['raw', 'corrected', 'climatology']:
            error = -d.observed_anomaly_mm.values if method == 'climatology' else d[method + '_error_mm'].values
            result['amount'][method] = {'bias_mm': avg(error, av), 'mae_mm': avg(np.abs(error), av),
                                         'rmse_mm': float(np.sqrt(avg(error ** 2, av))),
                                         'crps_mm': avg(d[method + '_crps_mm'].values, av)}
        for v in result['amount'].values():
            v['crpss'] = skill(v['crps_mm'], result['amount']['climatology']['crps_mm'])
        result['observed_mean_mm'] = avg(d.observed_total_mm.values, av)
        result['corrected_mean_mm'] = avg(d.corrected_mean_mm.values, av)
        result['observed_mean_anomaly_mm'] = avg(d.observed_anomaly_mm.values, av)
        result['forecast_mean_anomaly_mm'] = avg(d.corrected_mean_anomaly_mm.values, av)
    if pv.any():
        y = d.observed_category.values
        if not np.isin(y[pv], [0, 1, 2]).all():
            raise ValueError('Invalid observed verification category')
        result['observed_category_area_fractions'] = [avg(y == k, pv) for k in range(3)]
        for method in PROB_METHODS:
            bs = d[method + '_brier'].transpose('lat', 'lon', 'category').values
            result['probability'][method] = {'rps': avg(d[method + '_rps'].values, pv),
                                              'brier_by_category': [avg(bs[..., k], pv) for k in range(3)],
                                              'log_loss': avg(d[method + '_log_loss'].values, pv)}
        for v in result['probability'].values():
            ref = result['probability']['climatology']
            v['rpss'] = skill(v['rps'], ref['rps'])
            v['bss_by_category'] = [skill(a, b) for a, b in zip(v['brier_by_category'], ref['brier_by_category'])]
        result['shared_mean_probabilities'] = [avg(d.shared_blend_probability.values[..., k], pv) for k in range(3)]
        result['blend_minus_smoothed_rps'] = result['probability']['shared_blend']['rps'] - result['probability']['corrected_smoothed']['rps']
    return result


def reproduce_country(actual, expected):
    for family in ['amount', 'probability']:
        for method, metrics in actual[family].items():
            for key, value in metrics.items():
                other = expected[family][method][key]
                if (value is None) != (other is None) or (value is not None and not np.allclose(value, other, atol=2e-6, rtol=0)):
                    raise ValueError('Country scores do not reproduce Step 30: ' + family + '/' + method + '/' + key)
    for key in ['amount_cells', 'probability_cells', 'amount_country_area_percent', 'probability_country_area_percent', 'observed_category_area_fractions']:
        if not np.allclose(actual[key], expected[key], atol=2e-6, rtol=0):
            raise ValueError('Country coverage/category mismatch: ' + key)


def inspect_source(root, target, snapshot):
    folder = root / 'results' / target
    rp, dp = folder / 'verification_report.json', folder / 'verification_fields.nc'
    fp = root / f'frozen_forecasts/{CYCLE.tag}_{target}/forecast_{YEAR}.nc'
    op = root / f'observations/{target}/chirps_{YEAR}_common.nc'
    report = read(rp)
    if report['target'] != target or report['year'] != YEAR or report['forecast_sha256'] != snapshot['forecast_sha256'][target] or report['observations_sha256'] != sha(op):
        raise ValueError('Verification report belongs to different inputs')
    with xr.open_dataset(dp) as ds:
        d = ds.load()
    with xr.open_dataset(fp) as ds:
        f = ds.load()
    with xr.open_dataset(op) as ds:
        obs = ds.load()
    same_grid(d, f)
    same_grid(d, obs)
    check_forecast(f, target)
    if d.attrs.get('target') != target or int(d.attrs.get('evaluation_year', -1)) != YEAR or d.attrs.get('reference_years') != f'{REF}':
        raise ValueError('Unexpected verification field metadata')
    if list(map(str, d.category.values)) != CATS or not np.array_equal(d.country_mask, f.region_mask):
        raise ValueError('Verification country mask/category order changed')
    for key in ['country_mask', 'amount_support', 'probability_support']:
        if not np.isin(d[key], [0, 1]).all():
            raise ValueError('Verification masks must be binary')
    av, pv = d.amount_support.values == 1, d.probability_support.values == 1
    if np.any(av & ((f.region_mask.values != 1) | (f.amount_eligible.values != 1))) or np.any(pv & (~av | (f.probability_eligible.values != 1))):
        raise ValueError('Verification support exceeds frozen eligibility')
    checks = [(d.observed_total_mm.values[av], obs.precip_season.values[av]),
              (d.corrected_mean_mm.values[av], f.corrected_ensemble_mean.values[av]),
              (d.observed_anomaly_mm.values[av], (obs.precip_season - f.observed_training_mean).values[av]),
              (d.corrected_mean_anomaly_mm.values[av], f.corrected_mean_anomaly.values[av]),
              (d.corrected_error_mm.values[av], (f.corrected_ensemble_mean - obs.precip_season).values[av]),
              (d.shared_blend_probability.values[pv], f.blend_probability.values[pv])]
    for a, b in checks:
        if not np.allclose(a, b, atol=1e-8, rtol=0):
            raise ValueError('Verification fields differ from frozen forecast / prepared observations')
    y = np.where(obs.precip_season.values < f.q1.values, 0, np.where(obs.precip_season.values > f.q2.values, 2, 1))
    if not np.array_equal(d.observed_category.values[pv], y[pv]):
        raise ValueError('Observed categories differ from frozen thresholds')
    reproduce_country(summarize_domain(d, d.country_mask.values == 1), report)
    return d, {'verification_fields_sha256': sha(dp), 'verification_report_sha256': sha(rp),
               'forecast_sha256': sha(fp), 'observations_sha256': sha(op), 'country_reproduction_passed': True}


def write_outputs(result, out):
    write(out / 'regime_verification_summary.json', result)
    lines = [f'# {YEAR} verification by climatological regime', '',
             'Single-year descriptive assessment. Positive RPSS/CRPSS means improvement over climatology on the same domain and support. Empty domains have no score.', '',
             '| Target | Domain | Probability cells | Probability coverage within domain | Shared RPSS | Smooth RPSS | Corrected CRPSS |',
             '|---|---|---:|---:|---:|---:|---:|']
    def fmt(x):
        return '—' if x is None else f'{x:.3f}'
    for record in result['results']:
        for domain, row in record['domains'].items():
            if row['domain_cells'] == 0:
                continue
            p, a = row['probability'], row['amount']
            lines.append(f"| {record['target']} | {domain} | {row['probability_cells']} | {fmt(row['probability_domain_area_percent'])}% | {fmt(p.get('shared_blend', {}).get('rpss'))} | {fmt(p.get('corrected_smoothed', {}).get('rpss'))} | {fmt(a.get('corrected', {}).get('crpss'))} |")
    lines += ['', result['mask_note'], '', result['limitations']]
    (out / 'REGIME_VERIFICATION.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    with (out / 'regime_metrics.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['target', 'domain', 'family', 'method', 'metric', 'value'])
        for r in result['results']:
            for domain, row in r['domains'].items():
                for family in ['amount', 'probability']:
                    for method, metrics in row[family].items():
                        for key, value in metrics.items():
                            if isinstance(value, list):
                                for cat, v in zip(CATS, value):
                                    writer.writerow([r['target'], domain, family, method, key + '_' + cat, v])
                            else:
                                writer.writerow([r['target'], domain, family, method, key, value])
    fig, axes = plt.subplots(len(result['results']), 1, figsize=(11, 3.3 * len(result['results'])), squeeze=False, layout='constrained')
    for ax, r in zip(axes.flat, result['results']):
        domains = [(key, r['domains'][key]) for key in ['all_country', 'regime_0', 'regime_1', 'regime_2', 'regime_3', DOMAIN_VIEW] if r['domains'][key]['probability']]
        x = np.arange(len(domains))
        for offset, method, color in [(-.18, 'corrected_smoothed', '#d18a24'), (.18, 'shared_blend', '#24629b')]:
            vals = [v['probability'][method]['rpss'] for _, v in domains]
            ax.bar(x + offset, [np.nan if v is None else v for v in vals], .36, label=method, color=color)
        ax.axhline(0, color='black', lw=.8)
        ax.set(xticks=x, xticklabels=[k.replace('regime_', 'R').replace(DOMAIN_VIEW, domain_label()) for k, _ in domains], ylabel='RPSS', title=CYCLE.target_label(r['target']) + ' | positive values beat climatology')
        ax.legend(fontsize=8)
    fig.savefig(out / 'regime_probability_skill.png', dpi=150)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--targets', nargs='+', choices=TARGETS, default=list(SEASON_MONTHS))
    ap.add_argument('--verification-root', default=f'outputs/verification_{YEAR}')
    ap.add_argument('--mask', default='evidence/followup_regime_comparison_and_masks.nc')
    ap.add_argument('--output-root', default='outputs/verification_followup/regimes')
    ap.add_argument('--regenerate', action='store_true')
    a = ap.parse_args()
    try:
        targets = list(dict.fromkeys(a.targets))
        root, mp = path(a.verification_root), path(a.mask)
        out = path(a.output_root) / '_'.join(targets)
        protect_output(out, [root, mp])
        snapshot = freeze_snapshot(root)
        if not mp.is_file():
            raise ValueError('Regime reconciliation mask missing. Run compare_regime_definitions.py --regenerate, or specify --mask with its exact path.')
        with xr.open_dataset(mp) as ds:
            mask = ds.load()
        rows = []
        for target in targets:
            d, provenance = inspect_source(root, target, snapshot)
            domains = make_domains(mask, d)
            rows.append({'target': target, 'provenance': provenance, 'domains': {key: summarize_domain(d, v) for key, v in domains.items()}})
            print('Verified regime summaries:', target, flush=True)
        result = {'year': YEAR, 'created_utc': now(), 'targets': targets, 'regime_labels': LABELS, 'mask_path': str(mp),
                  'mask_sha256': sha(mp), 'classification_method': METHOD, 'frozen_forecasts': snapshot, 'results': rows,
                  'mask_note': f'Regime classification uses only CHIRPS {REGIME} and the previously defined GitHub refinement. All-country scores are retained. ' + ("JJAS R1+R2 rainfall domain" if SEASON == "JJAS" else domain_label()) + f' uses the cleaned classes and rainfall criteria; no onset gate. This mask is valid for {YEAR} stratification, not retrospective historical fitting. R1/R2/R3 are rules, not official administrative or independently validated EMI zones.',
                  'limitations': 'One year only; no reliability or significance claim. Amount/probability supports differ. Low CRPS in dry regions need not mean greater predictability. Domains overlap and are not independent. No method selection, coefficient change or forecast overwrite.'}
        unchanged(root, snapshot)
        with staged_output(out, a.regenerate) as stage:
            write_outputs(result, stage)
        print('Regime verification ready:', out, flush=True)
    except (ValueError, KeyError, OSError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    main()
