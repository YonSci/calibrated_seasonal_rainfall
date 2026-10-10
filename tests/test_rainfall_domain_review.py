"""Rainfall-domain review: scientific calculations and integration checks (synthetic data; no local caches needed)."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import rainfall_climatology_core as rc          # noqa: E402
import climatology_reference_core as cr        # noqa: E402
import rainfall_domain_assessment as ra        # noqa: E402

FMAM = [2, 3, 4, 5]


def monthly(values, years, ny=1, nx=1):
    v = np.asarray(values, float).reshape(len(years), 12, ny, nx)
    return xr.DataArray(v, dims=('year', 'month', 'lat', 'lon'),
                        coords=dict(year=years, month=np.arange(1, 13), lat=np.arange(ny) * .25 + 5, lon=np.arange(nx) * .25 + 40))


class Calendar(unittest.TestCase):
    def test_constant_daily_rainfall_gives_120_and_121_mm(self):
        days = np.arange(np.datetime64('2023-01-01'), np.datetime64('2025-01-01'))
        years, m = rc.monthly_totals_from_daily(days, np.ones(len(days)))         # 1 mm/day, mm per one-day interval
        fmam = m[:, [mo - 1 for mo in FMAM]].sum(axis=1)
        self.assertEqual(years, [2023, 2024])
        self.assertEqual(fmam.tolist(), [120.0, 121.0])                          # Feb 29 retained in 2024
        self.assertEqual(m.sum(axis=1).tolist(), [365.0, 366.0])

    def test_missing_or_duplicate_dates_are_rejected(self):
        days = np.arange(np.datetime64('2023-01-01'), np.datetime64('2024-01-01'))
        with self.assertRaises(ValueError):                                      # a date absent from the coordinate
            rc.monthly_totals_from_daily(np.delete(days, 40), np.ones(len(days) - 1))
        with self.assertRaises(ValueError):
            rc.monthly_totals_from_daily(np.r_[days, days[:1]], np.ones(len(days) + 1))

    def test_incomplete_baseline_is_not_relabelled(self):
        years = list(range(1993, 2026))
        m = monthly(np.ones(len(years) * 12), years)
        st = rc.period_status(m.year.values, [1991, 2020])
        self.assertEqual((st['status'], st['missing_years']), ('unavailable', [1991, 1992]))
        with self.assertRaises(rc.IncompleteBaseline):
            rc.climatology(m, 1991, 2020, FMAM)
        self.assertEqual(rc.climatology(m, 1993, 2025, FMAM).attrs['reference_period'], '1993-2025')

    def test_missing_month_makes_the_cell_unclassifiable(self):
        v = np.ones((2, 12, 1, 2))
        v[1, 6, 0, 1] = np.nan                                                   # one July missing in one cell
        c = rc.climatology(monthly(v, [2000, 2001], 1, 2), 2000, 2001, FMAM)
        self.assertTrue(np.isfinite(c.season_share_percent.values[0, 0]))
        self.assertTrue(np.isnan(c.season_share_percent.values[0, 1]))
        self.assertEqual(c.valid_year_count.values.tolist(), [[2, 1]])


class Climatology(unittest.TestCase):
    def test_ratio_of_means_not_mean_of_ratios(self):
        v = np.zeros((2, 12))
        v[:, 1] = 100                        # FMAM 100 in both years (February)
        v[0, 0], v[1, 0] = 100, 900          # annual 200 and 1000
        c = rc.climatology(monthly(v, [2000, 2001]), 2000, 2001, FMAM)
        self.assertAlmostEqual(float(c.season_share_percent.values.squeeze()), 100 * 100 / 600, places=4)   # 16.6667, not 30

    def test_seasonal_identities(self):
        rng = np.random.default_rng(1)
        m = monthly(rng.gamma(2, 30, size=(5 * 12 * 3 * 4)), list(range(2000, 2005)), 3, 4)
        c = rc.climatology(m, 2000, 2004, FMAM)
        mm = c.monthly_mean_mm
        np.testing.assert_allclose(c.season_mean_mm, mm.sel(month=2) + mm.sel(month=[3, 4, 5]).sum('month'))
        np.testing.assert_allclose(c.annual_mean_mm, mm.sum('month'))

    def test_area_weighted_coverage(self):
        self.assertAlmostEqual(rc.area_coverage(np.array([1, 0]), np.array([1, 1.5])), 40.0)
        self.assertAlmostEqual(rc.area_coverage(np.array([1, -1, -2]), np.array([1, 1, 1])), 100 / 3)   # unknown is not included

    def test_country_area_weights_from_intersections(self):
        w, country, outside = rc.country_area_weights(np.arange(3.125, 15, .25), np.arange(33.125, 48, .25),
                                                      'data/boundaries/ethiopia/eth_admin0.shp')
        total = float(w.ethiopia_cell_area_km2.sum())
        self.assertAlmostEqual((total + outside) / country, 1, places=4)
        self.assertTrue(1.0e6 < country < 1.2e6)
        frac = w.ethiopia_fraction.values
        self.assertTrue(((frac >= 0) & (frac <= 1 + 1e-9)).all() and ((frac > 0) & (frac < 1)).any())


class References(unittest.TestCase):
    SHARE = [dict(class_id=1, source_label='< 10', lower_displayed=None, upper_displayed=10, lower_inclusive=True, reference_value=None),
             dict(class_id=2, source_label='11-20', lower_displayed=11, upper_displayed=20, lower_inclusive=True, reference_value=None),
             dict(class_id=3, source_label='21-30', lower_displayed=21, upper_displayed=30, lower_inclusive=True, reference_value=None),
             dict(class_id=4, source_label='> 50', lower_displayed=30, upper_displayed=None, lower_inclusive=False, reference_value=None)]

    def test_values_inside_a_class_have_zero_deviation_and_no_exact_value(self):
        v = np.array([5, 15, 25, 40])
        k = cr.classify_values(v, self.SHARE)
        self.assertEqual(k.tolist(), [0, 1, 2, 3])
        self.assertEqual(cr.interval_deviation(v, k, self.SHARE).tolist(), [0, 0, 0, 0])
        self.assertAlmostEqual(float(cr.interval_deviation(np.array([25.0]), np.array([1]), self.SHARE)[0]), 25 - 20.5)
        self.assertTrue(all(c['reference_value'] is None for c in self.SHARE))
        res = cr.compare_reference_classes(v, np.array([0, 1, 2, 2]), self.SHARE, np.ones(4), {})
        self.assertAlmostEqual(res['exact_agreement'], .75)
        self.assertAlmostEqual(res['within_one_class'], 1.0)

    def test_numeric_comparison_refuses_class_data(self):
        for rep in ('digitized_classes', 'published_image'):
            with self.assertRaises(ValueError):
                cr.compare_numeric_fields(np.ones(3), np.ones(3), np.ones(3), rep)
        r = cr.compare_numeric_fields(np.array([1., 2, 3]), np.array([1., 2, 4]), np.ones(3), 'numeric_grid')
        self.assertAlmostEqual(r['bias'], -1 / 3)

    def test_registry_records_and_modes(self):
        reg = cr.load_registry('config/climatology_references/registry.json')
        rec = reg['references'][0]
        self.assertIsNone(rec['temporal']['reference_years'])
        self.assertEqual(cr.comparison_mode(rec, None, FMAM)[0], 'visual_only')
        bad = json.loads(json.dumps(rec))
        bad['representation']['classes'][0]['reference_value'] = 35
        with self.assertRaises(ValueError):
            cr.check_record(bad)
        ext = dict(status='reviewed', legend=[1], registration={'a': 1}, classification={}, edge_convention={})
        ext['review'] = dict(document_sha256=rec['identity']['document_sha256'], panel_sha256=rec['location']['extracted_image_sha256'],
                             content_sha256=cr.extraction_hash(ext))
        self.assertEqual(cr.comparison_mode(rec, ext, FMAM, [1993, 2025])[0], 'exploratory_class_comparison')   # period undocumented

    def test_implied_membership_leaves_straddling_classes_undecided(self):
        ref = np.array([0, 1, 2, 3, -1])
        self.assertEqual(cr.implied_membership(ref, self.SHARE, 20).tolist(), [0, 0, 1, 1, -1])
        self.assertEqual(cr.implied_membership(ref, self.SHARE, 15).tolist(), [0, -1, 1, 1, -1])


class Candidates(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(7)
        mm = rng.uniform(20, 600, (8, 9))
        share = rng.uniform(2, 70, (8, 9))
        mm[0, 0] = np.nan
        self.clim = xr.Dataset({'season_mean_mm': (('lat', 'lon'), mm), 'season_share_percent': (('lat', 'lon'), share)},
                               coords=dict(lat=np.arange(8) * .25 + 5, lon=np.arange(9) * .25 + 38))
        self.frac = np.ones((8, 9))
        self.frac[-1] = 0

    def test_codes(self):
        codes = ra.classify(self.clim, 100, 20, self.frac)
        self.assertEqual(codes[0, 0], ra.UNKNOWN)
        self.assertTrue((codes[-1] == ra.OUTSIDE).all())

    def test_threshold_monotonicity(self):
        cfg = dict(candidate_thresholds=dict(seasonal_rainfall_mm=[75, 100, 125, 150], annual_share_percent=[10, 15, 20, 25, 30]))
        cands = rc.candidates(cfg)
        codes = {c['id']: ra.classify(self.clim, c['seasonal_rainfall_mm'], c['annual_share_percent'], self.frac) for c in cands}
        self.assertTrue(ra.monotonic(cands, codes))
        area = np.ones((8, 9))
        inc = {c['id']: rc.area_coverage(codes[c['id']], area) for c in cands}
        for c in cands:
            for d in cands:
                if d['seasonal_rainfall_mm'] >= c['seasonal_rainfall_mm'] and d['annual_share_percent'] >= c['annual_share_percent']:
                    self.assertLessEqual(inc[d['id']], inc[c['id']])


class Provenance(unittest.TestCase):
    def test_changed_inputs_make_the_assessment_stale(self):
        import run_rainfall_domain_review as runner
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for ext in ('.shp', '.shx', '.dbf', '.prj'):
                shutil.copy2(ROOT / f'data/boundaries/ethiopia/eth_admin0{ext}', tmp / f'b{ext}')
            cache = tmp / 'cache.nc'
            xr.Dataset({'monthly_total': (('year',), [1.0])}, attrs=dict(source_sha256='abc')).to_netcdf(cache)
            cfg = rc.load_review_config('config/rainfall_domains/fmam_review.json')
            cfg.update(country_boundary=str(tmp / 'b.shp'), monthly_cache=str(cache), comparators=[], reference_ids=[])
            before = runner.fingerprint(cfg)
            with open(tmp / 'b.shp', 'ab') as f:
                f.write(b'\0')
            after = runner.fingerprint(cfg)
            self.assertNotEqual(before['country_boundary'], after['country_boundary'])
            xr.Dataset({'monthly_total': (('year',), [1.0])}, attrs=dict(source_sha256='changed')).to_netcdf(cache)
            self.assertNotEqual(after['chirps_source_sha256'], runner.fingerprint(cfg)['chirps_source_sha256'])
        rec = cr.load_registry('config/climatology_references/registry.json')['references'][1]
        ext = dict(status='reviewed', legend=[[1, 2, 3]], registration={'affine': [[1, 0, 0], [0, 1, 0]]}, classification={}, edge_convention={})
        ext['review'] = dict(document_sha256=rec['identity']['document_sha256'], panel_sha256=rec['location']['extracted_image_sha256'],
                             content_sha256=cr.extraction_hash(ext))
        self.assertEqual(cr.extraction_state(rec, ext), 'reviewed')
        ext['legend'] = [[9, 9, 9]]                                              # analyst choice changed after the review
        self.assertEqual(cr.extraction_state(rec, ext), 'stale')
        self.assertEqual(cr.comparison_mode(rec, ext, FMAM)[0], 'visual_only')


class Integration(unittest.TestCase):
    def test_exported_mask_contract_and_one_definition(self):
        import run_rainfall_domain_review as runner
        import presentation_layers as pl
        cfg = rc.load_review_config('config/rainfall_domains/fmam_review.json')
        clim = xr.Dataset({'season_mean_mm': (('lat', 'lon'), [[150., 50.]]), 'annual_mean_mm': (('lat', 'lon'), [[500., 1000.]]),
                           'season_share_percent': (('lat', 'lon'), [[30., 5.]])}, coords=dict(lat=[5.0], lon=[40.0, 40.25]))
        codes = np.array([[1, 0]], 'int8')
        spec = dict(seasonal_rainfall_mm=100, annual_share_percent=20)
        row = dict(included_country_percent=50.0, included_area_km2=700.0)
        out = runner.domain_dataset(cfg, codes, clim, 'mm100_share20', spec, row, {}, 'test', 'v1')
        self.assertEqual(out.season_domain.values.tolist(), [[1, 0]])
        self.assertEqual(out.season_share_of_annual.values.tolist(), [[.3, .05]])                    # fraction, not percent
        self.assertEqual(out.attrs['season'], 'FMAM')
        self.assertIn('>= 100 mm', out.attrs['domain_definition'])
        self.assertIn('>= 20%', out.attrs['view_label'])
        recs = [dict(domain_definition=out.attrs['domain_definition'])] * 3
        self.assertEqual(pl.gallery_definition(recs)[0], out.attrs['domain_definition'])
        with self.assertRaises(ValueError):                                     # products from two masks never share one caption
            pl.gallery_definition(recs + [dict(domain_definition='another domain')])


if __name__ == '__main__':
    unittest.main()
