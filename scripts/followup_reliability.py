"""Optional probability-file checks and reliability diagnostics; no fitting."""
import numpy as np
import xarray as xr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from followup_common import *


def calculate(d, expected):
    if list(map(str, d.category.values)) != CATS or d.year.values.tolist() != [r['year'] for r in expected]:
        raise ValueError('Historical categories or years differ from evidence')
    y = d.observed_category.transpose('year', 'lat', 'lon').values
    pv = d.probability_common_support.transpose('year', 'lat', 'lon').values == 1
    if not np.isin(d.probability_common_support, [0, 1]).all() or not np.isin(d.region_mask, [0, 1]).all():
        raise ValueError('Historical support masks must be binary')
    if np.any(pv & ~(d.region_mask.values == 1)):
        raise ValueError('Historical support extends outside country')
    if not np.isin(y[pv], [0, 1, 2]).all():
        raise ValueError('Invalid observed category on historical support')
    w = np.where(pv, area(d)[None, ...], 0.)
    if np.any(w.sum((1, 2)) == 0):
        raise ValueError('Historical year has empty probability support')
    w /= w.sum((1, 2), keepdims=True)
    truth = y[..., None] == np.arange(3)
    result = {'methods': {}, 'annual_observed_category_fractions':
              [{ 'year': int(year), 'fractions': [float(np.sum(w[i] * truth[i, ..., k])) for k in range(3)]}
               for i, year in enumerate(d.year.values)]}
    for method in METHODS:
        p = d[method + '_probability'].transpose('year', 'lat', 'lon', 'category').values
        if not np.isfinite(p[pv]).all() or (p[pv] < 0).any() or (p[pv] > 1).any() or not np.allclose(p[pv].sum(-1), 1, atol=1e-10, rtol=0):
            raise ValueError('Invalid historical probabilities: ' + method)
        bs = (p - truth) ** 2
        rps = np.sum(np.cumsum(p - truth, axis=-1)[..., :2] ** 2, -1)
        selected = np.take_along_axis(p, np.maximum(y, 0)[..., None], -1)[..., 0]
        ll = -np.log(np.maximum(selected, 1e-12))
        for i, row in enumerate(expected):
            scores = {'rps': float(np.sum(np.where(pv[i], rps[i], 0) * w[i])),
                      'log_loss': float(np.sum(np.where(pv[i], ll[i], 0) * w[i])),
                      'brier_by_category': np.sum(np.where(pv[i, ..., None], bs[i], 0) * w[i, ..., None], (0, 1))}
            if int(pv[i].sum()) != row['probability_cells']:
                raise ValueError('NetCDF/evidence support count mismatch')
            for k, value in scores.items():
                if not np.allclose(value, row['probability'][method][k], atol=2e-6, rtol=0):
                    raise ValueError('NetCDF does not reproduce evidence: ' + method + ' ' + k)
        reliability = {}
        for k, cat in enumerate(CATS):
            bins = []
            edges = np.linspace(0, 1, 11)
            for j in range(10):
                mask = pv & (p[..., k] >= edges[j]) & ((p[..., k] < edges[j + 1]) if j < 9 else (p[..., k] <= 1))
                wb = np.where(mask, w / len(y), 0.)
                mass = float(wb.sum())
                bins.append({'lower': float(edges[j]), 'upper': float(edges[j + 1]), 'weight_fraction': mass,
                             'mean_probability': float(np.sum(np.where(mask, p[..., k], 0) * wb) / mass) if mass else None,
                             'observed_frequency': float(np.sum(truth[..., k] * wb) / mass) if mass else None,
                             'cell_year_count': int(mask.sum()), 'years_contributing': int(mask.reshape(len(y), -1).any(1).sum())})
            reliability[cat] = bins
        result['methods'][method] = reliability
    return result


def review_fields(review, root, output):
    result = []
    for record in review['reviews']:
        target, mode = record['target'], record['mode']
        source = root / f'init05_{target}' / mode / 'regime_probabilities_and_weights.nc'
        if not source.is_file():
            raise ValueError('Optional field input missing: ' + str(source) + '. Run without --with-fields for the summary review.')
        with xr.open_dataset(source) as ds:
            d = ds.load()
        if d.attrs.get('classification_method') != METHOD or d.attrs.get('target') != target or d.attrs.get('mode') != mode:
            raise ValueError('Wrong historical field classification/target/mode')
        r = calculate(d, record['domains']['all_country']['annual'])
        r.update(target=target, mode=mode, source_sha256=sha(source), note='Descriptive equal-year area-weighted reliability. Cell-year counts are not independent sample sizes; no confidence bands or automatic selection.')
        dest = output / 'reliability' / target / mode
        dest.mkdir(parents=True)
        write(dest / 'reliability.json', r)
        fig, axes = plt.subplots(2, 3, figsize=(12, 7), layout='constrained')
        for k, cat in enumerate(CATS):
            axes[0, k].plot([0, 1], [0, 1], '--', color='gray')
            for method, color in zip(METHODS, ['#888888', '#d18a24', '#24629b']):
                rows = r['methods'][method][cat]
                valid = [v for v in rows if v['weight_fraction'] > 0]
                axes[0, k].plot([v['mean_probability'] for v in valid], [v['observed_frequency'] for v in valid], 'o-', color=color, label=method, ms=4)
                axes[1, k].step(np.arange(.05, 1, .1), [v['weight_fraction'] for v in rows], where='mid', color=color)
            axes[0, k].set(title=cat.capitalize(), xlim=(0, 1), ylim=(0, 1), xlabel='Forecast probability', ylabel='Observed frequency')
            axes[1, k].set(xlim=(0, 1), xlabel='Forecast probability', ylabel='Weighted fraction')
        axes[0, 0].legend(fontsize=8)
        fig.suptitle(f'{target} | {mode} | descriptive historical reliability\nEqual years and within-year area weights; spatial cells are dependent')
        fig.savefig(dest / 'reliability.png', dpi=150)
        plt.close(fig)
        result.append({'target': target, 'mode': mode, 'source_sha256': r['source_sha256'], 'evidence_reproduction_passed': True})
        print('Checked historical probability fields:', target, mode, flush=True)
    return result
