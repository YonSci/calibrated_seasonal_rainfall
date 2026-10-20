"""Accuracy of the CRPS used to score the rainfall-distribution models (docs/48, 54).

Distribution.crps (scripts/dist_calibration.py) integrates (F(x) - 1{x >= y})^2 by the trapezoidal rule on 400 points spaced
uniformly from 0 to beyond y and the 99.9% quantile. The integrand jumps at the observation y, which in general falls between
grid points, so the error is of the order of the grid step. This script measures that error against a reference and tests a
corrected rule that puts grid points on both sides of y (and keeps the far tail), on:
  * single censored shifted gammas, where the closed form of Scheuerer & Hamill (2015) is the reference;
  * equal mixtures of three of them (the DRN forecast), with adaptive quadrature split at y and 0 as the reference;
  * dry, ordinary, wet and extreme observations (beyond the 99.9% quantile), and an observation of zero.

  python scripts/crps_precision.py            ->  outputs/crps_precision/report.json (and a table on screen)
"""
import json
from pathlib import Path

import numpy as np
from scipy import integrate

import dist_calibration as dc
import neural_calibration as nc

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/crps_precision'


def reference(dist, y):
    """CRPS by adaptive quadrature, split at 0, y and the 99.9% quantile, with the upper tail to the 1 - 1e-10 quantile."""
    out = np.empty(len(y))
    for i in range(len(y)):
        F = lambda x: float(dist.cdf(np.full(len(y), x))[i])          # noqa: E731
        hi = float(dist.quantile(np.full(len(y), 1 - 1e-10))[i])
        lo_part = integrate.quad(lambda x: F(x) ** 2, 0, y[i], limit=400, epsabs=1e-10)[0] if y[i] > 0 else 0.
        top = max(hi, y[i])
        hi_part = integrate.quad(lambda x: (1 - F(x)) ** 2, y[i], top, limit=400, epsabs=1e-10)[0]
        out[i] = lo_part + hi_part
    return out


def split_grid(dist, y, points=400):
    """The corrected rule: trapezoids on [0, y] and [y, top] separately (points / 2 each), top beyond y and the 99.99% quantile."""
    top = np.maximum(np.nan_to_num(dist.quantile(np.full(len(y), .9999)), nan=0.), y) * 1.05 + 1e-6
    n = points // 2
    a = np.linspace(0, 1, n)[:, None] * y[None, :]
    b = y[None, :] + np.linspace(0, 1, n)[:, None] * (top - y)[None, :]
    Fa = np.stack([dist.cdf(xi) for xi in a])
    Fb = np.stack([dist.cdf(xi) for xi in b])
    return np.trapz(Fa ** 2, a, axis=0) + np.trapz((1 - Fb) ** 2, b, axis=0)


def csg(k, theta, delta, scale=1.):
    k, theta, delta = (np.atleast_1d(np.asarray(v, float)) for v in (k, theta, delta))
    n = len(k)
    return dc.CSGamma(k, theta, delta, np.full(n, scale), np.ones(n, bool))


def cases():
    """(label, distribution, observations) in mm."""
    out = []
    # the case raised in the review: shape 3, scale 100 mm, shift -10 mm
    for y in (0., 5., 60., 210., 400., 900.):
        out.append((f'CSG k=3, θ=100 mm, δ=−10 mm; y={y:g} mm', csg(3, 100, -10), np.array([y])))
    # typical relative distributions (unit = the cell's mean), scaled to dry, ordinary and wet cells
    for scale, kind in ((15., 'dry month (mean 15 mm)'), (120., 'ordinary month (mean 120 mm)'), (700., 'wet season (mean 700 mm)')):
        for k, th, de in ((0.8, 1.4, -0.08), (2.5, 0.42, -0.05), (8., 0.13, -0.02)):
            d = csg(k, th, de, scale)
            for q in (0.0, 0.3, 0.5, 0.9, 0.9995):
                y = 0. if q == 0 else float(d.quantile(np.array([q]))[0])
                out.append((f'CSG {kind}, k={k}, obs at {q:g} quantile', d, np.array([y])))
    # mixtures of three seeds (nc.CSGMixture), relative parameters close together and far apart
    for scale in (15., 120., 700.):
        for parts in (((2.4, .44, -.05), (2.6, .40, -.04), (2.5, .43, -.06)), ((1.2, .9, -.1), (4., .25, -.02), (2.5, .5, -.05))):
            m = nc.CSGMixture([tuple(np.array([v]) for v in p) for p in parts], np.array([scale]), np.ones(1, bool))
            for q in (0.0, 0.3, 0.5, 0.9, 0.9995):
                y = 0. if q == 0 else float(m.quantile(np.array([q]))[0])
                out.append((f'mixture of 3, mean {scale:g} mm, {"close" if parts[0][0] == 2.4 else "spread"} seeds, obs at {q:g} quantile', m, np.array([y])))
    return out


def main():
    rows = []
    for label, d, y in cases():
        ref = reference(d, y)
        if isinstance(d, dc.CSGamma):               # closed form, in relative units times the scale
            exact = d.scale * nc.crps_csg(d.k, d.theta, d.delta, y / d.scale)
            assert np.allclose(exact, ref, rtol=1e-6, atol=1e-6), (label, exact, ref)
        cur, new = d.crps(y), split_grid(d, y)
        rows.append(dict(case=label, observation_mm=float(y[0]), reference=float(ref[0]), current=float(cur[0]), split=float(new[0]),
                         current_error=float(cur[0] - ref[0]), split_error=float(new[0] - ref[0])))
    OUT.mkdir(parents=True, exist_ok=True)
    big = max(rows, key=lambda r: abs(r['current_error']))
    summary = dict(cases=len(rows), max_abs_error_current_mm=max(abs(r['current_error']) for r in rows),
                   max_abs_error_split_mm=max(abs(r['split_error']) for r in rows),
                   max_rel_error_current=max(abs(r['current_error']) / max(r['reference'], 1e-9) for r in rows),
                   max_rel_error_split=max(abs(r['split_error']) / max(r['reference'], 1e-9) for r in rows), largest_current=big['case'])
    (OUT / 'report.json').write_text(json.dumps(dict(summary=summary, rows=rows), indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'{"case":78} {"ref":>10} {"current":>10} {"err":>9} {"split err":>10}')
    for r in rows:
        print(f'{r["case"][:78]:78} {r["reference"]:10.4f} {r["current"]:10.4f} {r["current_error"]:+9.4f} {r["split_error"]:+10.5f}')
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    main()
