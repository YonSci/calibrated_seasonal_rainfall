import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import site_cells as sc          # noqa: E402

CYCLE = 'config/cycles/sep_2026_ondj.json'


@unittest.skipUnless((ROOT / 'site_data/cycles.json').is_file() and (ROOT / 'outputs/final_shared_blend/init09_ONDJ/2026').is_dir(),
                     'needs the built site data and the ONDJ 2026 forecast')
class Cells(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        out = Path(cls.tmp.name) / 'ondj2026'
        env = dict(os.environ, CALIBRATION_CYCLE=str(ROOT / CYCLE))
        subprocess.run([sys.executable, str(ROOT / 'scripts/site_cells.py'), '--cycle', CYCLE, '--id', 'ondj2026', '--out', str(out)],
                       cwd=ROOT, env=env, check=True, capture_output=True)
        cls.grid = json.loads((out / 'grid.json').read_text(encoding='utf-8'))
        cls.out = out
        page = json.loads((ROOT / 'site_data/cycles.json').read_text(encoding='utf-8'))
        cls.cycle = next(c for c in page['cycles'] if c['id'] == 'ondj2026')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_area_means_reproduce_the_published_summaries(self):
        g = self.grid
        w = np.cos(np.deg2rad(g['lat0'] + g['dlat'] * (np.array(g['cells']) // g['nlon'])))
        for t in self.cycle['targets']:
            d = json.loads((self.out / f"{t['id']}.json").read_text(encoding='utf-8'))
            for view in g['views']:
                pos = np.array(g['views'][view])
                P = np.array([[np.nan if v is None else v for v in d[k]] for k in ('pb', 'pn', 'pa')]).T[pos]
                ok = np.isfinite(P).all(1)
                mine = (w[pos][ok, None] * P[ok]).sum(0) / w[pos][ok].sum()
                np.testing.assert_allclose(mine, t['forecast'][view]['summary']['mean_local_probabilities'], atol=2e-3)

    def test_domain_cells_and_skill_present(self):
        self.assertEqual(len(self.grid['views']['ondj_rainfall_domain']), 575)
        d = json.loads((self.out / 'ONDJ.json').read_text(encoding='utf-8'))
        self.assertEqual(len(d['rb_tr']), len(self.grid['cells']))
        self.assertEqual(d['n_tr'], 24)


class Areas(unittest.TestCase):
    def test_every_area_has_cells_and_parents(self):
        with tempfile.TemporaryDirectory() as tmp:
            lat, lon = 3.125 + .25 * np.arange(48), 33.125 + .25 * np.arange(60)
            sc.export_areas(Path(tmp), lat, lon)
            a = json.loads((Path(tmp) / 'areas.json').read_text(encoding='utf-8'))
        levels = {lv: [x for x in a['areas'] if x['level'] == lv] for lv in (1, 2, 3)}
        self.assertEqual([len(levels[lv]) for lv in (1, 2, 3)], [15, 107, 1148])
        self.assertTrue(all(x['cells'] for x in a['areas']))
        self.assertTrue(all(x.get('region') for x in levels[2] + levels[3]) and all(x.get('zone') for x in levels[3]))
        self.assertIn('regions', a['outlines'])


if __name__ == '__main__':
    unittest.main()
