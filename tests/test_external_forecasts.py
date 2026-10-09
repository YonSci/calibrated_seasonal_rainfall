import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import external_forecasts as ef                                            # noqa: E402
from compare_external_forecasts import compare, favoured, relationship, window_limitation   # noqa: E402
from interpret_external_forecasts import interpret                          # noqa: E402

REGISTRY = ROOT / 'config/external_forecasts/ondj_2026_27.json'
CACHE = ROOT / 'data/external_forecasts'
MASK = ROOT / 'data/masks/init09_ONDJ_regime_domain.nc'
HAVE_CACHE = (CACHE / 'ondj_2026_27/current.json').is_file() and MASK.is_file()


class Matching(unittest.TestCase):
    def test_emi_outlook_part_of_combined_titles(self):
        a = ef.EMIAdapter(dict(outlook_season='bega', outlook_years=[2026, 2027]))
        self.assertTrue(a.matches('Kiremt 2026 Assessment and Bega 2026_27 Outlook Hydro met Bulletin'))
        self.assertTrue(a.matches('Bega 2026/27 Seasonal Climate Forecast'))
        # Bega appears only in the assessment half: an outlook for Belg must not match.
        self.assertFalse(a.matches('Bega 2026-27 Assessment and Belg 2027 hydro met Bulletin'))
        self.assertFalse(a.matches('kiremt 2025_Assessment and Bega ,2025_2026 Outlook Hydro met Bulletin'))

    def test_year_forms(self):
        self.assertEqual(ef._years('Bega 2026_27'), {2026, 2027})
        self.assertEqual(ef._years('bega 2025/26'), {2025, 2026})
        self.assertEqual(ef._years('bega-202526'), {2025, 2026})

    def test_extraction_status_follows_source_hash(self):
        rec = dict(source_sha256='a' * 64, status='validated')
        self.assertEqual(ef.extraction_status(rec, 'a' * 64), 'validated')
        self.assertEqual(ef.extraction_status(rec, 'b' * 64), 'needs_extraction_review')
        self.assertEqual(ef.extraction_status(dict(rec, status='draft'), 'a' * 64), 'needs_extraction_review')
        self.assertEqual(ef.extraction_status(None, 'a' * 64), 'needs_extraction')


class Rules(unittest.TestCase):
    def test_favoured_and_relationship(self):
        self.assertEqual(favoured([.2, .25, .55], .4), 'above')
        self.assertEqual(favoured([.35, .33, .32], .4), 'weak')
        self.assertEqual(relationship('below', 'above'), 'opposing_favoured_categories')
        self.assertEqual(relationship('above', 'above'), 'same_favoured_category')
        self.assertEqual(relationship('near', 'above'), 'near_versus_other')
        self.assertEqual(relationship('weak', 'above'), 'weak_signal')

    def test_window_mismatch_names_months(self):
        lim = window_limitation(dict(target_start='2026-10-01', target_end='2027-01-31'),
                                dict(target_start='2026-10-01', target_end='2026-12-31'))
        self.assertEqual(lim['only_platform'], ['Jan 2027'])
        self.assertIsNone(window_limitation(dict(target_start='2026-10-01', target_end='2027-01-31'),
                                            dict(target_start='2026-10-01', target_end='2027-01-31')))


