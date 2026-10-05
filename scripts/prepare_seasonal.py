"""Prepare native-grid seasonal totals only. No bias correction or regridding.

Explicit source contract: ECMWF tp in metres accumulated since initialization,
first endpoint at init+24 h, and all endpoints 24 h apart. CHIRPS is daily mm.
Unsupported structures fail rather than guessing units or interval meanings.
"""
import argparse
from datetime import datetime, timezone
import json
import numpy as np
import pandas as pd
import xarray as xr
from common import ROOT, load_config, make_folders, model_path, source_path, save_json, save_netcdf, season_window
from cycle import CYCLE


def season_dates(cfg, year):
    start, end = season_window(cfg, year)
    return pd.date_range(start, end, freq="D")


def open_model(ds, cfg):
    """Return a standard (time, member, lat, lon) cumulative array and init date."""
    var = cfg["ecmwf_variable"]
    da = ds[var]
    if str(da.attrs.get("units", "")).strip().lower() not in {"m", "metres", "meters"}:
        raise ValueError(f"{var}: expected cumulative metres, found units={da.attrs.get('units')!r}")
    ref = np.asarray(ds["forecast_reference_time"].values).reshape(-1)
    if len(ref) != 1:
        raise ValueError("Expected one forecast_reference_time per file")
    init = pd.Timestamp(ref[0])
    # Drop only singleton dimensions outside the four required axes.
    names = {"forecast_period", "number", "latitude", "longitude"}
    for dim in list(da.dims):
        if dim not in names:
            if da.sizes[dim] != 1:
                raise ValueError(f"Unexpected non-singleton dimension: {dim}")
            da = da.isel({dim: 0}, drop=True)
    if set(da.dims) != names:
        raise ValueError(f"Expected dimensions {sorted(names)}, found {list(da.dims)}")
    vt = np.asarray(ds["valid_time"].values).squeeze().reshape(-1)
    times = pd.DatetimeIndex(vt)
    if len(times) != da.sizes["forecast_period"] or len(times) < 2:
        raise ValueError("valid_time must match the forecast_period axis")
    if init != init.normalize() or times[0] != init + pd.Timedelta(days=1):
        raise ValueError("Expected midnight initialization and first endpoint at init+24h")
    if not np.all(np.diff(times.asi8) == pd.Timedelta(days=1).value):
        raise ValueError("Missing, duplicate, unordered, or non-daily ECMWF endpoints")
    da = da.rename({"forecast_period": "time", "number": "member", "latitude": "lat", "longitude": "lon"})
    da = da.transpose("time", "member", "lat", "lon")
    for axis in ("member", "lat", "lon"):
        values = da[axis].values
        if len(np.unique(values)) != len(values):
            raise ValueError(f"Duplicate {axis} coordinates")
    da = da.assign_coords(time=times)
    return da, init


def model_season(ds, cfg, year):
    da, init = open_model(ds, cfg)
    if init.year != year or init.month != cfg["initialization_month"]:
        raise ValueError(f"Initialization {init} does not match requested {year}/{cfg['initialization_month']}")
    cumulative = da.values.astype("float64")
    fill = da.attrs.get("GRIB_missingValue")
    if fill is not None:
        cumulative[cumulative == float(fill)] = np.nan
    if np.any(np.isinf(cumulative)):
        raise ValueError("Infinite ECMWF accumulation")
    tol = cfg["negative_increment_tolerance_mm"]
    if np.any(cumulative < -tol / 1000):
        raise ValueError("Negative cumulative precipitation")
    daily = np.diff(cumulative, axis=0, prepend=np.zeros_like(cumulative[:1])) * 1000.0
    if np.any(daily < -tol):
        raise ValueError("Negative increments exceed tolerance; inspect accumulation resets or corruption")
    dates = pd.DatetimeIndex(da.time.values) - pd.Timedelta(days=1)
    expected = season_dates(cfg, year)
    indices = dates.get_indexer(expected)
    if np.any(indices < 0):
        raise ValueError("ECMWF does not cover every required season interval")
    block = daily[indices]
    complete = np.isfinite(block).all(axis=0)
    # Verify telescoping sum before clipping tiny numerical negatives.
    raw_total = np.sum(block, axis=0)
    last = indices[-1]
    first = indices[0]
    start_c = cumulative[first - 1] if first > 0 else np.zeros_like(cumulative[0])
    direct = 1000.0 * (cumulative[last] - start_c)
    if complete.any() and not np.allclose(raw_total[complete], direct[complete], rtol=1e-10, atol=1e-7):
        raise ValueError("Daily sum disagrees with endpoint difference")
    total = np.where(complete, np.maximum(block, 0).sum(axis=0), np.nan)
    if not complete.any():
        raise ValueError("No complete member/grid-cell seasonal totals")
    coords = {k: da[k].values for k in ("member", "lat", "lon")}
    out = xr.Dataset({
        "precip_season": (("member", "lat", "lon"), total),
        "valid_day_count": (("member", "lat", "lon"), np.isfinite(block).sum(axis=0).astype("int16"))
    }, coords=coords)
    out.precip_season.attrs.update(units="mm", long_name="Uncalibrated seasonal total precipitation")
    max_adjust = float(np.nanmax(np.abs(total - raw_total)))
    out.attrs.update(initialization=str(init), season_start=str(expected[0].date()),
                     season_end=str(expected[-1].date()), expected_days=len(expected),
                     member_count=da.sizes["member"], grid="native ECMWF; no remapping",
                     negative_increment_tolerance_mm=tol,
                     maximum_clipping_adjustment_mm=max_adjust,
                     interval_label="start of daily interval; valid_time minus 24 hours")
    qc = {"year": year, "members": da.sizes["member"], "days": len(expected),
          "missing_seasonal_fraction": float((~complete).mean()),
          "clipping_adjustment_max_mm": max_adjust}
    return out, qc


