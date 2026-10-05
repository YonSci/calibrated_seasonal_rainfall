"""Synthetic checks; no actual forecast/CHIRPS files are needed."""
import sys
from pathlib import Path
import unittest
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import numpy as np
import pandas as pd
import xarray as xr
from common import save_netcdf
from prepare_seasonal import model_season, chirps_season

CFG = {"ecmwf_variable": "tp", "chirps_variable": "precip", "initialization_month": 5,
       "season": {"start": "06-01", "end": "09-30"}, "negative_increment_tolerance_mm": 0.001}


def model(members=25):
    dates = pd.date_range("1993-05-02", "1993-10-31")
    values = np.broadcast_to(np.arange(1, len(dates) + 1)[:, None, None, None] * .001,
                             (len(dates), members, 2, 2)).copy()
    return xr.Dataset({"tp": (("forecast_period", "number", "latitude", "longitude"),
                               values, {"units": "m"})}, coords={
        "forecast_period": np.arange(len(dates)), "number": np.arange(members),
        "latitude": [10.5, 9.5], "longitude": [38.5, 39.5],
        "valid_time": ("forecast_period", dates),
        "forecast_reference_time": np.datetime64("1993-05-01")})


class PreparationTests(unittest.TestCase):
    def test_one_mm_per_day(self):
        out, qc = model_season(model(), CFG, 1993)
        np.testing.assert_allclose(out.precip_season, 122.0)
        self.assertEqual(qc["members"], 25)

    def test_51_members(self):
        out, _ = model_season(model(51), CFG, 1993)
        self.assertEqual(out.sizes["member"], 51)

    def test_boundary_days(self):
        ds = model()
        # Rain on May 31 must be excluded; rain on Sep 30 must be included.
        starts = pd.DatetimeIndex(ds.valid_time.values) - pd.Timedelta(days=1)
        increments = np.zeros(len(starts))
        increments[starts == "1993-05-31"] = 100
        increments[starts == "1993-09-30"] = 7
        ds.tp.values[:] = np.cumsum(increments)[:, None, None, None] / 1000
        out, _ = model_season(ds, CFG, 1993)
        np.testing.assert_allclose(out.precip_season, 7.0)

    def test_reset_rejected(self):
        ds = model()
        ds.tp.values[80:] = 0
        with self.assertRaisesRegex(ValueError, "Negative increments"):
            model_season(ds, CFG, 1993)

    def test_gap_rejected(self):
        ds = model().isel(forecast_period=[i for i in range(183) if i != 70])
        with self.assertRaisesRegex(ValueError, "non-daily"):
            model_season(ds, CFG, 1993)

    def test_missing_member_cell_remains_missing(self):
        ds = model()
        ds.tp.values[80, 0, 0, 0] = np.nan
        out, _ = model_season(ds, CFG, 1993)
        self.assertTrue(np.isnan(out.precip_season.values[0, 0, 0]))

    def test_units_rejected(self):
        ds = model()
        ds.tp.attrs["units"] = "mm"
        with self.assertRaisesRegex(ValueError, "metres"):
            model_season(ds, CFG, 1993)

    def test_chirps_missing_day_pixel(self):
        dates = pd.date_range("1993-06-01", "1993-09-30")
        data = np.ones((len(dates), 2, 2))
        data[5, 0, 0] = np.nan
        ds = xr.Dataset({"precip": (("time", "lat", "lon"), data, {"units": "mm/day"})},
                        coords={"time": dates, "lat": [9.125, 9.375], "lon": [38.125, 38.375]})
        out = chirps_season(ds, CFG, 1993)
        self.assertTrue(np.isnan(out.precip_season.values[0, 0, 0]))
        self.assertEqual(float(out.precip_season.values[0, 1, 1]), 122)

    def test_netcdf_roundtrip(self):
        out, _ = model_season(model(), CFG, 1993)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.nc"
            save_netcdf(out, path)
            with xr.open_dataset(path) as reopened:
                np.testing.assert_allclose(reopened.precip_season, 122)


if __name__ == "__main__":
    unittest.main()
