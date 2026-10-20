import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import accept_results as ar          # noqa: E402


def bench(targets=5, members=25, clean=True, searched=True):
    fit = {'drn_csg': {'hidden': [32], 'decay': 1e-4, 'steps': [10, 20, 30],
                       'validation_crps': {'[32]|0.0001': 0.3} if searched else {}}}
    scores = {'training': {'ethiopia': {'crps': 1}}, 'test': {'ethiopia': {'crps': 1}}}
    return dict(created_utc='2026-10-20T00:00:00+00:00', config='c.json', training_years=[1993, 2016], test_years=[2017, 2025],
                models=['drn_csg'], config_contents=dict(members=members, models=['drn_csg']),
                provenance=dict(commit='abc1234', uncommitted_changes=not clean),
                targets={f'T{i}': dict(methods={'drn_csg': scores}, fitted=fit) for i in range(targets)})


class Accept(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.saved = (ar.ROOT, ar.REGISTRY, ar.ARCHIVE, ar.OUTPUTS)
        ar.ROOT, ar.REGISTRY, ar.ARCHIVE, ar.OUTPUTS = root, root / 'reg.json', root / 'acc', root / 'out'

    def tearDown(self):
        ar.ROOT, ar.REGISTRY, ar.ARCHIVE, ar.OUTPUTS = self.saved
        self.tmp.cleanup()

    def write(self, cycle, d):
        f = ar.OUTPUTS / cycle / 'neural' / 'benchmark.json'
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(d), encoding='utf-8')
        return f

    def test_incomplete_results_are_refused(self):
        self.assertEqual(ar.check(bench()), [])
        self.assertTrue(any('targets' in p for p in ar.check(bench(targets=4))))
        self.assertTrue(any('members' in p for p in ar.check(bench(members=51))))
        self.assertTrue(any('clean commit' in p for p in ar.check(bench(clean=False))))
        self.assertTrue(any('configurations evaluated' in p for p in ar.check(bench(searched=False))))

    def test_a_batch_is_accepted_whole_or_not_at_all(self):
        for c in ar.CYCLES[:-1]:
            self.write(c, bench())
        self.write(ar.CYCLES[-1], bench(targets=3))
        with self.assertRaises(SystemExit):
            ar.accept('neural', 'v1')
        self.assertEqual(ar.load()['accepted'], {})

    def test_only_the_accepted_version_is_published(self):
        for c in ar.CYCLES:
            self.write(c, bench())
        ar.accept('neural', 'v1')
        first = ar.resolve('neural', 'jan_fmam')[0].read_bytes()
        newer = bench()
        newer['created_utc'] = '2026-10-21T00:00:00+00:00'
        self.write('jan_fmam', newer)                       # a rerun overwrites outputs/
        self.assertEqual(ar.resolve('neural', 'jan_fmam')[0].read_bytes(), first)
        row = next(r for r in ar.status() if r['family'] == 'neural' and r['cycle'] == 'jan_fmam')
        self.assertEqual(row['pending']['problems'], [])
        self.assertIsNone(ar.resolve('neural_ext', 'jan_fmam'))   # gated family, nothing accepted


if __name__ == '__main__':
    unittest.main()
