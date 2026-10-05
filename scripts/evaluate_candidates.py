"""Fit on 1993-2016; exploratory evaluation on 2017-2025, all 51 members."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import xarray as xr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from common import ROOT, load_config, source_path, save_json, save_netcdf
from calibration_core import fit_amount, correct_amount, probabilities, labels
from run_calibration import load_inputs, load_land, cell_area, params_dataset
from compare_calibration import NAMES, make_record, fit_maps, smooth, predict, score, summarize
from verification_core import probability_losses, mean_valid, roc_curve

TRAIN = list(range(1993, 2017))
TARGET = list(range(2017, 2026))
DISPLAY = ['base', 'dirichlet_original', 'blend', 'temperature', 'dirichlet_smooth']


def fit_training(models, obs, land, area, progress=print):
    records = []
    for y in TRAIN:
        records.append(make_record([z for z in TRAIN if z != y], y, models, obs, land))
        progress(f'Training OOF: {y}')
    maps = fit_maps(records, area)
    pars = fit_amount([models[y] for y in TRAIN], np.stack([obs[y] for y in TRAIN]), land)
    cats = np.stack([labels(obs[y], pars) for y in TRAIN])
    clim = np.stack([(cats == k).mean(axis=0) for k in range(3)], axis=-1)
    clim[~pars['probability_eligible']] = np.nan
    return pars, maps, clim


def evaluate(models, obs, pars, maps, clim, area, region):
    records, rows = [], []
    for y in TARGET:
        base = probabilities(correct_amount(models[y], pars), pars)
        p = predict(dict(p=base, s=smooth(base, len(models[y])), clim=clim), maps)
        truth = labels(obs[y], pars)
        rows.append(dict(year=y, metrics=score(p, truth, area, region)))
        records.append(dict(pred=p, y=truth))
    return rows, records


def diagnostics(records, area, region):
    truth = np.stack([r['y'] for r in records])
    valid = (truth >= 0) & region[None, :]
    for name in NAMES:
        valid &= np.isfinite(np.stack([r['pred'][name] for r in records])).all(axis=-1)
    w = np.where(valid, area[None, :], 0.)
    if (w.sum(axis=1) == 0).any():
        raise ValueError('A target year has no valid evaluation cells.')
    w = w / w.sum(axis=1, keepdims=True) / len(records)
    bins, rocs, spatial = {}, {}, {}
    for name in NAMES:
        p = np.stack([r['pred'][name] for r in records])
        bs, rps, ll = probability_losses(p, truth)
        rps[~valid] = np.nan
        spatial[name] = mean_valid(rps)
        bins[name], rocs[name] = [], []
        for k in range(3):
            category_bins = []
            for j in range(10):
                chosen = valid & (p[..., k] >= j/10) & (p[..., k] < (j+1)/10 if j<9 else p[..., k] <= 1)
                mass = float(w[chosen].sum())
                category_bins.append(dict(lower=j/10, upper=(j+1)/10, weight=mass,
                    pairs=int(chosen.sum()),
                    forecast_probability=float(w[chosen] @ p[..., k][chosen] / mass) if mass else None,
                    observed_frequency=float(w[chosen] @ (truth[chosen] == k) / mass) if mass else None))
            bins[name].append(category_bins)
            curve = roc_curve(p[..., k].ravel(), (truth == k).ravel(), w.ravel())
            rocs[name].append(None if curve is None else dict(fpr=curve[0].tolist(), tpr=curve[1].tolist(), auc=curve[2]))
    return bins, rocs, spatial, valid.sum(axis=0)


def plots(out, rows, bins, rocs, spatial, lat, lon):
    cats = ['Below normal', 'Near normal', 'Above normal']
    fig, axes = plt.subplots(2, 3, figsize=(13, 8))
    for k in range(3):
        axes[0,k].plot([0,1], [0,1], 'k--', lw=1)
        for name in DISPLAY:
            b = bins[name][k]
            axes[0,k].plot([v['forecast_probability'] for v in b], [v['observed_frequency'] for v in b], 'o-', label=name, ms=3)
            axes[1,k].plot([.05+.1*j for j in range(10)], [v['weight'] for v in b], 'o-', label=name, ms=3)
        axes[0,k].set(title=cats[k], xlabel='Forecast probability', ylabel='Observed frequency', xlim=(0,1), ylim=(0,1))
        axes[1,k].set(xlabel='Probability bin midpoint', ylabel='Fraction of evaluation weight', xlim=(0,1))
    axes[0,0].legend(fontsize=7)
    fig.suptitle('2017-2025 exploratory evaluation | supplied region mask')
    fig.tight_layout(); fig.savefig(out/'reliability_and_histograms.png', dpi=170); plt.close(fig)
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    for k, ax in enumerate(axes):
        ax.plot([0,1], [0,1], 'k--')
        for name in DISPLAY:
            r = rocs[name][k]
            if r is not None: ax.plot(r['fpr'], r['tpr'], label=f"{name}: {r['auc']:.3f}")
        ax.set(title=cats[k], xlabel='False positive rate', ylabel='True positive rate'); ax.legend(fontsize=6)
    fig.tight_layout(); fig.savefig(out/'roc_curves.png', dpi=170); plt.close(fig)
    fig, ax = plt.subplots(figsize=(11, 4))
    for name in DISPLAY + ['climatology']:
        ax.plot(TARGET, [r['metrics'][name]['rps'] for r in rows], 'o-', label=name, ms=3)
    ax.set(ylabel='RPS (lower is better)', xlabel='Year', title='Annual area-weighted RPS | supplied region mask')
    ax.legend(fontsize=7, ncol=3); fig.tight_layout(); fig.savefig(out/'annual_rps.png', dpi=170); plt.close(fig)
    fig, axes = plt.subplots(1, 3, figsize=(13, 5))
    baseline = spatial['climatology']
    fields = [np.divide(baseline-spatial[n], baseline, out=np.full_like(baseline,np.nan), where=baseline>0) for n in ['dirichlet_original','blend']]
    fields.append(spatial['blend']-spatial['dirichlet_original'])
    for ax, field, title, limit in zip(axes, fields, ['Original Dirichlet RPSS','Blend RPSS','Blend minus original RPS'], [.5,.5,.1]):
        im = ax.pcolormesh(lon, lat, field.reshape(len(lat),len(lon)), cmap='RdBu' if limit==.5 else 'RdBu_r', vmin=-limit,vmax=limit,shading='auto')
        ax.set(title=title, xlabel='Longitude', ylabel='Latitude'); ax.set_aspect('equal'); fig.colorbar(im, ax=ax, shrink=.7, extend='both')
    fig.suptitle('2017-2025 | region masked; no boundary outline drawn')
    fig.tight_layout(); fig.savefig(out/'spatial_rps.png', dpi=170); plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/project.json')
    parser.add_argument('--region-mask', required=True)
    parser.add_argument('--land-mask')
    args = parser.parse_args(); cfg = load_config(args.config)
    tag, models, obs, members, lat, lon = load_inputs(cfg, TRAIN+TARGET, TRAIN+TARGET)
    land, land_info = load_land(args.land_mask, lat, lon)
    path = source_path(args.region_mask)
    with xr.open_dataset(path) as d:
        mask = d.region_mask.transpose('lat','lon')
        if not np.array_equal(mask.lat,lat) or not np.array_equal(mask.lon,lon): raise ValueError('Region grid mismatch.')
        if not np.isin(mask.values,[0,1]).all() or not (mask.values==1).any(): raise ValueError('Expected nonempty binary region mask.')
        region = mask.values.reshape(-1)==1
    area = cell_area(lat,lon)
    out = ROOT/'outputs/model_comparison'/tag/'operational_period'
    if out.exists(): raise FileExistsError(f'{out} exists. Rename it before rerunning.')
    pars, maps, clim = fit_training(models,obs,land,area, lambda text: print(text,flush=True))
    rows, records = evaluate(models,obs,pars,maps,clim,area,region)
    bins, rocs, spatial, counts = diagnostics(records,area,region)
    summary = summarize(rows,bootstrap=5000)
    attrs = dict(config_json=json.dumps(cfg), training_years='1993-2016', evaluation_years='2017-2025',
                 primary_candidate='blend', status='exploratory; evaluation period previously inspected',
                 processing_utc=datetime.now(timezone.utc).isoformat())
    save_netcdf(params_dataset(pars,lat,lon,attrs),out/'amount_parameters.nc')
    save_json(out/'fitted_probability_models.json',dict(training_years=TRAIN,alpha_per_category=.5,**maps))
    report = dict(training_years=TRAIN,target_years=TARGET,primary_candidate='blend',
        equal_year_summary=summary,years=rows,land_mask=land_info,
        region_mask=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),cells=int(region.sum()),use='evaluation only'),
        members={str(y):len(members[y]) for y in TRAIN+TARGET},
        note='All fits use 1993-2016 only. No tuning or automatic method selection on 2017-2025. Original scores not overwritten.',
        uncertainty='5000 paired whole-year resamples of 9 years; fixed fits; descriptive, ignores serial dependence and fit uncertainty.',
        code_sha256={n:hashlib.sha256((Path(__file__).parent/n).read_bytes()).hexdigest() for n in ['evaluate_candidates.py','compare_calibration.py','calibration_core.py']})
    save_json(out/'operational_comparison_summary.json',report)
    save_json(out/'reliability_bins.json',bins); save_json(out/'roc_curves.json',rocs)
    d = xr.Dataset(coords=dict(year=TARGET,lat=lat,lon=lon,category=['below','near','above']),attrs=attrs)
    for name in NAMES:
        d[name+'_probability'] = (('year','lat','lon','category'),np.stack([r['pred'][name] for r in records]).reshape(9,len(lat),len(lon),3))
    d['observed_category'] = (('year','lat','lon'),np.stack([r['y'] for r in records]).reshape(9,len(lat),len(lon)))
    d['region_mask'] = (('lat','lon'),region.reshape(len(lat),len(lon)).astype('int8'))
    save_netcdf(d,out/'operational_probabilities.nc')
    sd = xr.Dataset(coords=dict(lat=lat,lon=lon),attrs=attrs)
    for name in NAMES:
        sd[name+'_rps'] = (('lat','lon'),spatial[name].reshape(len(lat),len(lon)))
    sd['valid_year_count'] = (('lat','lon'),counts.reshape(len(lat),len(lon)))
    save_netcdf(sd,out/'spatial_scores.nc')
    plots(out,rows,bins,rocs,spatial,lat,lon)
    print('Fitted blend climatology weight:',maps['blend_lambda'])
    for name in NAMES: print(f"{name:22s} RPS={summary[name]['rps']:.5f} RPSS={summary[name]['rpss']:.4f}")
    print('Complete:',out)


if __name__=='__main__': main()
