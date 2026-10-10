"""CHIRPS v3 track: tile reading and aggregation onto the 0.25 degree grid, and the v2/v3 comparison helpers."""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import prepare_chirps_v3 as p3                # noqa: E402
import compare_chirps_versions as cv          # noqa: E402


def write_tile(path, data):
    """A GeoTIFF shaped like the CHIRPS v3 Africa tiles (0.05 deg, origin 20W 40N)."""
    import tifffile
    tifffile.imwrite(path, data.astype('float32'), compression='lzw', extratags=[
        (33550, 'd', 3, (p3.PIXEL, p3.PIXEL, 0.0), False),                      # ModelPixelScaleTag
        (33922, 'd', 6, (0.0, 0.0, 0.0, p3.WEST, p3.NORTH, 0.0), False)])        # ModelTiepointTag


class Aggregation(unittest.TestCase):
    def test_blocks_align_with_the_quarter_degree_cells(self):
        data = np.full(p3.SHAPE, 2.0)
        lat, lon = np.array([3.125, 3.375]), np.array([33.125])
        # the 0.05 deg cells of the cell centred 3.125N 33.125E: rows for 3.25..3.0N, columns for 33.0..33.25E
        r0, c0 = round((p3.NORTH - 3.25) / p3.PIXEL), round((33.0 - p3.WEST) / p3.PIXEL)
        data[r0:r0 + 5, c0:c0 + 5] = 7.0
        data[r0, c0] = -9999.0                                   # one missing sub-cell
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 't.tif'
            write_tile(f, data)
            block = p3.read_block(f, lat, lon)
        self.assertEqual(block.shape, (2, 5, 1, 5))
        self.assertEqual(int(np.isfinite(block[0]).sum()), 24)
        self.assertAlmostEqual(float(np.nanmean(block[0])), 7.0)   # southern cell: the 7s, minus the missing one
        self.assertAlmostEqual(float(np.nanmean(block[1])), 2.0)   # the cell to its north is untouched

    def test_unexpected_grid_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 't.tif'
            write_tile(f, np.zeros((10, 10)))
            with self.assertRaises(ValueError):
                p3.read_block(f, np.array([3.125]), np.array([33.125]))


class Comparison(unittest.TestCase):
    def test_cross_year_season_takes_next_january(self):
        ym = np.zeros((2, 12, 1, 1))
        ym[0, 9:12] = 10.0                     # Oct-Dec of year 1
        ym[1, 0] = 5.0                         # January of year 2
        tot = cv.season_totals(ym, [10, 11, 12, 1], cross_year=True)
        self.assertEqual(tot.shape[0], 1)      # one complete ONDJ season from two calendar years
        self.assertAlmostEqual(float(tot[0, 0, 0]), 35.0)

    def test_categories_and_correlation(self):
        x = np.array([[1.0], [2.0], [3.0], [4.0], [5.0], [6.0]])[:, :, None]
        q = cv.terciles(x)
        self.assertEqual(cv.category(x, q)[:, 0, 0].tolist(), [0, 0, 1, 1, 2, 2])
        self.assertAlmostEqual(float(cv.corr(x, 2 * x + 1)[0, 0]), 1.0)



class MonthlyArchive(unittest.TestCase):
    """prepare_seasonal: a monthly CHIRPS archive (v3 track) sums whole months; incomplete seasons are refused."""

    def setUp(self):
        import pandas as pd
        import xarray as xr
        times = pd.date_range('2024-09-01', '2025-02-01', freq='MS')
        data = np.ones((len(times), 1, 2))
        data[:, 0, 1] = np.nan                                     # one cell missing throughout
        self.da = xr.DataArray(data, dims=('time', 'lat', 'lon'), coords=dict(time=times, lat=[5.0], lon=[40.0, 40.25]),
                               attrs={'units': 'mm'})
        self.cfg = dict(initialization_month=9, season=dict(name='ONDJ', start='10-01', end='01-31'),
                        chirps_temporal='monthly', chirps_variable='monthly_total')

    def test_cross_year_sum_and_day_count(self):
        import prepare_seasonal as ps
        out = ps.chirps_season(self.da.to_dataset(name='monthly_total'), self.cfg, 2024)
        self.assertEqual(float(out.precip_season.values[0, 0, 0]), 4.0)      # Oct, Nov, Dec 2024 and Jan 2025
        self.assertTrue(np.isnan(out.precip_season.values[0, 0, 1]))
        self.assertEqual(int(out.valid_day_count.values[0, 0, 0]), 123)
        self.assertEqual(out.attrs['expected_days'], 123)

    def test_missing_month_is_refused(self):
        import prepare_seasonal as ps
        short = self.da.sel(time=self.da.time < np.datetime64('2025-01-01')).to_dataset(name='monthly_total')
        with self.assertRaisesRegex(ValueError, 'Missing CHIRPS months'):
            ps.chirps_season(short, self.cfg, 2024)


if __name__ == '__main__':
    unittest.main()