def chirps_season(ds, cfg, year):
    da = ds[cfg["chirps_variable"]]
    units = str(da.attrs.get("units", "")).strip().lower()
    if units not in {"mm/day", "mm/d", "mm day-1", "mm day^-1", "mm d-1", "mm"}:
        raise ValueError(f"Expected daily CHIRPS mm/day or mm; found {units!r}")
    if set(da.dims) != {"time", "lat", "lon"}:
        raise ValueError(f"Expected CHIRPS time/lat/lon, found {list(da.dims)}")
    expected = season_dates(cfg, year)
    dates = pd.DatetimeIndex(da.time.values)
    if not dates.is_unique or not dates.is_monotonic_increasing or not (dates == dates.normalize()).all():
        raise ValueError("CHIRPS daily dates must be unique, increasing, and midnight start labels")
    if np.any(dates.get_indexer(expected) < 0):
        raise ValueError(f"Missing CHIRPS dates for {year}")
    block = da.sel(time=expected).transpose("time", "lat", "lon").load()
    if np.isinf(block.values).any() or (block.values < 0).any():
        raise ValueError("Invalid negative or infinite CHIRPS rainfall")
    count = block.count("time")
    total = block.sum("time", skipna=False)
    if not np.isfinite(total.values).any():
        raise ValueError(f"No complete CHIRPS cells for {year}")
    total.name = "precip_season"
    total.attrs = {"units": "mm", "long_name": "Observed seasonal total precipitation"}
    out = xr.Dataset({"precip_season": total, "valid_day_count": count.astype("int16")})
    out = out.expand_dims(year=[year])
    out.attrs.update(grid="native CHIRPS; no remapping", expected_days=len(expected))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="config/project.json")
    which = ap.add_mutually_exclusive_group(required=True)
    which.add_argument("--years", type=int, nargs="+",
                       help="Explicit years; begin with 1993, then expand after inspection")
    which.add_argument("--all-years", action="store_true",
                       help="Every year in the configured archive_years range")
    args = ap.parse_args()
    cfg = load_config(args.config)
    if args.all_years:
        args.years = list(range(cfg["archive_years"][0], cfg["archive_years"][1] + 1))
    make_folders()
    source = source_path(cfg["chirps_file"])
    if not source.is_file():
        raise SystemExit(f"CHIRPS file not found: {source}")
    tag = f"init{cfg['initialization_month']:02d}_{cfg['season']['name']}"
    qc = []
    with xr.open_dataset(source) as obs:
        for year in sorted(set(args.years)):
            path = model_path(cfg, year)
            if not path.is_file():
                raise FileNotFoundError(path)
            with xr.open_dataset(path) as ds:
                model, report = model_season(ds, cfg, year)
            expected_members = CYCLE.members(year)
            if report["members"] != expected_members:
                raise ValueError(f"{year}: expected {expected_members} members per project inventory, found {report['members']}")
            model.attrs.update(source_file=str(path), processing_utc=datetime.now(timezone.utc).isoformat(),
                               config_json=json.dumps(cfg))
            save_netcdf(model, ROOT / f"data/interim/{tag}/ecmwf_{year}_native.nc")
            if cfg["observation_years"][0] <= year <= cfg["observation_years"][1]:
                observed = chirps_season(obs, cfg, year)
                observed.attrs.update(source_file=str(source), config_json=json.dumps(cfg))
                save_netcdf(observed, ROOT / f"data/interim/{tag}/chirps_{year}_native.nc")
            else:
                report["observations"] = "Outside configured observation period; no verification"
            qc.append(report)
            print(f"Prepared {year}: {report['members']} members; {report['days']} days")
    save_json(ROOT / f"outputs/qc/preparation_{tag}.json", qc)
    print("Native-grid seasonal totals ready. Regridding and calibration are subsequent stages.")


if __name__ == "__main__":
    main()
