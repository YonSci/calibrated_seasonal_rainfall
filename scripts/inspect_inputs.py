"""Inventory every configured ECMWF file and CHIRPS without loading entire fields."""
import argparse
import csv
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import xarray as xr
from common import ROOT, make_folders, load_config, model_path, source_path, save_json
from cycle import CYCLE
from prepare_seasonal import open_model, season_dates


def inspect_model(path, cfg, year):
    row = {"year": year, "path": str(path), "status": "missing"}
    if not path.is_file():
        return row
    try:
        with xr.open_dataset(path) as ds:
            da, init = open_model(ds, cfg)
            dates = pd.DatetimeIndex(da.time.values) - pd.Timedelta(days=1)
            expected = season_dates(cfg, year)
            if init.year != year or init.month != cfg["initialization_month"]:
                raise ValueError("Initialization disagrees with filename/configuration")
            if (dates.get_indexer(expected) < 0).any():
                raise ValueError("Target season not fully covered")
            sample = da.isel(member=0, lat=da.sizes["lat"] // 2, lon=da.sizes["lon"] // 2).values
            negative = int(np.sum(np.diff(sample) * 1000 < -cfg["negative_increment_tolerance_mm"]))
            members = da.sizes["member"]
            if members != CYCLE.members(year):
                raise ValueError(f"Unexpected member count: {members}; inspect provenance")
            if negative:
                raise ValueError("Sample has negative accumulation increments")
            row.update(status="ok", initialization=str(init), members=members,
                       endpoint_first=str(da.time.values[0]), endpoint_last=str(da.time.values[-1]),
                       daily_date_first=str(dates[0]), daily_date_last=str(dates[-1]),
                       lat_count=da.sizes["lat"], lon_count=da.sizes["lon"],
                       lat_min=float(da.lat.min()), lat_max=float(da.lat.max()),
                       lon_min=float(da.lon.min()), lon_max=float(da.lon.max()),
                       sample_negative_increments=negative,
                       note="Metadata plus one series checked; preparation checks all increments")
    except Exception as exc:
        row.update(status="error", message=str(exc))
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="config/project.json")
    args = ap.parse_args()
    cfg = load_config(args.config)
    make_folders()
    years = range(cfg["archive_years"][0], cfg["archive_years"][1] + 1)
    rows = [inspect_model(model_path(cfg, y), cfg, y) for y in years]
    for row in rows:
        print(f"{row['year']}: {row['status']} {row.get('message', '')}")
    path = source_path(cfg["chirps_file"])
    obs = {"path": str(path), "status": "missing"}
    if path.is_file():
        try:
            with xr.open_dataset(path) as ds:
                da = ds[cfg["chirps_variable"]]
                dates = pd.DatetimeIndex(da.time.values)
                expected = pd.date_range(f"{cfg['observation_years'][0]}-01-01",
                                         f"{cfg['observation_years'][1]}-12-31", freq="D")
                if not dates.is_unique or not dates.is_monotonic_increasing:
                    raise ValueError("Duplicate or unordered CHIRPS dates")
                missing = len(expected.difference(dates))
                obs.update(status="ok" if missing == 0 else "error", dimensions=dict(da.sizes),
                           units=da.attrs.get("units"), first=str(dates[0]), last=str(dates[-1]),
                           missing_dates=missing, attributes=dict(da.attrs),
                           note="Pixel missingness and negative values checked during seasonal preparation")
        except Exception as exc:
            obs.update(status="error", message=str(exc))
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "config": cfg,
              "ecmwf": rows, "chirps": obs,
              "provenance": "User reports SEAS5; member counts alone do not verify system version."}
    # May-initialized JJAS keeps the original location; other seasons get their own folder.
    tag = f"init{cfg['initialization_month']:02d}_{cfg['season']['name']}"
    folder = ROOT / "outputs/inspection" / ("" if tag == "init05_JJAS" else tag)
    folder.mkdir(parents=True, exist_ok=True)
    save_json(folder / "inventory.json", report)
    columns = sorted(set().union(*(r.keys() for r in rows)))
    with (folder / "ecmwf_inventory.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    summary = ["# Input inventory", "", f"CHIRPS status: **{obs['status']}**", "",
               "| Year | Status | Members |", "| --- | --- | --- |"]
    summary.extend(f"| {r['year']} | {r['status']} | {r.get('members', '')} |" for r in rows)
    summary.extend(["", "See inventory.json for details. No source files were changed.",
                    "This inventory does not independently establish model-system provenance."])
    (folder / "inspection_summary.md").write_text("\n".join(summary), encoding="utf-8")
    if any(r["status"] != "ok" for r in rows) or obs["status"] != "ok":
        raise SystemExit("Inventory has missing/error entries. Review reports before full processing.")
    print("Inventory passed. Run synthetic tests, then prepare one historical year.")


if __name__ == "__main__":
    main()
