"""The multiple-testing correction of the method selection (docs/50): re-decide 'confirmed' within each benchmark family.

Every benchmark stores, per method, target and score, the unadjusted p-value of the training-period sign-flip test, the mean
differences over the training and test years, and its own decision with Holm. The selection rule
(`config/method_selection_rule.json`, `multiple_testing`) may use another correction: the decisions are recomputed here from
the stored p-values, within the same families as the benchmark (its methods x targets, per score), with no refitting.
A method is confirmed when it is better over the training years with adjusted p < 0.05 and not worse over the test years.
`holm_check` recomputes Holm and compares it with the stored decisions, to prove the families are rebuilt correctly.
"""
from significance import holm

ALPHA = 0.05
CORRECTIONS = ('holm', 'benjamini_hochberg')


def bh(pvalues):
    """Benjamini-Hochberg adjusted p-values (false discovery rate)."""
    keys = sorted(pvalues, key=lambda k: pvalues[k])
    m, adjusted, running = len(keys), {}, 1.0
    for i in range(m - 1, -1, -1):
        running = min(running, pvalues[keys[i]] * m / (i + 1))
        adjusted[keys[i]] = min(1.0, running)
    return adjusted


def family_tests(tests, methods, score):
    """{(method, target): test} of one family and score."""
    return {(m, t): x for m in methods if score in tests.get(m, {}) for t, x in tests[m][score].items()}


def decide(tests, methods, score, correction):
    """{(method, target): dict(p_adjusted, correction, confirmed)} for one family and score."""
    if correction not in CORRECTIONS:
        raise ValueError(f'unknown correction {correction}')
    fam = family_tests(tests, methods, score)
    if not fam:
        return {}
    p = {k: x['training']['p_improvement'] for k, x in fam.items()}
    adj = bh(p) if correction == 'benjamini_hochberg' else holm(p)
    return {k: dict(p_adjusted=float(adj[k]), correction=correction,
                    confirmed=bool(x['training']['mean_difference'] < 0 and adj[k] < ALPHA and x['test']['mean_difference'] <= 0))
            for k, x in fam.items()}


def holm_check(tests, methods, score):
    """Largest difference between the recomputed Holm p and the benchmark's stored one, and the decisions that differ."""
    ours = decide(tests, methods, score, 'holm')
    diff, mismatched = 0.0, []
    for (m, t), d in ours.items():
        stored = tests[m][score][t]['decision']
        sp = stored.get('holm_p_family', stored.get('holm_p'))
        diff = max(diff, abs(sp - d['p_adjusted']))
        if stored['confirmed'] != d['confirmed']:
            mismatched.append((m, t))
    return diff, mismatched
