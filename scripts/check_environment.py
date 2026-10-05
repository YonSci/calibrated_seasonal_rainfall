"""Check imports and record the exact installed environment; no climate data needed."""
import importlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from common import ROOT, make_folders, save_json

PACKAGES = {"numpy": "numpy", "pandas": "pandas", "xarray": "xarray",
            "scipy": "scipy", "netCDF4": "netCDF4", "dask": "dask", "matplotlib": "matplotlib"}


def main():
    make_folders()
    if not (3, 11) <= sys.version_info[:2] <= (3, 12):
        raise SystemExit("Use Python 3.11 or 3.12 for this starter.")
    failed = []
    report = {"python": sys.version, "executable": sys.executable,
              "platform": platform.platform(), "packages": {}}
    for package, module in PACKAGES.items():
        try:
            importlib.import_module(module)
            report["packages"][package] = importlib.metadata.version(package)
            print(f"OK  {package}: {report['packages'][package]}")
        except Exception as exc:
            failed.append(package)
            print(f"FAIL {package}: {exc}")
    save_json(ROOT / "logs/environment.json", report)
    if failed:
        raise SystemExit("Install requirements.txt, then rerun this check.")
    freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
    (ROOT / "logs/requirements-resolved.txt").write_text(freeze, encoding="utf-8")
    print("Environment ready. Versions recorded in logs/.")


if __name__ == "__main__":
    main()