@unittest.skipUnless(HAVE_CACHE, 'official snapshots not present')
class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.reg = ef.load_registry(REGISTRY)
        shutil.copytree(ROOT / self.reg['extractions_dir'], self.tmp / 'extractions')
        self.reg['extractions_dir'] = str(self.tmp / 'extractions')
        # Start every test from unreviewed copies, whatever the real records' review state is.
        for p in (self.tmp / 'extractions').glob('*.json'):
            rec = json.loads(p.read_text(encoding='utf-8'))
            rec.update(status='draft', review=None)
            p.write_text(json.dumps(rec), encoding='utf-8')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def native(self):
        """Synthetic forecast on the mask grid; categories stored in a different order on purpose."""
        import xarray as xr
        with xr.open_dataset(MASK) as m:
            lat, lon = m.lat.values, m.lon.values
        p = np.zeros((len(lat), len(lon), 3))
        p[...] = [.55, .25, .20]                         # above, near, below
        p[:, lon < 36] = [.20, .30, .50]                 # west favours below
        ds = xr.Dataset(dict(blend_probability=(('lat', 'lon', 'category'), p),
                             probability_eligible=(('lat', 'lon'), np.ones((len(lat), len(lon)), 'int8')),
                             region_mask=(('lat', 'lon'), np.ones((len(lat), len(lon)), 'int8')),
                             corrected_mean_anomaly=(('lat', 'lon'), np.zeros((len(lat), len(lon))))),
                        coords=dict(lat=lat, lon=lon, category=['above', 'near', 'below']))
        f = self.tmp / 'native.nc'
        ds.to_netcdf(f)
        return f

    def run_all(self):
        ef.prepare(self.reg, CACHE, MASK, self.tmp / 'sources')
        compare(self.tmp / 'sources', self.native(), MASK, self.reg, self.tmp / 'comparison')
        return interpret(self.tmp / 'comparison', self.tmp / 'sources', self.tmp / 'interpretation')

    def test_digitized_icpac_map(self):
        import xarray as xr
        with xr.open_dataset(MASK) as m:
            lat, lon = m.lat.values.astype(float), m.lon.values.astype(float)
        rec = json.loads((ROOT / 'config/external_forecasts/extractions/icpac_ond_2026_update_rainfall.json').read_text(encoding='utf-8'))
        current = json.loads((CACHE / 'ondj_2026_27/current.json').read_text())['icpac_ond_2026_update_rainfall']
        fields, qc = ef.digitize_dominant_map(ROOT / current['file'], rec['template'], lat, lon)
        self.assertLess(max(qc['tick_fit_max_residual_px']), 1.5)
        i, j = np.argmin(abs(lat - 6.125)), np.argmin(abs(lon - 44.125))
        self.assertEqual((fields['category'][i, j], fields['state'][i, j]), ('above', 'forecast'))
        self.assertGreaterEqual(fields['low'][i, j], 60)
        i, j = np.argmin(abs(lat - 13.125)), np.argmin(abs(lon - 39.125))
        self.assertEqual(fields['state'][i, j], 'no_forecast_shown')

    def test_draft_values_are_not_published_until_reviewed(self):
        res = self.run_all()
        published = [p for p in res['paragraphs'] if p['status'] == 'validated' and p['finding']]
        self.assertEqual(published, [])
        comparison = json.loads((self.tmp / 'comparison/comparison.json').read_text(encoding='utf-8'))
        shown = [m for m in comparison['metrics'] if m['metric'] == 'display_official_probabilities']
        self.assertTrue(shown and all(m['value'] is None and m['status'] == 'pending_review' for m in shown))
        anomaly = next(m for m in comparison['metrics'] if m['metric'] == 'rainfall_anomaly_difference')
        self.assertEqual((anomaly['status'], anomaly['value']), ('unavailable', None))

    def test_review_publishes_and_labels_disagreement(self):
        ef.review(self.reg, 'emi_bega_2026_27_outlook', 'Test reviewer', cache_root=CACHE)
        res = self.run_all()
        zone3 = next(p for p in res['paragraphs'] if p['area'] == 'EMI zone III')
        self.assertEqual(zone3['status'], 'validated')
        self.assertEqual(zone3['relationship'], 'opposing_favoured_categories')
        self.assertIn('disagreement in the favoured rainfall category', zone3['text'])
        zone8 = next(p for p in res['paragraphs'] if p['area'] == 'EMI zone VIII')
        self.assertIn('wetter-than-normal', zone8['text'])
        # ICPAC is still a draft: its findings stay unpublished, and its window mismatch is recorded.
        icpac = [p for p in res['paragraphs'] if p['source_id'] == 'icpac_ond_2026_update_rainfall']
        self.assertTrue(icpac and all(p['status'] == 'draft' for p in icpac))
        self.assertIn('Jan 2027', icpac[0]['text'])

    def test_changed_source_needs_review_again(self):
        ef.review(self.reg, 'emi_bega_2026_27_outlook', 'Test reviewer', cache_root=CACHE)
        p = self.tmp / 'extractions/emi_bega_2026_27_outlook.json'
        rec = json.loads(p.read_text(encoding='utf-8'))
        rec['source_sha256'] = '0' * 64                  # as if the provider replaced the PDF
        p.write_text(json.dumps(rec), encoding='utf-8')
        ef.prepare(self.reg, CACHE, MASK, self.tmp / 'sources')
        records = json.loads((self.tmp / 'sources/official_records.json').read_text(encoding='utf-8'))['records']
        self.assertTrue(all(r['extraction_status'] == 'needs_extraction_review'
                            for r in records if r['representation'] == 'zone_tercile_probabilities'))


if __name__ == '__main__':
    unittest.main()
