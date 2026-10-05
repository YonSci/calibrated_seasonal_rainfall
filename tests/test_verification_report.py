"""Report consistency tests using the delivered evidence snapshots; no model fitting."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from verification_report_core import validate, performance_notes, export_report

# Evidence snapshots: the delivered Step 32 folder if installed, otherwise the
# locally built Jun-Aug report (same evidence/ and maps/ layout).
REPORT_CANDIDATES = [ROOT / 'completed_report', ROOT / 'outputs/verification_report_2026/Jun_Jul_Aug']
REPORT_DIR = next((d for d in REPORT_CANDIDATES if (d / 'evidence/country_summary.json').is_file()), None)


class EmbeddedImages(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = []
        self.remote_resources = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'img':
            self.images.append(a.get('src', ''))
        if tag in ['img', 'script', 'link']:
            for key in ['src', 'href']:
                if a.get(key, '').startswith(('http:', 'https:', '//')):
                    self.remote_resources.append(a[key])


class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if REPORT_DIR is None:
            raise unittest.SkipTest('No Jun-Aug verification evidence; run build_verification_report.py --targets Jun Jul Aug')
        folder = REPORT_DIR / 'evidence'
        cls.country = json.loads((folder / 'country_summary.json').read_text())
        cls.regimes = json.loads((folder / 'regime_summary.json').read_text())
        cls.history = json.loads((folder / 'historical_review.json').read_text())

    def test_real_evidence_and_no_invented_season(self):
        validate(self.country, self.regimes, ['Jun', 'Jul', 'Aug'])
        with self.assertRaisesRegex(ValueError, 'Targets missing'):
            validate(self.country, self.regimes, ['JJAS'])
        notes = performance_notes(self.regimes, ['Jun', 'Jul', 'Aug'])
        june_r0 = next(n for n in notes if n['target'] == 'Jun' and n['domain'] == 'regime_0')
        self.assertEqual(june_r0['amount_comparison'], 'below_climatology')
        self.assertEqual(june_r0['probability_comparison'], 'below_climatology')
        august_r3 = next(n for n in notes if n['target'] == 'Aug' and n['domain'] == 'regime_3')
        self.assertEqual(august_r3['blend_effect'], 'improved_RPS')
        self.assertEqual(august_r3['negative_bss_categories'], ['above'])

    def test_reject_mixed_hashes_and_bad_scores(self):
        for kind in ['hash', 'rps', 'partition']:
            d = copy.deepcopy(self.regimes)
            if kind == 'hash':
                d['results'][0]['provenance']['forecast_sha256'] = 'different'
            elif kind == 'rps':
                d['results'][0]['domains']['regime_1']['probability']['shared_blend']['rps'] += .1
            else:
                d['results'][0]['domains']['regime_1']['amount_cells'] += 1
            with self.assertRaises(ValueError):
                validate(self.country, d, ['Jun'])

    def test_portable_report_and_evidence_preservation(self):
        original = json.dumps(self.regimes, sort_keys=True)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            source = REPORT_DIR / 'maps/Jun_verification.png'
            result = export_report(self.country, self.regimes, self.history, ['Jun', 'Jul', 'Aug'], out,
                                   {'audit_scope': 'Test build from actual supplied summaries.', 'source_sha256': {}}, {'Jun': source})
            self.assertFalse(result['full_JJAS_verified'])
            self.assertFalse(result['forecast_changed'])
            self.assertEqual(result['targets_pending_in_report'], ['Sep', 'JJAS'])
            parser = EmbeddedImages()
            page = (out / 'VERIFICATION_REPORT.html').read_text()
            parser.feed(page)
            self.assertEqual(len(parser.images), 1)
            self.assertTrue(parser.images[0].startswith('data:image/png;base64,'))
            self.assertFalse(parser.remote_resources)
            self.assertIn('Pending in this report: Sep, JJAS', page)
            self.assertIn('above-normal-category Brier Skill Score', page)
            self.assertTrue((out / 'VERIFICATION_ADDENDUM.md').is_file())
            self.assertTrue((out / 'evidence/regime_summary.json').is_file())
        self.assertEqual(json.dumps(self.regimes, sort_keys=True), original)


if __name__ == '__main__':
    unittest.main(verbosity=2)
