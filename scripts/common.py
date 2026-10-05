"""Shared project paths, explicit configuration, and safe output writing."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = ["data/raw/ecmwf", "data/raw/chirps", "data/interim", "data/processed",
           "outputs/inspection", "outputs/qc", "outputs/validation", "outputs/forecast",
           "outputs/figures", "models", "logs", "notebooks"]


def make_folders():
    for name in FOLDERS:
        (ROOT / name).mkdir(parents=True, exist_ok=True)


def load_config(path):
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    with path.open(encoding="utf-8-sig") as stream:
        cfg = json.load(stream)
    if not 1 <= cfg["initialization_month"] <= 12:
        raise ValueError("initialization_month must be 1..12")
    season_window(cfg, 2000)   # validates the season definition
    return cfg


def season_window(cfg, year):
    """First and last day of the target period for the forecast initialized in `year`.

    The period starts in the initialization year when its start month is on or after
    the initialization month, otherwise in the next year (e.g. January after a
    September start). It ends in the following year when its end month precedes
    its start month (e.g. ONDJ). May-initialized JJAS keeps both dates in `year`.
    """
    from datetime import date
    start_m, start_d = map(int, cfg["season"]["start"].split("-"))
    end_m, end_d = map(int, cfg["season"]["end"].split("-"))
    first_year = year if start_m >= cfg["initialization_month"] else year + 1
    last_year = first_year if (end_m, end_d) >= (start_m, start_d) else first_year + 1
    start, end = date(first_year, start_m, start_d), date(last_year, end_m, end_d)
    if (end - start).days >= 366:
        raise ValueError("Target periods longer than one year are not supported.")
    return start, end


def season_months(cfg):
    """Calendar months covered by the season, in order, e.g. [10, 11, 12, 1] for ONDJ."""
    start, end = season_window(cfg, 2001)
    months, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(m)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return months


def source_path(value):
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def model_path(cfg, year):
    return source_path(cfg["ecmwf_directory"]) / cfg["ecmwf_pattern"].format(
        year=year, month=cfg["initialization_month"])


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def save_netcdf(ds, path):
    """Write derived output atomically. Source files are never written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.nc")
    try:
        ds.to_netcdf(tmp, engine="netcdf4", encoding={
            name: {"zlib": True, "complevel": 4} for name in ds.data_vars})
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
