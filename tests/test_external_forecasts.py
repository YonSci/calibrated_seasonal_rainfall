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

    def test_emi_skips_a_matching_page_without_a_document(self):
        pages = {
            'L1': b'<a href="/f/bega-forecast/">Bega 2026/27 Seasonal Climate Forecast</a>',
            'L2': b'<a href="/h/bulletin/">Kiremt 2026 Assessment and Bega 2026_27 Outlook Hydro met Bulletin</a>',
            'https://x.test/f/bega-forecast/': b'<h1>Bega 2026/27 Seasonal Climate Forecast</h1>',
            'https://x.test/h/bulletin/': b'<a href="/documents/1/bulletin.pdf">PDF</a>'}
        real = ef.fetch
        ef.fetch = lambda url, **kw: (url, pages[url], {})
        try:
            a = ef.EMIAdapter(dict(outlook_season='bega', outlook_years=[2026, 2027], listing_urls=['L1', 'L2']))
            import urllib.parse
            orig = urllib.parse.urljoin
            urllib.parse.urljoin = lambda base, u: u if u.startswith('http') else 'https://x.test' + u
            try:
                found = a.discover()
            finally:
                urllib.parse.urljoin = orig
        finally:
            ef.fetch = real
        self.assertTrue(found['download_url'].endswith('bulletin.pdf'))
        self.assertEqual(found['skipped'][0]['reason'], 'no PDF on the page yet')

    def test_year_forms(self):
        self.assertEqual(ef._years('Bega 2026_27'), {2026, 2027})
        self.assertEqual(ef._years('bega 2025/26'), {2025, 2026})
        self.assertEqual(ef._years('bega-202526'), {2025, 2026})

    def test_extraction_status_follows_source_hash(self):
        rec = dict(source_sha256='a' * 64, status='validated')
        self.assertEqual(ef.extraction_status(rec, 'a' * 64), 'needs_extraction_review')   # not bound to its contents
        rec['review'] = dict(content_sha256=ef.content_sha256(rec))
        self.assertEqual(ef.extraction_status(rec, 'a' * 64), 'validated')
        self.assertEqual(ef.extraction_status(rec, 'b' * 64), 'needs_extraction_review')
        self.assertEqual(ef.extraction_status(dict(rec, status='draft'), 'a' * 64), 'needs_extraction_review')
        self.assertEqual(ef.extraction_status(None, 'a' * 64), 'needs_extraction')


