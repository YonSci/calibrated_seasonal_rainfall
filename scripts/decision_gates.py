"""Gate candidate calibration changes with paired whole-year significance tests.

Read-only experiment: never touches final_shared_blend outputs or frozen forecasts.
Every variant uses the local_blend protocol (docs 17):
  training    : nested LOYO over 1993-2016, outer year excluded from all inner fits
  operational : all fits on 1993-2016, scored on 2017-2025 (exploratory)
Scores: tercile RPS on Ethiopia cells, spherical area weights, one score per year.

Variants (shared-blend probabilities unless noted):
  current          affine correction, lambda fitted on the full rectangle
  ethiopia_lambda  affine correction, lambda fitted on Ethiopia cells only
  sqrt             square-root-space affine correction, full-rectangle lambda
  sqrt_ethiopia    both changes
Also gated: smooth (no blend) and climatology against current.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import numpy as np
import compare_calibration as cc
import calibration_core as core
from common import ROOT, load_config, save_json
from final_shared_blend import TARGETS, load_region
from local_blend import run
from run_calibration import load_inputs, load_land, cell_area
from significance import paired_summary, holm, gate

TRAIN = list(range(1993, 2017))
TEST = list(range(2017, 2026))
VARIANTS = {'current': (False, False), 'ethiopia_lambda': (False, True),
            'sqrt': (True, False), 'sqrt_ethiopia': (True, True)}


def fit_sqrt(models, observations, land):
    pars = core.fit_amount(models, observations, land)
    e = pars['amount_eligible']
    sm = [np.sqrt(m) for m in models]
    mu_h = np.mean([m.mean(0) for m in sm], axis=0)
    sd_h = np.sqrt(np.maximum(np.mean([(m * m).mean(0) for m in sm], axis=0) - mu_h ** 2, 0))
    so = np.sqrt(np.where(e[None, :], np.asarray(observations, float), 0))
    mu_o, sd_o = so.mean(0), so.std(0)
    r = np.ones_like(mu_h)
    np.divide(sd_o, sd_h, out=r, where=sd_h >= 0.1)
    pars.update(sqrt_mu_model=mu_h, sqrt_mu_obs=mu_o, sqrt_scale=np.clip(r, .5, 2.))
    return pars


def correct_sqrt(m, pars):
    s = pars['sqrt_mu_obs'] + pars['sqrt_scale'] * (np.sqrt(m) - pars['sqrt_mu_model'])
    out = np.maximum(s, 0) ** 2
    out[:, ~pars['amount_eligible']] = np.nan
    return out


@contextmanager
def amount_method(use_sqrt):
    """Swap the amount correction used by compare_calibration.make_record."""
    saved = cc.fit_amount, cc.correct_amount
    if use_sqrt:
        cc.fit_amount, cc.correct_amount = fit_sqrt, correct_sqrt
    try:
        yield
    finally:
        cc.fit_amount, cc.correct_amount = saved


def per_year(models, obs, land, area, region, mode, use_sqrt):
    with amount_method(use_sqrt):
        targets, rows, _, weights = run(models, obs, land, area, region, mode, progress=lambda s: None)
    return dict(years=targets,
                rps={k: [r['metrics'][k]['rps'] for r in rows] for k in ('shared_blend', 'smooth', 'climatology')},
                mean_lambda=float(np.mean([w['shared_lambda'] for w in weights])))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--config', default='config/project.json')
    p.add_argument('--targets', nargs='+', choices=TARGETS, default=TARGETS)
    p.add_argument('--region-mask', default='data/masks/ethiopia_common.nc')
    args = p.parse_args()
    from run_monthly import monthly_config
    base = load_config(args.config)
    month = {'Jun': 6, 'Jul': 7, 'Aug': 8, 'Sep': 9}
    scores = {}
    for t in args.targets:
        cfg = base if t == 'JJAS' else monthly_config(base, month[t])
        _, models, obs, _, lat, lon = load_inputs(cfg, TRAIN + TEST, TRAIN + TEST)
        region, _ = load_region(args.region_mask, lat, lon)
        full, _ = load_land(None, lat, lon)
        area = cell_area(lat, lon)
        scores[t] = {}
        for name, (use_sqrt, eth) in VARIANTS.items():
            land = region if eth else full
            scores[t][name] = {mode: per_year(models, obs, land, area, region, mode, use_sqrt)
                               for mode in ('training', 'operational')}
            tr = scores[t][name]
            print(f"{t} {name:16s} RPS train {np.mean(tr['training']['rps']['shared_blend']):.5f} "
                  f"oper {np.mean(tr['operational']['rps']['shared_blend']):.5f} "
                  f"lambda {tr['operational']['mean_lambda']:.3f}", flush=True)

    # Comparisons: (family, candidate variant, candidate score, reference score)
    comparisons = {
        'ethiopia_lambda_vs_current': ('ethiopia_lambda', 'shared_blend'),
        'sqrt_vs_current': ('sqrt', 'shared_blend'),
        'sqrt_ethiopia_vs_current': ('sqrt_ethiopia', 'shared_blend'),
        'no_blend_vs_current': ('current', 'smooth'),
        'climatology_vs_current': ('current', 'climatology'),
    }
    gates = {}
    for family, (variant, key) in comparisons.items():
        stats = {}
        for t in scores:
            ref = scores[t]['current']
            cand = scores[t][variant]
            stats[t] = {mode: paired_summary(cand[mode]['rps'][key], ref[mode]['rps']['shared_blend'])
                        for mode in ('training', 'operational')}
        adjusted = holm({t: s['training']['p_improvement'] for t, s in stats.items()})
        gates[family] = {t: dict(**stats[t], decision=gate(stats[t]['training'], stats[t]['operational'], adjusted[t]))
                         for t in stats}
        print(f"\n{family}")
        for t, g in gates[family].items():
            tr, op, dcs = g['training'], g['operational'], g['decision']
            print(f"  {t:4s} train d={tr['mean_difference']:+.5f} p={tr['p_improvement']:.3f} holm={dcs['holm_p']:.3f} "
                  f"CI[{tr['bootstrap_95'][0]:+.4f},{tr['bootstrap_95'][1]:+.4f}] {tr['years_better']}/{tr['years']} | "
                  f"oper d={op['mean_difference']:+.5f} {op['years_better']}/{op['years']} -> adopt={dcs['adopt']}")
    out = ROOT / 'outputs/decision_gates/decision_gates.json'
    save_json(out, dict(created_utc=datetime.now(timezone.utc).isoformat(), protocol=__doc__.strip(),
                        rule=gate.__doc__.strip(), per_year_scores=scores, gates=gates))
    print('\nSaved:', out)


if __name__ == '__main__':
    main()
