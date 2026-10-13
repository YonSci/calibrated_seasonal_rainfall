import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import site_files as sf                  # noqa: E402


class Offload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / 'site'
        (self.out / 'downloads/bias/c').mkdir(parents=True)
        (self.out / 'data').mkdir()
        self.big = self.out / 'downloads/bias/c/cells.nc'
        self.big.write_bytes(b'x' * (sf.MIN_BYTES + 1))
        (self.out / 'downloads/small.json').write_text('{}', encoding='utf-8')
        (self.out / 'downloads/report.html').write_bytes(b'<p>' * sf.MIN_BYTES)
        (self.out / 'downloads/other.pdf').write_bytes(b'y' * (sf.MIN_BYTES + 5))
        (self.out / 'index.html').write_text(
            '<a href="downloads/bias/c/cells.nc">a</a><a href="downloads/other.pdf">b</a><a href="downloads/small.json">c</a>'
            '<script>{"href": "downloads/bias/c/cells.nc"}</script>', encoding='utf-8')
        (self.out / 'data/x.json').write_text('{"netcdf": "downloads/bias/c/cells.nc"}', encoding='utf-8')
        (self.out / 'downloads/index.html').write_text('<a href="bias/c/cells.nc">a</a><a href="other.pdf">b</a>', encoding='utf-8')
        self.manifest = sf.MANIFEST
        sf.MANIFEST = Path(self.tmp.name) / 'site_files.json'
        name = sf.asset_name('downloads/bias/c/cells.nc', sf.sha256(self.big))
        self.url = sf.URL + name
        sf.MANIFEST.write_text(json.dumps(dict(release=sf.TAG, assets={name: dict(url=self.url)})), encoding='utf-8')

    def tearDown(self):
        sf.MANIFEST = self.manifest
        self.tmp.cleanup()

    def test_uploaded_files_are_linked_and_removed_others_stay_local(self):
        r = sf.offload(self.out, offline=True)
        self.assertEqual(r['linked'], 1)
        self.assertEqual(r['pending'], ['downloads/other.pdf'])               # large but not uploaded: kept and linked locally
        self.assertFalse(self.big.exists())
        self.assertFalse((self.out / 'downloads/bias').exists())               # emptied folders removed
        page = (self.out / 'index.html').read_text(encoding='utf-8')
        self.assertEqual(page.count(self.url), 2)
        self.assertIn('href="downloads/other.pdf"', page)
        self.assertIn('href="downloads/small.json"', page)
        self.assertIn(self.url, (self.out / 'data/x.json').read_text(encoding='utf-8'))
        listing = (self.out / 'downloads/index.html').read_text(encoding='utf-8')
        self.assertIn(f'href="{self.url}"', listing)
        self.assertIn('href="other.pdf"', listing)
        self.assertTrue((self.out / 'downloads/report.html').exists())         # pages are never offloaded

    def test_asset_names_are_content_addressed_and_safe(self):
        a = sf.asset_name('downloads/probcal/x y/benchmark.json', 'ab' * 32)
        self.assertEqual(a, 'abababababababab-probcal.x_y.benchmark.json')


if __name__ == '__main__':
    unittest.main()