class Rules(unittest.TestCase):
    def test_tied_leaders_have_no_favoured_category(self):
        self.assertEqual(favoured([.40, .40, .20], .4), 'weak')
        self.assertEqual(favoured([.41, .40, .19], .4), 'below')

    def test_review_covers_the_extracted_contents(self):
        rec = dict(source_sha256='a' * 64, status='validated', zones=[dict(zone_label='III', probabilities=dict(below=.2, near=.25, above=.55))])
        rec['review'] = dict(content_sha256=ef.content_sha256(rec))
        self.assertEqual(ef.extraction_status(rec, 'a' * 64), 'validated')
        rec['zones'][0]['probabilities'] = dict(below=.55, near=.25, above=.2)      # edited after review
        self.assertEqual(ef.extraction_check(rec, 'a' * 64), ('needs_extraction_review', 'The extracted values or settings changed after review'))

    def test_number_formatting(self):
        from interpret_external_forecasts import share, share1, rounded_triple
        self.assertEqual((share(.9965), share(.003), share(1.0), share(0.0), share(.4547)), ('>99%', '<1%', '100%', '0%', '45%'))
        self.assertEqual((share1(.94478), share1(1.0)), ('94.5%', '100%'))
        self.assertEqual(sum(rounded_triple([.2196, .2432, .5372])), 100)
        self.assertEqual(rounded_triple([.2196, .2432, .5372]), [22, 24, 54])

    def test_stale_inputs_are_named(self):
        from site_extras import _stale_reasons
        saved = dict(native_sha256='n', domain_mask_sha256='m', registry_sha256='r',
                     sources=dict(s1=dict(sha256='x', extraction_status='validated', content_sha256='c')))
        self.assertEqual(_stale_reasons(saved, saved), [])
        now = dict(saved, native_sha256='n2', sources=dict(s1=dict(sha256='x', extraction_status='validated', content_sha256='c2')))
        self.assertEqual(_stale_reasons(saved, now), ['the platform forecast', 'the extraction record of s1'])

    def test_favoured_and_relationship(self):
        self.assertEqual(favoured([.2, .25, .55], .4), 'above')
        self.assertEqual(favoured([.35, .33, .32], .4), 'weak')
        self.assertEqual(relationship('below', 'above'), 'opposing_favoured_categories')
        self.assertEqual(relationship('above', 'above'), 'same_favoured_category')
        self.assertEqual(relationship('near', 'above'), 'near_versus_other')
        self.assertEqual(relationship('weak', 'above'), 'weak_signal')

    def test_scores_against_observations(self):
        from verify_external_forecasts import outcome, score
        self.assertEqual(outcome('above', 2), 'hit')
        self.assertEqual(outcome('below', 2), 'opposite')
        self.assertEqual(outcome('near', 0), 'near_other')
        # Four equal-area cells: observed above, above, below, and one not scored (-1).
        obs = np.array([[2, 2], [0, -1]])
        fav = np.array([['above', 'above'], ['above', 'weak']], dtype=object)
        clim = np.full((2, 2, 3), 1 / 3)
        w, mask = np.ones((2, 2)), np.ones((2, 2), bool)
        r = score(fav, obs, clim, w, mask)
        self.assertEqual(r['cells'], 3)
        self.assertAlmostEqual(r['favoured_share'], 1.0)
        self.assertAlmostEqual(r['hit_share'], 2 / 3)
        self.assertAlmostEqual(r['opposite_share'], 1 / 3)
        self.assertAlmostEqual(r['chance_of_favoured'], 1 / 3)
        self.assertNotIn('rpss', r)                       # no probabilities given (as for ICPAC)
        # Probabilities equal to climatology score RPSS 0 against that climatology.
        from verify2026_math import probability_losses
        _, rps_clim, _ = probability_losses(clim, obs)
        r = score(fav, obs, clim, w, mask, clim, rps_clim)
        self.assertAlmostEqual(r['rpss'], 0.0)
        sharp = np.where(obs[..., None] == 2, [[[.1, .2, .7]]], [[[.2, .3, .5]]])
        self.assertGreater(score(fav, obs, clim, w, mask, sharp, rps_clim)['rpss'], 0)

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
        # Region layer still a draft: whole-zone means stay out of the published columns and paragraphs.
        row3 = next(r for r in res['emi_table'] if r['zone'] == 'III')
        self.assertIsNone(row3.get('zone_mean'))
        self.assertTrue(row3.get('zone_mean_draft'))
        self.assertNotIn('whole zone', zone3['text'])
        zone8 = next(p for p in res['paragraphs'] if p['area'] == 'EMI zone VIII')
        self.assertIn('wetter-than-normal', zone8['text'])
        # ICPAC is still a draft: its findings stay unpublished, and its window mismatch is recorded.
        icpac = [p for p in res['paragraphs'] if p['source_id'] == 'icpac_ond_2026_update_rainfall']
        self.assertTrue(icpac and all(p['status'] == 'draft' for p in icpac))
        self.assertIn('Jan 2027', icpac[0]['text'])
        # Area-scoped summaries: zone III (west) is outside the ONDJ domain, so only the national summary names it.
        emi = {i['area_key']: i for i in res['summary'] if i['id'].startswith('emi_zones_')}
        self.assertIn('zone III', emi['all_ethiopia']['text'])
        self.assertNotIn('zone III', emi['season_domain']['text'])
        # ICPAC table: one row per sampled location plus one per area, ICPAC values as category + printed interval.
        it = res['icpac_table']
        self.assertEqual(sorted(r['zone'] for r in it if r['kind'] == 'sample'), ['III', 'VI', 'VII', 'VIII'])
        self.assertEqual({r['area_key'] for r in it if r['kind'] == 'area'}, {'all_ethiopia', 'season_domain'})
        row8 = next(r for r in it if r.get('zone') == 'VIII')
        self.assertTrue(row8['official'].startswith('Above normal') and '%' in row8['official'])
        self.assertEqual(sum(int(x.rstrip('%')) for x in row8['platform'].split(' / ')), 100)
        robust = next(i for i in res['summary'] if i['id'] == 'robustness_summary')
        self.assertIn('not statistical confidence intervals', robust['text'])
        # The synthetic forecast changes from below to above at 36 deg E, within the tested shifts of zone III's
        # arrow tip (35.7 deg E): the sensitivity check must flag it; zone VIII (43.5 deg E) is stable.
        table = {r['zone']: r for r in res['emi_table']}
        self.assertFalse(table['III']['stable'])
        self.assertTrue(table['VIII']['stable'])

    def test_reviewed_regions_publish_whole_zone_means(self):
        ef.review(self.reg, 'emi_bega_2026_27_outlook', 'Test reviewer', cache_root=CACHE)
        ef.review(self.reg, 'emi_rainfall_regions', 'Test reviewer', cache_root=CACHE)
        res = self.run_all()
        row3 = next(r for r in res['emi_table'] if r['zone'] == 'III')
        self.assertTrue(row3['zone_mean'] and row3['zone_name'] == 'Southwest')
        self.assertIsNone(row3.get('zone_mean_draft'))
        para = next(p for p in res['paragraphs'] if p['area'] == 'EMI zone III')
        self.assertIn('whole zone', para['text'])
        maps = json.loads((self.tmp / 'comparison/comparison.json').read_text(encoding='utf-8'))['maps']
        self.assertIn('emi_bega_2026_27_outlook_regions.png', maps)

    def test_layout_change_is_reported_not_fatal(self):
        p = self.tmp / 'extractions/icpac_ond_2026_update_rainfall.json'
        rec = json.loads(p.read_text(encoding='utf-8'))
        rec['template']['x_ticks_deg'] = rec['template']['x_ticks_deg'][:-1]      # as if the map layout changed
        p.write_text(json.dumps(rec), encoding='utf-8')
        ef.prepare(self.reg, CACHE, MASK, self.tmp / 'sources')
        manifest = json.loads((self.tmp / 'sources/source_manifest.json').read_text(encoding='utf-8'))
        icpac = next(s for s in manifest['sources'] if s['source_id'] == 'icpac_ond_2026_update_rainfall')
        self.assertEqual(icpac['extraction']['status'], 'needs_extraction_review')
        self.assertIn('does not fit', icpac['extraction']['note'])
        compare(self.tmp / 'sources', self.native(), MASK, self.reg, self.tmp / 'comparison')   # still runs

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


