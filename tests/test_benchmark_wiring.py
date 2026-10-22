import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


class Wiring(unittest.TestCase):
    """Every module attribute the benchmark runners use exists. The final assembly of a run (after hours of fitting) is not
    exercised by the other tests; a missing name there (dist_calibration.SCORING_VERSION, October 2026) only failed at the
    end of each run."""

    def check(self, runner, alias, module):
        src = (ROOT / 'scripts' / runner).read_text(encoding='utf-8')
        mod = __import__(module)
        names = sorted(set(re.findall(rf'\b{alias}\.([A-Za-z_][A-Za-z0-9_]*)', src)))
        self.assertTrue(names, f'{runner} uses no {alias}.* names')
        missing = [n for n in names if not hasattr(mod, n)]
        self.assertEqual(missing, [], f'{runner}: {module} has no {missing}')

    def test_dist_benchmark_uses_existing_names(self):
        self.check('dist_benchmark.py', 'dc', 'dist_calibration')

    def test_pooled_benchmark_uses_existing_names(self):
        self.check('pooled_benchmark.py', 'dc', 'dist_calibration')
        self.check('pooled_benchmark.py', 'db', 'dist_benchmark')

    def test_scoring_version_is_recorded(self):
        import dist_calibration as dc
        self.assertEqual(dc.SCORING_VERSION, 2)


if __name__ == '__main__':
    unittest.main()
