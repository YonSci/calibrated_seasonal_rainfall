"""Paired whole-year significance tests and the method-adoption gate.

Scores are compared year by year (one area-weighted score per year), so every
test resamples or permutes whole years. This keeps the spatial correlation within
a season intact: the ~1,480 Ethiopia cells of one year count as one observation,
not 1,480. No further spatial-duplication correction is needed for these tests.
"""
from itertools import product
import numpy as np

ALPHA = 0.05


def paired_summary(candidate, reference, draws=5000, seed=20261005):
    """Mean of candidate - reference (negative favours candidate for RPS/CRPS)."""
    d = np.asarray(candidate, float) - np.asarray(reference, float)
    n = len(d)
    idx = np.random.default_rng(seed).integers(0, n, (draws, n))
    boot = d[idx].mean(axis=1)
    return dict(mean_difference=float(d.mean()),
                bootstrap_95=[float(np.quantile(boot, .025)), float(np.quantile(boot, .975))],
                p_improvement=sign_flip_p(d),
                years_better=int((d < 0).sum()), years=n)


def sign_flip_p(d, max_exact=20, draws=200000, seed=20261005):
    """One-sided paired permutation p-value for mean(d) < 0.

    Under H0 (no difference) each year's sign is exchangeable. Exact enumeration
    for n <= max_exact years (2^n patterns), Monte Carlo otherwise.
    """
    d = np.asarray(d, float)
    observed = d.mean()
    if len(d) <= max_exact:
        signs = np.array(list(product([1., -1.], repeat=len(d))))
    else:
        signs = np.random.default_rng(seed).choice([1., -1.], (draws, len(d)))
    return float(np.mean((signs * np.abs(d)).mean(axis=1) <= observed + 1e-15))


def holm(pvalues):
    """Holm step-down adjusted p-values (family-wise error control)."""
    keys = list(pvalues)
    order = sorted(keys, key=lambda k: pvalues[k])
    m, running, adjusted = len(keys), 0., {}
    for i, k in enumerate(order):
        running = max(running, min(1., (m - i) * pvalues[k]))
        adjusted[k] = running
    return adjusted


def gate(training, operational, adjusted_p):
    """Adoption rule, fixed in docs/36 before the gated comparisons were run.

    Adopt the candidate for a target only if, on clean nested 1993-2016 scores,
    it improves the mean with Holm-adjusted one-sided p < ALPHA across the five
    targets, AND on 2017-2025 its mean score is not worse than the reference.
    """
    passed_training = training['mean_difference'] < 0 and adjusted_p < ALPHA
    no_harm = operational['mean_difference'] <= 0
    return dict(adopt=bool(passed_training and no_harm), training_significant=bool(passed_training),
                operational_no_harm=bool(no_harm), holm_p=float(adjusted_p))