ONDJ_OUT = ROOT / 'outputs/operational_2026_ondj/comparisons'


class Publication(unittest.TestCase):
    def test_overlap_labels(self):
        from site_extras import overlap_label
        self.assertEqual(overlap_label(0.0), 'Outside the domain')
        self.assertEqual(overlap_label(1.0), 'Entire sample in the domain')
        self.assertEqual(overlap_label(0.4375), 'Partly overlaps the domain — 44% of sample cells')

    def test_threshold_and_manifest_staleness(self):
        from site_extras import _stale_reasons, saved_output_consistency
        saved = dict(native_sha256='n', domain_mask_sha256='m', registry_sha256='r', minimum_leading_probability=0.4, sources={})
        self.assertEqual(_stale_reasons(saved, dict(saved, minimum_leading_probability=0.5)), ['the favoured-category threshold'])
        manifest = dict(sources=[dict(source_id='s1', sha256='x', extraction=dict(status='validated', content_sha256='c'))])
        comparison = dict(inputs=dict(saved, sources=dict(s1=dict(sha256='x', extraction_status='validated', content_sha256='c'))))
        self.assertEqual(saved_output_consistency(manifest, comparison, dict(inputs=comparison['inputs'])), [])
        manifest['sources'][0]['sha256'] = 'y'                      # e.g. a restored older manifest
        self.assertIn('the saved source manifest', saved_output_consistency(manifest, comparison, dict(inputs=comparison['inputs']))[0])

    @unittest.skipUnless((ONDJ_OUT / 'interpretation/interpretation.json').is_file(), 'ONDJ comparison outputs not present')
    def test_public_reports_use_published_data_only(self):
        import dataclasses
        from cycle import load_cycle
        from site_extras import export_comparison, local_images
        tmp = Path(tempfile.mkdtemp()).resolve()
        try:
            shutil.copytree(ONDJ_OUT, tmp / 'comparisons')
            p = tmp / 'comparisons/interpretation/interpretation.json'
            interp = json.loads(p.read_text(encoding='utf-8'))
            marker = 'UNREVIEWED-DRAFT-MARKER 12.3%'
            interp['paragraphs'].append(dict(id='x', finding='x', source_id='s', area='A', area_key='all_ethiopia', status='draft',
                                             relationship=None, text=marker, evidence_ids=[]))
            interp['summary'].append(dict(id='y', area_key='all_ethiopia', source_id='s', status='draft', title='Draft', text=marker,
                                          evidence_ids=[], scope={}))
            p.write_text(json.dumps(interp), encoding='utf-8')
            c = load_cycle(ROOT / 'config/cycles/sep_2026_ondj.json')
            raw = dict(c.raw, external_comparison=dict(c.raw['external_comparison'], output_root=str(tmp / 'comparisons')))
            site = tmp / 'site'
            res = export_comparison(dataclasses.replace(c, raw=raw), 'ondj2026', site)
            for f in ['downloads/ondj2026_comparison_report.html', 'downloads/ondj2026_comparison_report_package.html',
                      'downloads/ondj2026_comparison.json', 'data/ondj2026_comparison.json']:
                self.assertNotIn('UNREVIEWED-DRAFT-MARKER', (site / f).read_text(encoding='utf-8'), f)
            packaged = (site / 'downloads/ondj2026_comparison_report_package.html').read_text(encoding='utf-8')
            in_zip = {z for _, z in res['package']}
            self.assertTrue(local_images(packaged))
            self.assertTrue(all('comparison/' + s in in_zip for s in local_images(packaged)))
            web = (site / 'downloads/ondj2026_comparison_report.html').read_text(encoding='utf-8')
            self.assertTrue(all((site / 'downloads' / s).resolve().is_file() for s in local_images(web)))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


