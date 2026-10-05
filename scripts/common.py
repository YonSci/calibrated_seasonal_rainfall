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
    start, end = cfg["season"]["start"], cfg["season"]["end"]
    from datetime import date
    if date.fromisoformat("2000-" + end) < date.fromisoformat("2000-" + start):
        raise ValueError("This starter supports same-calendar-year seasons only.")
    return cfg


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
