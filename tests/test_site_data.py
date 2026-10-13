import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import site_data as sd                  # noqa: E402


class Slim(unittest.TestCase):
    def test_keeps_summaries_and_drops_series(self):
        x = dict(rpss=.1, per_year=dict(rps=[.2] * 24), _forest='object', protocol='long text',
                 tests=dict(decision=dict(confirmed=True, holm_p_family=.3)), cells=list(range(1484)), targets=['Feb', 'FMAM'],
                 levels=[.05] * 19)
        s = sd.slim(x)
        self.assertEqual(s['rpss'], .1)
        self.assertNotIn('per_year', s)
        self.assertNotIn('_forest', s)
        self.assertNotIn('protocol', s)
        self.assertTrue(s['tests']['decision']['confirmed'])
        self.assertIsNone(s['cells'])                       # long numeric array: per-cell values
        self.assertEqual(s['targets'], ['Feb', 'FMAM'])
        self.assertEqual(len(s['levels']), 19)              # short arrays (levels, coefficients) are kept


if __name__ == '__main__':
    unittest.main()