REGIONS = ROOT / 'data/masks/emi_rainfall_regions_korecha2013.nc'
REGION_IMAGE = ROOT / 'data/raw/reference/ethiopia_homogeneous_rainfall_regions_10.1002_2013WR013760.png'


@unittest.skipUnless(REGIONS.is_file(), 'digitized regions not present')
class RainfallRegions(unittest.TestCase):
    def test_emi_arrow_tips_fall_in_the_region_with_the_same_number(self):
        import xarray as xr
        rec = json.loads((ROOT / 'config/external_forecasts/extractions/emi_bega_2026_27_outlook.json').read_text(encoding='utf-8'))
        names = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII']
        with xr.open_dataset(REGIONS) as d:
            r, lat, lon = d.region.values, d.lat.values, d.lon.values
            self.assertEqual(json.loads(d.attrs['region_names'])['VIII'], 'South-Southeast lowlands')
            self.assertIn('10.1002/2013WR013760', d.attrs['doi'])
        for z in rec['zones']:
            i, j = np.argmin(abs(lat - z['anchor']['lat'])), np.argmin(abs(lon - z['anchor']['lon']))
            self.assertEqual(names[r[i, j] - 1], z['zone_label'])
        self.assertEqual(set(np.unique(r)) - {0}, set(range(1, 9)))

    @unittest.skipUnless(REGION_IMAGE.is_file(), 'source figure is kept locally only')
    def test_digitization_reproduces_the_stored_grid(self):
        import xarray as xr
        from digitize_rainfall_regions import digitize, to_grid
        rec = json.loads((ROOT / 'config/external_forecasts/extractions/emi_rainfall_regions.json').read_text(encoding='utf-8'))
        region, lon, lat, qc = digitize(REGION_IMAGE, rec['template'])
        with xr.open_dataset(REGIONS) as d:
            grid = to_grid(region, lon, lat, d.lat.values.astype(float), d.lon.values.astype(float), 0.25)
            self.assertTrue(np.array_equal(grid, d.region.values))
        self.assertEqual(len(set(qc['components'].values())), 8)


class FigureTools(unittest.TestCase):
    @unittest.skipUnless(HAVE_CACHE, 'official snapshots not present')
    def test_draft_layout_detection_on_the_ond_map(self):
        current = json.loads((CACHE / 'ondj_2026_27/current.json').read_text())['icpac_ond_2026_update_rainfall']
        lay = ef.detect_dominant_map_layout(ROOT / current['file'])
        self.assertEqual((len(lay['x_ticks_px']), len(lay['y_ticks_px'])), (6, 7))
        self.assertEqual([len(b) for b in lay['legend_bars']], [6, 5, 5])
        self.assertEqual(lay['legend_bars'][0][0], [9, 63, 33])          # the bar's centre colour, not its edge

    def test_zone_figure_digitization(self):
        """A synthetic two-zone figure: west half one colour, east half another, placed by the country outline box."""
        from PIL import Image
        import xarray as xr
        tmp = Path(tempfile.mkdtemp())
        try:
            img = np.full((300, 400, 3), 255, 'uint8')
            img[20:280, 20:200] = (54, 222, 42)
            img[20:280, 200:380] = (18, 138, 54)
            Image.fromarray(img).save(tmp / 'fig.png')
            rec = dict(geometry=dict(method='fill_colour_zones', colour_tolerance=40, bbox_deg=[33.0, 48.0, 3.4, 14.9]),
                       zones=[dict(zone_label='West', fill_rgb=[54, 222, 42]), dict(zone_label='East', fill_rgb=[18, 138, 54])])
            with xr.open_dataset(MASK) as m:
                lat, lon = m.lat.values.astype(float), m.lon.values.astype(float)
            grid, qc = ef.digitize_zone_figure(tmp / 'fig.png', rec, lat, lon)
            i = int(np.argmin(abs(lat - 9.0)))
            self.assertEqual(grid[i, int(np.argmin(abs(lon - 35.0)))], 'West')
            self.assertEqual(grid[i, int(np.argmin(abs(lon - 45.0)))], 'East')
            self.assertEqual(qc['bbox_deg'], [33.0, 48.0, 3.4, 14.9])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
