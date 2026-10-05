"""Run: python -m unittest discover -s tests -p test_comparison.py -v"""
import sys
import unittest
import tempfile
import json
from unittest.mock import patch
import xarray as xr
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from compare_calibration import smooth, make_record, fit_maps, predict, compare, summarize


class ComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(730)
        cls.models = {y: rng.gamma(8, 30, (25, 4)) for y in range(1993, 2017)}
        cls.obs = {y: rng.gamma(6, 30, 4) for y in cls.models}
        cls.land = np.ones(4, bool)
        cls.area = np.array([1., 1., 2., 2.])

    def test_smoothing_counts(self):
        p = np.array([[0., .4, .6]])
        np.testing.assert_allclose(smooth(p, 25), [[.5/26.5, 10.5/26.5, 15.5/26.5]])
        np.testing.assert_allclose(smooth(p, 51).sum(axis=1), 1)
        self.assertLess(smooth(p, 51)[0, 0], smooth(p, 25)[0, 0])

    def test_outer_observation_cannot_change_fit_or_predictions(self):
        target = 2016
        train = [y for y in self.models if y != target]
        records = [make_record([z for z in train if z != y], y, self.models, self.obs, self.land) for y in train]
        fit = fit_maps(records, self.area)
        original = make_record(train, target, self.models, self.obs, self.land)
        changed = dict(self.obs)
        changed[target] = changed[target] + 10000
        records2 = [make_record([z for z in train if z != y], y, self.models, changed, self.land) for y in train]
        fit2 = fit_maps(records2, self.area)
        modified = make_record(train, target, self.models, changed, self.land)
        self.assertEqual(fit, fit2)
        for name, p in predict(original, fit).items():
            np.testing.assert_allclose(p, predict(modified, fit2)[name])
        self.assertTrue(np.any(original['y'] != modified['y']))

    def test_full_comparison(self):
        rows, records, fits = compare(self.models, self.obs, self.land, self.area, np.array([1, 1, 0, 0], bool))
        self.assertEqual(len(rows), 24)
        summary = summarize(rows, bootstrap=50)
        self.assertAlmostEqual(summary['climatology']['rpss'], 0)
        for row, record, fit in zip(rows, records, fits):
            self.assertNotIn(row['year'], fit['training_years'])
            self.assertTrue(0 <= fit['blend_lambda'] <= 1)
            for p in record['pred'].values():
                np.testing.assert_allclose(p.sum(axis=1), 1)
            self.assertEqual(row['metrics']['base']['cells'], 2)

    def test_cli_outputs(self):
        import compare_calibration as module
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lat, lon = np.array([3., 4.]), np.array([33., 34.])
            mask_path = root/'mask.nc'
            xr.Dataset({'region_mask': (('lat','lon'), [[1,1],[0,0]])},
                       coords={'lat':lat, 'lon':lon}).to_netcdf(mask_path)
            loaded = ('init05_JJAS', self.models, self.obs,
                      {y: np.arange(25) for y in self.models}, lat, lon)
            with patch.object(module, 'ROOT', root), patch.object(module, 'load_config', return_value={}), \
                 patch.object(module, 'load_inputs', return_value=loaded), \
                 patch.object(sys, 'argv', ['compare', '--region-mask', str(mask_path)]):
                module.main()
            out = root/'outputs/model_comparison/init05_JJAS/training_only'
            report = json.loads((out/'comparison_summary.json').read_text())
            self.assertEqual(report['training_years'], list(range(1993,2017)))
            with xr.open_dataset(out/'cross_validated_probabilities.nc') as d:
                self.assertEqual(d.sizes['year'], 24)
                self.assertEqual(d.base_probability.shape, (24,2,2,3))
            self.assertTrue((out/'comparison_table.csv').exists())


if __name__ == '__main__':
    unittest.main()
