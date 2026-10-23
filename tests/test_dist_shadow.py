import json
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import dist_shadow as ds        # noqa: E402


def read(p):
    return json.loads((ROOT / p).read_text(encoding='utf-8'))


class PooledShadow(unittest.TestCase):
    def test_the_pooled_drn_has_a_shadow(self):
        self.assertNotIn('drn_pooled', ds.NO_SHADOW)
        self.assertIn('drn_pooled', ds.POOLED)
        self.assertEqual(read('config/probability_calibration/amount_shadow.json')['members'].get('drn_pooled'), 25)

    def test_months_and_their_positions(self):
        cycle, project = dict(targets=['Oct', 'Nov', 'Dec', 'Jan', 'ONDJ']), dict(season=dict(name='ONDJ'))
        self.assertEqual(ds.months_of(cycle, project), ['Oct', 'Nov', 'Dec', 'Jan'])
        h = ds.onehot(2, 3)
        self.assertEqual([h[f'target_{j}'][0] for j in range(1, 5)], [0., 0., 1., 0.])
        self.assertEqual(len(h['target_1']), 3)

    def test_every_cycle_orders_its_months_as_the_benchmark(self):
        """The month inputs must mean in the shadow what they meant when the pooled network was benchmarked."""
        scfg = read('config/probability_calibration/amount_shadow.json')
        files = ['config/operational.json', *sorted(str(p.relative_to(ROOT)) for p in (ROOT / 'config/cycles').glob('*.json'))]
        checked = 0
        for f in files:
            cycle = read(f)
            if 'project_config' not in cycle or 'targets' not in cycle:
                continue
            project = read(cycle['project_config'])
            entry = next((e for e in scfg['cycles'] if e['initialization_month'] == project['initialization_month']
                          and e['season'] == project['season']['name']), None)
            if entry is None:
                continue
            bench = read(entry['benchmark_config'])
            season = project['season']['name']
            self.assertEqual(ds.months_of(cycle, project), [t for t in bench['targets'] if t != season], f)
            checked += 1
        self.assertGreaterEqual(checked, 4)


if __name__ == '__main__':
    unittest.main()
