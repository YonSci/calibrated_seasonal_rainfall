import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import method_selection as ms              # noqa: E402


def cand(family, method, diff, seasons=None, status='candidate'):
    v = None if seasons is None else dict(seasons=[dict(year=2026 + i, method=d, reference=0.) for i, d in enumerate(seasons)],
                                          mean_difference=sum(seasons) / len(seasons) if seasons else None, required=3)
    return dict(family=family, method=method, label=method, historical=dict(training_difference=diff), validation=v, status=status)


class Selection(unittest.TestCase):
    def test_validation_decides_status(self):
        self.assertEqual(ms.status_of(cand('distribution_phase2', 'emos', -1.), 3), 'candidate')                       # no record
        self.assertEqual(ms.status_of(cand('distribution_phase2', 'emos', -1., [-0.5]), 3), 'candidate')               # 1 of 3
        self.assertEqual(ms.status_of(cand('distribution_phase2', 'emos', -1., [-0.5, 0.1, -0.2]), 3), 'recommended')  # mean not worse
        self.assertEqual(ms.status_of(cand('distribution_phase2', 'emos', -1., [0.5, 0.1, -0.2]), 3), 'not_supported')
        # bias-correction candidates keep the status bias_recommend.py gave them (same rule)
        self.assertEqual(ms.status_of(cand('bias_correction', 'sqrt_mvs', -1., [-0.5], status='recommended'), 3), 'recommended')

    def test_choice_prefers_recommended_then_largest_improvement(self):
        a = cand('bias_correction', 'vs', -0.5); a['status'] = 'candidate'
        b = cand('distribution_phase2', 'qr', -2.0); b['status'] = 'candidate'
        c = cand('distribution_phase2', 'emos', -0.1); c['status'] = 'recommended'
        self.assertEqual(ms.select([a, b])['method'], 'qr')
        self.assertEqual(ms.select([a, b, c])['method'], 'emos')
        d = cand('bias_correction', 'x', -9.); d['status'] = 'not_supported'
        self.assertIsNone(ms.select([d]))                                           # never select a method validation rejected
        self.assertIsNone(ms.select([]))

    def test_practical_tie_rule_prefers_the_simplest_close_candidate(self):
        drn, qr, emos = (cand('distribution_neural', 'drn_csg', -1.10), cand('distribution_phase2', 'quantile_regression', -1.08),
                         cand('distribution_phase2', 'emos_csg', -0.98))
        self.assertEqual(ms.select([drn, qr, emos])['method'], 'drn_csg')                       # no rule: the largest gain
        s = ms.select([drn, qr, emos], level=19.34, margin=0.01)                                # 1% of 19.34 = 0.19: all three tie
        self.assertEqual(s['method'], 'emos_csg')
        self.assertEqual(s['tie']['best'], 'drn_csg')
        self.assertEqual(ms.select([drn, qr, emos], level=19.34, margin=0.005)['method'], 'quantile_regression')   # 0.097: EMOS out
        self.assertEqual(ms.select([drn, cand('distribution_phase2', 'emos_csg', -0.5)], level=19.34, margin=0.01)['method'], 'drn_csg')
        rec = cand('distribution_neural', 'drn_csg', -0.9, [-0.5, -0.1, -0.2])
        rec['status'] = 'recommended'
        self.assertEqual(ms.select([rec, emos], level=19.34, margin=0.01)['method'], 'drn_csg')   # a recommended one first
        self.assertIn('practical tie rule', ms.why(s, 'amounts', 'Sep', 'MVS', [drn, qr, emos], 'CRPS (mm)'))

    def test_explanation_names_the_reference_and_the_alternatives(self):
        a = cand('bias_correction', 'vs', -0.5, [-0.1]); b = cand('distribution_phase2', 'qr', -2.0)
        for x in (a, b):
            x['historical'].update(holm_p=0.01, years_better=18, years=24, test_difference=-0.2)
        txt = ms.why(b, 'amounts', 'Sep', 'MVS ensemble', [a, b], 'CRPS (mm)')
        self.assertIn('MVS ensemble', txt)
        self.assertIn('No independent validation season yet', txt)
        self.assertIn('Also confirmed (one change at a time): vs (amount correction)', txt)
        self.assertIn('No method is confirmed better', ms.why(None, 'amounts', 'Sep', 'MVS ensemble', [], 'CRPS (mm)'))


class MosValidation(unittest.TestCase):
    def test_benchmark_year_and_shadow_seasons_one_per_year(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            old, ms.ROOT = ms.ROOT, Path(tmp)
            try:
                for year, observed, crps in ((2026, True, 9.), (2027, True, 4.), (2028, False, None)):
                    f = Path(tmp) / f'outputs/mos/may_jjas/shadow/{year}/pcr__Aug.json'
                    f.parent.mkdir(parents=True)
                    f.write_text(json.dumps(dict(forecast_year=year, observed=observed, scores=None if crps is None else dict(
                        crps=dict(method=crps, mvs_ensemble=5.), rps=dict(method=.3, published=.4)))), encoding='utf-8')
                mos = dict(validation=dict(Aug=dict(year=2026, crps=dict(pcr=6., mvs_ensemble=5.), rps=dict(pcr=.3, incumbent=.3))))
                v = ms.mos_validation('may_jjas', mos, 'pcr', 'Aug', 'crps', 3)
            finally:
                ms.ROOT = old
        self.assertEqual([s['year'] for s in v['seasons']], [2026, 2027])          # 2028 not yet observed
        self.assertEqual(v['seasons'][1], dict(year=2027, method=4., reference=5.))
        self.assertEqual(len(v['seasons']), 2)                                      # one record for 2026


if __name__ == '__main__':
    unittest.main()
