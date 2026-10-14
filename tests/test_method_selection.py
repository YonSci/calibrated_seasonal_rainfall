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

    def test_explanation_names_the_reference_and_the_alternatives(self):
        a = cand('bias_correction', 'vs', -0.5, [-0.1]); b = cand('distribution_phase2', 'qr', -2.0)
        for x in (a, b):
            x['historical'].update(holm_p=0.01, years_better=18, years=24, test_difference=-0.2)
        txt = ms.why(b, 'amounts', 'Sep', 'MVS ensemble', [a, b], 'CRPS (mm)')
        self.assertIn('MVS ensemble', txt)
        self.assertIn('No independent validation season yet', txt)
        self.assertIn('Also confirmed (one change at a time): vs (amount correction)', txt)
        self.assertIn('No method is confirmed better', ms.why(None, 'amounts', 'Sep', 'MVS ensemble', [], 'CRPS (mm)'))


if __name__ == '__main__':
    unittest.main()
